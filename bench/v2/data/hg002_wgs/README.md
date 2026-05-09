# `bench/v2/data/hg002_wgs/` — full HG002 WGS pointer (round 2)

This directory is **intentionally empty of payload**. The HG002 WGS
benchmark VCF used for round-2 Experiment 5 (`bench/v2/SPEC.md` §3.5) is
too large to commit (compressed 156 MB > 100 MB repo guideline;
uncompressed 2.8 GB), so this README captures the retrieval recipe in
its place.

## Source

NIST Genome in a Bottle (GIAB) high-confidence small-variant benchmark
v4.2.1 for HG002 (NA24385, Ashkenazim son), aligned to GRCh38, autosomes
only (chr1–22).

- Direct URL:
  `https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz`
- License: public domain (NIST GIAB releases are open data)
- Last-Modified header (server response): 2020-12-07
- HTTP `Content-Length`: 156 252 944 bytes

## Local layout used by the round-2 benchmark

```
/tmp/dotbio_wgs/
├── HG002_GRCh38_1_22_v4.2.1.vcf.gz   # 156 MB compressed
└── HG002_GRCh38_1_22_v4.2.1.vcf      # 2.8 GB decompressed
```

Decompression is required because `dotbio.vcfio.parse_vcf` opens the
file with `path.open()` (no gzip support in v0). A gzip-streaming
adapter is a candidate round-3 optimization.

## Retrieval recipe

```bash
mkdir -p /tmp/dotbio_wgs
cd /tmp/dotbio_wgs
curl -L -o HG002_GRCh38_1_22_v4.2.1.vcf.gz \
  "https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/AshkenazimTrio/HG002_NA24385_son/NISTv4.2.1/GRCh38/HG002_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
gunzip -k HG002_GRCh38_1_22_v4.2.1.vcf.gz
grep -vc "^#" HG002_GRCh38_1_22_v4.2.1.vcf   # → 4 048 342
```

## Variant count

`4 048 342` records on autosomes (chr1–22). chrX/chrY/chrM are not
included — the corresponding NIST file is `…_X_v4.2.1_benchmark.vcf.gz`
and was not retrieved for round 2 (the autosome set is already at
real-WGS scale for the manuscript headline).

## Round-2 measured numbers (cross-reference)

From `bench/v2/results/exp05_perf_wgs.json` on macOS-26.3-arm64,
Python 3.11.4:

| Metric | Value |
|---|---:|
| Variants | 4 048 342 |
| Compile cold (1 run) | 1658.4 s (~27.6 min) |
| Bundle uncompressed | 588.8 MB |
| Bundle compressed (`.bio.tar.gz`) | 370.9 MB |
| Compression ratio | 1.59× |
| Peak compile RSS | 2.88 GB |
| `bio show --view pgx` median (n=20) | 0.41 ms |
| `bio show --view pgx` p95 | 0.55 ms |
| `bio update` | skipped (WGS budget mode) |
| Total benchmark wall-clock | 3523.3 s (~58.7 min) |

## How to rerun the round-2 benchmark against this VCF

```bash
cd /Users/baozhiwei/projects/dotbio
PYTHONPATH=src \
  HG002_WGS_VCF=/tmp/dotbio_wgs/HG002_GRCh38_1_22_v4.2.1.vcf \
  HG002_WGS_ONLY=1 \
  HG002_WGS_N_COMPILE=1 \
  HG002_WGS_N_SHOW=20 \
  HG002_WGS_N_UPDATE=0 \
  python bench/v2/scripts/perf_bench.py \
    --out bench/v2/results/exp05_perf_wgs.json \
    --workdir /tmp/dotbio_wgs_workdir
```

The four `HG002_WGS_*` env vars are the budget-mode knobs added in
round 2; without them, the script would default to 5 cold+warm compile
runs which is intractable at WGS scale (see `README_perf.md`).

## Why not committed

| File | Size | In-repo? |
|---|---:|:---:|
| `HG002_GRCh38_1_22_v4.2.1.vcf.gz` | 156 MB | no — exceeds 100 MB guideline |
| `HG002_GRCh38_1_22_v4.2.1.vcf`    | 2.8 GB | no — too large for any repo |
| this README | <2 KB | yes — points at the source |

If the repo migrates to git-lfs or bench/v2 grows a `data/` quota
override, the compressed VCF can be tracked there. Until then this
README is the authoritative pointer.
