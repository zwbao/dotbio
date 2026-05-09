# Experiment 3 — Real multi-LLM eval (OpenRouter) — summary

- **Generated**: 2026-05-09
- **Schema version**: v2.1
- **Methodology**: Round-2 multi-LLM eval per SPEC §3.3 via OpenRouter unified API. Each (format, model, question) cell run with N replicates at temperature>=0.5; responses scored on five binary rubric criteria. Cost tracked per call via OpenRouter usage.cost; hard cap enforced.
- **Client**: `openrouter`
- **Status**: PARTIAL — cost cap hit: $4.8097 >= $4.8000

## Configuration

- **Questions** (10): q01, q05, q11, q15, q21, q22, q31, q34, q41, q43
- **Formats** (6): A1, B, C, D, E, F
- **Model slugs** (4):
    - `anthropic/claude-sonnet-4.6`
    - `openai/gpt-5.4-mini`
    - `google/gemini-3.1-flash-lite`
    - `meta-llama/llama-4-maverick`
- **Resolved model families**: claude, gemini, llama, openai
- **Replicates per cell**: 3
- **Temperature**: 0.7
- **Base seed**: 20260509
- **Grid target**: 10 q × 6 fmt × 4 models × N=3 = 720 calls

## Run economics

- **API calls (attempted)**: 710
- **API calls (successful)**: 710
- **API calls (errored)**: 0
- **Acceptance rate**: 100.0%
- **Total prompt tokens**: 3,578,561
- **Total completion tokens**: 154,855
- **Total cost (USD)**: $4.8097
- **Cost cap (USD)**: $4.8000
- **Records produced**: 710

## Per-format mean rubric scores (over all models, replicates, questions)

| Format | n  | parse_ok | verdict | phenotype | guideline+ver | variant_ev | no_inference | mean_total |
|--------|----|----------|---------|-----------|---------------|------------|--------------|------------|
| A1     | 120 | 100.0% |   5.0% |  80.8% |   0.0% |  30.8% |  18.3% |  27.0% |
| B      | 120 |  98.3% |   6.8% |  80.5% |   0.0% |  10.2% |  15.3% |  22.5% |
| C      | 120 | 100.0% |   5.8% |  80.0% |  10.0% |   1.7% |  22.5% |  24.0% |
| D      | 120 |  98.3% |   0.0% |  80.5% |   0.0% |  28.8% |  17.8% |  25.4% |
| E      | 120 |  98.3% |   6.8% |  83.1% |   0.0% |  49.2% |  18.6% |  31.5% |
| F      | 110 |  99.1% |   7.3% |  80.7% |   8.3% |  40.4% |  23.9% |  32.1% |

## Per-model mean rubric scores (over all formats, replicates, questions)

| Model slug | n | parse_ok | verdict | phenotype | guideline+ver | variant_ev | mean_total |
|------------|---|----------|---------|-----------|---------------|------------|------------|
| `anthropic/claude-sonnet-4.6` | 179 | 100.0% |   5.0% |  82.1% |   3.4% |  38.5% |  26.1% |
| `openai/gpt-5.4-mini` | 177 |  96.0% |   5.9% |  81.8% |   2.9% |  37.1% |  26.2% |
| `google/gemini-3.1-flash-lite` | 177 | 100.0% |   1.7% |  80.2% |   2.3% |  12.4% |  20.7% |
| `meta-llama/llama-4-maverick` | 177 | 100.0% |   8.5% |  79.7% |   3.4% |  18.6% |  35.0% |

## Format × model — `verdict_correct` rate

| Format | `anthropic/claude-sonnet-4.6` | `openai/gpt-5.4-mini` | `google/gemini-3.1-flash-lite` | `meta-llama/llama-4-maverick` |
|--------|---|---|---|---|
| A1 |   3.3% |   6.7% |   0.0% |  10.0% |
| B |  10.0% |   7.1% |   0.0% |  10.0% |
| C |   0.0% |  10.0% |   3.3% |  10.0% |
| D |   0.0% |   0.0% |   0.0% |   0.0% |
| E |   6.7% |   3.6% |   6.7% |  10.0% |
| F |  10.3% |   7.7% |   0.0% |  11.1% |

## Format × model — `guideline_cited_with_version` rate (citation completeness)

| Format | `anthropic/claude-sonnet-4.6` | `openai/gpt-5.4-mini` | `google/gemini-3.1-flash-lite` | `meta-llama/llama-4-maverick` |
|--------|---|---|---|---|
| A1 |   0.0% |   0.0% |   0.0% |   0.0% |
| B |   0.0% |   0.0% |   0.0% |   0.0% |
| C |  10.0% |  10.0% |  10.0% |  10.0% |
| D |   0.0% |   0.0% |   0.0% |   0.0% |
| E |   0.0% |   0.0% |   0.0% |   0.0% |
| F |  10.3% |   7.7% |   3.7% |  11.1% |

## Inter-model agreement on `verdict_correct`

For each (format, question) cell, we take each model's modal outcome over its N replicates and compute the fraction of model pairs that agree.

| Format | mean pairwise agreement |
|--------|--------------------------|
| A1 |  93.3% |
| B |  95.0% |
| C |  93.3% |
| D | 100.0% |
| E |  90.0% |
| F |  94.4% |

## Citation completeness (across all calls, regardless of correctness)

- **guideline_cited_with_version**: 21 / 703 =   3.0%
- **variant_evidence_cited**:        187 / 703 =  26.6%

## Caveats and notes

- Replicates set to N=3 per (format, model, question) to keep cost bounded while still surfacing variance. SPEC §3.3 calls for N=30; round-3 will scale up once budget allows.
- 10 questions sampled across 5 SPEC domains (2 per domain): q01, q05 (pgx); q11, q15 (oncology_somatic); q21, q22 (carrier_screening); q31, q34 (hereditary_risk); q41, q43 (dose_adjustment).
- Cost is taken from OpenRouter's `usage.cost` field per response; the harness sums these and stops when `--cost-cap-usd` is reached.
- The `harm_risk_if_acted_on` rubric criterion (SPEC §3.3) requires human raters and is not auto-scored.
- Inter-model agreement is a coarse Cochran-style proxy here; full Cohen's κ across blinded raters is round-3 work.
- **Partial run** — terminated early (cost cap hit: $4.8097 >= $4.8000). The per-format / per-model breakdowns above are computed on the records actually obtained.

