"""Schema-migration fuzz cases.

dotbio v0 ships with ``SCHEMA = 'dotbio.v0'``. This module probes how a
v0 reader behaves when handed bundles whose manifests claim a different
schema version, or whose manifests are missing required fields.

We do NOT yet have a v1 reader to test the forward-compat path; instead
we verify the v0 reader's behavior on tagged manifests so that a future
``schema_version`` gate (a v1 feature) has a baseline to point at.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from . import FuzzCase


REAL_VCF = Path(__file__).resolve().parents[4] / "examples" / "real-na12878" / "input.vcf"


def _bio(args: list[str], cwd: Path) -> tuple[int, str, str]:
    proc = subprocess.run(
        [sys.executable, "-m", "dotbio", *args],
        cwd=cwd, capture_output=True, text=True, timeout=60,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _fresh(work: Path, name: str = "out.bio") -> Path:
    out = work / name
    if out.exists():
        shutil.rmtree(out)
    rc, _, se = _bio(["compile", str(REAL_VCF), "-o", str(out)], work)
    if rc != 0:
        raise RuntimeError(f"setup compile failed: {se!r}")
    return out


def _patch_manifest(bundle: Path, **edits) -> None:
    m = json.loads((bundle / "manifest.json").read_text())
    for k, v in edits.items():
        if v is None and k in m:
            del m[k]
        else:
            m[k] = v
    (bundle / "manifest.json").write_text(json.dumps(m, indent=2))


def _case_v1_tag(work: Path) -> dict:
    """Stamp a v1 schema in the manifest and confirm v0 still serves the
    bundle (forward-compat: v0 reader ignores schema_version field today;
    a v1 reader would refuse to read a higher-than-supported version)."""
    bundle = _fresh(work)
    _patch_manifest(bundle, schema_version="dotbio.v1")
    rc, so, se = _bio(["show", str(bundle), "--view", "manifest"], work)
    return {"actual_exit": rc, "stdout": so[:400], "stderr": se,
            "ok": rc == 0,
            "notes": "v0 reader is permissive: it passes the schema_version field "
                     "through to the JSON dump. A v1 reader will be expected to "
                     "ENFORCE that schema_version<=its own; v0 cannot. Documented "
                     "data loss risk for forward-incompat fields."}


def _case_unknown_top_level_field(work: Path) -> dict:
    bundle = _fresh(work)
    _patch_manifest(bundle, future_field={"x": 1, "y": [2, 3]})
    rc, so, se = _bio(["show", str(bundle), "--view", "manifest"], work)
    return {"actual_exit": rc, "stdout": so[:400], "stderr": se,
            "ok": rc == 0 and "future_field" in so,
            "notes": "Unknown manifest fields round-trip unchanged (preservation "
                     "of forward-compat data)."}


def _case_drop_active_rulesets(work: Path) -> dict:
    bundle = _fresh(work)
    _patch_manifest(bundle, active_rulesets=None)
    rc, so, se = _bio(["update", str(bundle), "--ruleset", "clinvar@2026-05-08"], work)
    return {"actual_exit": rc, "stdout": so[:400], "stderr": se,
            "ok": rc == 0,
            "notes": "Missing active_rulesets: update path uses .get(default=[]) "
                     "and recovers; no crash."}


def _case_invalid_view_request(work: Path) -> dict:
    bundle = _fresh(work)
    rc, so, se = _bio(["show", str(bundle), "--view", "no-such-view"], work)
    return {"actual_exit": rc, "stdout": so, "stderr": se,
            "ok": rc != 0 and "available" in se,
            "notes": "Unknown view name returns non-zero AND lists the available views."}


def _case_show_missing_manifest(work: Path) -> dict:
    bundle = _fresh(work, name="no_manifest.bio")
    (bundle / "manifest.json").unlink()
    rc, so, se = _bio(["show", str(bundle), "--view", "manifest"], work)
    return {"actual_exit": rc, "stdout": so, "stderr": se,
            "ok": rc != 0,
            "notes": "Missing manifest.json: hard error rather than fabricated empty manifest."}


def _case_expand_unknown_claim(work: Path) -> dict:
    bundle = _fresh(work)
    rc, so, se = _bio(["expand", str(bundle), "claim:does-not-exist"], work)
    return {"actual_exit": rc, "stdout": so, "stderr": se,
            "ok": rc != 0 and "not found" in se.lower(),
            "notes": "Unknown claim id at expand: non-zero exit with explanatory message."}


def _case_diff_with_invalid_ref(work: Path) -> dict:
    bundle = _fresh(work)
    rc, so, se = _bio(["diff", str(bundle), "HEAD", "not-a-real-ref"], work)
    return {"actual_exit": rc, "stdout": so, "stderr": se,
            "ok": rc != 0,
            "notes": "Invalid ref name in diff: must error rather than diffing against null."}


CASES: list[FuzzCase] = [
    FuzzCase("sc01", "schema", "manifest stamped with future schema_version",
             "v0 reader is permissive today; this baselines forward-compat behavior.",
             "documented_data_loss", (0,), _case_v1_tag),
    FuzzCase("sc02", "schema", "unknown manifest top-level field",
             "Forward-compat: unknown fields must round-trip without loss.",
             "successful_handling", (0,), _case_unknown_top_level_field),
    FuzzCase("sc03", "schema", "missing active_rulesets in manifest",
             "Update path must tolerate optional fields being absent.",
             "successful_handling", (0,), _case_drop_active_rulesets),
    FuzzCase("sc04", "schema", "show with invalid --view name",
             "User-error path: must list valid choices and exit non-zero.",
             "graceful_failure", (1, 2), _case_invalid_view_request),
    FuzzCase("sc05", "schema", "show on bundle missing manifest.json",
             "Bundle integrity: missing manifest is a hard error.",
             "graceful_failure", (1, 2), _case_show_missing_manifest),
    FuzzCase("sc06", "schema", "expand on unknown claim id",
             "expand returns non-zero with explanatory message.",
             "graceful_failure", (1, 2), _case_expand_unknown_claim),
    FuzzCase("sc07", "schema", "diff with non-existent ref",
             "Invalid ref name on diff: graceful failure expected.",
             "graceful_failure", (1, 2), _case_diff_with_invalid_ref),
]


def build_cases() -> list[FuzzCase]:
    return list(CASES)
