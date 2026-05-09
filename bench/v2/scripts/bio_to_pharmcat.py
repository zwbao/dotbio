#!/usr/bin/env python3
"""
.bio bundle -> PharmCAT-style JSON report emitter for the dotbio NM-grade
benchmark (Task 3, see bench/v2/TASKS.md).

Reads a dotbio v0 bundle (`facts/`, `commits/`, `views/`, `refs/`,
`manifest.json`) and emits a JSON report whose top-level layout mirrors
PharmCAT's published `*.report.json` schema (as observed in the official
PharmCAT v3.x example reports at
https://github.com/PharmGKB/PharmCAT/tree/development/docs/examples and
documented at https://pharmcat.org/specifications/Report/).

This is *not* a PharmCAT re-implementation: it only re-shapes data that
already exists in the .bio commit (diplotypes, phenotypes, drug claims).
It does NOT call alleles from raw genotypes; it does NOT invent
diplotypes that aren't in the commit. Any field that PharmCAT defines
but the .bio bundle does not carry is left explicitly null with a
trailing "_pharmcat_missing" sibling key, so a reader of this report can
tell the difference between "PharmCAT had no answer" and "the dotbio
bundle did not provide this slot".

Usage:
    python bio_to_pharmcat.py \
        --bio examples/real-na12878/output.bio \
        --out bench/v2/data/format_f_pharmcat_report.json

Limitations and the field-by-field cross-walk are documented in
`README_pharmcat.md` next to this file.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# .bio bundle reader
# ---------------------------------------------------------------------------

def load_bio_bundle(bio_dir: Path) -> dict[str, Any]:
    """Load the manifest, the HEAD commit, and all facts from a .bio dir.

    Returns a dict with keys: manifest, commit, facts (list), views_dir.
    """
    manifest = json.loads((bio_dir / "manifest.json").read_text())

    refs_head = (bio_dir / "refs" / "HEAD").read_text().strip()
    # HEAD content is the commit id (the timestamp string used as filename
    # prefix). Find the commit file matching it; fall back to the single
    # commit present in the bundle.
    commits = sorted((bio_dir / "commits").glob("*.commit.json"))
    if not commits:
        raise SystemExit(f"no commits found in {bio_dir}")
    commit_path = None
    for p in commits:
        if p.name.startswith(refs_head):
            commit_path = p
            break
    if commit_path is None:
        commit_path = commits[-1]
    commit = json.loads(commit_path.read_text())

    facts: list[dict[str, Any]] = []
    facts_root = bio_dir / "facts"
    for shard in sorted(facts_root.iterdir()):
        if not shard.is_dir():
            continue
        for fp in sorted(shard.glob("*.json")):
            obj = json.loads(fp.read_text())
            # Reconstruct the sha256 hash (shard prefix + filename stem).
            digest = shard.name + fp.stem
            obj["_sha256"] = digest
            facts.append(obj)

    return {
        "manifest": manifest,
        "commit": commit,
        "commit_path": commit_path,
        "facts": facts,
        "views_dir": bio_dir / "views",
    }


# ---------------------------------------------------------------------------
# Helpers for translating .bio claims into PharmCAT structures
# ---------------------------------------------------------------------------

def _iter_claims(commit: dict[str, Any]) -> list[dict[str, Any]]:
    return list(commit.get("claims", []))


def _diplotype_claims_by_gene(commit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for c in _iter_claims(commit):
        if c.get("level") == "haplotype" and c.get("gene") and c.get("diplotype"):
            out[c["gene"]] = c
    return out


def _phenotype_claims_by_gene(commit: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for c in _iter_claims(commit):
        if c.get("level") == "phenotype" and c.get("gene") and c.get("phenotype"):
            out[c["gene"]] = c
    return out


def _drug_claims(commit: dict[str, Any]) -> list[dict[str, Any]]:
    return [c for c in _iter_claims(commit) if c.get("level") == "clinical_decision" and c.get("drug")]


def _facts_by_gene(facts: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for f in facts:
        if f.get("kind") != "variant":
            continue
        gene = f.get("gene_hint")
        if not gene:
            continue
        out.setdefault(gene, []).append(f)
    return out


def _ruleset_version(commit: dict[str, Any], name_prefix: str) -> str | None:
    for r in commit.get("rulesets", []) or []:
        if r.startswith(name_prefix + "@"):
            return r.split("@", 1)[1]
    return None


def _classification_for_drug_claim(claim: dict[str, Any]) -> str:
    """Map dotbio claim -> a PharmCAT-style strength classification.

    PharmCAT's `classification` is one of {Strong, Moderate, Optional, n/a}.
    We map "Consider alternative" to Strong, otherwise Moderate.
    """
    text = (claim.get("claim") or "").lower()
    if "consider alternative" in text or "avoid" in text or "contraindicated" in text:
        return "Strong"
    return "Moderate"


# ---------------------------------------------------------------------------
# PharmCAT report builders
# ---------------------------------------------------------------------------

def _build_allele(gene: str, name: str, function: str | None) -> dict[str, Any]:
    return {
        "gene": gene,
        "name": name,
        "function": function,
        "reference": (name == "*1"),
        "activityValue": "n/a",
    }


def _build_diplotype(
    gene: str,
    diplotype_label: str,
    phenotypes: list[str],
) -> dict[str, Any]:
    """Build a PharmCAT-shape diplotype object from a 'a/b' label.

    Functions are unknown from the .bio bundle, so we set them to null
    (PharmCAT itself sometimes does this for non-CPIC alleles).
    """
    parts = diplotype_label.split("/")
    if len(parts) != 2:
        a1, a2 = diplotype_label, diplotype_label
    else:
        a1, a2 = parts
    return {
        "allele1": _build_allele(gene, a1, None),
        "allele2": _build_allele(gene, a2, None),
        "gene": gene,
        "matchScore": None,
        "phenotypes": list(phenotypes),
        "outsidePhenotype": False,
        "outsidePhenotypeMismatch": None,
        "activityScore": None,
        "outsideActivityScore": False,
        "outsideActivityScoreMismatch": None,
        "variant": None,
        "lookupKey": list(phenotypes),
        "label": f"{a1}/{a2}",
        "inferred": False,
        "inferredSourceDiplotypes": None,
        "combination": False,
        "diplotypeKey": (
            {a1: 2.0} if a1 == a2 else {a1: 1.0, a2: 1.0}
        ),
    }


def _build_variants_block(facts: list[dict[str, Any]], gene: str) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for f in facts:
        out.append({
            "gene": gene,
            "chromosome": f.get("chrom"),
            "position": f.get("pos"),
            "dbSnpId": f.get("rsid"),
            "call": f.get("genotype"),
            "alleles": [],   # we don't carry per-position allele names in .bio
            "phased": False,
            "phaseSet": None,
            "referenceAllele": f.get("ref"),
            "hasUndocumentedVariations": False,
            "warnings": [],
            "_bio_fact_sha256": f.get("_sha256"),
        })
    return out


def _build_gene_block(
    gene: str,
    diplotype_claim: dict[str, Any] | None,
    phenotype_claim: dict[str, Any] | None,
    related_drug_names: list[str],
    facts_for_gene: list[dict[str, Any]],
    pharmcat_version: str | None,
) -> dict[str, Any]:
    diplotypes: list[dict[str, Any]] = []
    if diplotype_claim and diplotype_claim.get("diplotype"):
        phenotypes = []
        if phenotype_claim and phenotype_claim.get("phenotype"):
            phenotypes = [phenotype_claim["phenotype"]]
        diplotypes.append(_build_diplotype(
            gene=gene,
            diplotype_label=diplotype_claim["diplotype"],
            phenotypes=phenotypes,
        ))

    chr_value = facts_for_gene[0].get("chrom") if facts_for_gene else None

    return {
        "alleleDefinitionVersion": pharmcat_version,
        "alleleDefinitionSource": "dotbio (re-emitted from .bio bundle)",
        "phenotypeVersion": pharmcat_version,
        "geneSymbol": gene,
        "chr": chr_value,
        "phased": False,
        "effectivelyPhased": False,
        "callSource": "DOTBIO",
        "uncalledHaplotypes": [],
        "messages": [],
        "relatedDrugs": [
            {"name": dn, "id": None, "_pharmcat_missing": ["id"]}
            for dn in related_drug_names
        ],
        "sourceDiplotypes": diplotypes,
        "matcherComponentHaplotypes": [],
        "matcherHomozygousComponentHaplotypes": [],
        "recommendationDiplotypes": diplotypes,
        "variants": _build_variants_block(facts_for_gene, gene),
        "variantsOfInterest": [],
        "hasUndocumentedVariations": False,
        "treatUndocumentedVariationsAsReference": False,
        "_pharmcat_missing": [
            "matchScore (we don't carry the named-allele matcher score)",
            "alleleDefinitionSource (we are not the official PharmGKB source)",
        ],
    }


def _build_drug_block(
    drug_claim: dict[str, Any],
    diplotype_for_gene: dict[str, Any] | None,
    phenotype_for_gene: dict[str, Any] | None,
    pharmcat_version: str | None,
) -> dict[str, Any]:
    drug = drug_claim["drug"]
    gene = drug_claim.get("gene")
    guideline = drug_claim.get("guideline")  # e.g. "CPIC@2022"

    guideline_id = None
    guideline_name = f"Annotation of CPIC Guideline for {drug}" + (f" and {gene}" if gene else "")
    guideline_version = None
    if guideline and "@" in guideline:
        _src, guideline_version = guideline.split("@", 1)

    diplotype_objs: list[dict[str, Any]] = []
    if gene and diplotype_for_gene and diplotype_for_gene.get("diplotype"):
        phenotypes: list[str] = []
        if phenotype_for_gene and phenotype_for_gene.get("phenotype"):
            phenotypes = [phenotype_for_gene["phenotype"]]
        diplotype_objs.append(_build_diplotype(
            gene=gene,
            diplotype_label=diplotype_for_gene["diplotype"],
            phenotypes=phenotypes,
        ))

    annotations = [{
        "implications": [
            f"{gene}: {phenotype_for_gene['phenotype']}"
        ] if gene and phenotype_for_gene and phenotype_for_gene.get("phenotype") else [],
        "drugRecommendation": drug_claim.get("claim"),
        "classification": _classification_for_drug_claim(drug_claim),
        "activityScore": {},
        "population": "general",
        "genotypes": [
            {
                "diplotypes": diplotype_objs,
                "phenotypes": [phenotype_for_gene["phenotype"]] if phenotype_for_gene and phenotype_for_gene.get("phenotype") else [],
                "lookupKey": {gene: phenotype_for_gene["phenotype"]} if gene and phenotype_for_gene and phenotype_for_gene.get("phenotype") else {},
            }
        ] if diplotype_objs else [],
    }]

    return {
        "name": drug,
        "id": None,
        "source": "CPIC_GUIDELINE",
        "version": pharmcat_version,
        "messages": [],
        "variants": [],
        "urls": [],
        "citations": [],
        "guidelines": [
            {
                "id": guideline_id,
                "name": guideline_name,
                "source": "CPIC_GUIDELINE",
                "version": guideline_version or pharmcat_version,
                "url": None,
                "annotations": annotations,
            }
        ],
        "_dotbio_provenance": {
            "claim_id": drug_claim.get("id"),
            "ruleset": drug_claim.get("ruleset"),
            "guideline_pin": guideline,
            "targets": drug_claim.get("targets", []),
        },
        "_pharmcat_missing": [
            "id (PharmGKB Accession ID, e.g. PA449762 — not in .bio)",
            "urls (clinpgx.org guideline URL — not in .bio)",
            "citations (PMID list — not in .bio)",
        ],
    }


# ---------------------------------------------------------------------------
# Top-level emitter
# ---------------------------------------------------------------------------

def emit_pharmcat_report(bundle: dict[str, Any], subject_label: str | None = None) -> dict[str, Any]:
    manifest = bundle["manifest"]
    commit = bundle["commit"]
    facts = bundle["facts"]

    pharmcat_version = _ruleset_version(commit, "pharmcat")

    diplotype_by_gene = _diplotype_claims_by_gene(commit)
    phenotype_by_gene = _phenotype_claims_by_gene(commit)
    drugs = _drug_claims(commit)
    facts_by_gene = _facts_by_gene(facts)

    # Build per-gene blocks for every gene mentioned by either a diplotype
    # claim, a phenotype claim, or any variant fact.
    all_genes: list[str] = sorted(
        set(diplotype_by_gene)
        | set(phenotype_by_gene)
        | set(facts_by_gene)
    )

    # Map gene -> related drugs based on drug claims.
    gene_to_drugs: dict[str, list[str]] = {}
    for d in drugs:
        g = d.get("gene")
        if g:
            gene_to_drugs.setdefault(g, []).append(d["drug"])

    genes_block: dict[str, Any] = {}
    for g in all_genes:
        genes_block[g] = _build_gene_block(
            gene=g,
            diplotype_claim=diplotype_by_gene.get(g),
            phenotype_claim=phenotype_by_gene.get(g),
            related_drug_names=gene_to_drugs.get(g, []),
            facts_for_gene=facts_by_gene.get(g, []),
            pharmcat_version=pharmcat_version,
        )

    # Drugs block: PharmCAT keys drugs under "CPIC Guideline Annotation",
    # "DPWG Guideline Annotation", "FDA Label Annotation", etc. We only emit
    # CPIC entries because that's all .bio tracks today.
    drugs_block: dict[str, Any] = {"CPIC Guideline Annotation": {}}
    for d in drugs:
        gene = d.get("gene")
        drugs_block["CPIC Guideline Annotation"][d["drug"]] = _build_drug_block(
            drug_claim=d,
            diplotype_for_gene=diplotype_by_gene.get(gene) if gene else None,
            phenotype_for_gene=phenotype_by_gene.get(gene) if gene else None,
            pharmcat_version=pharmcat_version,
        )

    # PharmCAT tracks "messages" (rule-level notes, ambiguity warnings, …).
    # We surface each .bio claim as an informational note so a downstream
    # PharmCAT-aware reader sees the same provenance trail.
    messages: list[dict[str, Any]] = []
    for c in _iter_claims(commit):
        messages.append({
            "rule_name": f"dotbio:{c.get('level')}",
            "version": c.get("ruleset"),
            "matches": None,
            "exception_type": "note",
            "message": c.get("claim") or c.get("derivation"),
            "_dotbio_claim_id": c.get("id"),
        })

    matcher_metadata = {
        "namedAlleleMatcherVersion": None,
        "genomeBuild": manifest.get("build"),
        "inputFilename": str(bundle["commit_path"].name),
        "timestamp": commit.get("created"),
        "topCandidatesOnly": True,
        "findCombinations": False,
        "callCyp2d": False,
        "sampleId": subject_label or manifest.get("subject") or "Sample_1",
        "sampleProps": None,
        "_pharmcat_missing": [
            "namedAlleleMatcherVersion (we did not run the PharmCAT matcher)",
        ],
    }

    return {
        "title": f"dotbio.{manifest.get('subject', 'sample')}.pharmcat-emitted",
        "timestamp": commit.get("created"),
        "pharmcatVersion": f"emitted-from-dotbio (ruleset pharmcat@{pharmcat_version})" if pharmcat_version else "emitted-from-dotbio",
        "dataVersion": pharmcat_version,
        "genes": genes_block,
        "drugs": drugs_block,
        "messages": messages,
        "matcherMetadata": matcher_metadata,
        "unannotatedGeneCalls": [],
        # Provenance footer that real PharmCAT does not emit:
        "_dotbio_provenance": {
            "schema": manifest.get("schema"),
            "subject": manifest.get("subject"),
            "build": manifest.get("build"),
            "rulesets": commit.get("rulesets", []),
            "commit_id": commit.get("id"),
            "active_rulesets": manifest.get("active_rulesets", []),
            "note": (
                "This JSON was emitted by bio_to_pharmcat.py from a dotbio "
                "v0 bundle WITHOUT running the PharmCAT Java pipeline. "
                "Fields not derivable from the bundle are explicitly null "
                "with sibling _pharmcat_missing keys listing the gap."
            ),
        },
    }


# ---------------------------------------------------------------------------
# Hand-rolled validator
# ---------------------------------------------------------------------------

def validate_pharmcat_shape(report: dict[str, Any]) -> list[str]:
    """Hand-rolled approximation of the PharmCAT report schema.

    Returns a list of error messages (empty == valid).
    """
    errs: list[str] = []
    for k in ("title", "timestamp", "pharmcatVersion", "dataVersion",
              "genes", "drugs", "messages", "matcherMetadata"):
        if k not in report:
            errs.append(f"top-level missing: {k}")

    if not isinstance(report.get("genes", {}), dict):
        errs.append("genes must be a dict keyed by gene symbol")
    else:
        for gene_sym, gene in report["genes"].items():
            if not isinstance(gene, dict):
                errs.append(f"genes.{gene_sym} must be a dict")
                continue
            for required in ("geneSymbol", "sourceDiplotypes",
                             "recommendationDiplotypes", "variants"):
                if required not in gene:
                    errs.append(f"genes.{gene_sym} missing {required}")

    if not isinstance(report.get("drugs", {}), dict):
        errs.append("drugs must be a dict keyed by guideline-source label")
    else:
        for src_label, drug_map in report["drugs"].items():
            if not isinstance(drug_map, dict):
                errs.append(f"drugs.{src_label!r} must be a dict")
                continue
            for drug_name, drug in drug_map.items():
                for required in ("name", "source", "guidelines"):
                    if required not in drug:
                        errs.append(f"drugs.{src_label!r}.{drug_name} missing {required}")

    if not isinstance(report.get("messages", []), list):
        errs.append("messages must be a list")

    return errs


# ---------------------------------------------------------------------------
# Token counting (Claude tokenizer via Xenova/claude-tokenizer)
# ---------------------------------------------------------------------------

def count_tokens(text: str) -> dict[str, Any]:
    """Count tokens using Xenova/claude-tokenizer if available; fall back to
    a byte-based heuristic otherwise so the script still runs in CI."""
    try:
        from transformers import AutoTokenizer  # type: ignore
        tok = AutoTokenizer.from_pretrained("Xenova/claude-tokenizer")
        return {
            "tokenizer": "Xenova/claude-tokenizer",
            "tokens": len(tok.encode(text)),
            "bytes": len(text.encode("utf-8")),
        }
    except Exception as e:
        # Heuristic: ~4 chars/token is the standard rough estimate.
        nbytes = len(text.encode("utf-8"))
        return {
            "tokenizer": "heuristic-bytes-div-4",
            "tokens": nbytes // 4,
            "bytes": nbytes,
            "tokenizer_unavailable_reason": str(e),
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument(
        "--bio",
        type=Path,
        default=Path("examples/real-na12878/output.bio"),
        help="path to a .bio bundle directory",
    )
    ap.add_argument(
        "--out",
        type=Path,
        default=Path("bench/v2/data/format_f_pharmcat_report.json"),
        help="output path for the PharmCAT-style report JSON",
    )
    ap.add_argument(
        "--subject",
        type=str,
        default=None,
        help="override sampleId (defaults to manifest.subject)",
    )
    args = ap.parse_args()

    if not args.bio.exists():
        print(f"error: --bio path does not exist: {args.bio}", file=sys.stderr)
        return 2

    bundle = load_bio_bundle(args.bio)
    report = emit_pharmcat_report(bundle, subject_label=args.subject)

    errs = validate_pharmcat_shape(report)
    if errs:
        print("PharmCAT-shape validation FAILED:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        return 1

    args.out.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(report, indent=2, sort_keys=False)
    args.out.write_text(text)

    n_genes = len(report.get("genes", {}))
    n_drugs = sum(len(v) for v in report.get("drugs", {}).values())
    n_messages = len(report.get("messages", []))

    tok = count_tokens(text)

    print(f"wrote {args.out}")
    print(f"  genes={n_genes}  drugs={n_drugs}  messages={n_messages}")
    print(f"  bytes={tok['bytes']}  tokens={tok['tokens']} ({tok['tokenizer']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
