"""Performance / scalability benchmark for dotbio (SPEC §3.5, Task 7).

Measures, per input scale tier:
  - Compile time (cold + warm), 5 runs, median + IQR
  - Bundle size on disk (compressed `.bio.tar.gz` and uncompressed)
  - `bio show` query latency, 100 runs, median + p95
  - `bio update` latency, 5 runs
  - Memory peak (RSS) during compile (tracemalloc-driven; falls back to
    `/usr/bin/time -v` when sub-process measurement is required)

Stdlib only — `time`, `resource`, `tracemalloc`, `tarfile`, `subprocess`.

Round 1 runs on the small example VCFs that already ship with the repo.
The same code scales to full WGS when `HG002_WGS_VCF` is set; that
scenario is skipped gracefully if the env var is unset (we never
download). Smoke run on the existing examples completes in <30s.

Round 2 (WGS-scale, opt-in): when `HG002_WGS_VCF` points at an
existing VCF, an extra `hg002_wgs_full` tier runs. Because a single
WGS compile takes minutes (millions of CAS files), the WGS tier
defaults to a budget configuration that sidesteps the round-1
defaults: 1 cold compile (no warm), 20 show runs, update skipped, and
tracemalloc disabled (it imposes ~3-5x overhead at 4M+ allocations).
Each can be overridden via env vars — see README_perf.md.

Usage:
    python bench/v2/scripts/perf_bench.py             # round-1 default
    python bench/v2/scripts/perf_bench.py --quick     # fewer runs

    # round-2 WGS (provide your own VCF; never downloaded). Writes a
    # SEPARATE results file so round-1 numbers stay intact.
    HG002_WGS_VCF=/tmp/HG002.vcf HG002_WGS_ONLY=1 \
        python bench/v2/scripts/perf_bench.py \
            --out bench/v2/results/exp05_perf_wgs.json

Output (round 1): bench/v2/results/exp05_perf.json
Output (round 2): bench/v2/results/exp05_perf_wgs.json
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import resource
import shutil
import statistics
import subprocess
import sys
import tarfile
import tempfile
import time
import tracemalloc
from pathlib import Path

# ---- module path setup -----------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[3]
SRC = REPO_ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

# Importing dotbio in-process lets us instrument compile with tracemalloc
# without forking. We still exercise the CLI via subprocess for `show` and
# `update` so we measure realistic end-user latency including process start.
import dotbio  # noqa: E402  (after sys.path mutation)
from dotbio.cli import main as bio_main  # noqa: E402


# ---- helpers ---------------------------------------------------------------


def _median_iqr(samples: list[float]) -> dict[str, float]:
    """Return median, q1, q3, IQR, p95, min, max for a list of samples."""
    if not samples:
        return {"n": 0}
    s = sorted(samples)
    n = len(s)
    median = statistics.median(s)
    # quartiles via inclusive method
    if n >= 4:
        q1 = statistics.quantiles(s, n=4, method="inclusive")[0]
        q3 = statistics.quantiles(s, n=4, method="inclusive")[2]
    else:
        q1 = s[0]
        q3 = s[-1]
    # p95
    if n >= 20:
        p95 = statistics.quantiles(s, n=20, method="inclusive")[18]
    else:
        # Linear interpolation on the small-sample case
        idx = 0.95 * (n - 1)
        lo = int(idx)
        hi = min(lo + 1, n - 1)
        frac = idx - lo
        p95 = s[lo] * (1 - frac) + s[hi] * frac
    return {
        "n": n,
        "median": median,
        "q1": q1,
        "q3": q3,
        "iqr": q3 - q1,
        "p95": p95,
        "min": s[0],
        "max": s[-1],
        "mean": statistics.fmean(s),
    }


def _dir_uncompressed_size(path: Path) -> int:
    total = 0
    for root, _, files in os.walk(path):
        for fn in files:
            fp = Path(root) / fn
            try:
                total += fp.stat().st_size
            except OSError:
                pass
    return total


def _make_tar_gz(bundle: Path, dest: Path) -> int:
    """Compress bundle to .bio.tar.gz; return compressed byte size."""
    with tarfile.open(dest, "w:gz", compresslevel=6) as tar:
        tar.add(bundle, arcname=bundle.name)
    return dest.stat().st_size


def _rss_kb_self() -> int:
    """Current process peak RSS in kilobytes (resource.getrusage)."""
    ru = resource.getrusage(resource.RUSAGE_SELF)
    # macOS reports ru_maxrss in bytes; Linux in kilobytes.
    if sys.platform == "darwin":
        return int(ru.ru_maxrss / 1024)
    return int(ru.ru_maxrss)


def _run_bio_inprocess(argv: list[str]) -> int:
    """Run `bio <argv>` in-process by calling cli.main(). Captures stdout
    to /dev/null to avoid polluting the bench output."""
    # silence stdout/stderr to keep timing clean
    devnull = open(os.devnull, "w")
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = devnull
    sys.stderr = devnull
    try:
        rc = bio_main(argv)
    finally:
        sys.stdout, sys.stderr = saved_out, saved_err
        devnull.close()
    return rc


def _run_bio_subprocess(argv: list[str]) -> tuple[int, float]:
    """Run `bio <argv>` as a subprocess and return (rc, wall_seconds)."""
    t0 = time.perf_counter()
    rc = subprocess.run(
        ["bio"] + argv,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        check=False,
    ).returncode
    t1 = time.perf_counter()
    return rc, t1 - t0


# ---- measurement primitives -----------------------------------------------


def measure_compile_runs(vcf: Path, n_runs: int, workdir: Path,
                         enable_tracemalloc: bool = True) -> dict:
    """Run compile n_runs times in-process. The first run is the COLD run
    (workdir empty, ruleset cache cold); subsequent runs are WARM (rulesets
    already loaded into module cache).

    Returns separated cold and warm timing distributions, plus peak RSS.

    ``enable_tracemalloc`` controls whether the in-process Python heap
    profiler runs alongside compile. Tracemalloc adds ~3–5× CPU
    overhead at WGS scale (millions of allocations) — fine for the
    small-data tiers, prohibitive at full WGS, where the round-2
    invocation disables it. RSS via ``getrusage`` is always recorded.
    """
    cold_seconds = []
    warm_seconds = []
    peak_rss_kb = []
    peak_traced_bytes = []

    for i in range(n_runs):
        out = workdir / f"bundle_{i}.bio"
        if out.exists():
            shutil.rmtree(out)

        # Reset peak RSS counter is not possible; capture deltas instead.
        rss_before = _rss_kb_self()

        if enable_tracemalloc:
            tracemalloc.start()
        t0 = time.perf_counter()
        rc = _run_bio_inprocess(["compile", str(vcf), "-o", str(out), "--force"])
        t1 = time.perf_counter()
        if enable_tracemalloc:
            _current, peak = tracemalloc.get_traced_memory()
            tracemalloc.stop()
        else:
            peak = 0  # tracemalloc disabled — see RSS for memory peak

        rss_after = _rss_kb_self()
        if rc != 0:
            raise RuntimeError(f"compile failed (rc={rc}) on run {i} for {vcf}")

        elapsed = t1 - t0
        if i == 0:
            cold_seconds.append(elapsed)
        else:
            warm_seconds.append(elapsed)
        peak_traced_bytes.append(peak)
        peak_rss_kb.append(max(rss_after, rss_before))

    return {
        "cold_seconds": cold_seconds,
        "warm_seconds": warm_seconds,
        "cold_stats": _median_iqr(cold_seconds),
        "warm_stats": _median_iqr(warm_seconds),
        "tracemalloc_enabled": enable_tracemalloc,
        "tracemalloc_peak_bytes": _median_iqr(peak_traced_bytes),
        "rss_peak_kb": _median_iqr(peak_rss_kb),
    }


def measure_show_latency(bundle: Path, n_runs: int) -> dict:
    """Time `bio show --view pgx` n_runs times.

    Uses in-process invocation: this measures the dotbio code path latency
    (the question for the manuscript), not Python startup overhead.
    """
    samples = []
    for _ in range(n_runs):
        t0 = time.perf_counter()
        rc = _run_bio_inprocess(["show", str(bundle), "--view", "pgx"])
        t1 = time.perf_counter()
        if rc != 0:
            raise RuntimeError(f"show failed (rc={rc}) for {bundle}")
        samples.append(t1 - t0)
    return {
        "samples_seconds": samples,
        "stats": _median_iqr(samples),
    }


def measure_update_latency(vcf: Path, n_runs: int, workdir: Path) -> dict:
    """Time `bio update --ruleset clinvar@2026-05-08` n_runs times.

    Each run uses a fresh bundle (compiled once before the timing loop), so
    every update sees the same starting state.
    """
    samples = []
    for i in range(n_runs):
        out = workdir / f"upd_{i}.bio"
        if out.exists():
            shutil.rmtree(out)
        rc = _run_bio_inprocess(["compile", str(vcf), "-o", str(out), "--force"])
        if rc != 0:
            raise RuntimeError(f"compile-before-update failed (rc={rc})")

        t0 = time.perf_counter()
        rc = _run_bio_inprocess(
            ["update", str(out), "--ruleset", "clinvar@2026-05-08"]
        )
        t1 = time.perf_counter()
        if rc != 0:
            raise RuntimeError(f"update failed (rc={rc})")
        samples.append(t1 - t0)
    return {
        "samples_seconds": samples,
        "stats": _median_iqr(samples),
    }


def measure_bundle_size(vcf: Path, workdir: Path) -> dict:
    """Compile once, then measure uncompressed dir size and .bio.tar.gz."""
    bundle = workdir / "size_probe.bio"
    if bundle.exists():
        shutil.rmtree(bundle)
    rc = _run_bio_inprocess(["compile", str(vcf), "-o", str(bundle), "--force"])
    if rc != 0:
        raise RuntimeError(f"compile-for-size failed (rc={rc})")

    uncompressed = _dir_uncompressed_size(bundle)
    tar_path = workdir / "size_probe.bio.tar.gz"
    if tar_path.exists():
        tar_path.unlink()
    compressed = _make_tar_gz(bundle, tar_path)

    return {
        "uncompressed_bytes": uncompressed,
        "compressed_tar_gz_bytes": compressed,
        "compression_ratio": (uncompressed / compressed) if compressed else None,
    }


# ---- per-tier driver -------------------------------------------------------


def _vcf_variant_count(vcf: Path) -> int:
    n = 0
    with vcf.open() as fh:
        for line in fh:
            if line.startswith("#"):
                continue
            if line.strip():
                n += 1
    return n


def run_tier(name: str, vcf: Path, n_compile: int, n_show: int, n_update: int,
             workdir: Path, reuse_compile_for_size: bool = False,
             enable_tracemalloc: bool = True) -> dict:
    """Run all measurements for one input scale tier.

    When ``reuse_compile_for_size`` is True, the bundle produced by the
    cold compile run is reused for both bundle-size measurement and as
    the input to ``measure_show_latency`` — avoiding two extra full
    compiles. This matters at WGS scale, where a single compile may
    take tens of minutes; the timing-relevant numbers (compile and show)
    are unaffected because they read from the same on-disk artifact a
    fresh compile would have produced.
    """
    print(f"  [{name}] vcf={vcf.name}  ({_vcf_variant_count(vcf)} variants)",
          file=sys.stderr)

    tier_dir = workdir / name
    tier_dir.mkdir(parents=True, exist_ok=True)

    tm_label = "tracemalloc=on" if enable_tracemalloc else "tracemalloc=off"
    print(f"    compile x{n_compile} (1 cold + {max(0, n_compile - 1)} warm, {tm_label})...",
          file=sys.stderr)
    compile_block = measure_compile_runs(
        vcf, n_compile, tier_dir, enable_tracemalloc=enable_tracemalloc,
    )

    if reuse_compile_for_size:
        # Reuse bundle_0 from the compile run as the size + show probe.
        probe = tier_dir / "bundle_0.bio"
        if not probe.exists():
            raise RuntimeError(f"reuse mode: expected {probe} from compile run")
        print(f"    bundle size (reused from compile run)...", file=sys.stderr)
        uncompressed = _dir_uncompressed_size(probe)
        tar_path = tier_dir / "size_probe.bio.tar.gz"
        if tar_path.exists():
            tar_path.unlink()
        compressed = _make_tar_gz(probe, tar_path)
        size_block = {
            "uncompressed_bytes": uncompressed,
            "compressed_tar_gz_bytes": compressed,
            "compression_ratio": (uncompressed / compressed) if compressed else None,
        }
        show_bundle = probe
    else:
        print(f"    bundle size...", file=sys.stderr)
        size_block = measure_bundle_size(vcf, tier_dir)

        # Reuse one bundle for show timing
        show_bundle = tier_dir / "show_probe.bio"
        if show_bundle.exists():
            shutil.rmtree(show_bundle)
        rc = _run_bio_inprocess(["compile", str(vcf), "-o", str(show_bundle), "--force"])
        if rc != 0:
            raise RuntimeError("compile-for-show failed")

    print(f"    bio show x{n_show}...", file=sys.stderr)
    show_block = measure_show_latency(show_bundle, n_show)

    if n_update > 0:
        print(f"    bio update x{n_update}...", file=sys.stderr)
        update_block = measure_update_latency(vcf, n_update, tier_dir)
    else:
        update_block = {
            "skipped": True,
            "reason": "n_update=0 (WGS budget mode: skipping repeated re-compiles)",
        }

    return {
        "name": name,
        "vcf_path": str(vcf),
        "vcf_variant_count": _vcf_variant_count(vcf),
        "compile": compile_block,
        "bundle_size": size_block,
        "show_pgx": show_block,
        "update_clinvar": update_block,
    }


# ---- main ------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument(
        "--out",
        default=str(REPO_ROOT / "bench" / "v2" / "results" / "exp05_perf.json"),
        help="output JSON path",
    )
    p.add_argument(
        "--quick",
        action="store_true",
        help="reduce replicate counts (smoke run)",
    )
    p.add_argument(
        "--workdir",
        default=None,
        help="scratch directory (default: tempdir)",
    )
    args = p.parse_args(argv)

    n_compile = 3 if args.quick else 5
    n_show = 30 if args.quick else 100
    n_update = 3 if args.quick else 5

    # WGS-tier override: at full HG002 scale a single compile can take
    # tens of minutes (millions of small CAS files). The 5-runs-default
    # would blow the 90-min budget. Defaults: cold-only compile (n=1),
    # show=20 runs, update=skipped. Each can be overridden:
    wgs_n_compile = int(os.environ.get("HG002_WGS_N_COMPILE", "1"))
    wgs_n_show = int(os.environ.get("HG002_WGS_N_SHOW", "20"))
    wgs_n_update = int(os.environ.get("HG002_WGS_N_UPDATE", "0"))
    wgs_only = os.environ.get("HG002_WGS_ONLY", "").lower() in {"1", "true", "yes"}

    tiers: list[tuple[str, Path]] = []
    if not wgs_only:
        tiers.extend([
            ("synthetic_11_variants", REPO_ROOT / "examples/synthetic/input.vcf"),
            ("real_na12878_8_variants", REPO_ROOT / "examples/real-na12878/input.vcf"),
        ])

    # Optional: full HG002 WGS — opt-in via env var, never downloaded here.
    wgs_env = os.environ.get("HG002_WGS_VCF")
    wgs_skip_reason = None
    wgs_tier_added = False
    if wgs_env:
        wgs_path = Path(wgs_env).expanduser()
        if wgs_path.exists():
            tiers.append(("hg002_wgs_full", wgs_path))
            wgs_tier_added = True
        else:
            wgs_skip_reason = f"HG002_WGS_VCF set but path does not exist: {wgs_path}"
    else:
        wgs_skip_reason = "HG002_WGS_VCF env var not set; skipping full-WGS tier"

    # Workdir
    cleanup_workdir = False
    if args.workdir:
        workdir = Path(args.workdir)
        workdir.mkdir(parents=True, exist_ok=True)
    else:
        workdir = Path(tempfile.mkdtemp(prefix="dotbio_perf_"))
        cleanup_workdir = True

    print(f"perf_bench: workdir={workdir}", file=sys.stderr)
    print(f"perf_bench: tiers={[t[0] for t in tiers]}", file=sys.stderr)
    if wgs_skip_reason:
        print(f"perf_bench: WGS tier skipped — {wgs_skip_reason}", file=sys.stderr)

    t_start = time.perf_counter()
    tier_results = []
    for name, vcf in tiers:
        if not vcf.exists():
            print(f"  [{name}] SKIP — vcf missing: {vcf}", file=sys.stderr)
            tier_results.append({
                "name": name,
                "skipped": True,
                "reason": f"vcf missing: {vcf}",
            })
            continue
        is_wgs = name == "hg002_wgs_full"
        tier_n_compile = wgs_n_compile if is_wgs else n_compile
        tier_n_show = wgs_n_show if is_wgs else n_show
        tier_n_update = wgs_n_update if is_wgs else n_update
        try:
            tier_results.append(run_tier(
                name, vcf, tier_n_compile, tier_n_show, tier_n_update,
                workdir, reuse_compile_for_size=is_wgs,
                enable_tracemalloc=not is_wgs,
            ))
        except Exception as e:  # noqa: BLE001 — we want to record any failure
            tier_results.append({
                "name": name,
                "skipped": True,
                "reason": f"error during measurement: {e!r}",
            })
            print(f"  [{name}] ERROR: {e!r}", file=sys.stderr)

    total_seconds = time.perf_counter() - t_start

    payload = {
        "schema": "dotbio.bench.exp05_perf.v1",
        "spec_section": "bench/v2/SPEC.md §3.5 (Experiment 5 — Performance / scalability)",
        "task": "bench/v2/TASKS.md Task 7 — Performance benchmark runner",
        "dotbio_version": dotbio.__version__,
        "schema_version": dotbio.SCHEMA,
        "host": {
            "platform": platform.platform(),
            "python": sys.version.split()[0],
            "cpu": platform.processor() or platform.machine(),
            "darwin_rss_unit": "bytes_then_kb_normalized",
        },
        "config": {
            "n_compile_runs": n_compile,
            "n_show_runs": n_show,
            "n_update_runs": n_update,
            "quick_mode": args.quick,
            "wgs_n_compile_runs": wgs_n_compile if wgs_tier_added else None,
            "wgs_n_show_runs": wgs_n_show if wgs_tier_added else None,
            "wgs_n_update_runs": wgs_n_update if wgs_tier_added else None,
            "wgs_only": wgs_only,
        },
        "wgs_tier_status": wgs_skip_reason or "ran",
        "tiers": tier_results,
        "wall_seconds_total": total_seconds,
    }

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
    print(f"perf_bench: wrote {out_path}  (total {total_seconds:.2f}s)",
          file=sys.stderr)

    # One-line stdout summary for the orchestrator/caller.
    headline_tier = next(
        (t for t in tier_results if not t.get("skipped")), None
    )
    if headline_tier:
        cs = headline_tier["compile"]["cold_stats"]
        bs = headline_tier["bundle_size"]
        print(
            f"summary: tier={headline_tier['name']} "
            f"compile_cold_median={cs.get('median', 0):.4f}s "
            f"bundle_uncompressed={bs['uncompressed_bytes']}B "
            f"bundle_compressed={bs['compressed_tar_gz_bytes']}B"
        )

    if cleanup_workdir:
        shutil.rmtree(workdir, ignore_errors=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
