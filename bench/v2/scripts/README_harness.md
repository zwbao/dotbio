# Multi-LLM eval harness — `bench/v2/scripts/llm_harness.py`

Implements **Task 5** of the v2 benchmark plan (see `bench/v2/TASKS.md`).
Drives Experiment 3 (end-to-end LLM correctness, SPEC §3.3).

## Files

| Path | Role |
|---|---|
| `llm_harness.py` | Single CLI entry; orchestrates (format × model × question × replicate) loops, writes JSON output |
| `llm_clients/anthropic.py` | Claude live-mode adapter (lazy SDK import, `ANTHROPIC_API_KEY`) |
| `llm_clients/openai.py` | GPT-4o live-mode adapter (`OPENAI_API_KEY`) |
| `llm_clients/gemini.py` | Gemini live-mode adapter (`GEMINI_API_KEY`) |
| `llm_clients/openrouter.py` | **Round-2** unified OpenRouter client (`OPENROUTER_API_KEY`); routes any provider through `https://openrouter.ai/api/v1/chat/completions`, exposes `usage.cost`, retries on 429/5xx |
| `llm_clients/mock.py` | Deterministic fixture-driven client; always available |
| `llm_clients/__init__.py` | `get_client(family, force_mock=...)` factory |
| `llm_scoring.py` | Pure-function rubric scorers + JSON extractor |
| `../tests/test_llm_scoring.py` | Pytest suite for scoring (≥ 5 tests, deterministic) |
| `../tests/test_openrouter_client.py` | Pytest suite for the OpenRouter client (mocked HTTP) |
| `../results/exp03_llm_eval_smoke.json` | Smoke-run output (mock client) |
| `../results/exp03_llm_eval_real.json` | **Round-2** real multi-LLM eval (OpenRouter) |
| `../results/exp03_llm_eval_real_summary.md` | Human-readable summary of the real run |

## Quickstart

```bash
# Smoke run (no API keys required):
python -m bench.v2.scripts.llm_harness \
    --question q01 \
    --formats A1,A2,B,C \
    --models claude,openai,gemini \
    --n-replicates 3 \
    --force-mock \
    --out bench/v2/results/exp03_llm_eval_smoke.json
```

The CLI also accepts `python bench/v2/scripts/llm_harness.py …` for ad
hoc invocation; the two paths are equivalent.

### Round-2 real eval via OpenRouter

OpenRouter's unified API lets a single key hit Anthropic, OpenAI,
Google, and Meta endpoints. Set `OPENROUTER_API_KEY` and pass
`--client openrouter --model "<comma-separated slugs>"`. The
`--models` family flag is ignored in this mode — the slug *is* the
selector and the per-record `model_family` field is derived from the
slug head (`anthropic/...` → `claude`, etc.).

```bash
export OPENROUTER_API_KEY=sk-or-v1-...

python -m bench.v2.scripts.llm_harness \
    --client openrouter \
    --model "anthropic/claude-sonnet-4.6,openai/gpt-5.4-mini,google/gemini-3.1-flash-lite,meta-llama/llama-4-maverick" \
    --question "q01,q05,q11,q15,q21,q22,q31,q34,q41,q43" \
    --formats "A1,B,C,D,E,F" \
    --n-replicates 3 \
    --temperature 0.7 \
    --base-seed 20260509 \
    --load-questions-from-yaml \
    --cost-cap-usd 4.80 \
    --out bench/v2/results/exp03_llm_eval_real.json
```

The above is the exact command used to produce
`bench/v2/results/exp03_llm_eval_real.json` for round-2 task R5
(10 questions × 4 models × 6 formats × N=3 = 720 calls, hard cap
$4.80, wall-clock cap 60 min).

The OpenRouter client adds `"usage": {"include": true}` to each
request body so the response carries a per-call dollar cost; the
harness sums these and stops when `--cost-cap-usd` is reached. On
early termination the output JSON sets `"partial": true` and
`"stop_reason"` is populated.

### Environment variables

| Var | Used by | Live model |
|---|---|---|
| `ANTHROPIC_API_KEY` | `llm_clients/anthropic.py` | `claude-3-5-sonnet-20241022` |
| `OPENAI_API_KEY` | `llm_clients/openai.py` | `gpt-4o-2024-08-06` |
| `GEMINI_API_KEY` | `llm_clients/gemini.py` | `gemini-1.5-pro` |
| `OPENROUTER_API_KEY` | `llm_clients/openrouter.py` | any slug from `/models`, default `anthropic/claude-3.5-sonnet` |
| *(none — Together)* | Llama 3 currently routed to mock | `llama-3-70b` (also reachable via OpenRouter as `meta-llama/llama-4-maverick`) |

When the env var is unset *or* the live SDK is not installed, the
factory automatically substitutes the mock client; no command-line flag
is required to make the smoke run work on CI.

## Output schema

The output JSON mirrors `bench/results/llm_eval.json` (round-1) with
extra per-record fields. Top level:

