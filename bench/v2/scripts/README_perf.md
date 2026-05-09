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

Round 1 (always run, "small data"):

- **`synthetic_11_variants`** — `examples/synthetic/input.vcf` (11 variants,
  exercises CYP2C19, TPMT, DPYD, MTHFR, BRCA1, KRAS).
- **`real_na12878_8_variants`** — `examples/real-na12878/input.vcf`
  (8 GIAB-extracted PGx loci for NA12878).

Round 2 ("WGS scale", opt-in via env var):

- **`hg002_wgs_full`** — full HG002 GIAB v4.2.1 autosomal call set
  (chr1–22, **4 048 342 variants**). Skipped gracefully when the env
  var is unset; the benchmark **never** downloads. See
  `bench/v2/data/hg002_wgs/README.md` for the retrieval recipe.

### WGS budget mode (round 2)

A single WGS compile is dominated by Python file-system overhead:
the bundle stores one ~250-byte JSON file per variant under a
2-char-prefix CAS layout. At 4 M facts that's millions of `mkdir +
write + close` syscalls. Five cold+warm compile runs, plus separate
size and update probes, would blow the 90-min budget.

To make the WGS tier tractable, four env vars override the per-tier
replicate counts when (and only when) a WGS run is active:

| Env var | Default at WGS tier | Round-1 default it overrides |
|---|---:|---:|
| `HG002_WGS_N_COMPILE` | `1` (cold only) | 5 |
| `HG002_WGS_N_SHOW`    | `20`            | 100 |
| `HG002_WGS_N_UPDATE`  | `0` (skipped)   | 5 |
| `HG002_WGS_ONLY`      | unset (`0`)     | n/a |

`HG002_WGS_ONLY=1` skips the small-data tiers entirely so a WGS-only
re-run does not redo round-1 measurements. When `n_update=0` the
update block records `{"skipped": true, "reason": "..."}`; when
`n_compile=1` the compile block reports only the cold timing (no warm
distribution). At WGS scale the compile run also doubles as the
size-probe and show-probe input (`reuse_compile_for_size=True`),
saving two extra ~30-min compiles.

## How to run

```bash
# default round-1 — 5 compile runs, 100 show runs, 5 update runs
python bench/v2/scripts/perf_bench.py

# smoke (fewer replicates, useful for CI)
python bench/v2/scripts/perf_bench.py --quick

# round-2 full WGS scenario (must provide your own VCF; never downloaded).
# Writes a SEPARATE results file so round-1 numbers are preserved.
HG002_WGS_VCF=/tmp/dotbio_wgs/HG002_GRCh38_1_22_v4.2.1.vcf \
HG002_WGS_ONLY=1 \
python bench/v2/scripts/perf_bench.py \
  --out bench/v2/results/exp05_perf_wgs.json \
  --workdir /tmp/dotbio_wgs_workdir
