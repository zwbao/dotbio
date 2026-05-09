"""Multi-LLM evaluation harness for the dotbio NM-grade benchmark.

Single CLI entry. Usage:

    python -m bench.v2.scripts.llm_harness \
        --question q01 --formats A1,A2,B,C \
        --models claude,openai,gemini --n-replicates 3 \
        --out bench/v2/results/exp03_llm_eval_smoke.json

Falls back to the deterministic mock client when API keys are unset, so
the smoke run completes on CI machines with no network access.

Output JSON shape mirrors `bench/results/llm_eval.json` (round-1 single-
shot) with extra fields per response: `model`, `replicate_idx`,
`temperature`, `seed`, plus the scoring sub-block from `llm_scoring`.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Allow running as `python bench/v2/scripts/llm_harness.py` *or* as
# `python -m bench.v2.scripts.llm_harness`. The latter is the documented
# entry point but the former is convenient during development.
_HERE = Path(__file__).resolve().parent
if __package__ in (None, ""):
    sys.path.insert(0, str(_HERE.parent.parent.parent))  # repo root
    sys.path.insert(0, str(_HERE))                       # bench/v2/scripts

try:  # package-style import
    from bench.v2.scripts import llm_scoring
    from bench.v2.scripts.llm_clients import get_client
except ImportError:  # script-style fallback
    import llm_scoring  # type: ignore
    from llm_clients import get_client  # type: ignore


REPO_ROOT = Path(__file__).resolve().parents[3]
PROMPT_TEMPLATE_PATH = REPO_ROOT / "bench" / "prompts" / "llm_eval_template.md"

# ---------------------------------------------------------------------------
# Built-in question fixtures used by the smoke run.
#
# In production these would be loaded from
# `bench/v2/data/questions/qNN.yaml` (Task 4). The smoke fixture below
# mirrors q01 from the SPEC so the harness is self-contained until that
# task lands.
# ---------------------------------------------------------------------------

DEFAULT_QUESTIONS: Dict[str, Dict[str, Any]] = {
    "q01": {
        "id": "q01",
        "domain": "pgx",
        "question": (
            "Patient has CYP2C19 *1/*2. Can they take clopidogrel at "
            "standard dose for ACS/PCI?"
        ),
        "gold_answer": {
            "verdict": ["no", "depends", "alternative", "consider alternative"],
            "phenotype": "Intermediate Metabolizer",
            "cited_guideline": "CPIC@2022",
            "rationale": "Reduced active metabolite; alternative P2Y12 preferred.",
        },
    }
}

# Format text fixtures. Round-1 already has format A (VCF), B (.genome),
# and C (.bio view). For A1/A2 we map A1 -> VCF only, A2 -> VCF + ruleset
# stub (mock client doesn't actually need the file content; live clients
# would). When a file is missing, the harness still runs in mock mode.
#
# Round-2 adds D (Phenopacket), E (FHIR), F (PharmCAT) — these are the
# six formats called for in SPEC §3.3 and the round-2 R5 task.
DEFAULT_FORMAT_FILES: Dict[str, Optional[str]] = {
    "A1": "bench/data/format_a_vcf.txt",
    "A2": "bench/data/format_a_vcf.txt",  # ruleset appended in production
    "B": "bench/data/format_b_genome_reconstructed.md",
    "C": "bench/data/format_c_bio_view.md",
    "D": "bench/v2/data/format_d_phenopacket.json",   # Phenopacket v2
    "E": "bench/v2/data/format_e_fhir_bundle.json",   # FHIR Genomics IG bundle
    "F": "bench/v2/data/format_f_pharmcat_report.json",  # PharmCAT report
    "G": None,  # methylation pilot — Task 10
    "H": None,  # full .bio bundle — future
}


def _load_format_text(fmt: str) -> str:
    rel = DEFAULT_FORMAT_FILES.get(fmt)
    if not rel:
        return f"<{fmt}: format text not yet available in v2 round-1>"
    p = REPO_ROOT / rel
    if not p.exists():
        return f"<{fmt}: file {rel} not found>"
    return p.read_text(encoding="utf-8")


def _load_prompt_template() -> str:
    """Return the strict no-tools prompt text from the round-1 template."""
    if not PROMPT_TEMPLATE_PATH.exists():
        return _MINIMAL_PROMPT_FALLBACK
    raw = PROMPT_TEMPLATE_PATH.read_text(encoding="utf-8")
    # Extract the fenced prompt block (```...```).
    import re

    m = re.search(r"```\s*\n(.*?)\n```", raw, re.DOTALL)
    if not m:
        return raw
    return m.group(1)


_MINIMAL_PROMPT_FALLBACK = (
    "You are participating in a controlled experiment. Answer ONLY from the\n"
    "embedded document. Use ZERO tools. Reply with ONLY a JSON object.\n\n"
    "QUESTION: {question}\n\n"
    "DOCUMENT:\n==========\n{format_content}\n==========\n"
)


def build_prompt(template: str, question_text: str, format_content: str) -> str:
    """Substitute the {question}/{format_content} placeholders.

    The round-1 template hardcodes the clopidogrel question. We
    re-substitute the literal `Can the patient ... clopidogrel safely at
    standard dose?` line with the parametrized question if a placeholder
    isn't present.
    """
    out = template
    if "{format_content}" in out:
        out = out.replace("{format_content}", format_content)
    else:
        out = out + "\n\nDOCUMENT:\n" + format_content
    if "{question}" in out:
        out = out.replace("{question}", question_text)
    else:
        # Replace the literal round-1 question line if present.
        import re

        out = re.sub(
            r"QUESTION:\s*Can the patient \(NA12878\)[^\n]*",
            f"QUESTION: {question_text}",
            out,
        )
    return out


# ---------------------------------------------------------------------------
# Harness driver
# ---------------------------------------------------------------------------


def run_one(
    *,
    family: str,
    format_id: str,
    question: Dict[str, Any],
    template: str,
    n_replicates: int,
    temperature: float,
    base_seed: int,
    force_mock: bool,
    model: Optional[str] = None,
    client: Any = None,
) -> List[Dict[str, Any]]:
    """Run N replicates of one (family, format, question) cell.

    ``client`` may be supplied to share a single connection across
    cells (used by the OpenRouter driver to amortise the requests
    Session); otherwise a fresh client is fetched via the factory.
    ``model`` overrides the client's default model slug.
    """
    if client is None:
        client = get_client(family, force_mock=force_mock)
    is_mock = client.name == "mock"
    fmt_text = _load_format_text(format_id)
    prompt = build_prompt(template, question["question"], fmt_text)

    out: List[Dict[str, Any]] = []
    for i in range(n_replicates):
        seed = base_seed + i
        complete_kwargs: Dict[str, Any] = dict(
            format_id=format_id,
            question_id=question["id"],
            replicate_idx=i,
            temperature=temperature,
            seed=seed,
        )
        if model is not None:
            complete_kwargs["model"] = model
        completion = client.complete(prompt, **complete_kwargs)
        scoring = llm_scoring.score_response(completion.text, question["gold_answer"])
        record: Dict[str, Any] = {
            "id": f"{format_id}-{question['id']}-{family}-{i}",
            "format": format_id,
            "question_id": question["id"],
            "model": completion.model,
            "model_family": family,
            "client": client.name,
            "is_mock": is_mock,
            "replicate_idx": i,
            "temperature": temperature,
            "seed": seed,
            "prompt_chars": len(prompt),
            "response_text": completion.text,
            "response": scoring["parsed"],
            "scoring": {
                k: v
                for k, v in scoring.items()
                if k not in {"parsed"}
            },
            "raw": completion.raw,
        }
        out.append(record)
    return out


# ---------------------------------------------------------------------------
# Round-2: YAML question loader + OpenRouter driver
# ---------------------------------------------------------------------------


def load_questions_from_yaml(question_dir: Path, qids: List[str]) -> Dict[str, Dict[str, Any]]:
    """Load `qNN.yaml` files into the in-memory question dict.

    YAML loaded with PyYAML when available; otherwise a minimal
    hand-rolled parser is used (we control these YAML files and they
    follow a fixed schema, so we keep PyYAML optional).
    """
    out: Dict[str, Dict[str, Any]] = {}
    try:
        import yaml  # type: ignore  # pyright: ignore[reportMissingImports]
    except Exception:  # pragma: no cover - PyYAML is on the pinned env
        yaml = None
    for qid in qids:
        path = question_dir / f"{qid}.yaml"
        if not path.exists():
            raise FileNotFoundError(f"question file not found: {path}")
        text = path.read_text(encoding="utf-8")
        if yaml is None:
            raise RuntimeError(
                "PyYAML is required to load round-2 question YAMLs. "
                "Run `pip install pyyaml`."
            )
        data = yaml.safe_load(text)
        if not isinstance(data, dict) or "id" not in data or "gold_answer" not in data:
            raise ValueError(f"malformed question YAML at {path}")
        out[qid] = data
    return out


def run_smoke(
    *,
    questions: Dict[str, Dict[str, Any]],
    formats: List[str],
    families: List[str],
    n_replicates: int,
    temperature: float,
    base_seed: int,
    force_mock: bool,
    question_ids: Optional[List[str]] = None,
) -> Dict[str, Any]:
    template = _load_prompt_template()
    used_ids = question_ids or list(questions.keys())
    conditions: List[Dict[str, Any]] = []
    for qid in used_ids:
        q = questions[qid]
        for fmt in formats:
            for fam in families:
                conditions.extend(
                    run_one(
                        family=fam,
                        format_id=fmt,
                        question=q,
                        template=template,
                        n_replicates=n_replicates,
                        temperature=temperature,
                        base_seed=base_seed,
                        force_mock=force_mock,
                    )
                )
    return {
        "experiment": "exp03_llm_eval",
        "schema_version": "v2.0",
        "methodology": (
            "Multi-LLM end-to-end eval per SPEC §3.3. Each (format, model, "
            "question) triple is replicated N times with temperature>=0.5; "
            "responses scored on five binary rubric criteria from §3.3."
        ),
        "date": _dt.date.today().isoformat(),
        "replicates_per_cell": n_replicates,
        "temperature": temperature,
        "base_seed": base_seed,
        "formats": formats,
        "model_families": families,
        "question_ids": used_ids,
        "questions": {qid: questions[qid] for qid in used_ids},
        "n_records": len(conditions),
        "any_live_client": any(not c["is_mock"] for c in conditions),
        "conditions": conditions,
    }


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Multi-LLM eval harness (bench/v2)")
    p.add_argument(
        "--question",
        default="q01",
        help="Comma-separated question IDs to run (default: q01).",
    )
    p.add_argument(
        "--formats",
        default="A1,A2,B,C",
        help="Comma-separated format IDs (A1,A2,B,C,D,E,F,G,H).",
    )
    p.add_argument(
        "--models",
        default="claude,openai,gemini",
        help=(
            "Comma-separated model families (claude,openai,gemini,llama3,mock). "
            "Ignored when --client openrouter is set; in that case --model selects."
        ),
    )
    p.add_argument(
        "--client",
        default=None,
        choices=[None, "openrouter"],
        help=(
            "If 'openrouter', route ALL traffic through the OpenRouter "
            "client and treat --model as the model slug (or comma-separated "
            "list of slugs). The --models families flag is then ignored."
        ),
    )
    p.add_argument(
        "--model",
        default=None,
        help=(
            "Model slug(s) for --client openrouter, comma-separated "
            "(e.g. 'anthropic/claude-sonnet-4.6,openai/gpt-5.4-mini')."
        ),
    )
    p.add_argument("--n-replicates", type=int, default=3)
    p.add_argument("--temperature", type=float, default=0.7)
    p.add_argument("--base-seed", type=int, default=20260509)
    p.add_argument(
        "--force-mock",
        action="store_true",
        help="Use the mock client even when API keys are present.",
    )
    p.add_argument(
        "--questions-dir",
        default="bench/v2/data/questions",
        help="Directory containing qNN.yaml files for round-2 question loading.",
    )
    p.add_argument(
        "--load-questions-from-yaml",
        action="store_true",
        help="Load question YAML files from --questions-dir instead of DEFAULT_QUESTIONS.",
    )
    p.add_argument(
        "--cost-cap-usd",
        type=float,
        default=None,
        help="Hard cost cap (sums OpenRouter usage.cost across calls).",
    )
    p.add_argument(
        "--out",
        default="bench/v2/results/exp03_llm_eval_smoke.json",
        help="Output JSON path (relative to repo root).",
    )
    return p.parse_args(argv)


def _resolve_model_slug(slug: str) -> str:
    """Map a slug like ``anthropic/...`` to a model_family label.

    Used so per-record bookkeeping retains the family even when the
    OpenRouter client is shared across families.
    """
    head = slug.split("/", 1)[0].lower()
    if head == "anthropic":
        return "claude"
    if head == "openai":
        return "openai"
    if head == "google":
        return "gemini"
    if head in ("meta-llama", "meta"):
        return "llama"
    return head or "openrouter"


def run_openrouter(
    *,
    questions: Dict[str, Dict[str, Any]],
    formats: List[str],
    model_slugs: List[str],
    n_replicates: int,
    temperature: float,
    base_seed: int,
    cost_cap_usd: Optional[float],
    progress: bool = True,
) -> Dict[str, Any]:
    """Drive the full (model_slug × format × question × replicate) grid
    through a single OpenRouter client, tracking cumulative cost.

    Stops early (and marks ``partial=True``) if ``cost_cap_usd`` is
    reached. Each individual API failure is recorded as a Completion
    with ``finish_reason='error'`` and contributes a zero-score record;
    the loop continues so the rest of the grid is still attempted.
    """
    try:  # package-style import (mirrors llm_harness module preamble)
        from bench.v2.scripts.llm_clients.openrouter import Client as ORClient
    except ImportError:  # script-style fallback
        from llm_clients.openrouter import Client as ORClient  # type: ignore

    template = _load_prompt_template()
    client = ORClient()
    used_ids = list(questions.keys())
    conditions: List[Dict[str, Any]] = []
    cost_total = 0.0
    tokens_in_total = 0
    tokens_out_total = 0
    n_calls = 0
    n_calls_ok = 0
    partial = False
    stop_reason: Optional[str] = None

    grid_total = len(used_ids) * len(formats) * len(model_slugs) * n_replicates

    for qid in used_ids:
        if partial:
            break
        q = questions[qid]
        for fmt in formats:
            if partial:
                break
            fmt_text = _load_format_text(fmt)
            prompt = build_prompt(template, q["question"], fmt_text)
            for slug in model_slugs:
                if partial:
                    break
                family = _resolve_model_slug(slug)
                for i in range(n_replicates):
                    if cost_cap_usd is not None and cost_total >= cost_cap_usd:
                        partial = True
                        stop_reason = (
                            f"cost cap hit: ${cost_total:.4f} >= ${cost_cap_usd:.4f}"
                        )
                        break
                    seed = base_seed + i
                    completion = client.complete(
                        prompt,
                        format_id=fmt,
                        question_id=qid,
                        replicate_idx=i,
                        temperature=temperature,
                        seed=seed,
                        model=slug,
                    )
                    n_calls += 1
                    is_error = completion.finish_reason == "error"
                    usage = (completion.raw or {}).get("usage") or {}
                    cost = float(usage.get("cost") or 0.0)
                    cost_total += cost
                    tokens_in_total += int(usage.get("prompt_tokens") or 0)
                    tokens_out_total += int(usage.get("completion_tokens") or 0)
                    if not is_error:
                        n_calls_ok += 1
                    scoring = llm_scoring.score_response(
                        completion.text, q["gold_answer"]
                    )
                    record: Dict[str, Any] = {
                        "id": f"{fmt}-{qid}-{family}-{i}",
                        "format": fmt,
                        "question_id": qid,
                        "model": slug,
                        "model_family": family,
                        "client": client.name,
                        "is_mock": False,
                        "replicate_idx": i,
                        "temperature": temperature,
                        "seed": seed,
                        "prompt_chars": len(prompt),
                        "response_text": completion.text,
                        "response": scoring["parsed"],
                        "scoring": {
                            k: v for k, v in scoring.items() if k != "parsed"
                        },
                        "raw": completion.raw,
                        "is_error": is_error,
                        "call_cost_usd": cost,
                    }
                    conditions.append(record)
                    if progress and n_calls % 10 == 0:
                        print(
                            f"  [{n_calls}/{grid_total}] cost=${cost_total:.4f} "
                            f"ok={n_calls_ok} err={n_calls - n_calls_ok}",
                            file=sys.stderr,
                        )
    return {
        "experiment": "exp03_llm_eval_real",
        "schema_version": "v2.1",
        "methodology": (
            "Round-2 multi-LLM eval per SPEC §3.3 via OpenRouter unified API. "
            "Each (format, model, question) cell run with N replicates at "
            "temperature>=0.5; responses scored on five binary rubric criteria. "
            "Cost tracked per call via OpenRouter usage.cost; hard cap enforced."
        ),
        "client": "openrouter",
        "date": _dt.date.today().isoformat(),
        "replicates_per_cell": n_replicates,
        "temperature": temperature,
        "base_seed": base_seed,
        "formats": formats,
        "model_slugs": model_slugs,
        "model_families": sorted({_resolve_model_slug(s) for s in model_slugs}),
        "question_ids": used_ids,
        "questions": {qid: questions[qid] for qid in used_ids},
        "n_records": len(conditions),
        "n_calls": n_calls,
        "n_calls_ok": n_calls_ok,
        "n_calls_err": n_calls - n_calls_ok,
        "tokens_in_total": tokens_in_total,
        "tokens_out_total": tokens_out_total,
        "cost_total_usd": round(cost_total, 6),
        "cost_cap_usd": cost_cap_usd,
        "partial": partial,
        "stop_reason": stop_reason,
        "any_live_client": True,
        "conditions": conditions,
    }


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]

    # Round-2: --client openrouter takes precedence and dispatches via slugs.
    if args.client == "openrouter":
        if not args.model:
            print("error: --model is required when --client openrouter", file=sys.stderr)
            return 2
        slugs = [s.strip() for s in args.model.split(",") if s.strip()]
        qids = [q.strip() for q in args.question.split(",") if q.strip()]
        if args.load_questions_from_yaml:
            qdir = REPO_ROOT / args.questions_dir if not Path(args.questions_dir).is_absolute() else Path(args.questions_dir)
            questions = load_questions_from_yaml(qdir, qids)
        else:
            for qid in qids:
                if qid not in DEFAULT_QUESTIONS:
                    print(f"warning: question {qid!r} not in built-in fixture; skipping", file=sys.stderr)
            qids = [q for q in qids if q in DEFAULT_QUESTIONS]
            questions = {q: DEFAULT_QUESTIONS[q] for q in qids}
        if not qids:
            print("error: no valid question IDs", file=sys.stderr)
            return 2
        payload = run_openrouter(
            questions=questions,
            formats=formats,
            model_slugs=slugs,
            n_replicates=args.n_replicates,
            temperature=args.temperature,
            base_seed=args.base_seed,
            cost_cap_usd=args.cost_cap_usd,
        )
        out_path = REPO_ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
        print(
            f"wrote {payload['n_records']} records "
            f"(calls={payload['n_calls']} ok={payload['n_calls_ok']} "
            f"err={payload['n_calls_err']}, cost=${payload['cost_total_usd']:.4f}, "
            f"partial={payload['partial']}) -> {out_path}"
        )
        return 0

    families = [m.strip() for m in args.models.split(",") if m.strip()]
    qids = [q.strip() for q in args.question.split(",") if q.strip()]
    for qid in qids:
        if qid not in DEFAULT_QUESTIONS:
            print(f"warning: question {qid!r} not in built-in fixture; skipping",
                  file=sys.stderr)
    qids = [q for q in qids if q in DEFAULT_QUESTIONS]
    if not qids:
        print("error: no valid question IDs", file=sys.stderr)
        return 2

    payload = run_smoke(
        questions=DEFAULT_QUESTIONS,
        formats=formats,
        families=families,
        n_replicates=args.n_replicates,
        temperature=args.temperature,
        base_seed=args.base_seed,
        force_mock=args.force_mock,
        question_ids=qids,
    )

    out_path = REPO_ROOT / args.out if not Path(args.out).is_absolute() else Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2, sort_keys=False) + "\n")
    print(
        f"wrote {payload['n_records']} records "
        f"({len(formats)} formats x {len(families)} families x "
        f"{args.n_replicates} replicates x {len(qids)} questions) -> {out_path}"
    )
    if not payload["any_live_client"]:
        print("note: all responses came from the mock client (no API keys set)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
