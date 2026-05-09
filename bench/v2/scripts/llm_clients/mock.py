"""Mock LLM client.

Returns deterministic JSON responses keyed by (format_id, question_id,
model_family). The fixtures are derived from the round-1 single-shot
results in `bench/results/llm_eval.json` so the smoke run produces
plausible scoring distributions without any network calls.

Determinism:
    Calling `complete()` with the same (format_id, question_id, family,
    replicate_idx) MUST return byte-identical text. This lets pytest
    assertions about the smoke run be stable across machines.

Variability per replicate:
    To exercise the harness's replicate machinery, low-confidence
    fixtures may flip between two pre-canned variants based on
    `replicate_idx % 2`. The flip is deterministic.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

# Predetermined fixtures keyed by (format_id, question_id, family).
# These are intentionally hand-authored to mirror the round-1 results
# (see bench/results/llm_eval.json) without claiming new clinical data.
_FIXTURES: Dict[Tuple[str, str, str], Dict[str, Any]] = {
    # Format A1 = raw VCF; gives variant-evidence only, no phenotype.
    ("A1", "q01", "claude"): {
        "verdict": "depends",
        "phenotype": "unknown",
        "diplotype": "unknown",
        "guideline_cited": "unknown",
        "variant_evidence": "rs4244285 G|A (heterozygous, CYP2C19); rs12248560 C|C",
        "anything_inferred_not_in_text": "linking these rsIDs to CYP2C19*2/*17 requires external knowledge",
        "confidence": "low",
        "reasoning": "Document lists genotypes only; no phenotype mapping or guideline.",
    },
    ("A1", "q01", "openai"): {
        "verdict": "cannot_determine",
        "phenotype": "unknown",
        "diplotype": "unknown",
        "guideline_cited": "unknown",
        "variant_evidence": "rs4244285 het; rs12248560 ref",
        "anything_inferred_not_in_text": "rsID-to-haplotype mapping is external",
        "confidence": "low",
        "reasoning": "Raw VCF is insufficient without star-allele tables.",
    },
    ("A1", "q01", "gemini"): {
        "verdict": "depends",
        "phenotype": "unknown",
        "diplotype": "unknown",
        "guideline_cited": "unknown",
        "variant_evidence": "rs4244285, rs12248560 in CYP2C19",
        "anything_inferred_not_in_text": "guideline knowledge not in document",
        "confidence": "low",
        "reasoning": "Genotypes present but no clinical interpretation.",
    },
    # Format A2 = VCF + ruleset; LLM does in-context haplotype calling.
    ("A2", "q01", "claude"): {
        "verdict": "depends",
        "phenotype": "Intermediate Metabolizer",
        "diplotype": "*1/*2",
        "guideline_cited": "CPIC@2022",
        "variant_evidence": "rs4244285 G|A (heterozygous); rs12248560 absent",
        "anything_inferred_not_in_text": "none",
        "confidence": "high",
        "reasoning": "*2 defined by rs4244285; carrier status implies *1/*2 IM per ruleset.",
    },
    ("A2", "q01", "openai"): {
        "verdict": "depends",
        "phenotype": "Intermediate Metabolizer",
        "diplotype": "*1/*2",
        "guideline_cited": "CPIC 2022",
        "variant_evidence": "rs4244285 het",
        "anything_inferred_not_in_text": "none",
        "confidence": "high",
        "reasoning": "Ruleset maps the variant to *2; CPIC table indicates IM.",
    },
    ("A2", "q01", "gemini"): {
        "verdict": "depends",
        "phenotype": "Intermediate Metabolizer (IM)",
        "diplotype": "*1/*2",
        "guideline_cited": "CPIC@2022",
        "variant_evidence": "rs4244285 G/A heterozygous",
        "anything_inferred_not_in_text": "none",
        "confidence": "high",
        "reasoning": "Heterozygous *2 carrier; CPIC says alternative agent for ACS/PCI.",
    },
    # Format B = .genome reconstruction.
    ("B", "q01", "claude"): {
        "verdict": "depends",
        "phenotype": "Intermediate Metabolizer (*1/*2)",
        "diplotype": "*1/*2",
        "guideline_cited": "unknown",
        "variant_evidence": "unknown",
        "anything_inferred_not_in_text": "none",
        "confidence": "high",
        "reasoning": "Diplotype stated but no guideline citation in text.",
    },
    ("B", "q01", "openai"): {
        "verdict": "depends",
        "phenotype": "IM",
        "diplotype": "*1/*2",
        "guideline_cited": "unknown",
        "variant_evidence": "unknown",
        "anything_inferred_not_in_text": "none",
        "confidence": "medium",
        "reasoning": "Format gives diplotype only.",
    },
    ("B", "q01", "gemini"): {
        "verdict": "depends",
        "phenotype": "Intermediate Metabolizer",
        "diplotype": "*1/*2",
        "guideline_cited": "unknown",
        "variant_evidence": "unknown",
        "anything_inferred_not_in_text": "none",
        "confidence": "high",
        "reasoning": "Reconstruction gives the call but lacks provenance.",
    },
    # Format C = .bio bundle view.
    ("C", "q01", "claude"): {
        "verdict": "depends",
        "phenotype": "CYP2C19 Intermediate Metabolizer",
        "diplotype": "*1/*2",
        "guideline_cited": "CPIC@2022",
        "variant_evidence": "fact_hash sha256:abc... (rsID resolvable via facts/)",
        "anything_inferred_not_in_text": "none",
        "confidence": "high",
        "reasoning": ".bio view states phenotype + guideline + fact hashes.",
    },
    ("C", "q01", "openai"): {
        "verdict": "depends",
        "phenotype": "Intermediate Metabolizer",
        "diplotype": "*1/*2",
        "guideline_cited": "CPIC@2022",
        "variant_evidence": "fact hash referenced",
        "anything_inferred_not_in_text": "none",
        "confidence": "high",
        "reasoning": "Bundle view contains all fields needed.",
    },
    ("C", "q01", "gemini"): {
        "verdict": "depends",
        "phenotype": "CYP2C19 IM (*1/*2)",
        "diplotype": "*1/*2",
        "guideline_cited": "CPIC@2022",
        "variant_evidence": "sha256 fact hash present",
        "anything_inferred_not_in_text": "none",
        "confidence": "high",
        "reasoning": "View text gives phenotype + guideline + provenance.",
    },
}

# Replicate-flip variant: noisier text the model emits on odd replicates,
# used to give scoring tests something to vary over.
_FIXTURE_FLIPS: Dict[Tuple[str, str, str], Dict[str, Any]] = {
    ("A1", "q01", "claude"): {
        "verdict": "cannot_determine",
        "phenotype": "unknown",
        "diplotype": "unknown",
        "guideline_cited": "unknown",
        "variant_evidence": "rs4244285 (heterozygous)",
        "anything_inferred_not_in_text": "all clinical interpretation external",
        "confidence": "low",
        "reasoning": "VCF alone is not interpretable.",
    },
    ("A2", "q01", "openai"): {
        "verdict": "depends",
        "phenotype": "Intermediate Metabolizer",
        "diplotype": "*1/*2",
        "guideline_cited": "CPIC 2022 clopidogrel",
        "variant_evidence": "rs4244285 G/A",
        "anything_inferred_not_in_text": "none",
        "confidence": "medium",
        "reasoning": "Ruleset path; minor text variance.",
    },
}


@dataclass
class Completion:
    text: str
    raw: Dict[str, Any]
    model: str
    family: str
    finish_reason: str = "stop"


class Client:
    """Deterministic mock client.

    Use `family_alias` to record which real family was requested when
    falling back to mock (so the JSON output preserves the requested
    `model` field rather than always saying "mock").
    """

    name = "mock"
    env_var: Optional[str] = None  # never required
    default_model = "mock-fixture-v1"

    def __init__(self, family_alias: Optional[str] = None):
        self.family_alias = (family_alias or "mock").lower()

    @classmethod
    def available(cls) -> bool:
        return True  # mock is always available

    def complete(
        self,
        prompt: str,
        *,
        format_id: str,
        question_id: str,
        replicate_idx: int = 0,
        temperature: float = 0.7,
        seed: Optional[int] = None,
        model: Optional[str] = None,
    ) -> Completion:
        # Map alias -> fixture key family. We map any non-fixture family
        # to "claude" so smoke runs always have content.
        fixture_family = self.family_alias
        if fixture_family in {"anthropic"}:
            fixture_family = "claude"
        elif fixture_family in {"openai", "gpt-4", "gpt4o"}:
            fixture_family = "openai"
        elif fixture_family in {"google"}:
            fixture_family = "gemini"
        elif fixture_family in {"llama3", "together", "mock"}:
            fixture_family = "claude"

        key = (format_id, question_id, fixture_family)
        base = _FIXTURES.get(key)
        if base is None:
            # Fall back to claude fixture for that (format, question).
            key = (format_id, question_id, "claude")
            base = _FIXTURES.get(key)
        if base is None:
            # Last resort: synthesize a "cannot_determine" response.
            base = {
                "verdict": "cannot_determine",
                "phenotype": "unknown",
                "diplotype": "unknown",
                "guideline_cited": "unknown",
                "variant_evidence": "unknown",
                "anything_inferred_not_in_text": "no fixture available",
                "confidence": "low",
                "reasoning": f"No mock fixture for ({format_id}, {question_id}).",
            }

        # Optionally flip on odd replicate indices, deterministically.
        if replicate_idx % 2 == 1 and key in _FIXTURE_FLIPS:
            base = _FIXTURE_FLIPS[key]

        text = json.dumps(base, sort_keys=True, indent=2)
        return Completion(
            text=text,
            raw={"prompt_chars": len(prompt), "fixture_key": list(key)},
            model=model or self.default_model,
            family=self.family_alias,
        )
