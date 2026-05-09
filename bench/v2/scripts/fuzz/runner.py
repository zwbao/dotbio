"""Fuzz suite runner — Experiment 7.

Runs every case from fuzz_vcf, fuzz_rulesets, fuzz_schema, fuzz_hashes
in fresh per-case temporary working directories, classifies each
outcome as PASS / FAIL / UNEXPECTED, and writes a JSON report to
``bench/v2/results/exp07_adversarial.json``.

Classification:
- PASS: case.run() returned ``ok=True``. The case's expected behavior
  was observed.
- FAIL: ``ok=False`` AND the actual exit code was within the case's
  documented expected_exit_codes set. (i.e. it failed, but it failed
  in a documented way — still useful, but flagged for triage.)
- UNEXPECTED: ``ok=False`` AND the exit code was outside the documented
  set, OR the case raised an exception. These need investigation.

Run as a module:

    python -m bench.v2.scripts.fuzz.runner

or directly:

    python bench/v2/scripts/fuzz/runner.py
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

# Allow running both as a module (-m) and as a script (python file.py).
if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent.parent))
    from bench.v2.scripts.fuzz import (
        fuzz_hashes,
        fuzz_rulesets,
        fuzz_schema,
        fuzz_vcf,
    )
else:
    from . import fuzz_hashes, fuzz_rulesets, fuzz_schema, fuzz_vcf  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[4]
RESULTS_PATH = REPO_ROOT / "bench" / "v2" / "results" / "exp07_adversarial.json"


def _classify(case, outcome: dict) -> str:
    if outcome.get("ok"):
        return "PASS"
    rc = outcome.get("actual_exit")
    if rc is not None and case.expected_exit_codes and rc in case.expected_exit_codes:
        return "FAIL"   # failed within documented exit-code set
    return "UNEXPECTED"


def _run_one(case, *, verbose: bool) -> dict:
    started = time.time()
    with tempfile.TemporaryDirectory(prefix=f"dotbio_fuzz_{case.case_id}_") as td:
        workdir = Path(td)
        try:
            outcome = case.run(workdir) or {}
        except Exception as e:  # pragma: no cover  (defensive)
            outcome = {
                "ok": False,
                "actual_exit": None,
                "stdout": "",
                "stderr": "",
                "notes": f"runner caught exception: {type(e).__name__}: {e}",
                "traceback": traceback.format_exc(),
            }
    elapsed = time.time() - started
    status = _classify(case, outcome)
    record = {
        "case_id": case.case_id,
        "module": case.module,
        "title": case.title,
        "rationale": case.rationale,
        "expected_behavior": case.expected,
        "expected_exit_codes": list(case.expected_exit_codes),
        "actual_exit": outcome.get("actual_exit"),
        "status": status,
        "elapsed_sec": round(elapsed, 3),
        "notes": outcome.get("notes", ""),
    }
    # Truncate to keep the report compact; full output is regenerable.
    if outcome.get("stdout"):
        record["stdout_head"] = outcome["stdout"][:600]
    if outcome.get("stderr"):
        record["stderr_head"] = outcome["stderr"][:600]
    if "traceback" in outcome:
        record["traceback_head"] = outcome["traceback"][:1200]
    if verbose:
        print(f"[{status:11s}] {case.case_id:6s} {case.title}")
        if status == "UNEXPECTED" and outcome.get("stderr"):
            print("  stderr:", outcome["stderr"][:200].replace("\n", " "))
    return record


def collect_cases() -> list:
    cases = []
    cases += fuzz_vcf.build_cases()
    cases += fuzz_rulesets.build_cases()
    cases += fuzz_schema.build_cases()
    cases += fuzz_hashes.build_cases()
    return cases


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="dotbio fuzz suite runner")
    p.add_argument("--filter", default=None,
                   help="run only cases whose case_id starts with this prefix "
                        "(e.g. 'vcf', 'rs', 'sc', 'hs')")
    p.add_argument("--quiet", action="store_true",
                   help="suppress per-case stdout (still writes JSON)")
    p.add_argument("--out", default=str(RESULTS_PATH),
                   help=f"output JSON path (default: {RESULTS_PATH})")
    args = p.parse_args(argv)

    cases = collect_cases()
    if args.filter:
        cases = [c for c in cases if c.case_id.startswith(args.filter)]
    started = time.time()
    records = [_run_one(c, verbose=not args.quiet) for c in cases]
    elapsed = time.time() - started

    summary = {
        "total": len(records),
        "pass": sum(1 for r in records if r["status"] == "PASS"),
        "fail": sum(1 for r in records if r["status"] == "FAIL"),
        "unexpected": sum(1 for r in records if r["status"] == "UNEXPECTED"),
        "by_module": {},
    }
    for r in records:
        m = r["module"]
        b = summary["by_module"].setdefault(
            m, {"total": 0, "pass": 0, "fail": 0, "unexpected": 0})
        b["total"] += 1
        b[r["status"].lower()] += 1

    report = {
        "experiment": "exp07_adversarial",
        "spec_section": "3.7",
        "task": "Task 9 — Adversarial robustness suite",
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "elapsed_sec": round(elapsed, 3),
        "summary": summary,
        "cases": records,
    }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False))

    print()
    print(f"=== fuzz summary ({elapsed:.1f}s) ===")
    print(f"  total       : {summary['total']}")
    print(f"  PASS        : {summary['pass']}")
    print(f"  FAIL (doc'd): {summary['fail']}")
    print(f"  UNEXPECTED  : {summary['unexpected']}")
    print(f"  report      : {out.relative_to(REPO_ROOT) if out.is_relative_to(REPO_ROOT) else out}")

    return 0 if summary["unexpected"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
