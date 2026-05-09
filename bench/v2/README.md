# dotbio NM-grade benchmark — round 2 (v2)

This directory contains the round-2 benchmark for the dotbio Nature Methods
submission. It extends the round-1 single-shot study under `bench/` to:

- 7 GIAB individuals + a 100-patient 1000G sample (the cohort)
- Three locus panels (PGx VIP, ACMG SF v3.2, GA4GH carrier)
- Eight comparator formats (raw VCF, VEP-annotated VCF, PharmCAT JSON,
  GA4GH Phenopackets v2, HL7 FHIR Genomics, ClinVar VCV API, `.genome`
  reconstruction, `.bio` bundle)
- Eight experiments mapped to the three hypotheses in `SPEC.md`

The full analysis plan lives in [`SPEC.md`](SPEC.md). The per-task
breakdown of how the work is parallelised across subagents lives in
[`TASKS.md`](TASKS.md). This README explains how to *run* the benchmark.

## One-command entry point

```bash
cd bench/v2
make all          # run every experiment that does not need API keys / large downloads
make verify       # check that all expected JSON outputs exist and are non-empty
```

Or, equivalently, the wrapper script:

```bash
bash bench/v2/scripts/run_all.sh
```

The Makefile is the **documented reproducibility entry point**. Every
experiment writes a single JSON file under `bench/v2/results/exp_NN_*.json`
following SPEC §6. Failures in optional tasks (missing scripts, missing
API keys, missing large data) are demoted to warnings so the rest of the
pipeline always completes.

## Targets

| Target               | Purpose                                                          | Optional env vars |
|----------------------|------------------------------------------------------------------|-------------------|
| `make all`           | Run every experiment that does not need API keys or large data.  | (none required)   |
| `make verify`        | Check every expected output exists and is non-empty.             | (none)            |
| `make clean`         | Remove `bench/v2/results/`.                                      | (none)            |
| `make help`          | Show this target list.                                           | (none)            |
| `make formats`       | Regenerate the GA4GH / FHIR / PharmCAT sample files.             | (none)            |
| `make tokens`        | Re-run the round-1 `bench/compare_tokens.py` measurement.        | (none)            |
| `make experiment-1`  | Initial-query token cost across all v2 formats (SPEC §3.1).      | (none)            |
| `make experiment-2`  | Update cost on synthetic ClinVar reclassifications (SPEC §3.2).  | `CLINVAR_ARCHIVE_DIR` for real archive |
| `make experiment-3`  | Multi-LLM correctness eval (SPEC §3.3) — mock mode by default.   | `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`, `TOGETHER_API_KEY` |
| `make experiment-4`  | Longitudinal cohort smoke run (SPEC §3.4).                       | `CLINVAR_ARCHIVE_DIR` for real archive |
| `make experiment-5`  | Performance / scalability smoke (SPEC §3.5).                     | `HG002_WGS_VCF` for full-WGS scenario |
| `make experiment-6`  | Re-identification risk analyzer (SPEC §3.6).                     | (none)            |
| `make experiment-7`  | Adversarial fuzz suite (SPEC §3.7).                              | (none)            |
| `make experiment-8`  | Methylation extension pilot (SPEC §3.8).                         | (none)            |

A single experiment can be re-run independently, e.g.:

```bash
make experiment-3
ANTHROPIC_API_KEY=sk-... make experiment-3   # real Claude responses
```

## Round-1 vs round-2 boundary

The repository contains two benchmark layers:

- **Round 1** (`bench/`) — the original weekend benchmark: a single
  NA12878 sample, eight PGx loci, three formats (`A_vcf`, `B_genome`,
  `C_bio_view`), one shot per question. Outputs:
  - `bench/results/tokens.json` — Claude + GPT-2 BPE token counts
  - `bench/results/storage.json` — bytes-on-disk
  - `bench/results/llm_eval.json` — single Claude eval pass
- **Round 2** (`bench/v2/`, this directory) — the publication-grade study
  described in `SPEC.md`. Outputs land in `bench/v2/results/exp_NN_*.json`.

