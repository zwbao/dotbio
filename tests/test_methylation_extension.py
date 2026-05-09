"""Tests for the methylation extension (Task 10 / SPEC §3.8).

The extension applies the Horvath 2013 epigenetic clock to Illumina 450K
β-values. These tests demonstrate that the three dotbio principles hold
for non-DNA data:

1. multi-scale  — probe facts → epigenetic-age claim → bundle view
2. evidence chain — claim.targets enumerates contributing fact hashes
3. time          — bundle layout is a commit DAG identical to the DNA case
"""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path

import pytest

from dotbio.bundle import Bundle
from dotbio.extensions.methylation import (
    HORVATH_CLOCK_PATH,
    compile_methylation_csv,
    horvath_age_transform,
    load_horvath_clock,
    parse_methylation_csv,
    score_horvath_clock,
)


# ---- helpers -----------------------------------------------------------


def _write_methylation_csv(
    path: Path,
    probe_betas: dict[str, float],
    sample_id: str = "sample_test",
) -> Path:
    with path.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["probe_id", "beta_value", "sample_id"])
        for pid, beta in probe_betas.items():
            w.writerow([pid, f"{beta}", sample_id])
    return path


def _all_zero_betas(rs: dict) -> dict[str, float]:
    return {pid: 0.0 for pid in rs["probes"]}


# ---- 1. ruleset shape --------------------------------------------------


def test_horvath_ruleset_loads_with_353_probes() -> None:
    rs = load_horvath_clock()
    # 353 probes is the canonical Horvath 2013 clock size
    assert rs["n_probes"] == 353
    assert len(rs["probes"]) == 353
    # All probe IDs follow Illumina cgXXXXXXXX format
    for pid in rs["probes"]:
        assert pid.startswith("cg")
        assert len(pid) >= 10
    # Coefficients are floats and bounded to plausible magnitudes.
    # Horvath 2013 published weights are unitless elastic-net regression
    # coefficients (against transformed age); 12 of 353 have |c| >= 1.0,
    # with the largest published magnitude near 3.07 (cg14424579).
    for coef in rs["probes"].values():
        assert isinstance(coef, (int, float))
        assert abs(coef) < 5.0
    # Intercept matches the Horvath 2013 published value
    assert rs["intercept"] == pytest.approx(0.6955, abs=1e-6)
    assert rs["adult_age"] == 20
    assert rs["name"] == "horvath_clock"
    assert rs["version"] == "2013"
    # Ruleset advertises licence + citation, like ClinVar/PharmCAT/OncoKB
    assert "Horvath" in rs["source"]
    assert rs["url"].startswith("http")
    assert "license" in rs


# ---- 2. age transform --------------------------------------------------


def test_horvath_age_transform_piecewise() -> None:
    """Age transform: (1+20)*exp(x)-1 when x<0; (1+20)*x+20 when x>=0."""
    # x = 0 → adult_age boundary (linear branch)
    assert horvath_age_transform(0.0) == pytest.approx(20.0)
    # Linear branch: x = 1 → 21*1 + 20 = 41
    assert horvath_age_transform(1.0) == pytest.approx(41.0)
    # Linear branch: x = 0.6955 → ~34.6
    assert horvath_age_transform(0.6955) == pytest.approx(34.6055, abs=1e-3)
    # Exponential branch (negative x): x = -1 → 21*exp(-1) - 1 ≈ 6.7257
    assert horvath_age_transform(-1.0) == pytest.approx(
        21.0 * math.exp(-1.0) - 1.0, abs=1e-9
    )
    # Continuity at x = 0
    eps = 1e-9
    assert horvath_age_transform(-eps) == pytest.approx(
        horvath_age_transform(eps), abs=1e-6
    )


# ---- 3. CSV parsing ---------------------------------------------------


