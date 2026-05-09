# dotbio NM-grade benchmark — analysis specification

**Version**: v2.0-spec, 2026-05-09
**Target venue**: Nature Methods (main track)
**Status**: spec frozen for round-1 execution

This document is the authoritative analysis plan for elevating dotbio from
"weekend hack" to a publishable methods paper. It defines what is measured,
on what data, with what comparators, and what counts as success.

---

## 1. Hypotheses

The paper claims three measurable advantages of the dotbio architecture
(`facts/` + `commits/` + `views/` + `refs/`) over flat genomic-data formats:

- **H1 (correctness)** — At equal token budget, an LLM consuming a `.bio`
  bundle reaches a clinical answer with **strictly more provenance citations**
  (ruleset version, guideline version, fact hash) than flat alternatives,
  with **no loss in correctness**.

- **H2 (update efficiency)** — When a ruleset update reclassifies one
  variant, the bytes/tokens needed to detect what changed are
  **asymptotically O(diff)** for `.bio` and **O(file size)** for flat
  alternatives. We expect ≥10× reduction at full-PGx-panel scale.

- **H3 (longitudinal value)** — Over 24 months of real ClinVar history,
  a `.bio`-based pipeline reaches a **lower false-negative rate** for
  clinically actionable reclassifications than the standard-of-care
  "periodic re-annotation" workflow, at lower cumulative compute cost.

H1 and H2 are addressable on existing data; H3 requires a longitudinal
cohort simulation.

---

## 2. Data

### 2.1 Patient cohort

| Source | Individuals | Build | Notes |
|---|---|---|---|
| GIAB / 1000G 30x | HG001 (NA12878) | GRCh38 | Already extracted in `bench/data/format_a_vcf.txt` (8 loci); to be expanded |
| GIAB AJ trio | HG002, HG003, HG004 | GRCh38 | NIST FTP; PrecisionFDA truth set |
| GIAB Han Chinese trio | HG005, HG006, HG007 | GRCh38 | NIST FTP |
| 1000G 30x random sample | 100 individuals | GRCh38 | Stratified by superpopulation (5 pops × 20) |

For the longitudinal study, the 100-individual subsample is the operational
cohort; the 7 GIAB individuals are the per-format correctness cohort.

### 2.2 Locus panel

Three panels of increasing scope:

- **Panel A (PGx VIP)** — PharmGKB Tier 1 Very Important Pharmacogenes,
  ~36 genes, ~250 actionable rsIDs. Used for the clopidogrel-style
  questions.
- **Panel B (ACMG SF v3.2)** — 73 genes for secondary findings;
  ~5,000 reportable variants when combined with ClinVar P/LP/VUS.
- **Panel C (Carrier panel)** — GA4GH-recommended ~200-gene reproductive
  carrier screening panel.

Total addressable variant universe per individual: ~5,500 reportable
positions on the union panel.

### 2.3 Comparator formats (must support all)

For each (individual, panel) pair, an equivalent representation in:

1. **VCF (raw)** — 1000G-style genotypes, no annotation
2. **VCF + VEP-annotated** — VEP/snpEff INFO field annotation
3. **PharmCAT JSON** — running PharmCAT on the VCF and saving the JSON report
4. **GA4GH Phenopackets v2** — `Phenopacket` JSON with `interpretation` block
5. **HL7 FHIR Genomics IG bundle** — FHIR R4 bundle with `Observation/genetics`
6. **ClinVar VCV API JSON dump** — ad-hoc combiner that fetches per-rsID
7. **`.genome` reconstruction** — best-faith reconstruction (proprietary; documented assumptions)
8. **`.bio` bundle** — dotbio v0 output

Items 1, 7, 8 already exist for NA12878 8-locus. The rest are net-new in v2.

### 2.4 Ruleset / reference data sources

- **PharmCAT allele tables**, version 2025.x current at submission time
  (and historical: every release between 2024-01 and 2025-12)
- **CPIC guidelines** — at-least-one canonical version per drug
- **ClinVar** — monthly XML release archive 2024-01 → 2025-12 (24 snapshots)
- **OncoKB** — for somatic comparison, latest snapshot
- **CIViC** — somatic alternative

All must be pinned with version + URL + retrieval timestamp.

---

## 3. Experimental design

### 3.1 Experiment 1 — Initial-query token cost (H1)

For each (format, individual) pair, with both Claude (Xenova port) and
GPT-2 BPE tokenizers, measure:

- Total input token count for "manifest + view-relevant slice"
- Per-claim token cost amortized

Unit of comparison: tokens per actionable claim returned.

### 3.2 Experiment 2 — Update cost (H2)

For 50 randomly sampled real ClinVar reclassifications (drawn from the
2024–2025 archive), measure for each format:

- Bytes that change on disk after the update is applied
- Tokens an LLM must read to detect "what changed"
- Wall-clock time to apply the update

### 3.3 Experiment 3 — End-to-end LLM correctness (H1)

**Question bank**: 50 clinically curated questions covering five domains
(PGx, oncology, carrier, hereditary risk, dose adjustment). Each question
has a gold-standard answer adjudicated by a panel of clinical
geneticists using CPIC / ClinGen / NCCN / ACMG references.

**Models**: Claude 3.5 Sonnet, GPT-4o, Llama 3 70B, Gemini 1.5 Pro
(four families).

