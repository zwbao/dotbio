"""Rule engine tests — ClinVar, PharmCAT, OncoKB application."""

from __future__ import annotations

from dotbio.engine import apply_clinvar, apply_oncokb, apply_pharmcat, load_ruleset


# ---- ClinVar -----------------------------------------------------------


def _v(rsid: str, ref: str, alt: str, gt: str, **extra) -> dict:
    return {
        "kind": "variant",
        "chrom": "chr1",
        "pos": 100,
        "ref": ref,
        "alt": alt,
        "rsid": rsid,
        "genotype": gt,
        "build": "GRCh38",
        **extra,
    }


def test_clinvar_matches_homozygous_variant() -> None:
    rs = load_ruleset("clinvar@2026-05-01")
    fact = _v("rs429358", "T", "C", "C/C")
    claims = apply_clinvar([("sha256:abc", fact)], rs)
    assert len(claims) == 1
    c = claims[0]
    assert c["level"] == "variant"
    assert c["gene"] == "APOE"
    assert c["significance"] == "risk_factor"
    assert c["targets"] == ["sha256:abc"]
    assert c["ruleset"] == "clinvar@2026-05-01"
    assert "Late-onset Alzheimer" in c["condition"]


def test_clinvar_matches_heterozygous_variant() -> None:
    rs = load_ruleset("clinvar@2026-05-01")
    fact = _v("rs429358", "T", "C", "T/C")
    claims = apply_clinvar([("sha256:abc", fact)], rs)
    assert len(claims) == 1
    assert claims[0]["significance"] == "risk_factor"


def test_clinvar_genotype_order_invariant() -> None:
    """A heterozygous call written 'C/T' should match a rule keyed as 'T/C'."""
    rs = load_ruleset("clinvar@2026-05-01")
    fact = _v("rs429358", "T", "C", "C/T")  # alt/ref instead of ref/alt
    claims = apply_clinvar([("sha256:abc", fact)], rs)
    assert len(claims) == 1


def test_clinvar_skips_unknown_rsid() -> None:
    rs = load_ruleset("clinvar@2026-05-01")
    fact = _v("rsXXX", "T", "C", "T/C")
    claims = apply_clinvar([("sha256:abc", fact)], rs)
    assert claims == []


def test_clinvar_skips_no_rsid() -> None:
    rs = load_ruleset("clinvar@2026-05-01")
    fact = _v(None, "T", "C", "T/C")  # type: ignore[arg-type]
    fact.pop("rsid")
    claims = apply_clinvar([("sha256:abc", fact)], rs)
    assert claims == []


def test_clinvar_carries_previous_classification_on_reclassification() -> None:
    rs_new = load_ruleset("clinvar@2026-05-08")
    fact = _v("rs80357906", "GAG", "G", "GAG/G")
    claims = apply_clinvar([("sha256:abc", fact)], rs_new)
    assert len(claims) == 1
    c = claims[0]
    assert c["significance"] == "pathogenic"
    assert c["previous_classification"] == "likely_pathogenic"
    assert c["reclassified_on"] == "2026-05-08"


def test_clinvar_indel_genotype_match() -> None:
    rs = load_ruleset("clinvar@2026-05-01")
    fact = _v("rs113993960", "CTT", "C", "CTT/C")
    claims = apply_clinvar([("sha256:abc", fact)], rs)
    assert len(claims) == 1
    assert claims[0]["gene"] == "CFTR"
    assert claims[0]["significance"] == "carrier"


# ---- PharmCAT (haplotype calling) --------------------------------------


def test_pharmcat_calls_homozygous_star17() -> None:
    rs = load_ruleset("pharmcat@2025.3")
    fact = _v("rs12248560", "C", "T", "T/T")  # homozygous *17 SNP
    claims = apply_pharmcat([("sha256:f17", fact)], rs)
    levels = {c["level"] for c in claims}
    assert "haplotype" in levels
    assert "phenotype" in levels
    diplotype_claim = next(c for c in claims if c["level"] == "haplotype")
    assert diplotype_claim["diplotype"] == "*17/*17"
    pheno_claim = next(c for c in claims if c["level"] == "phenotype")
    assert pheno_claim["phenotype"] == "Ultrarapid Metabolizer"


def test_pharmcat_calls_heterozygous_star3c_tpmt() -> None:
    rs = load_ruleset("pharmcat@2025.3")
    fact = _v("rs1142345", "T", "C", "T/C")
    claims = apply_pharmcat([("sha256:tpmt", fact)], rs)
    diplotype = next(c for c in claims if c["level"] == "haplotype")["diplotype"]
    pheno = next(c for c in claims if c["level"] == "phenotype")["phenotype"]
    assert diplotype == "*1/*3C"
    assert pheno == "Intermediate Metabolizer"


def test_pharmcat_emits_per_drug_guidance() -> None:
    rs = load_ruleset("pharmcat@2025.3")
    fact = _v("rs12248560", "C", "T", "T/T")
    claims = apply_pharmcat([("sha256:f17", fact)], rs)
    drugs = {c.get("drug") for c in claims if c["level"] == "clinical_decision"}
    assert "clopidogrel" in drugs
    assert "voriconazole" in drugs


def test_pharmcat_skips_genes_with_no_observations() -> None:
    """If no DPYD variants are observed, no DPYD claims should be produced."""
    rs = load_ruleset("pharmcat@2025.3")
    fact = _v("rs12248560", "C", "T", "T/T")  # CYP2C19 only
    claims = apply_pharmcat([("sha256:f17", fact)], rs)
    genes_with_claims = {c.get("gene") for c in claims}
    assert "DPYD" not in genes_with_claims
    assert "TPMT" not in genes_with_claims


def test_pharmcat_haplotype_targets_point_back_to_facts() -> None:
    rs = load_ruleset("pharmcat@2025.3")
    fact = _v("rs12248560", "C", "T", "T/T")
    claims = apply_pharmcat([("sha256:abc123", fact)], rs)
    for c in claims:
        assert "sha256:abc123" in c["targets"]


# ---- OncoKB ------------------------------------------------------------


def test_oncokb_matches_somatic_annotation() -> None:
    rs = load_ruleset("oncokb@2026-04-15")
    fact = {
        "kind": "variant",
        "chrom": "chr17",
        "pos": 7675088,
        "ref": "G",
        "alt": "A",
        "rsid": "rs28934578",
        "genotype": "G/A",
        "build": "GRCh38",
        "somatic": True,
        "annotation": "TP53:p.R175H",
    }
    claims = apply_oncokb([("sha256:tp53", fact)], rs)
    assert len(claims) == 1
    c = claims[0]
    assert c["gene"] == "TP53"
    assert c["alteration"] == "p.R175H"
    assert c["oncogenicity"] == "Oncogenic"


def test_oncokb_skips_germline() -> None:
    """Without somatic flag the OncoKB ruleset should not produce a claim."""
    rs = load_ruleset("oncokb@2026-04-15")
    fact = {
        "kind": "variant",
        "annotation": "TP53:p.R175H",
        # no somatic flag
    }
    claims = apply_oncokb([("sha256:abc", fact)], rs)
    assert claims == []


def test_oncokb_level_field_does_not_clobber_claim_level() -> None:
    """Regression: the OncoKB 'level' field must not overwrite the claim's level."""
    rs = load_ruleset("oncokb@2026-04-15")
    fact = {
        "kind": "variant",
        "somatic": True,
        "annotation": "TP53:p.R175H",
    }
    claims = apply_oncokb([("sha256:abc", fact)], rs)
    assert claims[0]["level"] == "variant"  # not None, not the OncoKB level
    assert "oncokb_level" in claims[0]
