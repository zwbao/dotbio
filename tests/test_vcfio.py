"""VCF parser tests."""

from __future__ import annotations

import textwrap
from pathlib import Path

from dotbio.vcfio import parse_vcf


def write_vcf(tmp_path: Path, body: str) -> Path:
    header = textwrap.dedent("""\
        ##fileformat=VCFv4.2
        ##reference=GRCh38
        ##INFO=<ID=DP,Number=1,Type=Integer,Description="Depth">
        ##INFO=<ID=SOMATIC,Number=0,Type=Flag,Description="Somatic">
        ##INFO=<ID=ANN,Number=1,Type=String,Description="Annotation">
        ##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
        ##FORMAT=<ID=DP,Number=1,Type=Integer,Description="Depth">
        #CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tS1
    """)
    path = tmp_path / "in.vcf"
    path.write_text(header + body)
    return path


def test_parse_minimal_record(tmp_path: Path) -> None:
    p = write_vcf(tmp_path, "chr1\t100\trs1\tA\tG\t30\tPASS\tDP=20\tGT:DP\t0/1:20\n")
    recs = list(parse_vcf(p))
    assert len(recs) == 1
    r = recs[0]
    assert r.chrom == "chr1"
    assert r.pos == 100
    assert r.rsid == "rs1"
    assert r.ref == "A"
    assert r.alt == "G"
    assert r.qual == 30.0
    assert r.filter_ == "PASS"
    assert r.info["DP"] == "20"
    assert r.sample["GT"] == "0/1"
    assert r.sample["DP"] == "20"


def test_genotype_normalization_het(tmp_path: Path) -> None:
    p = write_vcf(tmp_path, "chr1\t100\t.\tA\tG\t30\tPASS\t.\tGT\t0/1\n")
    r = next(parse_vcf(p))
    assert r.genotype == "A/G"
    assert r.rsid is None
    assert r.is_homref is False


def test_genotype_normalization_hom_alt(tmp_path: Path) -> None:
    p = write_vcf(tmp_path, "chr1\t100\trsX\tA\tG\t30\tPASS\t.\tGT\t1/1\n")
    r = next(parse_vcf(p))
    assert r.genotype == "G/G"
    assert r.is_homref is False


def test_genotype_normalization_hom_ref(tmp_path: Path) -> None:
    p = write_vcf(tmp_path, "chr1\t100\trsX\tA\tG\t30\tPASS\t.\tGT\t0/0\n")
    r = next(parse_vcf(p))
    assert r.genotype == "A/A"
    assert r.is_homref is True


def test_phased_genotype_treated_as_unphased(tmp_path: Path) -> None:
    p = write_vcf(tmp_path, "chr1\t100\trsX\tA\tG\t30\tPASS\t.\tGT\t0|1\n")
    r = next(parse_vcf(p))
    assert r.genotype == "A/G"


def test_indel_genotype(tmp_path: Path) -> None:
    p = write_vcf(tmp_path, "chr7\t117559590\trsCFTR\tCTT\tC\t30\tPASS\t.\tGT\t0/1\n")
    r = next(parse_vcf(p))
    assert r.ref == "CTT"
    assert r.alt == "C"
    assert r.genotype == "CTT/C"


def test_info_flag_parsed_as_true(tmp_path: Path) -> None:
    p = write_vcf(tmp_path, "chr1\t100\t.\tA\tG\t30\tPASS\tSOMATIC;DP=10\tGT\t0/1\n")
    r = next(parse_vcf(p))
    assert r.info["SOMATIC"] is True
    assert r.info["DP"] == "10"


def test_info_annotation_parsed(tmp_path: Path) -> None:
    p = write_vcf(tmp_path, "chr17\t100\t.\tG\tA\t30\tPASS\tANN=TP53:p.R175H\tGT\t0/1\n")
    r = next(parse_vcf(p))
    assert r.info["ANN"] == "TP53:p.R175H"


def test_skip_blank_lines_and_comments(tmp_path: Path) -> None:
    body = "\n\nchr1\t100\t.\tA\tG\t30\tPASS\t.\tGT\t0/1\n\n"
    p = write_vcf(tmp_path, body)
    recs = list(parse_vcf(p))
    assert len(recs) == 1


def test_missing_qual_handled(tmp_path: Path) -> None:
    p = write_vcf(tmp_path, "chr1\t100\t.\tA\tG\t.\tPASS\t.\tGT\t0/1\n")
    r = next(parse_vcf(p))
    assert r.qual is None