def test_parse_methylation_csv_validates_inputs(tmp_path: Path) -> None:
    rs = load_horvath_clock()
    probes = list(rs["probes"])[:10]
    good = {p: 0.5 for p in probes}
    csv_path = _write_methylation_csv(tmp_path / "good.csv", good, "S1")
    sample_id, facts = parse_methylation_csv(csv_path)
    assert sample_id == "S1"
    assert len(facts) == 10
    assert all(f["kind"] == "methylation_probe" for f in facts)
    assert all(0.0 <= f["beta"] <= 1.0 for f in facts)
    assert all(f["sample_id"] == "S1" for f in facts)
    assert all(f["platform"].startswith("Illumina") for f in facts)

    # Out-of-range β values are silently dropped (not crash)
    bad = {p: 0.5 for p in probes}
    bad[probes[0]] = 2.5  # out of range
    bad[probes[1]] = -0.1  # out of range
    csv_path2 = _write_methylation_csv(tmp_path / "bad.csv", bad, "S1")
    _, facts2 = parse_methylation_csv(csv_path2)
    assert len(facts2) == 8

    # Missing required columns raises
    bad_csv = tmp_path / "missing.csv"
    bad_csv.write_text("probe_id,foo\ncg001,0.5\n")
    with pytest.raises(ValueError, match="missing required columns"):
        parse_methylation_csv(bad_csv)

    # Mixed sample_ids in one file is rejected (one bundle = one sample)
    mixed = tmp_path / "mixed.csv"
    with mixed.open("w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["probe_id", "beta_value", "sample_id"])
        w.writerow([probes[0], 0.4, "A"])
        w.writerow([probes[1], 0.6, "B"])
    with pytest.raises(ValueError, match="exactly one sample_id"):
        parse_methylation_csv(mixed)


# ---- 4. scoring (math correctness) ------------------------------------


def test_score_horvath_clock_zero_input_returns_intercept() -> None:
    """β = 0 across all clock probes → linear_score == intercept."""
    rs = load_horvath_clock()
    facts = [
        (f"sha256:fake{i:04d}", {
            "kind": "methylation_probe",
            "probe_id": pid,
            "beta": 0.0,
            "sample_id": "S",
            "platform": "Illumina HumanMethylation450",
        })
        for i, pid in enumerate(rs["probes"])
    ]
    score = score_horvath_clock(facts, rs)
    assert score["n_probes_used"] == 353
    assert score["n_probes_missing"] == 0
    assert score["linear_score"] == pytest.approx(rs["intercept"], abs=1e-9)
    # Age at score=intercept (linear branch since intercept > 0)
    expected_age = (1 + rs["adult_age"]) * rs["intercept"] + rs["adult_age"]
    assert score["epigenetic_age"] == pytest.approx(expected_age, abs=1e-6)


def test_score_horvath_clock_partial_coverage() -> None:
    """If only some clock probes are present, the rest contribute zero."""
    rs = load_horvath_clock()
    probes = list(rs["probes"])
    # supply only the first 10 probes
    subset_facts = [
        (f"sha256:fake{i:04d}", {
            "kind": "methylation_probe",
            "probe_id": pid,
            "beta": 0.5,
            "sample_id": "S",
        })
        for i, pid in enumerate(probes[:10])
    ]
    score = score_horvath_clock(subset_facts, rs)
    assert score["n_probes_used"] == 10
    assert score["n_probes_missing"] == 343
    # Manually recompute the expected linear score
    expected = rs["intercept"] + sum(0.5 * rs["probes"][p] for p in probes[:10])
    assert score["linear_score"] == pytest.approx(expected, abs=1e-9)


# ---- 5. compile end-to-end + bundle layout ----------------------------


def test_compile_methylation_csv_produces_bundle_with_evidence_chain(
    tmp_path: Path,
) -> None:
    """End-to-end: CSV → bundle, with manifest, commit, view, and refs."""
    rs = load_horvath_clock()
    # Use mid-range β=0.4 so all probes contribute and the score stays linear
    betas = {pid: 0.4 for pid in rs["probes"]}
    csv_path = _write_methylation_csv(tmp_path / "in.csv", betas, "subj42")
    out = tmp_path / "subj42.bio"

    bundle = compile_methylation_csv(csv_path, out, force=True)

    # --- bundle layout (parity with the DNA case)
    assert (out / "manifest.json").exists()
    assert (out / "facts").is_dir()
    assert (out / "commits").is_dir()
    assert (out / "views").is_dir()
    assert (out / "refs" / "HEAD").exists()
    assert (out / "refs" / "stable").exists()
    assert (out / "views" / "epigenetic-age.md").exists()

    # --- manifest carries modality + ruleset metadata
    m = json.loads((out / "manifest.json").read_text())
    assert m["modality"] == "methylation"
    assert m["claim_count"] == 1
    assert m["scopes"]["methylation_probe_count"] == 353
    assert m["scopes"]["clock_probes_used"] == 353
    rs_active = m["active_rulesets"][0]
    assert rs_active["name"] == "horvath_clock"
    assert rs_active["version"] == "2013"

    # --- exactly one commit, with one age claim
    head = bundle.read_ref("HEAD")
    commit = bundle.read_commit(head)
    assert commit["parent"] is None
    assert commit["rulesets"] == ["horvath_clock@2013"]
    assert len(commit["claims"]) == 1
    claim = commit["claims"][0]
    assert claim["level"] == "epigenetic_age"
    assert claim["ruleset"] == "horvath_clock@2013"
    assert claim["sample_id"] == "subj42"
    assert claim["n_probes_used"] == 353
    # Linear score for β=0.4 across all probes
    expected_score = rs["intercept"] + 0.4 * sum(rs["probes"].values())
    assert claim["linear_score"] == pytest.approx(expected_score, abs=1e-9)
    # epigenetic_age field is present and finite
    assert isinstance(claim["epigenetic_age"], float)
    assert math.isfinite(claim["epigenetic_age"])

    # --- evidence chain: every target in claim.targets resolves to a probe fact
    assert len(claim["targets"]) == 353
    for h in claim["targets"][:10]:
        f = bundle.read_fact(h)
        assert f["kind"] == "methylation_probe"
        assert f["sample_id"] == "subj42"
        assert 0.0 <= f["beta"] <= 1.0

    # --- view markdown carries the claim_id (so `bio expand` can resolve it)
    view = (out / "views" / "epigenetic-age.md").read_text()
    assert claim["id"] in view
    assert "Predicted epigenetic age" in view
    assert "horvath_clock@2013" in view

    # --- principle 3 (time): refusing to overwrite without --force protects history
    with pytest.raises(FileExistsError):
        compile_methylation_csv(csv_path, out, force=False)


# ---- 6. ruleset path resolution --------------------------------------


def test_horvath_ruleset_path_is_packaged() -> None:
    """The ruleset ships with the package via importlib.resources."""
    text = HORVATH_CLOCK_PATH.read_text()
    rs = json.loads(text)
    assert rs["name"] == "horvath_clock"
    assert "probes" in rs
    # Same content as load_horvath_clock()
    assert load_horvath_clock()["intercept"] == rs["intercept"]


# ---- 7. bundle re-uses the same Bundle plumbing as the DNA case -------


def test_methylation_bundle_uses_canonical_bundle_layer(tmp_path: Path) -> None:
    """Methylation bundles use the same Bundle CAS / commit / refs API."""
    rs = load_horvath_clock()
    betas = {pid: 0.5 for pid in list(rs["probes"])[:50]}
    csv_path = _write_methylation_csv(tmp_path / "small.csv", betas, "small_subj")
    out = tmp_path / "small.bio"
    compile_methylation_csv(csv_path, out, force=True)

    # Re-open with a fresh Bundle handle and exercise the standard API
    b2 = Bundle(out)
    refs = b2.list_refs()
    assert set(refs) == {"HEAD", "stable"}
    assert refs["HEAD"] == refs["stable"]

    chain = b2.commit_ancestry("HEAD")
    assert len(chain) == 1
    assert chain[0]["claims"][0]["level"] == "epigenetic_age"

    # commit_ancestry walking the (single-commit) DAG works
    head = b2.read_ref("HEAD")
    assert b2.read_commit(head)["id"] == head
