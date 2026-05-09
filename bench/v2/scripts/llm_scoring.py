"""Deterministic scoring functions for LLM evaluation responses.

Per SPEC §3.3 the scoring rubric is:
    - verdict_correct
    - phenotype_correct
    - guideline_cited_with_version
    - variant_evidence_cited
    - no_inference_required_outside_text
    - harm_risk_if_acted_on  (0/1/2 scale; deferred to human rater in v2)

This module covers the five binary criteria. Every function is a pure
function of (response_dict, gold_answer_dict): given the same inputs it
MUST return the same output. No randomness, no external state.

The `score_response` aggregator returns a flat dict suitable for direct
inclusion in the harness JSON output.
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, Iterable, List, Optional

# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _norm(text: Any) -> str:
    """Normalize a free-text field for matching: lower, collapse whitespace."""
    if text is None:
        return ""
    s = str(text).strip().lower()
    s = re.sub(r"\s+", " ", s)
    return s


def _contains_any(haystack: str, needles: Iterable[str]) -> bool:
    h = _norm(haystack)
    return any(_norm(n) and _norm(n) in h for n in needles)


def parse_json_response(text: str) -> Dict[str, Any]:
    """Extract a JSON object from a model response.

    Models occasionally wrap their JSON in ```json fences or add stray
    preamble; we strip those and parse the first {...} block. Returns an
    empty dict on hard parse failure (caller can mark the response as
    malformed).
    """
    if not isinstance(text, str):
        return {}
    s = text.strip()
    # Strip markdown fences.
    fence_match = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", s, re.DOTALL | re.IGNORECASE)
    if fence_match:
        s = fence_match.group(1)
    else:
        # Otherwise grab the first balanced {...} block.
        start = s.find("{")
        end = s.rfind("}")
        if start != -1 and end != -1 and end > start:
            s = s[start : end + 1]
    try:
        obj = json.loads(s)
    except json.JSONDecodeError:
        return {}
    return obj if isinstance(obj, dict) else {}


# ---------------------------------------------------------------------------
# Per-criterion scorers
# ---------------------------------------------------------------------------


def score_verdict(response: Dict[str, Any], gold: Dict[str, Any]) -> bool:
    """True iff the model verdict matches any acceptable gold verdict.

    `gold["verdict"]` may be a single string or a list of acceptable
    strings. Matching is case-insensitive substring (so "no — consider
    alternative" matches "no").
    """
    rv = _norm(response.get("verdict"))
    if not rv:
        return False
    accepted = gold.get("verdict")
    if accepted is None:
        return False
    if isinstance(accepted, str):
        accepted_list: List[str] = [accepted]
    else:
        accepted_list = [str(x) for x in accepted]
    return any(_norm(a) and _norm(a) in rv or rv in _norm(a) for a in accepted_list)


_PHENOTYPE_SYNONYMS = {
    "intermediate metabolizer": ["im", "intermediate metabolizer"],
    "poor metabolizer": ["pm", "poor metabolizer"],
    "rapid metabolizer": ["rm", "rapid metabolizer"],
    "ultrarapid metabolizer": ["um", "ultrarapid metabolizer", "ultra-rapid metabolizer"],
    "normal metabolizer": ["nm", "normal metabolizer", "extensive metabolizer", "em"],
    "likely pathogenic": ["lp", "likely pathogenic"],
    "pathogenic": ["pathogenic"],
    "benign": ["benign"],
    "likely benign": ["lb", "likely benign"],
    "vus": ["vus", "uncertain significance", "variant of uncertain significance"],
}


def score_phenotype(response: Dict[str, Any], gold: Dict[str, Any]) -> bool:
    """True iff the model phenotype matches gold (with synonym table)."""
    expected = _norm(gold.get("phenotype"))
    if not expected:
        # No phenotype required for this question — treat as correct.
        return True
    seen = _norm(response.get("phenotype"))
    if not seen:
        return False
    candidates = _PHENOTYPE_SYNONYMS.get(expected, [expected])
    return any(c in seen for c in candidates)


_VERSION_RE = re.compile(
    r"(?:@|\s|^)(?:19|20)\d{2}\b|"  # year token
    r"v\d+(?:\.\d+)*\b|"             # vN.N
    r"\b\d{4}\.\d+\b"                 # 2025.x
)


def score_guideline_cited(response: Dict[str, Any], gold: Dict[str, Any]) -> bool:
    """Guideline is cited *with* a version/year token.

    Gold answer can specify `cited_guideline` with the canonical name
    (e.g. "CPIC@2022"). The model passes if its `guideline_cited` field
    contains the gold guideline name (case-insensitive) AND a version
    token (year, vN.N, or YYYY.x).
    """
    cited = _norm(response.get("guideline_cited"))
    if not cited or cited == "unknown":
        return False
    gold_name = gold.get("cited_guideline") or gold.get("guideline")
    if isinstance(gold_name, list):
        gold_names = [str(g) for g in gold_name]
    elif gold_name:
        gold_names = [str(gold_name)]
    else:
        # If gold doesn't pin a name, the version-token check alone is enough.
        gold_names = []

    has_version = bool(_VERSION_RE.search(cited))
    if not gold_names:
        return has_version
    # Strip "@year" tail when matching the name.
    name_tokens = []
    for name in gold_names:
        n = _norm(name)
        n = re.sub(r"@.*$", "", n).strip()
        n = re.sub(r"\(.+\)$", "", n).strip()
        # Take first 1-2 words as identifying token (e.g. "cpic", "acmg").
        first = n.split(" ")[0] if n else ""
        if first:
            name_tokens.append(first)
    name_match = any(t and t in cited for t in name_tokens)
    return name_match and has_version


def score_variant_evidence(response: Dict[str, Any], gold: Dict[str, Any]) -> bool:
    """True iff `variant_evidence` cites an rsID, HGVS, or fact hash.

    rsID:       rs followed by ≥3 digits
    HGVS:       contains "c." or "p." or "g." with a position
    fact_hash:  contains "sha256:" or "sha-256" prefix
    """
    text = _norm(response.get("variant_evidence"))
    if not text or text == "unknown":
        return False
    if re.search(r"\brs\d{3,}\b", text):
        return True
    if re.search(r"\b[cgpmnr]\.\d+", text):
        return True
    if "sha256" in text or "sha-256" in text or "fact_hash" in text or "fact hash" in text:
        return True
    return False


def score_no_external_inference(response: Dict[str, Any], gold: Dict[str, Any]) -> bool:
    """Self-report that no external knowledge was needed.

    Pass iff `anything_inferred_not_in_text` is missing, empty, "none",
    "n/a", or equivalent.
    """
    raw = response.get("anything_inferred_not_in_text")
    if raw is None:
        return True
    n = _norm(raw)
    if not n:
        return True
    return n in {"none", "n/a", "na", "nothing", "no", "no inference", "no external knowledge"}


# ---------------------------------------------------------------------------
# Aggregator
# ---------------------------------------------------------------------------


SCORERS = {
    "verdict_correct": score_verdict,
    "phenotype_correct": score_phenotype,
    "guideline_cited_with_version": score_guideline_cited,
    "variant_evidence_cited": score_variant_evidence,
    "no_inference_required_outside_text": score_no_external_inference,
}


def score_response(
    response_text: str,
    gold: Dict[str, Any],
    *,
    parsed_response: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Score a raw LLM response string against a gold answer.

    Returns a dict with:
        - parsed:      the JSON object recovered from the response (or {})
        - parse_ok:    bool
        - <criterion>: bool, one per scorer
        - score_total: int sum of trues across the five binary criteria
    """
    parsed = parsed_response if parsed_response is not None else parse_json_response(response_text)
    parse_ok = bool(parsed)
    out: Dict[str, Any] = {"parsed": parsed, "parse_ok": parse_ok}
    total = 0
    for name, fn in SCORERS.items():
        val = bool(fn(parsed, gold)) if parse_ok else False
        out[name] = val
        if val:
            total += 1
    out["score_total"] = total
    return out


__all__ = [
    "parse_json_response",
    "score_verdict",
    "score_phenotype",
    "score_guideline_cited",
    "score_variant_evidence",
    "score_no_external_inference",
    "score_response",
    "SCORERS",
]
