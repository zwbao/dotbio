"""Longitudinal cohort simulator (SPEC §3.4, Task 6).

Round 1 deliverable:
  - Two arms: `arm_soc` (re-annotate every 3 months) and `arm_bio`
    (run `bio update` every month with `bio diff` capturing change).
  - Synthetic 24-month ClinVar archive (see `clinvar_archive.py`).
    The exact same simulator accepts a real archive via
    `--clinvar-archive <dir>` once `clinvar_archive.load_real_archive`
    is wired up; no other code changes are required.
  - Per arm, computes:
      * captured reclassifications
      * mean detection latency (months)
      * cumulative tokens read
      * FNR vs the synthetic ground truth

The two arms must invoke the *existing* `bio update` and `bio diff`
CLI commands; we exercise them via subprocess so the simulator
genuinely reflects the published interface, not a re-implementation.

Smoke run: 5 patients × 24 months, completes in <60s on a 2024 laptop.
The default cohort scales linearly to the SPEC's 100 patients — change
`--patients 100` and rerun.

Output: `bench/v2/results/exp04_longitudinal_smoke.json` with per-arm
endpoints, per-patient breakdowns, and ground-truth metadata.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

# Sibling import: prefer relative when run as a module, but support
# `python bench/v2/scripts/longitudinal_sim.py` invocation as well.
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import clinvar_archive as ca  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]
RESULTS_DIR = REPO_ROOT / "bench" / "v2" / "results"
EXAMPLE_VCF = REPO_ROOT / "examples" / "real-na12878" / "input.vcf"


# ---- patient cohort generation --------------------------------------------
#
# We expand the bundled 8-locus NA12878 VCF into N synthetic patients by
# varying the genotype calls for the ClinVar-reportable rsIDs (rs429358,
# rs6025, rs1801133, rs113993960, rs1800562, rs80357906) so each patient
# has a distinct interpretation profile. The non-ClinVar rsIDs
# (PharmCAT-only) are left as the example calls because they're not the
# subject of this experiment. Genotype prevalences are drawn from
# 1000G AF buckets and lightly randomized.
#
# This is purely cohort *plumbing* — the actual interpretation logic
# lives in dotbio.engine and is exercised verbatim through `bio compile`.

CLINVAR_GENOTYPE_OPTIONS: dict[str, list[tuple[str, float]]] = {
    # rsid: [(VCF_GT_string, prevalence_weight), ...]
    "rs429358":   [("0|0", 0.65), ("1|0", 0.30), ("1|1", 0.05)],
    "rs6025":     [("0|0", 0.95), ("1|0", 0.04), ("1|1", 0.01)],
    "rs1801133":  [("0|0", 0.45), ("1|0", 0.40), ("1|1", 0.15)],
    "rs113993960":[("0|0", 0.97), ("1|0", 0.03)],
    "rs1800562":  [("0|0", 0.85), ("1|0", 0.13), ("1|1", 0.02)],
    # rs80357906 is not in the example VCF; we add it for cohort 4+.
    # We synthesize a record in `_synthesize_patient_vcf` for patients
    # whose pop_idx selects it.
}


def _read_example_vcf_lines() -> list[str]:
    return EXAMPLE_VCF.read_text().splitlines(keepends=True)


def _synthesize_patient_vcf(seed: int, out_path: Path,
                            include_brca: bool) -> Path:
    """Write a synthetic VCF for one patient by perturbing the example.

    Determinism: same seed → same VCF. Genotype is sampled from
    `CLINVAR_GENOTYPE_OPTIONS`. BRCA1 rs80357906 is appended on chr17
    (hand-written record) only for patients flagged `include_brca`,
    so we get cohort heterogeneity in actionable variants.
    """
    import random as _random
    rng = _random.Random(seed)

    lines = _read_example_vcf_lines()
    # We mutate the GT field (last column) of each VCF record. The
    # example VCF's column 10 is the sample column.
    out_lines: list[str] = []
    for line in lines:
        if line.startswith("#") or not line.strip():
            out_lines.append(line)
            continue
        cols = line.rstrip("\n").split("\t")
        rsid = cols[2]
        if rsid in CLINVAR_GENOTYPE_OPTIONS:
            opts = CLINVAR_GENOTYPE_OPTIONS[rsid]
            gts, weights = zip(*opts)
            new_gt = rng.choices(gts, weights=weights, k=1)[0]
            cols[9] = new_gt
        out_lines.append("\t".join(cols) + "\n")

    if include_brca:
        # BRCA1 c.68_69delAG (185delAG) — Ashkenazi founder, rare globally.
        # Record is chr17 GRCh38 coords; inserted as a het GAG>G call.
        out_lines.append(
            "chr17\t43124027\trs80357906\tGAG\tG\t.\tPASS\tGENE=BRCA1\tGT\t1|0\n"
        )

    out_path.write_text("".join(out_lines))
    return out_path


def build_cohort(n: int, work_dir: Path, seed_base: int = 7000) -> list[dict]:
    """Build N patient VCFs and compile each to a .bio bundle.

    Returns a list of patient records (id, vcf_path, bundle_path).
    """
    cohort: list[dict] = []
    for i in range(n):
        pid = f"P{i+1:03d}"
        pdir = work_dir / pid
        pdir.mkdir(parents=True, exist_ok=True)
        vcf = pdir / "input.vcf"
        # alternate inclusion of BRCA1 to vary actionable footprint
        include_brca = (i % 2 == 0)
        _synthesize_patient_vcf(seed_base + i, vcf, include_brca)

        bundle = pdir / "patient.bio"
        compile_cmd = [
            sys.executable, "-m", "dotbio", "compile",
            str(vcf), "-o", str(bundle), "--force",
            "--subject", pid,
        ]
        proc = subprocess.run(compile_cmd, capture_output=True, text=True)
        if proc.returncode != 0:
            raise RuntimeError(
                f"compile failed for {pid}: rc={proc.returncode}\n"
                f"stdout: {proc.stdout}\n"
                f"stderr: {proc.stderr}"
            )
        cohort.append({
            "id": pid,
            "vcf": str(vcf),
            "bundle": str(bundle),
            "include_brca": include_brca,
        })
    return cohort


# ---- patient genotype lookup (for ground-truth filtering) -----------------


def _patient_clinvar_genotypes(vcf_path: Path) -> dict[str, str]:
    """Map rsid → genotype as it appears in the patient's VCF.

    We return the genotype in the SAME format the engine uses internally
    (i.e. the dotbio GT string after parse_vcf normalizes it). To stay
    decoupled from `vcfio.py` internals, we use the engine's parser.
    """
    from dotbio.vcfio import parse_vcf
    out: dict[str, str] = {}
    for rec in parse_vcf(vcf_path):
        if rec.rsid:
            out[rec.rsid] = rec.genotype
    return out


def _ground_truth_for_patient(
    snapshots: list[dict], patient_gts: dict[str, str]
) -> list[dict]:
    """Filter the global reclassification timeline down to events that
    materially change a claim FOR THIS PATIENT.

    A reclassification (rsid, genotype) only matters to a given patient
    if the patient's genotype matches that genotype cell. We accept both
    orderings (e.g. "T/C" or "C/T") to mirror the engine's behaviour.
    """
    def matches(patient_gt: str, cell_gt: str) -> bool:
        if patient_gt == cell_gt:
            return True
        a, _, b = patient_gt.partition("/")
        return f"{b}/{a}" == cell_gt

    out: list[dict] = []
    for snap in snapshots:
        for r in snap["reclassifications"]:
            rsid = r["rsid"]
            if rsid not in patient_gts:
                continue
            if not matches(patient_gts[rsid], r["genotype"]):
                continue
            out.append({**r, "released": snap["version"]})
    return out


# ---- arm logic -------------------------------------------------------------


def _bio(*args: str, capture: bool = True) -> tuple[int, str, str]:
    """Run `python -m dotbio <args>` and return (rc, stdout, stderr)."""
    cmd = [sys.executable, "-m", "dotbio", *args]
    proc = subprocess.run(cmd, capture_output=capture, text=True)
    return proc.returncode, proc.stdout, proc.stderr


def _read_head_ref(bundle: Path) -> str:
    head_file = bundle / "refs" / "HEAD"
    return head_file.read_text().strip()


def _save_ref(bundle: Path, name: str, value: str) -> None:
    """Write a ref file directly (avoids needing a CLI subcommand for it)."""
    refs = bundle / "refs"
    refs.mkdir(exist_ok=True)
    (refs / name).write_text(value + "\n")


def _parse_diff_changed(diff_text: str) -> list[dict]:
    """Pull the 'Reclassifications' block out of `bio diff` markdown.

    Each entry is `- **{gene} {variant_name|alteration}**` followed by
    indented `was:` / `now:` lines. We capture the gene and old→new
    significance pair when we can identify them.
    """
    changed: list[dict] = []
    in_reclass = False
    current: dict | None = None
    for line in diff_text.splitlines():
        s = line.strip()
        if s.startswith("## Reclassifications"):
            in_reclass = True
            continue
        if s.startswith("## ") and in_reclass:
            in_reclass = False
        if not in_reclass:
            continue
        if s.startswith("- **"):
            if current is not None:
                changed.append(current)
            head = s[4:].split("**", 1)[0]
            current = {"header": head}
        elif s.startswith("- was:") and current is not None:
            current["was"] = s[len("- was:"):].strip()
        elif s.startswith("- now:") and current is not None:
            current["now"] = s[len("- now:"):].strip()
        elif s.startswith("- reason:") and current is not None:
            current["reason"] = s[len("- reason:"):].strip()
    if current is not None:
        changed.append(current)
    return changed


def _approx_tokens(text: str) -> int:
    """Cheap ~4-chars-per-token estimate (matches dotbio CLI convention)."""
    return max(1, len(text) // 4)


def run_arm_bio(patient: dict, snapshots: list[dict]) -> dict:
    """`arm_bio`: monthly `bio update` + `bio diff` against last month."""
    bundle = Path(patient["bundle"])
    months: list[dict] = []
    cumulative_tokens = 0
    captured: list[dict] = []
    prev_head = _read_head_ref(bundle)

    # snapshots[0] is the baseline already compiled into the patient
    # bundle; we start applying updates from snapshots[1].
    for snap in snapshots[1:]:
        version = snap["version"]
        # 1. bio update --ruleset clinvar@<version>
        rc, out, err = _bio(
            "update", str(bundle), "--ruleset", f"clinvar@{version}"
        )
        if rc != 0:
            raise RuntimeError(f"bio update failed @ {version}: {err}")
        cumulative_tokens += _approx_tokens(out)

        new_head = _read_head_ref(bundle)
        # 2. bio diff prev_head new_head
        rc, diff_out, err = _bio("diff", str(bundle), prev_head, new_head)
        if rc != 0:
            raise RuntimeError(f"bio diff failed @ {version}: {err}")
        cumulative_tokens += _approx_tokens(diff_out)

        changed = _parse_diff_changed(diff_out)
        for ch in changed:
            captured.append({
                "patient": patient["id"],
                "released": version,
                "captured_at": version,
                "latency_months": 0,
                **ch,
            })

        months.append({
            "version": version,
            "n_changed": len(changed),
            "tokens_read_this_month": _approx_tokens(out) + _approx_tokens(diff_out),
        })
        prev_head = new_head

    return {
        "arm": "arm_bio",
        "patient": patient["id"],
        "captured": captured,
        "months": months,
        "cumulative_tokens": cumulative_tokens,
        "n_captured": len(captured),
    }


def run_arm_soc(patient: dict, snapshots: list[dict],
                quarter_months: tuple[int, ...] = (3, 6, 9, 12, 15, 18, 21, 24)) -> dict:
    """`arm_soc`: re-annotate every 3 months. Off-quarter months read
    the latest digest only at the next quarter boundary."""
    bundle = Path(patient["bundle"])
    months: list[dict] = []
    cumulative_tokens = 0
    captured: list[dict] = []
    prev_head = _read_head_ref(bundle)
    # Tag this baseline so we can diff against it from later quarters.
    _save_ref(bundle, "soc_last_quarter", prev_head)

    for month_idx, snap in enumerate(snapshots[1:], start=1):
        version = snap["version"]
        if month_idx not in quarter_months:
            # SoC does NOTHING off-quarter (this is the whole point).
            continue

        rc, out, err = _bio(
            "update", str(bundle), "--ruleset", f"clinvar@{version}"
        )
        if rc != 0:
            raise RuntimeError(f"bio update (SoC) failed @ {version}: {err}")
        cumulative_tokens += _approx_tokens(out)
        new_head = _read_head_ref(bundle)

        rc, diff_out, err = _bio("diff", str(bundle),
                                 _last_quarter_ref(bundle), new_head)
        if rc != 0:
            raise RuntimeError(f"bio diff (SoC) failed @ {version}: {err}")
        cumulative_tokens += _approx_tokens(diff_out)
        changed = _parse_diff_changed(diff_out)
        for ch in changed:
            captured.append({
                "patient": patient["id"],
                "released": version,
                "captured_at": version,
                # SoC sees everything that accumulated in this quarter.
                # We record the per-event latency at correlation time.
                "latency_months": 0,
                **ch,
            })

        months.append({
            "version": version,
            "n_changed": len(changed),
            "tokens_read_this_month": _approx_tokens(out) + _approx_tokens(diff_out),
        })
        _save_ref(bundle, "soc_last_quarter", new_head)

    return {
        "arm": "arm_soc",
        "patient": patient["id"],
        "captured": captured,
        "months": months,
        "cumulative_tokens": cumulative_tokens,
        "n_captured": len(captured),
    }


def _last_quarter_ref(bundle: Path) -> str:
    return (bundle / "refs" / "soc_last_quarter").read_text().strip()


# ---- ground-truth correlation --------------------------------------------


def _match_captured_to_truth(
    arm_run: dict, truth: list[dict], arm_kind: str
) -> tuple[list[dict], list[dict]]:
    """Decide which truth events are visible in the arm's captured diffs.

    Semantics:
      - **arm_bio** runs `bio diff prev_month current_month` every month,
        so a one-step transition X→Y at month m appears in month-m's diff.
        We mark a truth event captured iff a diff entry exists in its
        release-month with matching gene.
      - **arm_soc** runs `bio diff last_quarter current_quarter` only at
        months 3,6,9,... — the diff shows the NET change for the quarter.
        For any (gene, quarter) we observe at most ONE diff entry; that
        entry corresponds to the FINAL state of the variant at quarter
        end. We mark as captured only the *latest* truth event per
        (gene, quarter) — earlier intermediate transitions are FN
        because the cumulative diff overrode them.
    """
    matched: list[dict] = []
    unmatched: list[dict] = []

    captured = arm_run["captured"]
    if arm_kind == "arm_bio":
        # index captured rows by (gene, captured_at)
        cap_index: dict[tuple[str, str], int] = {}
        for ch in captured:
            gene = ch.get("header", "").split(" ", 1)[0]
            cap_index[(gene, ch["captured_at"])] = (
                cap_index.get((gene, ch["captured_at"]), 0) + 1
            )
        for t in truth:
            if cap_index.get((t["gene"], t["released"]), 0) > 0:
                matched.append(t)
                cap_index[(t["gene"], t["released"])] -= 1
            else:
                unmatched.append(t)
        return matched, unmatched

    # arm_soc: bucket truth events by (gene, quarter); last event per
    # bucket is captured iff the quarter-end diff shows a change.
    captured_quarters: set[tuple[str, int]] = set()
    for ch in captured:
        gene = ch.get("header", "").split(" ", 1)[0]
        captured_quarters.add((gene, _quarter_for(ch["captured_at"], truth)))

    by_bucket: dict[tuple[str, int], list[dict]] = {}
    for t in truth:
        q = _quarter_for(t["released"], truth)
        by_bucket.setdefault((t["gene"], q), []).append(t)

    for bucket, events in by_bucket.items():
        events.sort(key=lambda e: e["released"])
        if bucket in captured_quarters:
            matched.extend(events[-1:])    # only the final transition
            unmatched.extend(events[:-1])  # intermediates lost in diff
        else:
            unmatched.extend(events)       # whole quarter missed

    return matched, unmatched


def _quarter_for(version: str, ref_truth: list[dict]) -> int:
    """Return the SoC quarter (1..8 for 24 months) that contains `version`.
    Quarter k covers months (3k-2, 3k-1, 3k)."""
    m = _month_index(version, ref_truth)
    return (m + 2) // 3


def compute_endpoints(arm_run: dict, truth: list[dict],
                      arm_kind: str) -> dict:
    """Compute FNR / latency / token cost for one (arm, patient) run."""
    actionable_truth = [t for t in truth if t["actionable"]]
    matched, unmatched = _match_captured_to_truth(
        arm_run, actionable_truth, arm_kind
    )
    # Detection latency: for arm_bio it's 0 (monthly cadence catches the
    # release in the same month). For arm_soc, latency is the gap from
    # release-month to the next quarterly checkpoint.
    latencies: list[int] = []
    if arm_kind == "arm_bio":
        latencies = [0] * len(matched)
    else:
        # SoC quarterly checkpoints at months 3, 6, 9, ...
        for t in matched:
            release_month = _month_index(t["released"], truth)
            quarter = ((release_month + 2) // 3) * 3
            latencies.append(max(0, quarter - release_month))

    n_truth = len(actionable_truth)
    n_captured = len(matched)
    fnr = (n_truth - n_captured) / n_truth if n_truth > 0 else 0.0
    return {
        "n_actionable_truth": n_truth,
        "n_captured": n_captured,
        "fnr": fnr,
        "mean_latency_months": (sum(latencies) / len(latencies)) if latencies else 0.0,
        "cumulative_tokens": arm_run["cumulative_tokens"],
        "missed": [
            {"gene": t["gene"], "rsid": t["rsid"],
             "from": t["from"], "to": t["to"], "released": t["released"]}
            for t in unmatched
        ],
    }


def _month_index(version: str, ref_truth: list[dict]) -> int:
    """Return 1..N where 'YYYY-MM-01' falls in the timeline. Walks the
    archive's first-month tag to compute the offset."""
    # truth entries carry "released" YYYY-MM-DD strings; the simulator
    # uses month_versions starting at the archive's first version.
    if not ref_truth:
        # fallback: parse year/month directly
        y, m, _ = version.split("-")
        return (int(y) - 1900) * 12 + int(m)
    base = min(t["released"] for t in ref_truth)
    by, bm, _ = base.split("-")
    y, m, _ = version.split("-")
    return (int(y) - int(by)) * 12 + (int(m) - int(bm))