**Replicates**: N = 30 per (format, model, question), with temperature
≥ 0.5 to introduce variability.

**Scoring rubric** (each response scored 0/1 on each):
- `verdict_correct` — matches gold standard
- `phenotype_correct` — correct PGx phenotype where applicable
- `guideline_cited_with_version` — exact guideline name + version
- `variant_evidence_cited` — rsID/HGVS or fact hash
- `no_inference_required_outside_text` — model self-reports no external knowledge use
- `harm_risk_if_acted_on` — independent rater scores 0 (no harm) / 1 (mild) / 2 (severe)

**Inter-rater agreement**: Cohen's κ ≥ 0.7 across two blinded raters.

### 3.4 Experiment 4 — Longitudinal cohort study (H3)

**Setup**: 100 virtual patients, each scored against panels A+B+C, on
the 24 monthly ClinVar releases between 2024-01 and 2025-12.

**Two arms**:
- *SoC (status quo)*: re-annotate quarterly (months 0, 3, 6, …, 24)
- *.bio*: monthly `bio update` with `bio diff` capturing all changes

**Primary endpoints**:
- **FNR (false negative rate)** for clinically actionable reclassifications
  (P/LP ↔ VUS, LP ↔ P, drug-response significance changes)
- **Detection latency** (time from ClinVar release to capture)
- **Cumulative compute cost** (tokens across the 24 months)

### 3.5 Experiment 5 — Performance / scalability

On full HG002 WGS (~4.7M variants) and a 100-patient cohort:
- Compile time (cold + warm)
- Bundle size on disk (compressed + uncompressed)
- Single-view query latency
- Update latency
- Memory peak

Reported across 5 runs, median + IQR.

### 3.6 Experiment 6 — Re-identification / privacy risk

Erlich-Narayanan framework:
- For each format, the minimum number of markers an attacker needs to
  re-identify an individual from a public reference panel
- Compare VCF (lowest), `.genome` (medium), `.bio` (predicted lowest
  because facts are content-hashed, not raw genotypes; this is testable)

### 3.7 Experiment 7 — Adversarial robustness

Fuzz testing on each format with:
- Malformed VCF (missing REF, invalid GT, mixed builds)
- Conflicting rulesets (two ClinVar versions disagree on the same variant)
- Schema migration (v0 bundle ingested by hypothetical v1 reader)
- Hash collision attempts (constructed fact pairs colliding under SHA-256
  truncated to 16 chars — should never happen at full 256-bit, demonstrate)

### 3.8 Experiment 8 — Multi-omics extensibility (pilot)

Extend `.bio` to one non-DNA modality (chosen: Illumina 450K methylation):
- Define `facts/` schema for β-values + DMR observations
- Define a reference ruleset (e.g., epigenetic age estimator: Horvath clock)
- Run the Experiment-3-equivalent question set ("what's this patient's
  predicted epigenetic age?") on a public methylation cohort
- Measure: do the three principles (multi-scale, evidence chain, time)
  hold for non-DNA data?

### 3.9 Experiment 9 — User study (out-of-band)

20+ clinicians, randomized between formats, 10 clinical decision tasks
each. Endpoints: time, accuracy, trust calibration. **Out of scope for
automated subagent execution; recorded here for completeness.**

---

## 4. Statistical analysis

- **For continuous outcomes** (token count, latency, time-to-detect):
  median + IQR, Wilcoxon signed-rank for paired comparisons across formats
- **For binary outcomes** (verdict_correct, guideline_cited): proportion
  + 95% CI (Wilson), McNemar for paired comparisons
- **Multi-format ANOVA-style**: Friedman test for ranking across all
  comparators on each metric
- **Correction**: Bonferroni for the 6 primary endpoints in Experiment 3

Power analysis: at N=30 per condition × 4 LLMs × 50 questions =
6,000 observations per format. Detects a 5-percentage-point absolute
difference in correctness with α=0.05, power=0.95.

---

## 5. Reproducibility

Every artifact in this benchmark is reproducible via:

1. Public input data (1000G, GIAB, ClinVar archive — all open)
2. Pinned ruleset versions in the dotbio repo
3. Python environment locked via `pyproject.toml`
4. Snakemake/Nextflow pipeline orchestrating the full benchmark
   (Task 14 below)
5. Multi-LLM eval harness with explicit API key environment variables
6. CI-runnable subset (small data, reduced replicates) on every commit

Anything that requires API keys is gated behind an env var; the benchmark
falls back to mock mode when keys are not present, so the pipeline at
least executes end-to-end on every machine.

---

## 6. Reporting

- **Pre-registration** on OSF before LLM eval execution (lock the rubric)
- **Code and data** at github.com/zwbao/dotbio
- **Results**: each experiment outputs a JSON file under
  `bench/v2/results/exp_NN_<name>.json`
- **Manuscript figures**: generated by `bench/v2/scripts/make_figures.py`
- **Manuscript supplementary**: every raw model response in
  `bench/v2/results/raw_responses/`

---

## 7. Out-of-scope for v2

- IRB-required user study (Experiment 9)
- Theoretical analysis (information bounds, formal provenance theorem)
- Production deployment in a clinical lab
- Schema v1 design (only forward-compat tested)
- Cross-cohort merging / federation

These are flagged as future work in the manuscript.
