"""View renderers — turn claim lists into LLM-friendly Markdown.

Each rendered claim block carries an HTML comment with its claim_id so an LLM
(or `bio expand`) can resolve the block back to its commit and from there to
the underlying facts.
"""

from __future__ import annotations

from typing import Any


def _claim_block(claim: dict[str, Any]) -> str:
    extras = {k: v for k, v in claim.items() if k not in {"id", "claim", "targets", "level", "ruleset", "derivation", "guideline"}}
    lines = [
        f"### {claim['claim']}",
        "",
        f"<!-- claim_id: {claim['id']} | level: {claim['level']} | ruleset: {claim['ruleset']} -->",
        "",
    ]
    if "evidence" in extras and extras["evidence"]:
        lines.append(f"- **Evidence**: {extras['evidence']}")
    if "review_status" in extras and extras["review_status"]:
        lines.append(f"- **Review status**: {extras['review_status']}")
    if "context" in extras and extras["context"]:
        lines.append(f"- **Context**: {extras['context']}")
    if "previous_classification" in extras:
        lines.append(
            f"- **Reclassified**: {extras['previous_classification']} → "
            f"{extras.get('significance', claim['claim'])} on {extras.get('reclassified_on', 'unknown date')}"
        )
    lines.append(f"- **Derivation**: {claim['derivation']}")
    if claim.get("guideline"):
        lines.append(f"- **Guideline**: {claim['guideline']}")
    lines.append(f"- **Targets**: {', '.join(claim['targets'])}")
    lines.append("")
    return "\n".join(lines)


def _filter_claims(claims: list[dict], predicate) -> list[dict]:
    return [c for c in claims if predicate(c)]


def render_pgx_view(claims: list[dict]) -> str:
    drug_claims = _filter_claims(claims, lambda c: c["level"] == "clinical_decision")
    phenotype_claims = _filter_claims(claims, lambda c: c["level"] == "phenotype")
    if not (drug_claims or phenotype_claims):
        return "# Pharmacogenomic view\n\n_No PGx phenotypes called for this subject._\n"

    out = ["# Pharmacogenomic view", ""]
    out.append("> Pharmacogenomic phenotype calls and per-drug guidance derived from")
    out.append("> the active PharmCAT-style ruleset. Each claim below carries a")
    out.append("> claim_id; resolve via `bio expand <claim_id>` for full evidence.")
    out.append("")

    if phenotype_claims:
        out.append("## Phenotypes")
        out.append("")
        for c in phenotype_claims:
            out.append(_claim_block(c))

    if drug_claims:
        out.append("## Drug guidance")
        out.append("")
        # Group by gene if available
        for c in drug_claims:
            out.append(_claim_block(c))

    return "\n".join(out).rstrip() + "\n"


def render_germline_view(claims: list[dict]) -> str:
    """Germline clinical claims excluding PGx (which has its own view)."""
    germline = _filter_claims(claims, lambda c: c["ruleset"].startswith("clinvar@"))
    germline = [c for c in germline if c.get("significance") not in {"carrier"}]
    if not germline:
        return "# Germline clinical view\n\n_No germline clinical findings for this subject._\n"

    out = ["# Germline clinical view", ""]
    out.append("> Germline variants of clinical significance, not including")
    out.append("> pharmacogenomics (see `pgx.md`) or carrier status (see `carrier.md`).")
    out.append("")
    for c in germline:
        out.append(_claim_block(c))

    return "\n".join(out).rstrip() + "\n"


def render_carrier_view(claims: list[dict]) -> str:
    carriers = _filter_claims(claims, lambda c: c.get("significance") == "carrier")
    if not carriers:
        return "# Carrier-status view\n\n_No carrier-status findings for this subject._\n"

    out = ["# Carrier-status view", ""]
    out.append("> Carrier-status findings — heterozygous pathogenic variants where")
    out.append("> the subject is asymptomatic but reproductive-partner screening")
    out.append("> may be relevant.")
    out.append("")
    for c in carriers:
        out.append(_claim_block(c))

    return "\n".join(out).rstrip() + "\n"


def render_somatic_view(claims: list[dict]) -> str:
    somatic = _filter_claims(claims, lambda c: c["ruleset"].startswith("oncokb@"))
    if not somatic:
        return "# Somatic-oncology view\n\n_No somatic oncology findings for this subject._\n"

    out = ["# Somatic-oncology view", ""]
    out.append("> Somatic alterations annotated against an OncoKB-style ruleset.")
    out.append("> These represent tumor-only findings; germline interpretation is")
    out.append("> in `germline-clinical.md`.")
    out.append("")
    for c in somatic:
        out.append(_claim_block(c))

    return "\n".join(out).rstrip() + "\n"


VIEW_REGISTRY = {
    "pgx": ("Pharmacogenomic", render_pgx_view),
    "germline-clinical": ("Germline clinical", render_germline_view),
    "carrier": ("Carrier status", render_carrier_view),
    "somatic": ("Somatic oncology", render_somatic_view),
}
