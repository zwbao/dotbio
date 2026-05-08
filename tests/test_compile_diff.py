"""End-to-end tests: compile, update, diff, expand."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SYNTHETIC_VCF = REPO / "examples" / "synthetic" / "input.vcf"


def run_bio(*args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Invoke the bio CLI as a subprocess so we exercise the real entry point."""
    return subprocess.run(
        [sys.executable, "-m", "dotbio", *args],
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=check,
    )


def test_compile_produces_expected_structure(tmp_path: Path) -> None:
    bundle = tmp_path / "out.bio"
    r = run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    assert r.returncode == 0
    assert bundle.is_dir()
    assert (bundle / "manifest.json").is_file()
    assert (bundle / "facts").is_dir()
    assert (bundle / "commits").is_dir()
    assert (bundle / "views").is_dir()
    assert (bundle / "refs" / "HEAD").is_file()
    assert (bundle / "refs" / "stable").is_file()
    assert (bundle / "views" / "pgx.md").is_file()
    assert (bundle / "views" / "germline-clinical.md").is_file()
    assert (bundle / "views" / "carrier.md").is_file()
    assert (bundle / "views" / "somatic.md").is_file()


def test_compile_manifest_schema(tmp_path: Path) -> None:
    bundle = tmp_path / "out.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    manifest = json.loads((bundle / "manifest.json").read_text())
    assert manifest["schema"] == "dotbio.v0"
    assert manifest["build"] == "GRCh38"
    assert "HEAD" in manifest["refs"]
    assert manifest["scopes"]["germline_variant_count"] >= 1
    assert manifest["scopes"]["somatic_call_count"] >= 1
    assert any(v["scope"] == "pgx" for v in manifest["views"])
    assert any(rs["name"] == "clinvar" for rs in manifest["active_rulesets"])


def test_compile_produces_initial_commit(tmp_path: Path) -> None:
    bundle = tmp_path / "out.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    head = (bundle / "refs" / "HEAD").read_text().strip()
    commit_path = bundle / "commits" / f"{head}.commit.json"
    assert commit_path.is_file()
    commit = json.loads(commit_path.read_text())
    assert commit["parent"] is None
    assert len(commit["claims"]) > 0


def test_compile_facts_are_content_addressed(tmp_path: Path) -> None:
    bundle = tmp_path / "out.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    # Each fact file should exist at sha256:<prefix><rest>.json
    for prefix_dir in (bundle / "facts").iterdir():
        if not prefix_dir.is_dir():
            continue
        assert len(prefix_dir.name) == 2
        for fact_file in prefix_dir.glob("*.json"):
            assert len(fact_file.stem) == 62  # 64-char digest minus 2-char prefix


def test_update_appends_commit_and_advances_head(tmp_path: Path) -> None:
    bundle = tmp_path / "out.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    stable_before = (bundle / "refs" / "stable").read_text().strip()
    head_before = (bundle / "refs" / "HEAD").read_text().strip()
    assert stable_before == head_before  # initial state

    r = run_bio("update", str(bundle), "--ruleset", "clinvar@2026-05-08")
    assert r.returncode == 0

    stable_after = (bundle / "refs" / "stable").read_text().strip()
    head_after = (bundle / "refs" / "HEAD").read_text().strip()
    assert stable_after == stable_before  # stable unchanged
    assert head_after != head_before  # HEAD advanced
    new_commit = json.loads((bundle / "commits" / f"{head_after}.commit.json").read_text())
    assert new_commit["parent"] == head_before


def test_diff_surfaces_only_substantive_reclassifications(tmp_path: Path) -> None:
    """The whole point: cosmetic ruleset version bumps must NOT show up in diff,
    only real interpretation changes should."""
    bundle = tmp_path / "out.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    run_bio("update", str(bundle), "--ruleset", "clinvar@2026-05-08")
    r = run_bio("diff", str(bundle), "stable", "HEAD")
    assert r.returncode == 0
    out = r.stdout
    # The synthetic time-travel demo reclassifies BRCA1 only.
    assert "BRCA1" in out
    assert "likely_pathogenic" in out
    assert "pathogenic" in out
    # APOE/F5/MTHFR/CFTR are also covered by both ClinVar versions but
    # unchanged → should NOT appear in the diff.
    assert "APOE" not in out
    assert "F5 Factor V Leiden" not in out
    assert "MTHFR" not in out
    assert "CFTR" not in out
    # Exactly one substantive change.
    assert "1 changed" in out


def test_show_view_outputs_markdown(tmp_path: Path) -> None:
    bundle = tmp_path / "out.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    r = run_bio("show", str(bundle), "--view", "pgx")
    assert r.returncode == 0
    assert "Pharmacogenomic" in r.stdout
    assert "claim_id:" in r.stdout
    assert "Ultrarapid Metabolizer" in r.stdout


def test_expand_resolves_claim_to_evidence_chain(tmp_path: Path) -> None:
    bundle = tmp_path / "out.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    pgx = (bundle / "views" / "pgx.md").read_text()
    # extract first claim_id
    import re
    m = re.search(r"claim_id:\s*(claim:[a-f0-9]+)", pgx)
    assert m is not None
    claim_id = m.group(1)
    r = run_bio("expand", str(bundle), claim_id)
    assert r.returncode == 0
    assert claim_id in r.stdout
    assert "Underlying facts" in r.stdout
    assert "sha256:" in r.stdout


def test_log_lists_commits_with_refs(tmp_path: Path) -> None:
    bundle = tmp_path / "out.bio"
    run_bio("compile", str(SYNTHETIC_VCF), "-o", str(bundle))
    run_bio("update", str(bundle), "--ruleset", "clinvar@2026-05-08")
    r = run_bio("log", str(bundle))
    assert "(HEAD)" in r.stdout
    assert "(stable)" in r.stdout