# ---- top-level orchestration ----------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="longitudinal_sim")
    p.add_argument("--patients", type=int, default=5,
                   help="cohort size (smoke=5; SPEC target=100)")
    p.add_argument("--months", type=int, default=24)
    p.add_argument("--start", default="2024-01")
    p.add_argument("--seed", type=int, default=20240101)
    p.add_argument("--rate-scale", type=float, default=8.0,
                   help="see clinvar_archive.synthesize_archive")
    p.add_argument("--clinvar-archive", type=Path, default=None,
                   help="optional real ClinVar archive directory")
    p.add_argument("--out", type=Path,
                   default=RESULTS_DIR / "exp04_longitudinal_smoke.json")
    p.add_argument("--keep-tmp", action="store_true")
    args = p.parse_args(argv)

    t0 = time.time()
    print(f"[longitudinal_sim] patients={args.patients} months={args.months} "
          f"seed={args.seed} archive={'real' if args.clinvar_archive else 'synthetic'}")

    # 1. Get archive snapshots.
    if args.clinvar_archive:
        snapshots = ca.load_real_archive(args.clinvar_archive)
    else:
        snapshots = ca.synthesize_archive(
            start=args.start, n_months=args.months, seed=args.seed,
            rate_scale=args.rate_scale,
        )

    # 2. Install rulesets so `bio update` can find them.
    ruleset_paths = ca.install_archive(snapshots)
    print(f"[longitudinal_sim] installed {len(ruleset_paths)} ruleset files")

    # 3. Build cohort.
    work_root = Path(tempfile.mkdtemp(prefix="dotbio-longitudinal-"))
    try:
        cohort_t0 = time.time()
        cohort = build_cohort(args.patients, work_root)
        print(f"[longitudinal_sim] cohort built in "
              f"{time.time()-cohort_t0:.1f}s ({len(cohort)} patients)")

        # 4. Compile per-patient ground truth.
        per_patient_truth: dict[str, list[dict]] = {}
        for pat in cohort:
            gts = _patient_clinvar_genotypes(Path(pat["vcf"]))
            per_patient_truth[pat["id"]] = _ground_truth_for_patient(
                snapshots, gts
            )

        # 5. Run both arms.
        # We run arm_soc first because it leaves the bundle at the
        # latest-quarter HEAD; arm_bio must start from a fresh bundle.
        # To keep arms truly independent, we DUPLICATE each bundle.
        arm_results = {"arm_soc": [], "arm_bio": []}
        per_arm_endpoints = {"arm_soc": [], "arm_bio": []}

        for pat in cohort:
            for arm_kind in ("arm_soc", "arm_bio"):
                # clone bundle
                src = Path(pat["bundle"])
                dst = src.with_name(f"{src.name}.{arm_kind}")
                if dst.exists():
                    shutil.rmtree(dst)
                shutil.copytree(src, dst)
                pat_clone = {**pat, "bundle": str(dst)}

                if arm_kind == "arm_bio":
                    run = run_arm_bio(pat_clone, snapshots)
                else:
                    run = run_arm_soc(pat_clone, snapshots)
                arm_results[arm_kind].append(run)
                ep = compute_endpoints(run, per_patient_truth[pat["id"]],
                                       arm_kind)
                ep["patient"] = pat["id"]
                per_arm_endpoints[arm_kind].append(ep)

        # 6. Aggregate.
        def _agg(eps: list[dict]) -> dict:
            n_truth = sum(e["n_actionable_truth"] for e in eps)
            n_cap = sum(e["n_captured"] for e in eps)
            tokens = sum(e["cumulative_tokens"] for e in eps)
            lat_pairs = [
                (e["mean_latency_months"], e["n_captured"])
                for e in eps if e["n_captured"] > 0
            ]
            if lat_pairs:
                tot_lat = sum(l * n for l, n in lat_pairs)
                tot_n = sum(n for _, n in lat_pairs)
                weighted_lat = tot_lat / tot_n if tot_n else 0.0
            else:
                weighted_lat = 0.0
            return {
                "n_actionable_truth_total": n_truth,
                "n_captured_total": n_cap,
                "fnr": (n_truth - n_cap) / n_truth if n_truth > 0 else 0.0,
                "mean_latency_months_weighted": weighted_lat,
                "cumulative_tokens_total": tokens,
                "n_patients": len(eps),
            }

        summary = {
            "arm_soc": _agg(per_arm_endpoints["arm_soc"]),
            "arm_bio": _agg(per_arm_endpoints["arm_bio"]),
        }

        # 7. Emit JSON.
        archive_meta = {
            "mode": "real" if args.clinvar_archive else "synthetic",
            "start": args.start,
            "n_months": args.months,
            "seed": args.seed,
            "rate_scale": args.rate_scale,
            "n_snapshots": len(snapshots),
            "n_reclassifications_total": sum(
                len(s["reclassifications"]) for s in snapshots
            ),
            "n_actionable_total": sum(
                sum(1 for r in s["reclassifications"] if r["actionable"])
                for s in snapshots
            ),
            "transition_matrix_source": (
                "Landrum 2018 Nucleic Acids Res 46(D1):D1062 + "
                "Harrison & Rehm 2019 Genet Med — see clinvar_archive.py"
            ),
        }

        result = {
            "experiment": "exp04_longitudinal",
            "spec_section": "SPEC.md §3.4",
            "wall_clock_seconds": time.time() - t0,
            "archive": archive_meta,
            "cohort": [
                {"id": p["id"], "include_brca": p["include_brca"]}
                for p in cohort
            ],
            "summary": summary,
            "per_patient_endpoints": per_arm_endpoints,
            "per_patient_truth_counts": {
                pid: {
                    "n_total": len(truth),
                    "n_actionable": sum(1 for t in truth if t["actionable"]),
                }
                for pid, truth in per_patient_truth.items()
            },
        }
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps(result, indent=2, ensure_ascii=False))
        print(f"[longitudinal_sim] wrote {args.out}")
        print(f"[longitudinal_sim] arm_soc FNR={summary['arm_soc']['fnr']:.3f}  "
              f"arm_bio FNR={summary['arm_bio']['fnr']:.3f}  "
              f"({time.time()-t0:.1f}s)")

    finally:
        # 8. Cleanup ruleset files we installed; tmp dir is preserved
        # only when --keep-tmp is set.
        n = ca.uninstall_archive(snapshots)
        print(f"[longitudinal_sim] uninstalled {n} ruleset files")
        if not args.keep_tmp:
            shutil.rmtree(work_root, ignore_errors=True)
        else:
            print(f"[longitudinal_sim] kept tmp at {work_root}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
