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
DEFAULT_FORMAT_FILES: Dict[str, Optional[str]] = {
    "A1": "bench/data/format_a_vcf.txt",
    "A2": "bench/data/format_a_vcf.txt",  # ruleset appended in production
    "B": "bench/data/format_b_genome_reconstructed.md",
    "C": "bench/data/format_c_bio_view.md",
    "D": None,  # phenopacket — populated by Task 1
    "E": None,  # FHIR bundle — Task 2
    "F": None,  # PharmCAT json — Task 3
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
) -> List[Dict[str, Any]]:
    client = get_client(family, force_mock=force_mock)
    is_mock = client.name == "mock"
    fmt_text = _load_format_text(format_id)
    prompt = build_prompt(template, question["question"], fmt_text)

    out: List[Dict[str, Any]] = []
    for i in range(n_replicates):
        seed = base_seed + i
        completion = client.complete(
            prompt,
            format_id=format_id,
            question_id=question["id"],
            replicate_idx=i,
            temperature=temperature,
            seed=seed,
        )
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
        help="Comma-separated model families (claude,openai,gemini,llama3,mock).",
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
        "--out",
        default="bench/v2/results/exp03_llm_eval_smoke.json",
        help="Output JSON path (relative to repo root).",
    )
    return p.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)
    formats = [f.strip() for f in args.formats.split(",") if f.strip()]
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
