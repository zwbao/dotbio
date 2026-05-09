"""Pytest tests for `llm_scoring`.

Covers:
1. JSON extraction (with and without markdown fences)
2. Verdict matching (string + list-of-acceptable + substring tolerance)
3. Phenotype matching with the IM/PM/etc. synonym table
4. Guideline citation requires both a name token and a version token
5. Variant evidence accepts rsID, HGVS, and SHA-256 fact hashes
6. The aggregator returns booleans for every criterion + score_total
7. Mock-fixture round-trip: the smoke run produces parseable, scoreable records
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.v2.scripts import llm_scoring
from bench.v2.scripts.llm_harness import DEFAULT_QUESTIONS, run_smoke


GOLD_Q01 = DEFAULT_QUESTIONS["q01"]["gold_answer"]


# ---------------------------------------------------------------------------
# 1. parse_json_response
# ---------------------------------------------------------------------------


def test_parse_json_response_handles_plain_object():
    text = '{"verdict": "depends", "phenotype": "IM"}'
    assert llm_scoring.parse_json_response(text) == {
        "verdict": "depends",
        "phenotype": "IM",
    }


def test_parse_json_response_strips_markdown_fence():
    text = """Here is the answer:
```json
{"verdict": "no", "phenotype": "Intermediate Metabolizer"}
```
"""
    obj = llm_scoring.parse_json_response(text)
    assert obj["verdict"] == "no"
    assert obj["phenotype"] == "Intermediate Metabolizer"


def test_parse_json_response_returns_empty_on_garbage():
    assert llm_scoring.parse_json_response("not json at all") == {}
    assert llm_scoring.parse_json_response("") == {}


# ---------------------------------------------------------------------------
# 2. verdict
# ---------------------------------------------------------------------------


def test_verdict_accepts_substring_of_gold_list():
    # gold accepts ["no", "depends", "alternative", "consider alternative"]
    assert llm_scoring.score_verdict({"verdict": "depends"}, GOLD_Q01)
    assert llm_scoring.score_verdict({"verdict": "no — consider alternative"}, GOLD_Q01)
    assert not llm_scoring.score_verdict({"verdict": "yes"}, GOLD_Q01)
    assert not llm_scoring.score_verdict({"verdict": ""}, GOLD_Q01)


# ---------------------------------------------------------------------------
# 3. phenotype synonyms
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "model_phenotype,expected",
    [
        ("Intermediate Metabolizer", True),
        ("CYP2C19 IM", True),
        ("intermediate metabolizer (im)", True),
        ("Poor Metabolizer", False),
        ("unknown", False),
        ("", False),
    ],
)
def test_phenotype_synonyms(model_phenotype, expected):
    assert (
        llm_scoring.score_phenotype({"phenotype": model_phenotype}, GOLD_Q01) is expected
    )


# ---------------------------------------------------------------------------
# 4. guideline citation
# ---------------------------------------------------------------------------


def test_guideline_requires_name_and_version():
    # Name + year token => pass.
    assert llm_scoring.score_guideline_cited(
        {"guideline_cited": "CPIC@2022"}, GOLD_Q01
    )
    assert llm_scoring.score_guideline_cited(
        {"guideline_cited": "CPIC 2022 clopidogrel guideline"}, GOLD_Q01
    )
    # Name without version => fail.
    assert not llm_scoring.score_guideline_cited(
        {"guideline_cited": "CPIC"}, GOLD_Q01
    )
    # Version without name => fail when gold pins a name.
    assert not llm_scoring.score_guideline_cited(
        {"guideline_cited": "guideline v2.1 from somewhere"}, GOLD_Q01
    )
    # "unknown" => fail.
    assert not llm_scoring.score_guideline_cited(
        {"guideline_cited": "unknown"}, GOLD_Q01
    )


# ---------------------------------------------------------------------------
# 5. variant evidence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "evidence,expected",
    [
        ("rs4244285 G|A heterozygous", True),
        ("c.681G>A in CYP2C19", True),
        ("sha256:abc123 fact hash", True),
        ("fact_hash sha-256:deadbeef", True),
        ("unknown", False),
        ("", False),
        ("just some narrative without identifiers", False),
    ],
)
def test_variant_evidence_recognizes_identifiers(evidence, expected):
    assert (
        llm_scoring.score_variant_evidence({"variant_evidence": evidence}, GOLD_Q01)
        is expected
    )


# ---------------------------------------------------------------------------
# 6. aggregator
# ---------------------------------------------------------------------------


def test_score_response_returns_full_rubric():
    response_text = json.dumps(
        {
            "verdict": "depends",
            "phenotype": "Intermediate Metabolizer",
            "diplotype": "*1/*2",
            "guideline_cited": "CPIC@2022",
            "variant_evidence": "rs4244285 G|A; sha256:abc",
            "anything_inferred_not_in_text": "none",
            "confidence": "high",
        }
    )
    out = llm_scoring.score_response(response_text, GOLD_Q01)
    assert out["parse_ok"] is True
    assert out["verdict_correct"] is True
    assert out["phenotype_correct"] is True
    assert out["guideline_cited_with_version"] is True
    assert out["variant_evidence_cited"] is True
    assert out["no_inference_required_outside_text"] is True
    assert out["score_total"] == 5


def test_score_response_handles_unparseable_text():
    out = llm_scoring.score_response("not even close to JSON", GOLD_Q01)
    assert out["parse_ok"] is False
    assert out["score_total"] == 0
    assert all(out[k] is False for k in (
        "verdict_correct",
        "phenotype_correct",
        "guideline_cited_with_version",
        "variant_evidence_cited",
        "no_inference_required_outside_text",
    ))


# ---------------------------------------------------------------------------
# 7. End-to-end smoke run via the harness with the mock client
# ---------------------------------------------------------------------------


def test_smoke_run_with_mock_client_is_deterministic():
    payload_a = run_smoke(
        questions=DEFAULT_QUESTIONS,
        formats=["A1", "A2", "B", "C"],
        families=["claude", "openai", "gemini"],
        n_replicates=2,
        temperature=0.7,
        base_seed=42,
        force_mock=True,
    )
    payload_b = run_smoke(
        questions=DEFAULT_QUESTIONS,
        formats=["A1", "A2", "B", "C"],
        families=["claude", "openai", "gemini"],
        n_replicates=2,
        temperature=0.7,
        base_seed=42,
        force_mock=True,
    )
    # Same inputs -> identical response_text and scoring.
    assert payload_a["n_records"] == payload_b["n_records"] == 4 * 3 * 2
    for ra, rb in zip(payload_a["conditions"], payload_b["conditions"]):
        assert ra["response_text"] == rb["response_text"]
        assert ra["scoring"] == rb["scoring"]
    # All replicates carry full metadata.
    for rec in payload_a["conditions"]:
        for field in (
            "model",
            "model_family",
            "replicate_idx",
            "temperature",
            "seed",
            "scoring",
        ):
            assert field in rec, f"missing {field}"
    # The .bio (format C) row scores >= the raw VCF (A1) row on guideline.
    by_id = {(r["format"], r["model_family"], r["replicate_idx"]): r for r in payload_a["conditions"]}
    c_score = by_id[("C", "claude", 0)]["scoring"]["guideline_cited_with_version"]
    a1_score = by_id[("A1", "claude", 0)]["scoring"]["guideline_cited_with_version"]
    assert c_score is True
    assert a1_score is False


def test_smoke_run_writes_expected_top_level_keys():
    payload = run_smoke(
        questions=DEFAULT_QUESTIONS,
        formats=["A1"],
        families=["claude"],
        n_replicates=1,
        temperature=0.5,
        base_seed=1,
        force_mock=True,
    )
    for key in (
        "experiment",
        "schema_version",
        "methodology",
        "date",
        "replicates_per_cell",
        "temperature",
        "base_seed",
        "formats",
        "model_families",
        "question_ids",
        "n_records",
        "conditions",
    ):
        assert key in payload, f"missing top-level key: {key}"
