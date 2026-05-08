"""Rule application engine.

Three rulesets supported in v0:

- ClinVar — looks up germline variants by rsID + genotype, produces clinical
  significance claims.
- PharmCAT-style — haplotype calling for CYP2C19/TPMT/DPYD, then phenotype
  rollup, then per-drug guidance claims.
- OncoKB-style — looks up somatic variants by gene + p.notation.

Each rule produces 'claims', the unit of interpretation. Every claim points
back to the underlying fact hashes so the chain stays auditable.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from importlib import resources
from typing import Any

from .hashing import canonical_json


# ---- Loading bundled rulesets ------------------------------------------


def load_ruleset(name_at_version: str) -> dict[str, Any]:
    """Load a bundled ruleset by 'name@version' string."""
    if "@" in name_at_version:
        name, version = name_at_version.split("@", 1)
    else:
        name, version = name_at_version, ""
    filename = f"{name}-{version}.json" if version else f"{name}.json"
    text = resources.files("dotbio.rulesets").joinpath(filename).read_text()
    return json.loads(text)


# ---- Claim model -------------------------------------------------------


@dataclass
class Claim:
    claim: str
    targets: list[str]
    level: str  # "variant" | "haplotype" | "phenotype" | "clinical_decision"
    ruleset: str  # "name@version"
    derivation: str
    guideline: str | None = None
    extras: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "id": self._stable_id(),
            "claim": self.claim,
            "targets": sorted(self.targets),
            "level": self.level,
            "ruleset": self.ruleset,
            "derivation": self.derivation,
        }
        if self.guideline:
            d["guideline"] = self.guideline
        if self.extras:
            d.update(self.extras)
        return d

    def _stable_id(self) -> str:
        body = canonical_json({
            "claim": self.claim,
            "targets": sorted(self.targets),
            "ruleset": self.ruleset,
            "level": self.level,
        })
        return "claim:" + hashlib.sha256(body).hexdigest()[:16]


# ---- ClinVar ------------------------------------------------------------


def apply_clinvar(facts_with_hashes: list[tuple[str, dict]], ruleset: dict) -> list[dict]:
    name_at_v = f"{ruleset['name']}@{ruleset['version']}"
    entries = ruleset.get("entries", {})
    claims: list[Claim] = []

    for h, f in facts_with_hashes:
        if f.get("kind") != "variant":
            continue
        rsid = f.get("rsid")
        if not rsid or rsid not in entries:
            continue
        entry = entries[rsid]
        gt = f.get("genotype")
        if gt is None:
            continue

        # ClinVar entries key by ordered genotype "REF/ALT" or "ALT/ALT".
        # We accept both orderings.
        by_gt = entry.get("by_genotype", {})
        match = by_gt.get(gt)
        if match is None:
            a, _, b = gt.partition("/")
            match = by_gt.get(f"{b}/{a}")
        if match is None:
            continue

        gene = entry.get("gene", "")
        name = entry.get("name", rsid)
        derivation = (
            f"{rsid} ({gene}) genotype={gt} → "
            f"{match['significance']} for {match['condition']} "
            f"[{ruleset['name']}@{ruleset['version']}]"
        )
        extras: dict[str, Any] = {
            "gene": gene,
            "variant_name": name,
            "significance": match["significance"],
            "condition": match.get("condition"),
            "evidence": match.get("evidence"),
            "review_status": match.get("review_status"),
        }
        if "previous_classification" in match:
            extras["previous_classification"] = match["previous_classification"]
            extras["reclassified_on"] = match.get("reclassified_on")

        claims.append(Claim(
            claim=f"{gene} {name} ({gt}) — {match['significance']}: {match.get('condition', '')}".strip(),
            targets=[h],
            level="variant",
            ruleset=name_at_v,
            derivation=derivation,
            guideline=None,
            extras=extras,
        ))

    return [c.to_dict() for c in claims]


# ---- PharmCAT (haplotype calling) ---------------------------------------


def _call_haplotypes(gene: str, gene_haps: dict, facts_by_rsid: dict[str, tuple[str, dict]]) -> tuple[str, list[str]]:
    """Return (diplotype_string, list_of_target_fact_hashes).

    Simple algorithm:
    - For each non-reference star allele, check its defining variants. If all
      are present:
        - hom alt for all → 2 copies
        - het for any    → 1 copy (and the partner allele is *1)
    - The reference allele *1 fills any remaining slots.
    - Output is "*x/*y" sorted with reference first.
    """
    copies: dict[str, int] = {}
    targets: list[str] = []
    ref_name = "*1"

    for star, definition in gene_haps.items():
        if star == ref_name:
            continue
        defining = definition.get("defining_variants", [])
        if not defining:
            continue

        copy_count: int | None = None
        local_targets: list[str] = []
        for dv in defining:
            rsid = dv["rsid"]
            wanted_alt = dv["alt"]
            if rsid not in facts_by_rsid:
                copy_count = 0
                break
            h, fact = facts_by_rsid[rsid]
            gt = fact.get("genotype", "")
            ref = fact.get("ref", "")
            n = sum(1 for a in gt.split("/") if a == wanted_alt)
            if n == 0 and ref != wanted_alt:
                copy_count = 0
                break
            this_count = n
            copy_count = this_count if copy_count is None else min(copy_count, this_count)
            local_targets.append(h)

        if copy_count and copy_count > 0:
            copies[star] = copy_count
            targets.extend(local_targets)

    # Fill remaining slots with *1
    total_called = sum(copies.values())
    ref_copies = max(0, 2 - total_called)
    if ref_copies:
        copies[ref_name] = ref_copies

    # Build a stable "*x/*y" string. Reference goes first when present;
    # otherwise sort lexicographically.
    flattened: list[str] = []
    for star, n in copies.items():
        flattened.extend([star] * n)
    if ref_name in flattened:
        non_ref = sorted(s for s in flattened if s != ref_name)
        flattened = ([ref_name] * flattened.count(ref_name)) + non_ref
    else:
        flattened.sort()
    diplotype = "/".join(flattened[:2])
    return diplotype, targets


def apply_pharmcat(facts_with_hashes: list[tuple[str, dict]], ruleset: dict) -> list[dict]:
    name_at_v = f"{ruleset['name']}@{ruleset['version']}"
    haplotypes = ruleset.get("haplotypes", {})
    phenotypes = ruleset.get("phenotypes", {})
    guidance = ruleset.get("guidance", {})

    # Index facts by rsID for fast lookup
    facts_by_rsid: dict[str, tuple[str, dict]] = {}
    for h, f in facts_with_hashes:
        rsid = f.get("rsid")
        if rsid:
            facts_by_rsid[rsid] = (h, f)

    claims: list[Claim] = []

    for gene, gene_haps in haplotypes.items():
        diplotype, targets = _call_haplotypes(gene, gene_haps, facts_by_rsid)
        if not targets:
            continue  # no variants observed for this gene; skip silently

        # Haplotype-level claim
        claims.append(Claim(
            claim=f"{gene} diplotype: {diplotype}",
            targets=targets,
            level="haplotype",
            ruleset=name_at_v,
            derivation=f"PharmCAT-style allele calling on {gene} variants → {diplotype}",
            extras={"gene": gene, "diplotype": diplotype},
        ))

        # Phenotype-level claim
        phenotype = phenotypes.get(gene, {}).get(diplotype) or phenotypes.get(gene, {}).get(_swap(diplotype))
        if not phenotype:
            continue
        claims.append(Claim(
            claim=f"{gene} phenotype: {phenotype}",
            targets=targets,
            level="phenotype",
            ruleset=name_at_v,
            derivation=f"{gene} {diplotype} → {phenotype} [{ruleset['name']}@{ruleset['version']} phenotype table]",
            extras={"gene": gene, "diplotype": diplotype, "phenotype": phenotype},
        ))

        # Per-drug guidance claims
        for rec in guidance.get(gene, {}).get(phenotype, []):
            claims.append(Claim(
                claim=f"{rec['drug']}: {rec['recommendation']}",
                targets=targets,
                level="clinical_decision",
                ruleset=name_at_v,
                guideline=rec.get("guideline"),
                derivation=(
                    f"{gene} {diplotype} → {phenotype} → drug guidance for {rec['drug']} "
                    f"[{rec.get('guideline', 'guideline-unspecified')}]"
                ),
                extras={"gene": gene, "phenotype": phenotype, "drug": rec["drug"]},
            ))

    return [c.to_dict() for c in claims]


def _swap(diplotype: str) -> str:
    a, _, b = diplotype.partition("/")
    return f"{b}/{a}"


# ---- OncoKB-style somatic ----------------------------------------------


def apply_oncokb(facts_with_hashes: list[tuple[str, dict]], ruleset: dict) -> list[dict]:
    name_at_v = f"{ruleset['name']}@{ruleset['version']}"
    entries = ruleset.get("entries", {})
    claims: list[Claim] = []

    for h, f in facts_with_hashes:
        if not f.get("somatic"):
            continue
        ann = f.get("annotation")  # e.g. "TP53:p.R175H"
        if not ann or ann not in entries:
            continue
        entry = entries[ann]
        derivation = (
            f"{ann} → {entry['oncogenicity']}: {entry['mutation_effect']} "
            f"[{ruleset['name']}@{ruleset['version']}]"
        )
        claims.append(Claim(
            claim=f"{entry['gene']} {entry['alteration']} — {entry['oncogenicity']}",
            targets=[h],
            level="variant",
            ruleset=name_at_v,
            derivation=derivation,
            extras={
                "gene": entry["gene"],
                "alteration": entry["alteration"],
                "oncogenicity": entry["oncogenicity"],
                "mutation_effect": entry.get("mutation_effect"),
                "oncokb_level": entry.get("level"),
                "context": entry.get("context"),
            },
        ))

    return [c.to_dict() for c in claims]
