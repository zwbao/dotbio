#!/usr/bin/env python3
"""
reid_risk.py — Erlich-Narayanan-style re-identification risk analyzer.

Implements bench/v2/SPEC.md §3.6 / TASKS.md Task 8.

For each comparator format (VCF, .genome reconstruction, .bio bundle), we
compute (1) the marker count of independent variants an attacker can infer,
(2) the Shannon entropy of the publicly inferrable fingerprint, and (3) the
predicted re-identification probability in a reference population of
N = 10^5, with a 1000-iter bootstrap 95% CI on each metric.

The analysis is purely theoretical. No real public database is queried,
contacted, or attacked. We model the attack surface "given a leak in this
format, what fraction of independent loci is uniquely identifying?"

Threat model (Erlich & Narayanan 2014, Nat Rev Genet 15:409-21):
  - Attacker has access to a reference population of N=10^5 individuals
    with known genotypes at all loci that appear in the leak.
  - Attacker observes the leaked file and recovers as much per-locus
    information as the format permits.
  - Re-id probability is bounded above by 1 / (N * P_match), where
    P_match is the population probability of an exact fingerprint match
    under independent loci with allele frequencies p_i (Hardy-Weinberg).

Per-format leakage assumptions (documented in README_reid.md):
  VCF                  : full per-locus genotype + rsID + position; M markers
                         all usable.
  .genome (reconstr.)  : per-locus genotype + rsID; M markers usable; same
                         marker count as VCF for shared loci, but a small
                         fraction of homref calls is collapsed to a textual
                         "no variant" descriptor that still leaks the call.
  .bio facts/ (hashes) : facts are SHA-256 of the canonical JSON. The hash
                         is one-way. An attacker who ALSO holds the public
                         ruleset (which dotbio v0 publishes) can enumerate
                         the small per-locus genotype space (3 states under
                         a biallelic SNV) and brute-force the pre-image,
                         recovering the genotype. So under our threat model
                         the hash leaks one bit less per locus on average
                         (because the ALT-allele text is occasionally
                         missing for homref-only sites in the bundle), but
                         is otherwise equivalent to plaintext.
  .bio views/ only     : the bonus scenario — if only the rendered view is
                         leaked (not facts/), then only phenotype-level
                         claims (e.g., CYP2C19 IM) are exposed. This
                         collapses many independent variant loci into one
                         coarse phenotype, dramatically reducing markers
                         and entropy.

Per the SPEC, .bio is HYPOTHESISED to have lower attack surface than VCF
because (a) facts are content-addressed not coordinate-addressed (an
attacker cannot trivially join across files on chrom:pos), and (b) the
view-only layer collapses variants into phenotypes. We measure both
sub-scenarios for .bio: facts-leaked and views-only-leaked.

Usage:
    python reid_risk.py \
        --vcf  examples/real-na12878/input.vcf \
        --genome bench/data/format_b_genome_reconstructed.md \
        --bio  examples/real-na12878/output.bio \
        --out  bench/v2/results/exp06_reid_risk.json \
        --population 100000 \
        --bootstrap 1000

Reference:
    Erlich, Y. & Narayanan, A. Routes for breaching and protecting
    genetic privacy. Nat Rev Genet 15, 409-421 (2014).
    doi: 10.1038/nrg3723.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import random
import re
import statistics
import sys
import time
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# 1. Format parsers — extract (rsid, gt_count, alt_freq, gene) per locus.
#    gt_count is 0/1/2 ALT alleles; alt_freq is the population ALT-allele
#    frequency reported in the file (or, if absent, an HWE-neutral 0.5).
# ---------------------------------------------------------------------------


def parse_vcf(path: Path) -> list[dict[str, Any]]:
    """Parse a single-sample VCF; return one record per non-header line."""
    records: list[dict[str, Any]] = []
    with path.open() as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 10:
                continue
            chrom, pos, vid, ref, alt, _qual, _filt, info, fmt, sample = cols[:10]
            info_d = {}
            for kv in info.split(";"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    info_d[k] = v
            af = float(info_d.get("AF", "0.5") or "0.5")
            gene = info_d.get("GENE", "")
            fmt_keys = fmt.split(":")
            sample_vals = sample.split(":")
            sample_d = dict(zip(fmt_keys, sample_vals))
            gt = sample_d.get("GT", "./.")
            # genotype dosage: count ALT alleles. Phased "1|0" / unphased "0/1".
            tokens = re.split(r"[|/]", gt)
            try:
                dosage = sum(1 for t in tokens if t == "1")
            except Exception:
                dosage = 0
            records.append(
                {
                    "rsid": vid,
                    "chrom": chrom,
                    "pos": int(pos),
                    "ref": ref,
                    "alt": alt,
                    "alt_freq": af,
                    "dosage": dosage,
                    "gene": gene,
                }
            )
    return records


def parse_genome_reconstruction(path: Path) -> list[dict[str, Any]]:
    """
    Parse the .genome reconstruction markdown.

    Each `## Gene:` block contains a Variant + Genotype line for variant-
    style entries, or a Phenotype + Guidance pair for PGx-style entries.
    PGx entries collapse across multiple underlying loci into one phenotype
    call, so they contribute fewer independent markers than the underlying
    VCF. We model that collapse honestly in `count_markers_genome`.
    """
    text = path.read_text()
    blocks = re.split(r"^## Gene: ", text, flags=re.MULTILINE)[1:]
    records: list[dict[str, Any]] = []
    for blk in blocks:
        gene_line, *rest = blk.splitlines()
        gene = gene_line.split("(")[0].strip()
        body = "\n".join(rest)
        is_pgx = "Phenotype" in body and "Variant" not in body
        # Try to capture rsID
        m_rs = re.search(r"(rs\d+)", body)
        rsid = m_rs.group(1) if m_rs else f"gene:{gene}"
        # Try to capture genotype string
        m_gt = re.search(r"Genotype\*\*:\s*([^\n]+)", body)
        gt_str = m_gt.group(1).strip() if m_gt else ""
        records.append(
            {
                "rsid": rsid,
                "gene": gene,
                "is_pgx_collapsed": is_pgx,
                "gt_str": gt_str,
            }
        )
    return records


def parse_bio_facts(bio_root: Path) -> list[dict[str, Any]]:
    """Parse all variant facts in a .bio bundle's facts/ tree."""
    facts: list[dict[str, Any]] = []
    facts_dir = bio_root / "facts"
    if not facts_dir.exists():
        return facts
    for fp in sorted(facts_dir.rglob("*.json")):
        try:
            d = json.loads(fp.read_text())
        except json.JSONDecodeError:
            continue
        if d.get("kind") != "variant":
            continue
        facts.append(d)
    return facts


