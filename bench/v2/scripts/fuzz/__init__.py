"""Adversarial robustness fuzz suite for dotbio (Experiment 7).

Each module emits a list of FuzzCase objects via a top-level ``CASES``
list and/or a ``build_cases()`` factory. The runner imports them and
executes against the dotbio CLI as it currently exists; this code does
not modify dotbio source.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass
class FuzzCase:
    """A single fuzz scenario.

    Attributes:
        case_id: short stable identifier ("vcf01", "rs03", ...)
        module:  one of {"vcf", "rulesets", "schema", "hashes"}
        title:   one-line human description
        rationale: why this case exists
        expected: one of {"graceful_failure", "successful_handling",
                          "documented_data_loss", "infeasibility_proof"}
        expected_exit_codes: tuple of acceptable exit codes (only meaningful
                             for cases that actually invoke the CLI)
        run: callable taking a workdir Path -> dict result. The dict MUST
             include keys {"ok": bool, "actual_exit": int|None,
             "stdout": str, "stderr": str, "notes": str}.
    """

    case_id: str
    module: str
    title: str
    rationale: str
    expected: str
    expected_exit_codes: tuple[int, ...] = ()
    run: Callable[..., dict[str, Any]] = field(default=lambda *_a, **_k: {})


__all__ = ["FuzzCase"]
