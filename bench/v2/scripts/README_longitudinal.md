# Longitudinal cohort simulator (Task 6 / SPEC §3.4)

This directory implements the 24-month longitudinal cohort study from
`bench/v2/SPEC.md` §3.4 (hypothesis **H3**, "longitudinal value"). Two
arms are simulated against a sequence of monthly ClinVar releases:

| Arm | Cadence | What it does |
|---|---|---|
| `arm_soc` | quarterly (months 3, 6, 9, …, 24) | "re-annotate every quarter" — runs `bio update` and `bio diff` only at quarter boundaries |
| `arm_bio` | monthly (months 1–24) | runs `bio update` every month and `bio diff month-1 month` to capture the per-release delta |

Both arms invoke the **existing** `bio` CLI as a subprocess
(`python -m dotbio update …` and `python -m dotbio diff …`). The
simulator does *not* re-implement update or diff logic.

Files:

- `clinvar_archive.py` — generates 24 monthly ClinVar snapshots (real or
  synthetic) and installs them under the active dotbio package's
  `dotbio/rulesets/` resource directory so `bio update --ruleset
  clinvar@<version>` finds them.
- `longitudinal_sim.py` — top-level driver: builds the cohort, runs both
  arms, computes FNR/latency/token endpoints, writes the result JSON.
- `../results/exp04_longitudinal_smoke.json` — output from a 5-patient
  smoke run.

## Running the smoke test

```
python bench/v2/scripts/longitudinal_sim.py --patients 5 --months 24
```

Wall-clock target: <60 s on a 2024 laptop. The default smoke run
typically finishes in ~18 s. Output goes to
`bench/v2/results/exp04_longitudinal_smoke.json`.

## Scaling to the SPEC's 100-patient design

```
python bench/v2/scripts/longitudinal_sim.py --patients 100 --months 24
```

No code changes are required. Wall-clock scales linearly in
`patients × months × 2 arms × 2 CLI calls`; budget ~6 minutes for the
full 100-patient run on the same hardware.

## Ground truth and the FNR definition

For each patient we restrict the global reclassification timeline to
events that change a *claim that applies to that patient* (i.e. the
patient's genotype matches the cell that was reclassified). Of those
patient-level events we keep the **actionable** subset per SPEC §3.4
("P/LP ↔ VUS, LP ↔ P, drug-response significance changes").

Per-arm capture is graded as follows:

- `arm_bio` runs `bio diff prev_month current_month` every month, so a
  one-step transition X→Y at month *m* is observable in month-*m*'s
  diff. We mark a truth event *captured* iff a diff entry exists in its
  release month for the same gene.
- `arm_soc` runs `bio diff last_quarter current_quarter` only every 3
  months; the diff shows the **net** change for the whole quarter.
  When a variant flips multiple times within a quarter (e.g.
  LP → P → LP) the cumulative diff collapses to "no change" and the
  quarter's events are *all* false negatives. When the quarter has
  exactly one transition it is captured (with non-zero detection
  latency). When the quarter has multiple distinct transitions
  affecting the same variant we credit only the latest one (because
  that's all the cumulative diff retains); the intermediate transitions
  are FN.

This grading is conservative for bio (a real-world bio user would
still need to *act* on the diff to convert "captured" into "delivered
to clinician"; we don't model that step in Round 1) and reasonable for
SoC (a real-world re-annotation comparing point-in-time reports has
exactly this cumulative-diff property).

## What's simulated vs. real

| Component | Round 1 | Round 2+ |
|---|---|---|
| Monthly ClinVar snapshots | **synthetic**, generated via `clinvar_archive.synthesize_archive` | real ClinVar full-release XMLs via `clinvar_archive.load_real_archive` (stub raises with the FTP location) |
| Patient cohort | 5 synthetic VCFs perturbed from `examples/real-na12878/input.vcf` | 100 1000G 30x individuals from Task 11 |
| `bio update`, `bio diff` | **real** dotbio CLI subprocesses | unchanged |
| Token accounting | ~4-chars-per-token estimate (matches the existing dotbio CLI convention) | swap in a tokenizer-precise count via `Xenova/claude-tokenizer` (matches H1/H2 experiments) |

The simulator's `--clinvar-archive <path>` flag swaps synthetic for
real with no other code changes.

## Synthetic transition probabilities

Per-month per-cell transition rates were calibrated from the published
ClinVar reclassification audit literature:

- **Landrum, M.J. *et al.* (2018)**, "ClinVar: improving access to
  variant interpretations and supporting evidence", *Nucleic Acids
  Research* 46(D1):D1062–D1067 — documents that LP variants are
  reclassified more often than benign / likely-benign variants and
  that VUS resolutions skew toward LB/B with a small LP/P tail.
- **Harrison, S.M. & Rehm, H.L. (2019)**, "Is 'likely pathogenic'
  really 90% likely? Reclassification data in ClinVar", *Genome
  Medicine* 11:72 — reports cumulative reclassification rates across
  6+ years of ClinVar data (≈8% of LP variants downgraded; LP→P
  upgrades enriched in well-curated genes).
- **Yang, S. *et al.* (2017)**, "Sources of discordance among germline
  variant classifications in ClinVar", *Genet Med* 19:1118–1126 — VUS
  resolutions are dominantly toward LB/B but include a small clinically
  important LP-direction tail.

The matrix is in `clinvar_archive.TRANSITION_MATRIX`; see comments
there for which row corresponds to which source. Because the bundled
demo ruleset has only ~10 reclassifiable cells (vs. ~2 M in the real
archive), per-cell rates are scaled up by `rate_scale=8.0` so that
Round-1 smoke runs see 1–3 reclassifications/month — comparable in
*relative volume* to the 10–20/month SPEC §3.4 targets for the full
archive. Use `rate_scale=1.0` plus `--clinvar-archive` to recover the
true regime.

These rates are **not for clinical use** and are clearly tagged with
`_synthetic: true` and a `_synthetic_seed` field in every emitted
ruleset JSON.

## Output schema (smoke run)

`exp04_longitudinal_smoke.json` contains:

- `archive` — synthesis metadata (mode, seed, totals, source citation).
- `cohort` — per-patient identifiers and BRCA1 inclusion flag.
- `summary.{arm_soc,arm_bio}` — `n_actionable_truth_total`,
  `n_captured_total`, `fnr`, `mean_latency_months_weighted`,
  `cumulative_tokens_total`, `n_patients`.
- `per_patient_endpoints` — same fields per (arm, patient) plus a
  `missed` list naming each FN event.
- `per_patient_truth_counts` — total and actionable per-patient counts.

The 5-patient × 24-month smoke run that ships with this directory
reports **arm_soc FNR ≈ 0.57** vs **arm_bio FNR ≈ 0.00** at this seed
(`--seed 42`), with bio paying ≈2.4× more cumulative tokens for the
monthly cadence. These numbers are *for the smoke seed* and will
shift on the full 100-patient run; they are written here only to
sanity-check the pipeline, not as headline numbers for the manuscript.
