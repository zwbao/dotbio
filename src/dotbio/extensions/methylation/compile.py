"""Methylation array → .bio bundle compiler.

Pipeline:
    csv (probe_id, beta_value, sample_id)
       │
       ▼  parse_methylation_csv
    list[probe_fact]  (kind="methylation_probe")
       │
       ▼  score_horvath_clock
    epigenetic_age (years), evidence list of (probe_id, beta, coef, contribution)
       │
       ▼  bundle.write_fact / write_commit / write_view
    patient.bio/  facts/  commits/  views/  refs/

The Horvath 2013 clock takes 353 CpG probes' β values, computes a linear
combination (β · coefficient) plus an intercept, and applies a piecewise
transform to produce DNA-methylation age in years.

For Task 10 the 353 coefficients in `rulesets/horvath_clock.json` are
SYNTHETIC but deterministically generated; the intercept and transform are
exactly as published in Horvath (2013) Genome Biology 14:R115.

Bundle shape after compilation
------------------------------
- facts/        one fact per probe: {kind: methylation_probe, probe_id, beta, sample_id, platform}
- commits/      one commit with a single epigenetic-age claim
- views/        epigenetic-age.md  (the "view" specified by the SPEC)
- refs/HEAD     points at the commit
- manifest.json carries subject + active_rulesets + view summaries
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import math
import shutil
import uuid
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

from ... import SCHEMA  # noqa: F401  (re-exported for parity with cli)
from ...bundle import Bundle
from ...engine import Claim


# ---- Ruleset loading ---------------------------------------------------


HORVATH_CLOCK_PATH = (
    resources.files("dotbio.extensions.methylation.rulesets")
    .joinpath("horvath_clock.json")
)


def load_horvath_clock(path: Path | str | None = None) -> dict[str, Any]:
    """Load the Horvath 2013 clock ruleset (or any compatible JSON)."""
    if path is None:
        text = HORVATH_CLOCK_PATH.read_text()
    else:
        text = Path(path).read_text()
    rs = json.loads(text)
    # Minimal schema check
    for required in ("name", "version", "intercept", "probes", "transform"):
        if required not in rs:
            raise ValueError(f"horvath ruleset missing field: {required}")
    return rs


# ---- CSV → facts -------------------------------------------------------


def parse_methylation_csv(
    csv_path: Path | str,
    *,
    platform: str = "Illumina HumanMethylation450",
) -> tuple[str, list[dict[str, Any]]]:
    """Parse a methylation array CSV.

    Expected columns: ``probe_id, beta_value, sample_id``.
    Returns (sample_id, list_of_probe_facts).

    Each fact is a dict with kind=methylation_probe and the β value clamped
    to [0.0, 1.0] (rejecting silently malformed rows).
    """
    csv_path = Path(csv_path)
    facts: list[dict[str, Any]] = []
    sample_ids: set[str] = set()

    with csv_path.open(newline="") as fh:
        reader = csv.DictReader(fh)
        required = {"probe_id", "beta_value", "sample_id"}
        if reader.fieldnames is None or not required.issubset(reader.fieldnames):
            missing = required - set(reader.fieldnames or [])
            raise ValueError(
                f"methylation CSV missing required columns: {sorted(missing)}"
            )
        for row in reader:
            probe_id = (row.get("probe_id") or "").strip()
            sample_id = (row.get("sample_id") or "").strip()
            beta_raw = (row.get("beta_value") or "").strip()
            if not probe_id or not sample_id or not beta_raw:
                continue
            try:
                beta = float(beta_raw)
            except ValueError:
                continue
            if not (0.0 <= beta <= 1.0) or math.isnan(beta):
                # β values must be in [0, 1]; skip out-of-range probes
                continue
            sample_ids.add(sample_id)
            facts.append({
                "kind": "methylation_probe",
                "probe_id": probe_id,
                "beta": beta,
                "sample_id": sample_id,
                "platform": platform,
            })

    if not facts:
        raise ValueError(f"no usable methylation rows in {csv_path}")
    if len(sample_ids) != 1:
        raise ValueError(
            f"expected exactly one sample_id in {csv_path}, got {sorted(sample_ids)}"
        )
    return sample_ids.pop(), facts


# ---- Horvath scoring ---------------------------------------------------


def horvath_age_transform(linear_score: float, *, adult_age: float = 20.0) -> float:
    """Horvath 2013 piecewise age transform.

    F(x) = (1+adult_age)*exp(x) - 1   if x < 0
         = (1+adult_age)*x + adult_age otherwise

    where x = intercept + Σ β_i · coef_i over the clock probes.
    """
    if linear_score < 0:
        return (1.0 + adult_age) * math.exp(linear_score) - 1.0
    return (1.0 + adult_age) * linear_score + adult_age


def score_horvath_clock(
    probe_facts: Iterable[tuple[str, dict[str, Any]]],
    ruleset: dict[str, Any],
) -> dict[str, Any]:
    """Compute the Horvath epigenetic age from probe (hash, fact) pairs.

    Returns a dict with:
      - epigenetic_age (float, years)
      - linear_score   (intercept + Σ β·coef, before age transform)
      - intercept
      - n_probes_in_clock     (size of the ruleset)
      - n_probes_used         (probes that matched the clock)
      - n_probes_missing      (clock probes absent from input)
      - evidence              [{probe_id, beta, coef, contribution, fact_hash}, …]
    """
    intercept = float(ruleset["intercept"])
    adult_age = float(ruleset.get("adult_age", 20.0))
    coef_table: dict[str, float] = {p: float(c) for p, c in ruleset["probes"].items()}

    # Build a lookup probe_id -> (hash, fact)
    probe_index: dict[str, tuple[str, dict[str, Any]]] = {}
    for h, f in probe_facts:
        if f.get("kind") != "methylation_probe":
            continue
        pid = f.get("probe_id")
        if pid:
            probe_index[pid] = (h, f)

    used: list[dict[str, Any]] = []
    score = intercept
    for probe_id, coef in coef_table.items():
        hit = probe_index.get(probe_id)
        if hit is None:
            continue
        h, f = hit
        beta = float(f["beta"])
        contribution = beta * coef
        score += contribution
        used.append({
            "probe_id": probe_id,
            "beta": beta,
            "coef": coef,
            "contribution": contribution,
            "fact_hash": h,
        })

    age = horvath_age_transform(score, adult_age=adult_age)

    return {
        "epigenetic_age": age,
        "linear_score": score,
        "intercept": intercept,
        "n_probes_in_clock": len(coef_table),
        "n_probes_used": len(used),
        "n_probes_missing": len(coef_table) - len(used),
        "evidence": used,
    }


# ---- View renderer -----------------------------------------------------


def render_epigenetic_age_view(
    claim: dict[str, Any],
    *,
    sample_id: str,
    score: dict[str, Any],
    ruleset: dict[str, Any],
) -> str:
    """Render `views/epigenetic-age.md` for the methylation bundle.

    Mirrors the structure of `dotbio.views._claim_block` so an LLM (or
    `bio expand`) can resolve the block back to the underlying probe facts.
    """
    age = score["epigenetic_age"]
    n_used = score["n_probes_used"]
    n_total = score["n_probes_in_clock"]
    coverage = 100.0 * n_used / n_total if n_total else 0.0

    # Top-contributing probes (by absolute contribution)
    top = sorted(
        score["evidence"], key=lambda e: abs(e["contribution"]), reverse=True
    )[:5]

    lines: list[str] = []
    lines.append("# Epigenetic age view")
    lines.append("")
    lines.append("> Horvath 2013 DNA-methylation age estimator applied to this")
    lines.append("> subject's Illumina 450K β-values. Each claim below carries a")
    lines.append("> claim_id; resolve via `bio expand <claim_id>` for the full")
    lines.append("> evidence chain back to the contributing CpG probes.")
    lines.append("")
    lines.append(f"### Predicted epigenetic age: {age:.2f} years")
    lines.append("")
    lines.append(
        f"<!-- claim_id: {claim['id']} | level: {claim['level']} | ruleset: {claim['ruleset']} -->"
    )
    lines.append("")
    lines.append(f"- **Sample**: {sample_id}")
    lines.append(f"- **Linear score (x)**: {score['linear_score']:.6f}")
    lines.append(f"- **Intercept**: {score['intercept']:.6f}")
    lines.append(
        f"- **Probe coverage**: {n_used}/{n_total} clock probes "
        f"({coverage:.1f}%)"
    )
    lines.append(f"- **Derivation**: {claim['derivation']}")
    lines.append(f"- **Ruleset**: {claim['ruleset']}")
    if ruleset.get("source"):
        lines.append(f"- **Source**: {ruleset['source']}")
    lines.append("")
    lines.append("## Top contributing probes (by |β·coef|)")
    lines.append("")
    lines.append("| probe_id | β | coefficient | contribution |")
    lines.append("|---|---|---|---|")
    for ev in top:
        lines.append(
            f"| {ev['probe_id']} | {ev['beta']:.4f} | {ev['coef']:+.6f} | "
            f"{ev['contribution']:+.6f} |"
        )
    lines.append("")
    lines.append(f"- **Targets**: {len(score['evidence'])} probe facts "
                 "(see commit for full hash list)")
    lines.append("")
    return "\n".join(lines).rstrip() + "\n"


# ---- Compile entry point -----------------------------------------------


def _now_iso() -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _subject_id_from_sample(sample_id: str) -> str:
    return "subject:" + uuid.uuid5(uuid.NAMESPACE_OID, sample_id).hex[:12]


def compile_methylation_csv(
    csv_path: Path | str,
    out: Path | str,
    *,
    ruleset_path: Path | str | None = None,
    platform: str = "Illumina HumanMethylation450",
    subject: str | None = None,
    force: bool = False,
) -> Bundle:
    """Compile a methylation CSV into a `.bio` bundle.

    Parameters
    ----------
    csv_path : path
        Input CSV with columns ``probe_id, beta_value, sample_id``.
    out : path
        Output bundle directory (e.g. ``patient.bio``).
    ruleset_path : path, optional
        Override the bundled Horvath clock ruleset.
    platform : str
        Methylation array platform string (default: 450K).
    subject : str, optional
        Opaque subject id; if omitted, derived from sample_id.
    force : bool
        Overwrite an existing output directory.

    Returns
    -------
    Bundle
        The freshly written bundle.
    """
    out_path = Path(out)
    if out_path.exists():
        if not force:
            raise FileExistsError(
                f"refusing to overwrite existing bundle at {out_path}"
            )
        shutil.rmtree(out_path)

    bundle = Bundle(out_path)
    bundle.init()

    sample_id, probe_facts = parse_methylation_csv(csv_path, platform=platform)

    # Write each probe fact through the CAS layer
    facts_with_hashes: list[tuple[str, dict[str, Any]]] = []
    for f in probe_facts:
        h = bundle.write_fact(f)
        facts_with_hashes.append((h, f))

    ruleset = load_horvath_clock(ruleset_path)
    score = score_horvath_clock(facts_with_hashes, ruleset)

    name_at_v = f"{ruleset['name']}@{ruleset['version']}"
    targets = sorted(ev["fact_hash"] for ev in score["evidence"])
    age = score["epigenetic_age"]

    derivation = (
        f"Horvath 2013 epigenetic clock applied to {score['n_probes_used']}/"
        f"{score['n_probes_in_clock']} CpG probes "
        f"(intercept={score['intercept']:.4f}, "
        f"linear_score={score['linear_score']:.4f}) → "
        f"piecewise transform → DNAm age {age:.2f} y "
        f"[{name_at_v}]"
    )
    claim = Claim(
        claim=(
            f"Predicted epigenetic age (Horvath 2013): {age:.2f} years "
            f"for sample {sample_id}"
        ),
        targets=targets,
        level="epigenetic_age",
        ruleset=name_at_v,
        derivation=derivation,
        guideline=None,
        extras={
            "epigenetic_age": age,
            "linear_score": score["linear_score"],
            "intercept": score["intercept"],
            "n_probes_used": score["n_probes_used"],
            "n_probes_in_clock": score["n_probes_in_clock"],
            "platform": platform,
            "sample_id": sample_id,
        },
    ).to_dict()

    commit_id = _now_iso()
    commit = {
        "id": commit_id,
        "parent": None,
        "created": commit_id,
        "rulesets": [name_at_v],
        "claims": [claim],
    }
    bundle.write_commit(commit)
    bundle.write_ref("HEAD", commit_id)
    bundle.write_ref("stable", commit_id)

    view_text = render_epigenetic_age_view(
        claim, sample_id=sample_id, score=score, ruleset=ruleset
    )
    bundle.write_view("epigenetic-age", view_text)

    bundle.write_manifest({
        "subject": subject or _subject_id_from_sample(sample_id),
        "created": commit_id,
        "modality": "methylation",
        "platform": platform,
        "refs": bundle.list_refs(),
        "views": [{
            "name": "epigenetic-age",
            "title": "Epigenetic age (Horvath 2013)",
            "scope": "epigenetic-age",
            "path": "views/epigenetic-age.md",
            "claim_count": 1,
            "est_tokens": max(1, len(view_text) // 4),
        }],
        "active_rulesets": [{
            "name": ruleset["name"],
            "version": ruleset["version"],
            "type": ruleset.get("type"),
            "source_url": ruleset.get("url"),
            "source": ruleset.get("source"),
            "license": ruleset.get("license"),
        }],
        "scopes": {
            "methylation_probe_count": len(probe_facts),
            "clock_probes_used": score["n_probes_used"],
            "clock_probes_in_ruleset": score["n_probes_in_clock"],
        },
        "claim_count": 1,
    })

    return bundle
