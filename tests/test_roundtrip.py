"""Round-trip tests — same VCF compiled twice produces identical fact hashes."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SYNTHETIC_VCF = REPO / "examples" / "synthetic" / "input.vcf"


def run_bio(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dotbio", *args],
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )


def fact_hashes_in(bundle: Path) -> set[str]:
    out: set[str] = set()
    for prefix_dir in (bundle / "facts").iterdir():
        if not prefix_dir.is_dir():
            continue
        for fact_file in prefix_dir.glob("*.json"):
            out.add(f"sha256:{prefix_dir.name}{fact_file.stem}")
    return out


def test_compile_is_deterministic_on_facts(tmp_path: Path) -> None:
    a = tmp_path / "a.bio"
    b = tmp_path / "b.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(a))
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(b))
    assert fact_hashes_in(a) == fact_hashes_in(b)


def test_compile_fact_count_matches_input(tmp_path: Path) -> None:
    bundle = tmp_path / "out.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    n_lines = sum(1 for line in SYNTHETIC_VCF.read_text().splitlines() if line and not line.startswith("#"))
    assert len(fact_hashes_in(bundle)) == n_lines
