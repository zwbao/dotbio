"""Methylation extension — Illumina 450K β-values → .bio bundle.

This extension demonstrates that the three dotbio principles
(multi-scale, evidence chain, time) hold for non-DNA-variant data:

- multi-scale: probe-level facts (β values) → tissue-level commits
  (epigenetic age estimate) → patient-level views
- evidence chain: every age estimate carries a `claim_id` whose
  `targets` list every CpG probe fact contributing > 0 to the score
- time: a methylation bundle is a commit DAG just like the DNA case;
  re-running with a new clock (Hannum, PhenoAge, GrimAge) appends a
  new commit and the diff is auditable

Public entry point: :func:`compile_methylation_csv`.
"""

from __future__ import annotations

from .compile import (
    HORVATH_CLOCK_PATH,
    compile_methylation_csv,
    horvath_age_transform,
    load_horvath_clock,
    parse_methylation_csv,
    score_horvath_clock,
)

__all__ = [
    "HORVATH_CLOCK_PATH",
    "compile_methylation_csv",
    "horvath_age_transform",
    "load_horvath_clock",
    "parse_methylation_csv",
    "score_horvath_clock",
]