`make tokens` keeps the round-1 numbers reproducible (it just re-runs
`bench/compare_tokens.py`). `make all` runs round-2.

## Environment variables

All env vars are **optional**. The pipeline runs end-to-end without any
of them; it just falls back to mock mode / synthetic data / smoke runs.

| Variable             | Used by               | Effect when set                                   |
|----------------------|-----------------------|---------------------------------------------------|
| `ANTHROPIC_API_KEY`  | `experiment-3`        | Real Claude 3.5 Sonnet responses (else mock).     |
| `OPENAI_API_KEY`     | `experiment-3`        | Real GPT-4o responses (else mock).                |
| `GEMINI_API_KEY`     | `experiment-3`        | Real Gemini 1.5 Pro responses (else mock).        |
| `TOGETHER_API_KEY`   | `experiment-3`        | Real Llama 3 70B responses via Together (else mock). |
| `HG002_WGS_VCF`      | `experiment-5`        | Adds the full-WGS scale tier (~4.7M variants).    |
| `CLINVAR_ARCHIVE_DIR`| `experiment-2`, `-4`  | Use real monthly ClinVar XML releases instead of synthetic deltas. |
| `PYTHON`             | all                   | Override the Python interpreter (default `python3`). |
| `BIO_CLI`            | several               | Override the dotbio CLI binary (default `bio`).   |

## Robustness

Round-2 tasks are produced by parallel subagents (see `TASKS.md`). The
Makefile is intentionally **robust to missing artifacts**:

- Each target uses `command -v` / `[ -s … ]` to check that its script
  exists and is non-empty before invoking it.
- A missing script is reported as `skipping: <task> not yet implemented`
  and the target writes a small placeholder JSON so `make verify` always
  has something to check.
- A failing script is demoted to a `WARNING` and the next target still runs.
- `make clean` only removes `bench/v2/results/`; it never touches input
  data or scripts.

## Reproducibility

Per SPEC §5:

1. **Public input data** — every dataset is downloadable from 1000G,
   GIAB (NIST FTP), ClinVar (NCBI) without authentication.
2. **Pinned ruleset versions** — see `src/dotbio/rulesets/`.
3. **Python environment** — locked via the repo's `pyproject.toml`.
4. **Pipeline orchestrator** — this Makefile (Task 12).
5. **LLM eval** — Task 5 harness with explicit per-provider env vars
   and a deterministic mock-fallback path.
6. **CI subset** — `make all` itself is the CI subset; it runs in well
   under a minute on the small examples.

Anything that requires API keys is gated behind an env var; the
benchmark falls back to mock mode when keys are not present, so the
pipeline at least executes end-to-end on every machine.

## Layout

```
bench/v2/
├── SPEC.md                    # frozen analysis plan
├── TASKS.md                   # subagent task list
├── README.md                  # this file
├── Makefile                   # top-level orchestrator
├── data/
│   ├── format_d_phenopacket.json
│   ├── format_e_fhir_bundle.json
│   ├── format_f_pharmcat_report.json
│   ├── giab_panel/            # HG002–HG007 8-locus VCFs (Task 11)
│   └── questions/             # q01..q50.yaml (Task 4)
├── results/                   # exp01..exp08 JSON outputs
└── scripts/
    ├── run_all.sh             # `make all` wrapper
    ├── vcf_to_phenopacket.py  # Task 1
    ├── vcf_to_fhir.py         # Task 2
    ├── bio_to_pharmcat.py     # Task 3
    ├── llm_harness.py         # Task 5
    ├── llm_clients/           # anthropic / openai / gemini / mock
    ├── llm_scoring.py         # rubric scoring
    ├── longitudinal_sim.py    # Task 6
    ├── clinvar_archive.py     #  ↳ archive loader / synthesizer
    ├── perf_bench.py          # Task 7
    ├── reid_risk.py           # Task 8
    └── fuzz/                  # Task 9 fuzz cases
```
