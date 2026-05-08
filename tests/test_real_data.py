"""Real-data smoke test using NA12878 from 1000 Genomes.

NA12878 (HapMap CEU sample, female, public benchmark genome) is the
single most-validated public human genome. The VCF in
examples/real-na12878/input.vcf was extracted from the 1000 Genomes
Project 30x high-coverage phased panel (20220422 release).

These tests verify that dotbio produces biologically correct claims for
this individual at known PGx loci, not just on hand-crafted synthetic
inputs.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
NA12878_VCF = REPO / "examples" / "real-na12878" / "input.vcf"


def run_bio(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dotbio", *args],
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )


def test_real_vcf_compiles_without_error(tmp_path: Path) -> None:
    bundle = tmp_path / "na12878.bio"
    r = run_bio("compile", str(NA12878_VCF), "-o", str(bundle), "--subject", "NA12878")
    assert r.returncode == 0
    assert bundle.is_dir()
    assert (bundle / "manifest.json").is_file()


def test_na12878_is_cyp2c19_intermediate_metabolizer(tmp_path: Path) -> None:
    """NA12878 is a well-characterized CYP2C19 *1/*2 individual.

    rs4244285 (CYP2C19 *2 SNP) is heterozygous in NA12878 per 1000 Genomes;
    the engine should call diplotype *1/*2 → Intermediate Metabolizer.
    """
    bundle = tmp_path / "na12878.bio"
    run_bio("compile", str(NA12878_VCF), "-o", str(bundle))
    pgx = (bundle / "views" / "pgx.md").read_text()
    assert "CYP2C19" in pgx
    assert "Intermediate Metabolizer" in pgx
    assert "*1/*2" in pgx


def test_na12878_gets_clopidogrel_guidance(tmp_path: Path) -> None:
    """CYP2C19 IM phenotype should produce clopidogrel guidance per CPIC."""
    bundle = tmp_path / "na12878.bio"
    run_bio("compile", str(NA12878_VCF), "-o", str(bundle))
    pgx = (bundle / "views" / "pgx.md").read_text()
    assert "clopidogrel" in pgx
    assert "CPIC@2022" in pgx


def test_na12878_mthfr_heterozygous(tmp_path: Path) -> None:
    """rs1801133 in NA12878 is heterozygous (1|0 in 1000G), so the ClinVar
    drug_response claim for Folate metabolism should fire."""
    bundle = tmp_path / "na12878.bio"
    run_bio("compile", str(NA12878_VCF), "-o", str(bundle))
    germline = (bundle / "views" / "germline-clinical.md").read_text()
    assert "MTHFR" in germline
    assert "drug_response" in germline


def test_na12878_no_apoe_e4_claim(tmp_path: Path) -> None:
    """NA12878 is APOE ε3/ε3 (rs429358 T/T, rs7412 C/C), so the AD-risk
    claim should NOT fire — this verifies the engine doesn't false-positive."""
    bundle = tmp_path / "na12878.bio"
    run_bio("compile", str(NA12878_VCF), "-o", str(bundle))
    germline = (bundle / "views" / "germline-clinical.md").read_text()
    assert "APOE" not in germline


def test_na12878_no_factor_v_leiden(tmp_path: Path) -> None:
    """NA12878 is rs6025 C/C (no Factor V Leiden) — verify no VTE claim."""
    bundle = tmp_path / "na12878.bio"
    run_bio("compile", str(NA12878_VCF), "-o", str(bundle))
    germline = (bundle / "views" / "germline-clinical.md").read_text()
    assert "Factor V Leiden" not in germline
    assert "Venous thromboembolism" not in germline


def test_na12878_facts_persist_negative_results(tmp_path: Path) -> None:
    """Even when a position is reference (no claim), the fact must be stored.
    'Checked and negative' is information that survives in the bundle."""
    bundle = tmp_path / "na12878.bio"
    run_bio("compile", str(NA12878_VCF), "-o", str(bundle))
    r = run_bio("facts", str(bundle))
    assert "rs429358" in r.stdout  # APOE checked
    assert "rs1800562" in r.stdout  # HFE checked
    assert "rs1142345" not in r.stdout  # not in input VCF, should not appear


def test_na12878_manifest_has_correct_subject_and_scopes(tmp_path: Path) -> None:
    bundle = tmp_path / "na12878.bio"
    run_bio("compile", str(NA12878_VCF), "-o", str(bundle), "--subject", "NA12878")
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["subject"] == "NA12878"
    assert manifest["scopes"]["germline_variant_count"] == 8  # 8 rows in VCF
    assert manifest["scopes"]["somatic_call_count"] == 0  # no SOMATIC flag in input
