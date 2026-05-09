"""Malformed-VCF fuzz cases for dotbio.

Each case writes a synthetic VCF to a tempdir, invokes ``bio compile``,
and asserts that dotbio behaves per the documented expectation:

- graceful_failure: non-zero exit code with an error message on stderr
  (NOT a crash with traceback to stdout)
- successful_handling: exit 0; the malformed input was either ignored
  cleanly or coerced to a documented default
- documented_data_loss: exit 0 but with a manifest that records fewer
  facts than the raw VCF lines (i.e. the parser silently drops bad
  records — which is documented as the v0 behavior in vcfio.py)

Cases target dotbio CLI as-is; they do not modify the source.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from . import FuzzCase


# ---- helpers -----------------------------------------------------------


def _bio(args: list[str], cwd: Path) -> tuple[int, str, str]:
    """Run ``python -m dotbio <args>`` with a 30-s timeout."""
    proc = subprocess.run(
        [sys.executable, "-m", "dotbio", *args],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _write(path: Path, body: str) -> Path:
    path.write_text(body, encoding="utf-8")
    return path


def _compile(workdir: Path, vcf_text: str, *, name: str = "in.vcf") -> dict:
    vcf = _write(workdir / name, vcf_text)
    out = workdir / "out.bio"
    if out.exists():
        shutil.rmtree(out)
    rc, so, se = _bio(["compile", str(vcf), "-o", str(out)], workdir)
    return {"actual_exit": rc, "stdout": so, "stderr": se,
            "bundle_exists": out.exists()}


def _bundle_facts(bundle: Path) -> int:
    facts = bundle / "facts"
    if not facts.is_dir():
        return 0
    n = 0
    for prefix in facts.iterdir():
        if prefix.is_dir():
            n += sum(1 for _ in prefix.glob("*.json"))
    return n


# ---- VCF templates -----------------------------------------------------


_HEADER = """##fileformat=VCFv4.2
##reference=GRCh38
##contig=<ID=chr1,length=248956422>
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878
"""

_GOOD_LINE = "chr1\t11796321\trs1801133\tG\tA\t.\tPASS\t.\tGT\t1|0\n"


# ---- cases -------------------------------------------------------------


def _case_empty_file(work: Path) -> dict:
    r = _compile(work, "")
    return {**r, "ok": r["actual_exit"] == 0 and _bundle_facts(work / "out.bio") == 0,
            "notes": "Empty file: parser yields zero records; dotbio compiles an "
                     "empty bundle (documented data loss for empty-input edge)."}


def _case_header_only(work: Path) -> dict:
    r = _compile(work, _HEADER)
    return {**r, "ok": r["actual_exit"] == 0 and _bundle_facts(work / "out.bio") == 0,
            "notes": "Header-only VCF: zero data lines, zero facts, zero claims."}


def _case_missing_ref(work: Path) -> dict:
    body = _HEADER + "chr1\t11796321\trs1801133\t.\tA\t.\tPASS\t.\tGT\t1|0\n"
    r = _compile(work, body)
    return {**r, "ok": r["actual_exit"] == 0,
            "notes": "REF='.' is technically valid VCF; dotbio writes a fact with "
                     "ref='.', no clinical claim is produced (no rsID/genotype match)."}


def _case_invalid_gt(work: Path) -> dict:
    body = _HEADER + "chr1\t11796321\trs1801133\tG\tA\t.\tPASS\t.\tGT\tX/Y\n"
    r = _compile(work, body)
    return {**r, "ok": r["actual_exit"] == 0,
            "notes": "GT='X/Y' is not '0' or '1'; vcfio passes the literal through; "
                     "ruleset lookup misses; no crash."}


def _case_mixed_builds(work: Path) -> dict:
    body = _HEADER + "1\t11796321\trs1801133\tG\tA\t.\tPASS\t.\tGT\t1|0\n"
    r = _compile(work, body)
    return {**r, "ok": r["actual_exit"] == 0,
            "notes": "Chromosome '1' (no chr prefix) compiles; rsID lookup still works "
                     "because rulesets key on rsid, not on chrom string."}


def _case_truncated_record(work: Path) -> dict:
    # Only 5 columns — vcfio requires >= 8
    body = _HEADER + "chr1\t11796321\trs1801133\tG\tA\n"
    r = _compile(work, body)
    return {**r, "ok": r["actual_exit"] == 0 and _bundle_facts(work / "out.bio") == 0,
            "notes": "Truncated line (<8 cols): vcfio drops the record silently. "
                     "DOCUMENTED DATA LOSS."}


def _case_non_ascii_subject(work: Path) -> dict:
    body = _HEADER.replace("NA12878", "NA12878é")
    body += _GOOD_LINE
    r = _compile(work, body)
    return {**r, "ok": r["actual_exit"] == 0,
            "notes": "Non-ASCII sample name: header parses; record processed normally."}


def _case_huge_alt_allele(work: Path) -> dict:
    huge = "A" * 5000
    body = _HEADER + f"chr1\t11796321\trs1801133\tG\t{huge}\t.\tPASS\t.\tGT\t1|0\n"
    r = _compile(work, body)
    return {**r, "ok": r["actual_exit"] == 0,
            "notes": "5 kb ALT allele: stored verbatim; lookup misses (genotype "
                     "string is large but rulesets don't match) — robust to size."}


def _case_negative_pos(work: Path) -> dict:
    body = _HEADER + "chr1\t-100\trs1801133\tG\tA\t.\tPASS\t.\tGT\t1|0\n"
    r = _compile(work, body)
    return {**r, "ok": r["actual_exit"] == 0,
            "notes": "Negative POS is illegal per VCF spec; dotbio v0 does not "
                     "validate range — record is accepted. Acceptable today; future "
                     "v1 should reject."}


def _case_duplicate_records(work: Path) -> dict:
    body = _HEADER + _GOOD_LINE + _GOOD_LINE  # exact duplicate
    r = _compile(work, body)
    n_facts = _bundle_facts(work / "out.bio")
    return {**r, "ok": r["actual_exit"] == 0 and n_facts == 1,
            "notes": "Duplicate VCF lines hash to the same fact (CAS deduplication). "
                     "Bundle contains exactly one fact for both lines.",
            "n_facts": n_facts}


def _case_missing_vcf_file(work: Path) -> dict:
    out = work / "out.bio"
    if out.exists():
        shutil.rmtree(out)
    rc, so, se = _bio(["compile", str(work / "does_not_exist.vcf"),
                       "-o", str(out)], work)
    return {"actual_exit": rc, "stdout": so, "stderr": se,
            "bundle_exists": out.exists(),
            "ok": rc != 0,
            "notes": "Nonexistent input: argparse-level path is fine; FileNotFoundError "
                     "propagates with non-zero exit. Graceful failure expected."}


# ---- registry ----------------------------------------------------------


CASES: list[FuzzCase] = [
    FuzzCase("vcf01", "vcf", "empty file",
             "An empty VCF should not crash the parser.",
             "successful_handling", (0,), _case_empty_file),
    FuzzCase("vcf02", "vcf", "header-only VCF",
             "Header without records produces an empty bundle.",
             "successful_handling", (0,), _case_header_only),
    FuzzCase("vcf03", "vcf", "missing REF allele (REF='.')",
             "Spec-legal '.' REF must not crash; lookup is just a miss.",
             "successful_handling", (0,), _case_missing_ref),
    FuzzCase("vcf04", "vcf", "invalid genotype tokens",
             "Non-{0,1} alleles must not crash the genotype normalizer.",
             "successful_handling", (0,), _case_invalid_gt),
    FuzzCase("vcf05", "vcf", "mixed chromosome naming (no 'chr' prefix)",
             "Chrom strings vary in the wild; rsID-keyed lookup tolerates this.",
             "successful_handling", (0,), _case_mixed_builds),
    FuzzCase("vcf06", "vcf", "truncated record (<8 columns)",
             "Malformed line shorter than required; vcfio drops it (documented).",
             "documented_data_loss", (0,), _case_truncated_record),
    FuzzCase("vcf07", "vcf", "non-ASCII sample name",
             "Unicode in the sample column should round-trip cleanly.",
             "successful_handling", (0,), _case_non_ascii_subject),
    FuzzCase("vcf08", "vcf", "5 kb ALT allele",
             "Pathological large ALT allele must not OOM or crash.",
             "successful_handling", (0,), _case_huge_alt_allele),
    FuzzCase("vcf09", "vcf", "negative POS",
             "Out-of-range POS today is accepted; flagged for v1 strict mode.",
             "documented_data_loss", (0,), _case_negative_pos),
    FuzzCase("vcf10", "vcf", "duplicate records (CAS dedup)",
             "Two identical VCF lines must produce exactly one fact.",
             "successful_handling", (0,), _case_duplicate_records),
    FuzzCase("vcf11", "vcf", "nonexistent input file path",
             "Missing input file: graceful failure with non-zero exit.",
             "graceful_failure", (1, 2), _case_missing_vcf_file),
]


def build_cases() -> list[FuzzCase]:
    return list(CASES)