```jsonc
{
  "experiment": "exp03_llm_eval",
  "schema_version": "v2.0",
  "methodology": "...",
  "date": "YYYY-MM-DD",
  "replicates_per_cell": <int>,
  "temperature": <float>,
  "base_seed": <int>,
  "formats": ["A1", "A2", "B", "C", ...],
  "model_families": ["claude", "openai", "gemini"],
  "question_ids": ["q01", ...],
  "questions": { "q01": { /* full gold answer */ } },
  "n_records": <int>,
  "any_live_client": <bool>,
  "conditions": [ /* one per (format, model, question, replicate) */ ]
}
```

When run via `--client openrouter` the top level adds:
```jsonc
{
  "client": "openrouter",
  "model_slugs": ["anthropic/claude-sonnet-4.6", ...],
  "n_calls": <int>,
  "n_calls_ok": <int>,
  "n_calls_err": <int>,
  "tokens_in_total": <int>,
  "tokens_out_total": <int>,
  "cost_total_usd": <float>,
  "cost_cap_usd": <float|null>,
  "partial": <bool>,
  "stop_reason": <string|null>
}
```
and each record gains `call_cost_usd` (per-call dollar cost from
OpenRouter) plus `is_error` (true when the call failed after retries).

Each `conditions[i]` record:

```jsonc
{
  "id": "<format>-<question>-<family>-<replicate>",
  "format": "C",
  "question_id": "q01",
  "model": "claude-3-5-sonnet-20241022" | "mock-fixture-v1",
  "model_family": "claude",
  "client": "anthropic" | "mock",
  "is_mock": <bool>,
  "replicate_idx": <int>,
  "temperature": <float>,
  "seed": <int>,
  "prompt_chars": <int>,
  "response_text": "<raw model output>",
  "response": { /* parsed JSON or {} on parse failure */ },
  "scoring": {
    "parse_ok": <bool>,
    "verdict_correct": <bool>,
    "phenotype_correct": <bool>,
    "guideline_cited_with_version": <bool>,
    "variant_evidence_cited": <bool>,
    "no_inference_required_outside_text": <bool>,
    "score_total": <0..5>
  },
  "raw": { /* client-specific debug payload */ }
}
```

This shape is a strict superset of the round-1 output, so figures and
analyses that consumed `bench/results/llm_eval.json` keep working.

## Scoring rubric (SPEC §3.3)

Five binary criteria, all deterministic pure functions of
`(parsed_response, gold_answer)`:

1. **`verdict_correct`** — verdict matches the gold answer (substring
   match against any acceptable string).
2. **`phenotype_correct`** — phenotype matches gold, with synonym table
   for IM/PM/RM/UM/NM and ACMG categories (Pathogenic, LP, VUS, ...).
3. **`guideline_cited_with_version`** — model cites the guideline name
   *and* a version token (year, `vN.N`, or `YYYY.x`).
4. **`variant_evidence_cited`** — response references an rsID, HGVS
   (`c./p./g./n./m./r.`), or SHA-256 fact hash.
5. **`no_inference_required_outside_text`** — model self-reports it did
   not pull in external knowledge.

The sixth rubric item from SPEC §3.3, `harm_risk_if_acted_on`, is a
human-rater 0/1/2 score and is *not* scored automatically; the harness
leaves a slot for it via post-processing.

## Prompt template

The harness reads the round-1 strict no-tools prompt from
`bench/prompts/llm_eval_template.md` and substitutes
`{question}` / `{format_content}`. Semantics are unchanged from
round 1; only the question and document slots vary.

## Mock client determinism

The mock client returns predetermined JSON keyed by
`(format_id, question_id, model_family)`. Replicates may flip between
two pre-canned variants based on `replicate_idx % 2` so the harness's
replicate-aggregation code has non-degenerate input. Re-running the
smoke command produces a byte-identical JSON file given the same
arguments.

This determinism is enforced by
`tests/test_llm_scoring.py::test_smoke_run_with_mock_client_is_deterministic`.

## Tests

```bash
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 pytest bench/v2/ -v
```

The suite includes 13 test functions (parametrize expands to 27 cases)
covering JSON extraction, all five scoring criteria, the aggregator,
end-to-end determinism of the mock-mode smoke run, and the OpenRouter
client (availability gate, happy-path usage parsing, 429-retry, hard
404, and exhausted-retry behaviour).

## Round-2 status

- **Done (R5):** OpenRouter client + real multi-LLM eval at the 10-question /
  6-format / 4-model / N=3 scale. Results in
  `bench/v2/results/exp03_llm_eval_real.json` and a human-readable summary
  in `bench/v2/results/exp03_llm_eval_real_summary.md`.
- **Done:** YAML question loading from `bench/v2/data/questions/qNN.yaml`
  via `--load-questions-from-yaml`.
- Together AI / direct Llama path remains routed to mock; in practice
  `meta-llama/llama-4-maverick` over OpenRouter covers the same family.
- Inter-rater agreement (Cohen's κ ≥ 0.7) requires two human raters
  scoring `harm_risk_if_acted_on`; out of scope for the automated
  harness.
- McNemar / Friedman tests on the per-format binary outcomes per
  SPEC §4 are computed in `make_figures.py` (pending round-3).
