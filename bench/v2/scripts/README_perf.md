# Performance / scalability benchmark — `perf_bench.py`

**Task**: bench/v2/TASKS.md Task 7
**Spec**: bench/v2/SPEC.md §3.5 — Experiment 5
**Output**: `bench/v2/results/exp05_perf.json`

This script measures the wall-clock and memory footprint of the dotbio
pipeline across input scale tiers, so the manuscript can claim a concrete
performance budget. Round 1 covers the small example VCFs that already
ship with the repo; the same code path scales to a full HG002 WGS call
set when the user provides one (no download is performed by this
benchmark).

## What is measured

For each input scale tier (one VCF):

| Metric | Replicates | Reported |
|---|---|---|
| Compile time, cold | 1 (first run) | absolute wall-clock seconds |
| Compile time, warm | n − 1 follow-up runs | median + IQR + p95 |
| Bundle size, uncompressed | 1 | bytes (`os.walk` sum of `st_size`) |
| Bundle size, compressed | 1 | bytes (`.bio.tar.gz`, gzip level 6) |
| `bio show --view pgx` latency | 100 | median + p95 |
| `bio update --ruleset …` latency | 5 | median + IQR |
| Memory peak (`tracemalloc`) | every compile | median + IQR (bytes) |
| Memory peak (RSS, `getrusage`) | every compile | median + IQR (KB) |

The `cold` vs `warm` split for compile is a real distinction in dotbio:
the first run loads ruleset JSON files from disk into a module-level
cache (`dotbio.engine.load_ruleset`), so subsequent runs in the same
process pay only the parsing-from-cache cost.

## Tiers

Round 1 (always run):

- **`synthetic_11_variants`** — `examples/synthetic/input.vcf` (11 variants,
  exercises CYP2C19, TPMT, DPYD, MTHFR, BRCA1, KRAS).
- **`real_na12878_8_variants`** — `examples/real-na12878/input.vcf`
  (8 GIAB-extracted PGx loci for NA12878).

Optional (only when `HG002_WGS_VCF` env var points at an existing file):

- **`hg002_wgs_full`** — full HG002 WGS variant call set (~4.7M variants
  per the spec). Skipped gracefully with a logged reason if the env var
  is unset; the benchmark **never** downloads.

## How to run

```bash
# default — 5 compile runs, 100 show runs, 5 update runs
python bench/v2/scripts/perf_bench.py

# smoke (fewer replicates, useful for CI)
python bench/v2/scripts/perf_bench.py --quick

# full WGS scenario (must provide your own VCF; not downloaded)
HG002_WGS_VCF=/data/hg002/hg002.vcf.gz python bench/v2/scripts/perf_bench.py
```

The script writes `bench/v2/results/exp05_perf.json` and prints a
one-line summary on stdout.

## Methodology notes

- **Stdlib only.** Uses `time.perf_counter` for wall-clock,
  `tracemalloc` for in-process Python memory peaks, and
  `resource.getrusage(RUSAGE_SELF).ru_maxrss` for OS-reported peak RSS.
  On macOS the kernel reports `ru_maxrss` in bytes; on Linux it reports
  KB. The script normalizes both to KB and labels the convention in the
  output JSON (`host.darwin_rss_unit`).
- **In-process invocation.** `bio` is invoked via `dotbio.cli.main()`
  rather than by spawning a subprocess. This isolates the dotbio code
  path from Python interpreter startup overhead, which would dominate
  the per-call cost on the small examples and obscure scaling behavior.
  The `_run_bio_subprocess` helper is provided for callers who want
  end-user-perceived latency including process startup.
- **Cold/warm split.** The first compile run inside the benchmark is
  treated as cold; later runs are warm. We do not attempt to invalidate
  the OS page cache between runs — that would require sudo or
  `/usr/bin/time -v` — but rulesets are tiny JSON files and the page
  cache effect is negligible at this scale. For the WGS tier, where I/O
  cost matters, the cold run starts with a freshly created bundle
  directory and a freshly imported `dotbio` (so the module-level ruleset
  cache is empty for the cold call only because each run uses a
  different output directory).
- **Compression.** Compressed bundles are produced by `tarfile.open(...,
  mode="w:gz", compresslevel=6)` to a temporary file inside the per-tier
  workdir; only the final `st_size` is reported.
- **Statistics.** `median`, `q1`/`q3`, `iqr`, `p95`, `min`, `max`, `mean`
  computed via `statistics.quantiles(method="inclusive")` for n ≥ 4 and
  by linear interpolation for smaller samples (relevant only for the
  one-shot cold metric).

## Output schema

`exp05_perf.json` is the canonical output. Top-level keys:

- `schema` — `dotbio.bench.exp05_perf.v1`
- `dotbio_version`, `schema_version`
- `host` — platform, python version, RSS unit convention
- `config` — `n_compile_runs`, `n_show_runs`, `n_update_runs`, `quick_mode`
- `wgs_tier_status` — string explaining whether the WGS tier ran
- `tiers[]` — per-tier blocks. Each block contains:
  - `name`, `vcf_path`, `vcf_variant_count`
  - `compile.{cold_seconds, warm_seconds, cold_stats, warm_stats,
    tracemalloc_peak_bytes, rss_peak_kb}`
  - `bundle_size.{uncompressed_bytes, compressed_tar_gz_bytes,
    compression_ratio}`
  - `show_pgx.{samples_seconds, stats}`
  - `update_clinvar.{samples_seconds, stats}`
- `wall_seconds_total` — total benchmark wall-clock

A skipped tier is recorded as `{"name": "...", "skipped": true,
"reason": "..."}`.

## Round-1 results (existing examples)

The benchmark runs in well under 30 seconds on existing examples (the
acceptance criterion in TASKS.md Task 7). Representative numbers from
one run on macOS (M-series, Python 3.11):

| Tier | Variants | Compile cold | Compile warm (median) | `show` median | `show` p95 | Update median | Uncompressed | `.bio.tar.gz` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `synthetic_11_variants` | 11 | ~19 ms | ~11 ms | ~0.6 ms | ~0.9 ms | ~3 ms | ~20 KB | ~7 KB |
| `real_na12878_8_variants` | 8 | ~8 ms | ~9 ms | ~0.6 ms | ~0.9 ms | ~2 ms | ~6.6 KB | ~3.9 KB |

These numbers are illustrative; the JSON file is the authoritative
record and includes IQRs.

## What round 2 / round 3 should add

- A real `hg002_wgs_full` row (paper headline: "compile 4.7M variants in
  X minutes / Y GB peak RSS").
- A 100-patient cohort tier (compile per-individual in parallel,
  measure per-individual median + total wall-clock).
- A baseline comparator: time PharmCAT / VEP on the same inputs to
  contextualize whether dotbio's compile cost is competitive.
- Cache-cold compile via `subprocess` invocation with a fresh Python
  interpreter, to measure the user-perceived CLI startup as well.

## Files written

- `bench/v2/scripts/perf_bench.py` — this script
- `bench/v2/results/exp05_perf.json` — measurement output
- `bench/v2/scripts/README_perf.md` — this README