def parse_bio_views(bio_root: Path) -> list[dict[str, Any]]:
    """Parse claim blocks out of all rendered views/*.md files.

    Each claim is a top-level decision (phenotype, drug-guidance, etc.).
    A view-only leak exposes claim TEXT (e.g. "CYP2C19 IM") without
    revealing which underlying loci contributed."""
    claims: list[dict[str, Any]] = []
    views_dir = bio_root / "views"
    if not views_dir.exists():
        return claims
    claim_re = re.compile(
        r"<!--\s*claim_id:\s*(?P<cid>claim:[0-9a-f]+)\s*\|\s*level:\s*(?P<level>[\w\-]+)"
    )
    for vp in sorted(views_dir.glob("*.md")):
        for m in claim_re.finditer(vp.read_text()):
            claims.append({"claim_id": m.group("cid"), "level": m.group("level"),
                           "view": vp.name})
    return claims


# ---------------------------------------------------------------------------
# 2. Per-locus information content.
#    Under HWE, an SNV with ALT freq p has genotype probabilities
#    (1-p)^2, 2p(1-p), p^2. Shannon entropy H_locus = -sum p_i log2 p_i.
#    For the worst-case attacker, the whole-fingerprint match probability
#    given the observed dosage vector (g_1, ..., g_M) is the product of
#    per-locus genotype probabilities.
# ---------------------------------------------------------------------------


def hwe_genotype_probs(alt_freq: float) -> tuple[float, float, float]:
    p = max(min(alt_freq, 1.0), 0.0)
    q = 1.0 - p
    return q * q, 2 * p * q, p * p