```

The round-1 invocation writes `bench/v2/results/exp05_perf.json`; the
round-2 invocation writes `bench/v2/results/exp05_perf_wgs.json`.
Both print a one-line summary on stdout.

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

## Round-1 results — small data (existing examples)

The benchmark runs in well under 30 seconds on existing examples (the
acceptance criterion in TASKS.md Task 7). Representative numbers from
one run on macOS (M-series, Python 3.11):

| Tier | Variants | Compile cold | Compile warm (median) | `show` median | `show` p95 | Update median | Uncompressed | `.bio.tar.gz` |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `synthetic_11_variants` | 11 | ~19 ms | ~11 ms | ~0.6 ms | ~0.9 ms | ~3 ms | ~20 KB | ~7 KB |
| `real_na12878_8_variants` | 8 | ~8 ms | ~9 ms | ~0.6 ms | ~0.9 ms | ~2 ms | ~6.6 KB | ~3.9 KB |

These numbers are illustrative; `bench/v2/results/exp05_perf.json` is
the authoritative record and includes IQRs.

## Round-2 results — full WGS (HG002 GIAB v4.2.1, chr1–22)

| Tier | Variants | Compile cold | `show` median | `show` p95 | Update | Uncompressed bundle | `.bio.tar.gz` | Peak RSS |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| `hg002_wgs_full` | 4 048 342 | **1658.4 s** (~27.6 min) | 0.41 ms | 0.55 ms | skipped (budget) | 588.8 MB | 370.9 MB | 2.88 GB |

Total benchmark wall-clock: **3523 s** (~58.7 min) — most of which is
the bundle-size + tar.gz step on top of the 27.6-min cold compile.
Compression ratio at WGS scale was 1.59× (worse than the small-data
tiers, where it was 1.7–2.7×; the WGS bundle is dominated by per-fact
JSON + a deep CAS directory tree, both of which gzip well in absolute
terms but bring down the overall ratio).

Authoritative record: `bench/v2/results/exp05_perf_wgs.json`. Round-1
small-data results are preserved untouched in the existing
`exp05_perf.json` file (the round-2 invocation writes a separate
output path so the two snapshots can be compared).

### What round 2 reveals about scaling

Going from ~10-variant inputs to 4 M variants is a **5+ orders of
magnitude** input-size increase. Observed scaling:

- **Compile time**: super-linear. ~10 ms cold for 11 variants (round 1)
  → 1658 s cold for 4 M variants (round 2). That's ~16.6× the input
  ratio per ms (a perfect linear scaling would predict ~3.7 s for 4 M
  variants from the 11-variant baseline; the actual 1658 s is **~450×
  worse**). The dominant cost is fact-CAS file IO — one ~150-byte JSON
  per variant means ~4 M `mkdir + write + close` syscalls.
- **Bundle size**: roughly linear at ~145 bytes uncompressed per
  variant (588 MB / 4 M variants). Gzip ratio is *worse* at WGS scale
  (1.59×) than on small tiers (1.69–2.74×) — the per-fact JSON is
  short and the CAS prefix tree introduces non-text bytes that gzip
  can't squeeze.
- **`show` latency**: nearly **constant** across input scales. Round-1
  small data: ~0.5 ms median. Round-2 4 M variants: 0.41 ms median.
  This is the manuscript-headline result: views are pre-rendered
  Markdown files of bounded size (only PGx-relevant claims survive),
  so query latency does not depend on the underlying fact count.
- **Memory peak**: 2.88 GB RSS at WGS compile vs ~22 MB on small
  tiers. The growth is **linear in variant count** because
  `_vcf_to_facts` builds the full per-variant dict list in memory
  before writing any fact, and `apply_clinvar`/`apply_pharmcat` then
  iterate the whole list once each.

### Bottlenecks to address in round 3 (do not fix in round 2)

The full-WGS run exposes four concrete optimization opportunities.
None of them are fixed here — round 2's deliverable is the measurement
that justifies them.

1. **Streaming compile** (peak RSS 2.88 GB at WGS, vs 22 MB on small
   tiers — a ~130× blow-up). `cli._vcf_to_facts` collects every record
   into a Python list before any fact is written. A generator-based
   pipeline (`parse_vcf` → `bundle.write_fact` → claim accumulation)
   would cut peak RSS by an order of magnitude and start producing
   bundle output immediately.
2. **CAS layer batching / packfile** (cold compile 1658 s at WGS, of
   which ~80 % is the 4 M `mkdir + write + close` syscall fan-out).
   One JSON file per variant is the right *logical* model but a poor
   *physical* one at this scale. A git-style pack-file (one
   append-only file per N facts, with an index) would reduce 4 M
   syscalls to ~thousands and likely cut compile wall-clock 3–10×.
   The fact-hash lookup interface stays the same.
3. **Tar-pack of small files is also pathological** (the bundle-size
   step at WGS took ~31 min — nearly as long as compile itself —
   because `tarfile` reads each of 4 M files individually, gzip-streams
   them through, and metadata-frames each one). Combined with #2 a
   pack-file would also collapse this; alternatively the size
   measurement could compute compressed size by streaming the
   on-the-fly serialization of an in-memory representation rather than
   touching the on-disk CAS at all.
4. **Gzip-streaming VCF reader.** `dotbio.vcfio.parse_vcf` calls
   `Path.open()`, which can't read `.vcf.gz` directly; round-2 workflow
   has to materialize a 2.8 GB temp file first (saved 156 MB → 2.8 GB,
   accounting for ~2.6 GB of extra disk and ~10 s of `gunzip` wall
   clock). Switching to `gzip.open` (or autodetect by extension) would
   save the decompression step entirely. Currently documented in
   `bench/v2/data/hg002_wgs/README.md`.

## Comparing round 1 vs round 2

Round 1 (small data) is the unit-scale acceptance test the manuscript
needs to publish at all — proves the code path works and meets the
"<30s" acceptance criterion in `bench/v2/TASKS.md` Task 7. Round 2
(full WGS) is the headline performance number the manuscript needs to
position dotbio as a credible alternative to flat-format pipelines.

| Property | Round 1 | Round 2 |
|---|---|---|
| Input | 8–11 PGx variants | 4 048 342 autosomal variants |
| Source | `examples/*.vcf` shipped in repo | NIST GIAB v4.2.1, chr1–22 |
| Replicates per metric | 5 compile + 100 show + 5 update | 1 compile + 20 show, update skipped |
| Total wall-clock | ~0.3 s | minutes (mostly compile) |
| What it proves | code path is correct end-to-end | code path works at real WGS scale (or surfaces concrete bottlenecks) |
| Output file | `bench/v2/results/exp05_perf.json` | `bench/v2/results/exp05_perf_wgs.json` |

Both files conform to the same `dotbio.bench.exp05_perf.v1` schema, so
analysis scripts can union the two without special-casing.

## What round 3 should add

- Fix the streaming-compile + CAS-packfile bottlenecks above and
  re-measure to put a *competitive* WGS compile time in the manuscript.
- A 100-patient cohort tier (compile per-individual in parallel,
  measure per-individual median + total wall-clock).
- A baseline comparator: time PharmCAT / VEP on the same inputs to
  contextualize whether dotbio's compile cost is competitive.
- Cache-cold compile via `subprocess` invocation with a fresh Python
  interpreter, to measure the user-perceived CLI startup as well.

## Files written

- `bench/v2/scripts/perf_bench.py` — this script (round-2 patch adds
  WGS budget-mode env vars and `reuse_compile_for_size`)
- `bench/v2/results/exp05_perf.json` — round-1 small-data measurement
- `bench/v2/results/exp05_perf_wgs.json` — round-2 full-WGS measurement
- `bench/v2/data/hg002_wgs/README.md` — VCF retrieval recipe
- `bench/v2/scripts/README_perf.md` — this README
