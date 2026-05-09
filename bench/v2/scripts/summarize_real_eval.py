"""Generate a human-readable Markdown summary from
``exp03_llm_eval_real.json`` (round-2 OpenRouter run).

Usage:

    python -m bench.v2.scripts.summarize_real_eval \
        --in  bench/v2/results/exp03_llm_eval_real.json \
        --out bench/v2/results/exp03_llm_eval_real_summary.md
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List


def _mean(xs: Iterable[float]) -> float:
    xs = list(xs)
    return statistics.fmean(xs) if xs else 0.0


def _fmt_pct(p: float) -> str:
    return f"{100*p:5.1f}%"


def build_summary(payload: Dict[str, Any]) -> str:
    cs = payload["conditions"]
    cap = payload.get("cost_cap_usd")
    cost = payload.get("cost_total_usd", 0.0)
    n_calls = payload.get("n_calls", len(cs))
    n_ok = payload.get("n_calls_ok", sum(1 for c in cs if not c.get("is_error")))
    n_err = payload.get("n_calls_err", n_calls - n_ok)
    tokens_in = payload.get("tokens_in_total", 0)
    tokens_out = payload.get("tokens_out_total", 0)
    partial = payload.get("partial", False)
    stop_reason = payload.get("stop_reason")
    formats = payload.get("formats", [])
    qids = payload.get("question_ids", [])
    slugs = payload.get("model_slugs", [])
    families = payload.get("model_families", [])

    # Per-format aggregations.
    by_fmt: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in cs:
        by_fmt[c["format"]].append(c)
    by_model: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for c in cs:
        by_model[c["model"]].append(c)
    by_fmt_model: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for c in cs:
        by_fmt_model[(c["format"], c["model"])].append(c)

    def crit_mean(rows: List[Dict[str, Any]], crit: str) -> float:
        ok = [r for r in rows if r["scoring"]["parse_ok"] and not r.get("is_error")]
        if not ok:
            return 0.0
        return _mean(1.0 if r["scoring"][crit] else 0.0 for r in ok)

    out: List[str] = []
    e = out.append
    e("# Experiment 3 — Real multi-LLM eval (OpenRouter) — summary")
    e("")
    e(f"- **Generated**: {payload.get('date', '?')}")
    e(f"- **Schema version**: {payload.get('schema_version', '?')}")
    e(f"- **Methodology**: {payload.get('methodology', '?')}")
    e(f"- **Client**: `{payload.get('client', '?')}`")
    e(f"- **Status**: {'PARTIAL' if partial else 'COMPLETE'}"
      + (f" — {stop_reason}" if stop_reason else ""))
    e("")

    e("## Configuration")
    e("")
    e(f"- **Questions** ({len(qids)}): " + ", ".join(qids))
    e(f"- **Formats** ({len(formats)}): " + ", ".join(formats))
    e(f"- **Model slugs** ({len(slugs)}):")
    for s in slugs:
        e(f"    - `{s}`")
    e(f"- **Resolved model families**: " + ", ".join(families))
    e(f"- **Replicates per cell**: {payload.get('replicates_per_cell', '?')}")
    e(f"- **Temperature**: {payload.get('temperature', '?')}")
    e(f"- **Base seed**: {payload.get('base_seed', '?')}")
    e(f"- **Grid target**: {len(qids)} q × {len(formats)} fmt × {len(slugs)} models × N={payload.get('replicates_per_cell','?')} = "
      f"{len(qids)*len(formats)*len(slugs)*int(payload.get('replicates_per_cell',0))} calls")
    e("")

    e("## Run economics")
    e("")
    e(f"- **API calls (attempted)**: {n_calls}")
    e(f"- **API calls (successful)**: {n_ok}")
    e(f"- **API calls (errored)**: {n_err}")
    e(f"- **Acceptance rate**: {_fmt_pct(n_ok/max(n_calls,1))}")
    e(f"- **Total prompt tokens**: {tokens_in:,}")
    e(f"- **Total completion tokens**: {tokens_out:,}")
    e(f"- **Total cost (USD)**: ${cost:.4f}")
    e(f"- **Cost cap (USD)**: " + (f"${cap:.4f}" if cap is not None else "none"))
    e(f"- **Records produced**: {len(cs)}")
    e("")

    # Per-format mean correctness.
    crit_keys = [
        "verdict_correct",
        "phenotype_correct",
        "guideline_cited_with_version",
        "variant_evidence_cited",
        "no_inference_required_outside_text",
    ]
    e("## Per-format mean rubric scores (over all models, replicates, questions)")
    e("")
    e("| Format | n  | parse_ok | verdict | phenotype | guideline+ver | variant_ev | no_inference | mean_total |")
    e("|--------|----|----------|---------|-----------|---------------|------------|--------------|------------|")
    for fmt in formats:
        rows = by_fmt.get(fmt, [])
        n = len(rows)
        if n == 0:
            continue
        parse_ok = _mean(1.0 if r["scoring"]["parse_ok"] else 0.0 for r in rows)
        scores = [crit_mean(rows, k) for k in crit_keys]
        mean_total = _mean([(r["scoring"]["score_total"] / 5.0) for r in rows
                            if r["scoring"]["parse_ok"]])
        e(
            f"| {fmt:6s} | {n:>3d} | {_fmt_pct(parse_ok)} | {_fmt_pct(scores[0])} | "
            f"{_fmt_pct(scores[1])} | {_fmt_pct(scores[2])} | {_fmt_pct(scores[3])} | "
            f"{_fmt_pct(scores[4])} | {_fmt_pct(mean_total)} |"
        )
    e("")

    # Per-model mean.
    e("## Per-model mean rubric scores (over all formats, replicates, questions)")
    e("")
    e("| Model slug | n | parse_ok | verdict | phenotype | guideline+ver | variant_ev | mean_total |")
    e("|------------|---|----------|---------|-----------|---------------|------------|------------|")
    for slug in slugs:
        rows = by_model.get(slug, [])
        n = len(rows)
        if n == 0:
            continue
        parse_ok = _mean(1.0 if r["scoring"]["parse_ok"] else 0.0 for r in rows)
        scores = [crit_mean(rows, k) for k in crit_keys]
        mean_total = _mean(
            (r["scoring"]["score_total"] / 5.0) for r in rows if r["scoring"]["parse_ok"]
        )
        e(
            f"| `{slug}` | {n} | {_fmt_pct(parse_ok)} | {_fmt_pct(scores[0])} | "
            f"{_fmt_pct(scores[1])} | {_fmt_pct(scores[2])} | {_fmt_pct(scores[3])} | "
            f"{_fmt_pct(mean_total)} |"
        )
    e("")

    # Format × model heat-map (verdict_correct).
    e("## Format × model — `verdict_correct` rate")
    e("")
    e("| Format | " + " | ".join(f"`{s}`" for s in slugs) + " |")
    e("|--------|" + "|".join(["---"] * len(slugs)) + "|")
    for fmt in formats:
        cells = []
        for slug in slugs:
            rows = by_fmt_model.get((fmt, slug), [])
            ok = [r for r in rows if r["scoring"]["parse_ok"] and not r.get("is_error")]
            if not ok:
                cells.append("    -    ")
            else:
                m = _mean(1.0 if r["scoring"]["verdict_correct"] else 0.0 for r in ok)
                cells.append(_fmt_pct(m))
        e(f"| {fmt} | " + " | ".join(cells) + " |")
    e("")

    # Format × model — guideline_cited_with_version.
    e("## Format × model — `guideline_cited_with_version` rate (citation completeness)")
    e("")
    e("| Format | " + " | ".join(f"`{s}`" for s in slugs) + " |")
    e("|--------|" + "|".join(["---"] * len(slugs)) + "|")
    for fmt in formats:
        cells = []
        for slug in slugs:
            rows = by_fmt_model.get((fmt, slug), [])
            ok = [r for r in rows if r["scoring"]["parse_ok"] and not r.get("is_error")]
            if not ok:
                cells.append("    -    ")
            else:
                m = _mean(
                    1.0 if r["scoring"]["guideline_cited_with_version"] else 0.0
                    for r in ok
                )
                cells.append(_fmt_pct(m))
        e(f"| {fmt} | " + " | ".join(cells) + " |")
    e("")

    # Per-model agreement rate within each (format, question): for each
    # (format, question), compute fraction of model-pairs whose modal
    # verdict (across replicates) agrees. This is a coarse stand-in for
    # inter-model agreement — full Cohen's κ is human-rater work.
    e("## Inter-model agreement on `verdict_correct`")
    e("")
    e("For each (format, question) cell, we take each model's modal "
      "outcome over its N replicates and compute the fraction of model "
      "pairs that agree.")
    e("")
    by_fmt_q_model: Dict[tuple, List[Dict[str, Any]]] = defaultdict(list)
    for c in cs:
        by_fmt_q_model[(c["format"], c["question_id"], c["model"])].append(c)

    fmt_pair_rates: Dict[str, List[float]] = defaultdict(list)
    for fmt in formats:
        for qid in qids:
            modal: Dict[str, bool] = {}
            for slug in slugs:
                rows = by_fmt_q_model.get((fmt, qid, slug), [])
                ok = [r for r in rows if r["scoring"]["parse_ok"] and not r.get("is_error")]
                if not ok:
                    continue
                # majority vote on verdict_correct
                vc = sum(1 for r in ok if r["scoring"]["verdict_correct"])
                modal[slug] = (vc * 2 >= len(ok))
            if len(modal) < 2:
                continue
            vals = list(modal.values())
            n_pairs = 0
            n_agree = 0
            for i in range(len(vals)):
                for j in range(i + 1, len(vals)):
                    n_pairs += 1
                    if vals[i] == vals[j]:
                        n_agree += 1
            fmt_pair_rates[fmt].append(n_agree / n_pairs if n_pairs else 0.0)
    e("| Format | mean pairwise agreement |")
    e("|--------|--------------------------|")
    for fmt in formats:
        agreements = fmt_pair_rates.get(fmt) or []
        e(f"| {fmt} | {_fmt_pct(_mean(agreements))} |")
    e("")

    # Citation completeness summary.
    e("## Citation completeness (across all calls, regardless of correctness)")
    e("")
    cites_total = sum(
        1 for r in cs
        if r["scoring"]["parse_ok"]
        and not r.get("is_error")
        and r["scoring"]["guideline_cited_with_version"]
    )
    parsable = [r for r in cs if r["scoring"]["parse_ok"] and not r.get("is_error")]
    e(f"- **guideline_cited_with_version**: {cites_total} / {len(parsable)} "
      f"= {_fmt_pct(cites_total/max(len(parsable),1))}")
    var_ev = sum(
        1 for r in parsable if r["scoring"]["variant_evidence_cited"]
    )
    e(f"- **variant_evidence_cited**:        {var_ev} / {len(parsable)} "
      f"= {_fmt_pct(var_ev/max(len(parsable),1))}")
    e("")

    # Caveats.
    e("## Caveats and notes")
    e("")
    e("- Replicates set to N=3 per (format, model, question) to keep cost "
      "bounded while still surfacing variance. SPEC §3.3 calls for N=30; "
      "round-3 will scale up once budget allows.")
    e("- 10 questions sampled across 5 SPEC domains (2 per domain): "
      "q01, q05 (pgx); q11, q15 (oncology_somatic); q21, q22 "
      "(carrier_screening); q31, q34 (hereditary_risk); q41, q43 "
      "(dose_adjustment).")
    e("- Cost is taken from OpenRouter's `usage.cost` field per response; "
      "the harness sums these and stops when `--cost-cap-usd` is reached.")
    e("- The `harm_risk_if_acted_on` rubric criterion (SPEC §3.3) requires "
      "human raters and is not auto-scored.")
    e("- Inter-model agreement is a coarse Cochran-style proxy here; full "
      "Cohen's κ across blinded raters is round-3 work.")
    if partial:
        e(f"- **Partial run** — terminated early ({stop_reason}). The "
          "per-format / per-model breakdowns above are computed on the "
          "records actually obtained.")
    e("")

    return "\n".join(out) + "\n"


def parse_args(argv: List[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--in",
        dest="in_path",
        required=True,
        help="Path to exp03_llm_eval_real.json",
    )
    p.add_argument(
        "--out",
        dest="out_path",
        required=True,
        help="Path to write summary markdown",
    )
    return p.parse_args(argv)


def main(argv: List[str] | None = None) -> int:
    args = parse_args(argv)
    payload = json.loads(Path(args.in_path).read_text())
    md = build_summary(payload)
    Path(args.out_path).write_text(md)
    print(f"wrote {len(md)} chars -> {args.out_path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