def locus_entropy(alt_freq: float) -> float:
    probs = hwe_genotype_probs(alt_freq)
    return -sum(pi * math.log2(pi) for pi in probs if pi > 0.0)


def fingerprint_match_prob(records: list[dict[str, Any]]) -> float:
    """
    Population probability that a random individual matches the observed
    fingerprint EXACTLY. Independent loci assumption (no LD).
    """
    p_match = 1.0
    for r in records:
        probs = hwe_genotype_probs(r["alt_freq"])
        p_match *= probs[r["dosage"]]
    return p_match


# ---------------------------------------------------------------------------
# 3. Re-identification probability in a reference population of size N.
#    Standard Erlich-Narayanan calculation (their Box 1):
#
#      Expected matches = 1 + (N - 1) * P_match
#      P(unique re-id) = ((1 - P_match)^(N-1))
#
#    The second formula is the probability that NO other individual in the
#    panel matches; given the target IS in the panel, that's also the
#    probability of unambiguous re-id.
# ---------------------------------------------------------------------------


def reid_probability(p_match: float, population: int) -> float:
    """Probability that the target is uniquely identified by their fingerprint."""
    if p_match <= 0.0:
        return 1.0
    if p_match >= 1.0:
        return 0.0
    # log-space for numerical stability with large N.
    log_p = (population - 1) * math.log1p(-p_match)
    return math.exp(log_p)


def expected_matches(p_match: float, population: int) -> float:
    return 1.0 + (population - 1) * p_match


# ---------------------------------------------------------------------------
# 4. Per-format aggregation. Each format function returns a `Scenario` dict
#    with all metrics and a tag.
# ---------------------------------------------------------------------------


def scenario_vcf(records: list[dict[str, Any]]) -> dict[str, Any]:
    used = [r for r in records if r["rsid"].startswith("rs")]
    fingerprint_entropy = sum(locus_entropy(r["alt_freq"]) for r in used)
    p_match = fingerprint_match_prob(used)
    return {
        "format": "vcf_raw",
        "description": "Full per-locus genotype, rsID and position. "
                       "Worst-case attack surface for a single-sample VCF.",
        "marker_count": len(used),
        "fingerprint_entropy_bits": fingerprint_entropy,
        "fingerprint_match_prob": p_match,
        "fingerprint_log10_match_prob": (math.log10(p_match)
                                         if p_match > 0 else float("-inf")),
        "loci": [
            {"rsid": r["rsid"], "alt_freq": r["alt_freq"], "dosage": r["dosage"],
             "gene": r["gene"]}
            for r in used
        ],
    }


def scenario_genome(genome_records: list[dict[str, Any]],
                    vcf_records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    .genome reconstruction. Each non-PGx-collapsed gene block exposes a
    genotype string the attacker can resolve back to a dosage. PGx blocks
    name the phenotype but not the per-locus dosage, collapsing 1+ loci
    into a single phenotype call.

    We map each .genome record back to the matching VCF record (by rsID
    where available) to get population frequencies. PGx-collapsed blocks
    use a phenotype-level ALT-frequency proxy (see notes in README).
    """
    rs_to_vcf = {r["rsid"]: r for r in vcf_records}
    used: list[dict[str, Any]] = []
    collapsed_pgx_phenotypes = 0
    for g in genome_records:
        if g["is_pgx_collapsed"]:
            collapsed_pgx_phenotypes += 1
            continue
        vcf_r = rs_to_vcf.get(g["rsid"])
        if vcf_r is None:
            # rsID not in VCF (shouldn't happen for our example, but be safe)
            continue
        used.append(vcf_r)

    # Each collapsed PGx phenotype is treated as a single coarse marker
    # with phenotype-level entropy. For PharmCAT-style 4-bin phenotype
    # distributions (PM, IM, NM, RM/UM) we use a uniform-ish prior:
    # NM ~ 0.55, IM ~ 0.30, PM ~ 0.05, RM/UM ~ 0.10 for CYP2C19 in 1000G.
    # Source: Bertilsson 2002, Mizutani 2003. We use these only as a
    # plausible upper-bound entropy for one collapsed locus.
    phenotype_probs = (0.55, 0.30, 0.05, 0.10)
    collapsed_entropy_per_phen = -sum(p * math.log2(p) for p in phenotype_probs if p > 0)

    fingerprint_entropy = (
        sum(locus_entropy(r["alt_freq"]) for r in used)
        + collapsed_pgx_phenotypes * collapsed_entropy_per_phen
    )
    p_match_variant = fingerprint_match_prob(used)
    # Probability of matching collapsed phenotype labels: assume the most
    # common phenotype (NM, p=0.55) for the fingerprint, conservatively.
    p_match_pheno = max(phenotype_probs) ** collapsed_pgx_phenotypes
    p_match = p_match_variant * p_match_pheno

    return {
        "format": "genome_reconstruction",
        "description": "Markdown reconstruction with per-gene blocks. "
                       "Variant blocks expose genotypes; PGx blocks expose "
                       "only collapsed phenotype labels.",
        "marker_count": len(used) + collapsed_pgx_phenotypes,
        "variant_marker_count": len(used),
        "collapsed_pgx_phenotypes": collapsed_pgx_phenotypes,
        "fingerprint_entropy_bits": fingerprint_entropy,
        "fingerprint_match_prob": p_match,
        "fingerprint_log10_match_prob": (math.log10(p_match)
                                         if p_match > 0 else float("-inf")),
        "loci": [
            {"rsid": r["rsid"], "alt_freq": r["alt_freq"], "dosage": r["dosage"],
             "gene": r["gene"]}
            for r in used
        ],
        "notes": ("PGx phenotype probs (CYP2C19 1000G EUR-ish): "
                  "NM=0.55, IM=0.30, PM=0.05, RM/UM=0.10"),
    }


def scenario_bio_facts(bio_facts: list[dict[str, Any]],
                       vcf_records: list[dict[str, Any]],
                       ruleset_public: bool = True) -> dict[str, Any]:
    """
    .bio bundle, facts/ tree leaked.

    Critical modeling note: .bio facts are content-addressed via SHA-256
    of the canonical JSON. SHA-256 is one-way at the bit level. BUT the
    canonical fact JSON has a tiny enumeration space per locus (3 dosages
    × small allele set), so an attacker who holds the public ruleset can
    enumerate all plausible JSONs and recover the dosage by hash matching.

    Because dotbio v0 publishes the ruleset (intentional; it's the
    published interpretation logic), the ruleset_public branch is the
    realistic threat. We expose this as a parameter so the JSON output
    reflects both worlds:
      ruleset_public=True  -> hash leaks dosage (equivalent to VCF, modulo
                              loss of the chrom:pos coordinate if the
                              attacker doesn't have it)
      ruleset_public=False -> hash leaks nothing usable for re-id

    In our facts JSON, the genotype field is stored in plaintext alongside
    the rsid. So the realistic .bio leak is plaintext-equivalent on the
    set of loci that have facts/ entries.
    """
    rs_to_vcf = {r["rsid"]: r for r in vcf_records}
    used: list[dict[str, Any]] = []
    for f in bio_facts:
        rsid = f.get("rsid")
        if not rsid:
            continue
        vcf_r = rs_to_vcf.get(rsid)
        if vcf_r is None:
            continue
        used.append(vcf_r)

    if not ruleset_public:
        # Hash is opaque; attacker can't read genotypes. Re-id probability
        # collapses to 1/N (random pick).
        return {
            "format": "bio_facts_hash_only",
            "description": "Hash-only attack (attacker lacks ruleset). "
                           "SHA-256 pre-image resistance dominates; no "
                           "per-locus information is recoverable.",
            "marker_count": 0,
            "fingerprint_entropy_bits": 0.0,
            "fingerprint_match_prob": 1.0,  # everyone matches the empty fingerprint
            "fingerprint_log10_match_prob": 0.0,
            "loci": [],
        }

    fingerprint_entropy = sum(locus_entropy(r["alt_freq"]) for r in used)
    p_match = fingerprint_match_prob(used)
    return {
        "format": "bio_facts_with_public_ruleset",
        "description": "Realistic .bio attack: facts/ leaked AND attacker "
                       "holds the public ruleset. Brute-force recovery of "
                       "per-locus dosage by enumerating the small JSON space.",
        "marker_count": len(used),
        "fingerprint_entropy_bits": fingerprint_entropy,
        "fingerprint_match_prob": p_match,
        "fingerprint_log10_match_prob": (math.log10(p_match)
                                         if p_match > 0 else float("-inf")),
        "loci": [
            {"rsid": r["rsid"], "alt_freq": r["alt_freq"], "dosage": r["dosage"],
             "gene": r["gene"]}
            for r in used
        ],
    }


def scenario_bio_views(bio_view_claims: list[dict[str, Any]],
                       vcf_records: list[dict[str, Any]]) -> dict[str, Any]:
    """
    .bio bundle, ONLY views/ leaked (facts/ kept private).

    Each top-level claim collapses one or more loci into a single
    phenotype-level statement (e.g., "CYP2C19 IM"). This is the
    minimum-information leak scenario for .bio.

    For each phenotype-level claim we use the same 4-bin PGx phenotype
    prior as in scenario_genome. For germline-clinical claims (P/LP
    classification of a single rsID), the attacker can usually recover
    the rsID and dosage from the rendered text, so we treat those as
    plaintext-equivalent on that one locus.
    """
    pgx_phenotype_claims = sum(1 for c in bio_view_claims
                               if c["level"] == "phenotype")
    drug_claims = sum(1 for c in bio_view_claims
                      if c["level"] == "clinical_decision")
    # Each germline-clinical claim that names a P/LP rsID exposes one
    # plaintext locus. We approximate by counting any non-PGx claim and
    # assigning it the matching VCF locus by rough heuristic. To stay
    # honest we count claim_count-pheno_count exposed loci, drawing
    # ALT freqs from the rarest sites (most-informative upper bound).
    germline_clinical_claims = sum(1 for c in bio_view_claims
                                   if c["level"] not in ("phenotype",
                                                          "clinical_decision"))

    pheno_probs = (0.55, 0.30, 0.05, 0.10)
    H_pheno = -sum(p * math.log2(p) for p in pheno_probs if p > 0)

    # Drug claims are 1:1 derived from phenotype claims; they don't add
    # independent entropy (they're a deterministic function of phenotype).
    independent_pheno = pgx_phenotype_claims
    # Pick the rarest VCF loci for germline-clinical claims (worst case).
    sorted_by_rarity = sorted(vcf_records, key=lambda r: r["alt_freq"])
    used_germline = sorted_by_rarity[:germline_clinical_claims]
    H_germline = sum(locus_entropy(r["alt_freq"]) for r in used_germline)

    fingerprint_entropy = independent_pheno * H_pheno + H_germline
    p_match_pheno = max(pheno_probs) ** independent_pheno
    p_match_germ = fingerprint_match_prob(used_germline) if used_germline else 1.0
    p_match = p_match_pheno * p_match_germ

    return {
        "format": "bio_views_only",
        "description": "Minimum-leak scenario: only the rendered views/*.md "
                       "files are exposed; facts/ kept private. PGx claims "
                       "collapse to coarse phenotype labels.",
        "marker_count": independent_pheno + germline_clinical_claims,
        "phenotype_claims": independent_pheno,
        "drug_claims_dependent_on_phenotypes": drug_claims,
        "germline_clinical_claims": germline_clinical_claims,
        "fingerprint_entropy_bits": fingerprint_entropy,
        "fingerprint_match_prob": p_match,
        "fingerprint_log10_match_prob": (math.log10(p_match)
                                         if p_match > 0 else float("-inf")),
        "notes": ("PGx phenotype probs (CYP2C19 1000G EUR-ish): "
                  "NM=0.55, IM=0.30, PM=0.05, RM/UM=0.10. Drug-guidance "
                  "claims are a deterministic function of phenotype claims "
                  "and contribute no independent entropy."),
    }


# ---------------------------------------------------------------------------
# 5. Bootstrap. Resample loci with replacement; recompute the fingerprint
#    metrics; report 95% CI on (entropy, match_prob, reid_prob).
#    This estimates uncertainty due to which subset of loci ended up in
#    the leak — an attacker may not see all M markers in practice.
# ---------------------------------------------------------------------------


def _bootstrap_one(loci: list[dict[str, Any]], population: int,
                   seed: int) -> dict[str, float]:
    rng = random.Random(seed)
    if not loci:
        return {"entropy": 0.0, "match_prob": 1.0, "reid_prob": 0.0,
                "expected_matches": float(population)}
    sampled = [rng.choice(loci) for _ in range(len(loci))]
    H = sum(locus_entropy(r["alt_freq"]) for r in sampled)
    pm = 1.0
    for r in sampled:
        probs = hwe_genotype_probs(r["alt_freq"])
        d = r.get("dosage", 0)
        pm *= probs[d]
    return {
        "entropy": H,
        "match_prob": pm,
        "reid_prob": reid_probability(pm, population),
        "expected_matches": expected_matches(pm, population),
    }


def bootstrap_ci(loci: list[dict[str, Any]],
                 population: int,
                 n_iter: int,
                 seed_base: int = 0) -> dict[str, dict[str, float]]:
    if not loci:
        return {
            "entropy_bits": {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0},
            "match_prob":   {"mean": 1.0, "ci_low": 1.0, "ci_high": 1.0},
            "reid_prob":    {"mean": 0.0, "ci_low": 0.0, "ci_high": 0.0},
            "expected_matches": {"mean": float(population),
                                 "ci_low": float(population),
                                 "ci_high": float(population)},
        }

    samples = [_bootstrap_one(loci, population, seed_base + i) for i in range(n_iter)]

    def ci(values: list[float]) -> dict[str, float]:
        s = sorted(values)
        lo_idx = max(0, int(0.025 * len(s)) - 1)
        hi_idx = min(len(s) - 1, int(0.975 * len(s)))
        return {
            "mean": statistics.fmean(values),
            "ci_low": s[lo_idx],
            "ci_high": s[hi_idx],
        }

    return {
        "entropy_bits":      ci([x["entropy"] for x in samples]),
        "match_prob":        ci([x["match_prob"] for x in samples]),
        "reid_prob":         ci([x["reid_prob"] for x in samples]),
        "expected_matches":  ci([x["expected_matches"] for x in samples]),
    }


# ---------------------------------------------------------------------------
# 6. Top-level driver.
# ---------------------------------------------------------------------------


def run_analysis(args: argparse.Namespace) -> dict[str, Any]:
    vcf_records = parse_vcf(Path(args.vcf))
    genome_records = parse_genome_reconstruction(Path(args.genome))
    bio_facts = parse_bio_facts(Path(args.bio))
    bio_view_claims = parse_bio_views(Path(args.bio))

    scenarios = [
        scenario_vcf(vcf_records),
        scenario_genome(genome_records, vcf_records),
        scenario_bio_facts(bio_facts, vcf_records, ruleset_public=True),
        scenario_bio_facts(bio_facts, vcf_records, ruleset_public=False),
        scenario_bio_views(bio_view_claims, vcf_records),
    ]

    # Attach point estimate of reid probability + bootstrap CI to each.
    for s in scenarios:
        loci = s.get("loci", []) or []
        # For collapsed-phenotype scenarios, embed a synthetic locus per
        # phenotype claim so the bootstrap can resample over them. Use the
        # marker-count-implied number of slots.
        synth_loci = list(loci)
        if "phenotype_claims" in s:
            # one slot per phenotype claim with phenotype-level "freq" 0.55
            # giving the entropy mass of a 4-bin distribution.
            for _ in range(s["phenotype_claims"]):
                # Choose alt_freq so HWE entropy ~ phenotype-level entropy.
                # 0.5 yields max entropy; we use that as upper bound.
                synth_loci.append({"rsid": "phen", "alt_freq": 0.5,
                                   "dosage": 1, "gene": "PGx"})
        if "collapsed_pgx_phenotypes" in s:
            for _ in range(s["collapsed_pgx_phenotypes"]):
                synth_loci.append({"rsid": "phen", "alt_freq": 0.5,
                                   "dosage": 1, "gene": "PGx"})
        s["point_reid_prob_pop_{}".format(args.population)] = reid_probability(
            s.get("fingerprint_match_prob", 1.0), args.population
        )
        s["point_expected_matches_pop_{}".format(args.population)] = expected_matches(
            s.get("fingerprint_match_prob", 1.0), args.population
        )
        s["bootstrap_ci_95"] = bootstrap_ci(
            synth_loci, args.population, n_iter=args.bootstrap, seed_base=42
        )

    out = {
        "tool": "reid_risk.py",
        "spec_section": "bench/v2/SPEC.md §3.6",
        "task": "TASKS.md Task 8",
        "reference": ("Erlich, Y. & Narayanan, A. Routes for breaching and "
                      "protecting genetic privacy. Nat Rev Genet 15, 409-421 "
                      "(2014). doi:10.1038/nrg3723"),
        "threat_model": (
            "Attacker holds a population reference panel of size N=%d "
            "with known genotypes at all leaked loci. Loci are assumed "
            "independent (no LD); ALT-allele frequencies under "
            "Hardy-Weinberg equilibrium. The probability that a random "
            "individual in the panel matches the leaked fingerprint is "
            "the product of per-locus genotype probabilities. The "
            "probability of unique re-identification given the target is "
            "in the panel is (1 - P_match)^(N - 1)."
        ) % args.population,
        "population_size": args.population,
        "bootstrap_iters": args.bootstrap,
        "inputs": {
            "vcf": str(Path(args.vcf).resolve()),
            "genome": str(Path(args.genome).resolve()),
            "bio": str(Path(args.bio).resolve()),
        },
        "subject": "NA12878 (8-locus PGx VIP panel)",
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "scenarios": scenarios,
        "summary": _summary(scenarios, args.population),
    }
    return out


def _summary(scenarios: list[dict[str, Any]], population: int) -> dict[str, Any]:
    rows = []
    for s in scenarios:
        rows.append({
            "format": s["format"],
            "marker_count": s["marker_count"],
            "fingerprint_entropy_bits": round(s["fingerprint_entropy_bits"], 3),
            "fingerprint_log10_match_prob": (
                round(s["fingerprint_log10_match_prob"], 3)
                if math.isfinite(s["fingerprint_log10_match_prob"]) else None
            ),
            "point_reid_prob": round(
                s["point_reid_prob_pop_{}".format(population)], 6
            ),
            "expected_matches": round(
                s["point_expected_matches_pop_{}".format(population)], 3
            ),
            "ci95_reid_prob": [
                round(s["bootstrap_ci_95"]["reid_prob"]["ci_low"], 6),
                round(s["bootstrap_ci_95"]["reid_prob"]["ci_high"], 6),
            ],
        })
    return {
        "ranking_low_to_high_risk": sorted(
            (r["format"] for r in rows),
            key=lambda fmt: next(rr["point_reid_prob"] for rr in rows if rr["format"] == fmt)
        ),
        "rows": rows,
    }


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    here = Path(__file__).resolve().parent
    repo = here.parent.parent.parent  # bench/v2/scripts -> repo root
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--vcf", default=str(repo / "examples/real-na12878/input.vcf"))
    p.add_argument("--genome",
                   default=str(repo / "bench/data/format_b_genome_reconstructed.md"))
    p.add_argument("--bio", default=str(repo / "examples/real-na12878/output.bio"))
    p.add_argument("--out",
                   default=str(repo / "bench/v2/results/exp06_reid_risk.json"))
    p.add_argument("--population", type=int, default=100_000)
    p.add_argument("--bootstrap", type=int, default=1000)
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out = run_analysis(args)
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, default=str) + "\n")

    print(f"reid_risk: wrote {out_path}", file=sys.stderr)
    print("\nSUMMARY (population N={}):".format(args.population), file=sys.stderr)
    for row in out["summary"]["rows"]:
        print(("  {format:38s}  markers={marker_count:>3}  "
               "H={fingerprint_entropy_bits:>7.3f}  "
               "P_reid={point_reid_prob:.6g}  "
               "CI95=[{lo:.6g}, {hi:.6g}]")
              .format(lo=row["ci95_reid_prob"][0], hi=row["ci95_reid_prob"][1],
                      **row),
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
