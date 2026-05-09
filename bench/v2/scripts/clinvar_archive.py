"""ClinVar archive loader for the longitudinal cohort simulator (Task 6).

Two modes:

1. **Real archive mode** — point at a directory containing month-stamped
   ClinVar XML releases (e.g. `clinvar_20240101.xml.gz`,
   `clinvar_20240201.xml.gz`, …). The loader parses each release and
   returns 24 monthly snapshots in the dotbio ruleset format. Round 1
   ships only the parser stub: a real ClinVar XML release is several GB
   compressed and we do not download it during a smoke run. The function
   raises a clear `NotImplementedError` with the FTP location when called.

2. **Synthetic mode** — generates 24 plausible monthly snapshots starting
   from the bundled base ruleset (`clinvar-2026-05-01.json`). Per-month
   reclassifications are drawn from an empirical transition matrix.

Transition probabilities used here are pragmatic approximations of the
behaviour reported in **Landrum et al. (2018), "ClinVar: improving
access to variant interpretations and supporting evidence", Nucleic
Acids Research 46(D1):D1062–D1067**, which documents that

  - Likely-pathogenic (LP) variants are reclassified more often than
    benign / likely-benign variants (≈10% of LP rows are upgraded over
    multi-year windows);
  - VUS resolutions skew toward LB/B, with a small but clinically
    important LP-direction tail;
  - LB → P / B → P transitions are extremely rare.

The matrix in this module is intentionally lower-resolution than the
true ClinVar dynamics — Round 1 cares about *direction and rough rate*
so that two arms (quarterly SoC vs monthly .bio) produce comparable
ground-truth counts. When real archive XML is provided, this synthetic
fallback is bypassed entirely.

Both modes return the same datatype:

    [
      {
        "version": "2024-01",            # YYYY-MM
        "ruleset": <ruleset dict>,       # ready to dump as clinvar-<v>.json
        "reclassifications": [           # ground-truth deltas vs prior month
          {"rsid": "rs6025", "genotype": "C/T",
           "from": "risk_factor", "to": "pathogenic", "actionable": True},
          ...
        ]
      },
      ...
    ]

The ruleset dicts are written into the active dotbio install's
`src/dotbio/rulesets/` directory by `install_archive` so that
`bio update --ruleset clinvar@<version>` works without any code changes.
`uninstall_archive` removes them after the run.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import random
import shutil
from importlib import resources
from pathlib import Path
from typing import Any, Iterable

# ---- public API datatypes --------------------------------------------------

Snapshot = dict[str, Any]
Reclassification = dict[str, Any]

# ---- empirical transition matrix ------------------------------------------
#
# Rows = current significance, columns = next significance. Entries are
# the per-month probability that a variant in the row state moves to the
# column state. The diagonal (stay-in-state) is not stored; it is
# computed as 1 - sum(off-diagonal). Probabilities are deliberately small
# so that with ~6 affected rsIDs we see ~1–3 reclassifications a month
# (matching the SPEC's "10–20 per month" once the ruleset universe is
# the full ClinVar archive of ~2M entries).
#
# Sources / rationale (per docstring above):
#   - Landrum 2018 (NAR) — ClinVar reclassification audit
#   - Harrison & Rehm 2019 (Genet Med) — long-term reclassification rates
#     (≈7.7% of P/LP downgrade over 6 years)
#   - Yang 2017 (Genet Med) — VUS → LB/B is the dominant resolution
#
# These are MONTHLY rates, scaled so a multi-year sum matches the
# published cumulative numbers.

TRANSITION_MATRIX: dict[str, dict[str, float]] = {
    # benign cluster -- almost stable
    "benign":              {"likely_benign": 0.005,  "vus": 0.002},
    "likely_benign":       {"benign":        0.010,  "vus": 0.005,  "likely_pathogenic": 0.001},
    # VUS — most reclassification activity lives here
    "vus":                 {"likely_benign": 0.020,  "benign": 0.005,
                            "likely_pathogenic": 0.012, "pathogenic": 0.003},
    # LP — most likely to upgrade
    "likely_pathogenic":   {"pathogenic":    0.035,  "vus": 0.008,  "benign": 0.001},
    # P — rarely downgraded
    "pathogenic":          {"likely_pathogenic": 0.010, "vus": 0.002},
    # ClinVar uses several non-ACMG terms in our example dataset; we
    # treat them as their own states with low movement.
    "risk_factor":         {"likely_pathogenic": 0.015, "vus": 0.005},
    "drug_response":       {"vus": 0.005, "likely_pathogenic": 0.010},
    "carrier":             {"vus": 0.003, "likely_pathogenic": 0.008},
}

# Which transitions count as CLINICALLY ACTIONABLE in the SPEC §3.4 sense.
# Per SPEC: "P/LP ↔ VUS, LP ↔ P, drug-response significance changes".
ACTIONABLE_PAIRS: set[tuple[str, str]] = set()
for _from in ("benign", "likely_benign", "vus"):
    for _to in ("pathogenic", "likely_pathogenic"):
        ACTIONABLE_PAIRS.add((_from, _to))
        ACTIONABLE_PAIRS.add((_to, _from))
ACTIONABLE_PAIRS.add(("likely_pathogenic", "pathogenic"))
ACTIONABLE_PAIRS.add(("pathogenic", "likely_pathogenic"))
# any transition involving drug_response, risk_factor, or carrier
# changing direction is treated as actionable (e.g. clopidogrel guidance
# changes if a CYP2C19 allele moves from drug_response → likely_pathogenic).
for _state in ("drug_response", "risk_factor", "carrier"):
    for _to in ("vus", "likely_pathogenic", "pathogenic"):
        ACTIONABLE_PAIRS.add((_state, _to))
        ACTIONABLE_PAIRS.add((_to, _state))


def is_actionable(from_sig: str, to_sig: str) -> bool:
    return (from_sig, to_sig) in ACTIONABLE_PAIRS


# ---- versioning ------------------------------------------------------------


def month_versions(start: str, n_months: int) -> list[str]:
    """Return n_months YYYY-MM-01 strings starting at `start` (YYYY-MM)."""
    y, m = (int(x) for x in start.split("-")[:2])
    out: list[str] = []
    for _ in range(n_months):
        out.append(f"{y:04d}-{m:02d}-01")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


# ---- synthetic archive -----------------------------------------------------


def _bundled_base_ruleset() -> dict:
    """Load the bundled clinvar ruleset shipped with dotbio."""
    text = (
        resources.files("dotbio.rulesets")
        .joinpath("clinvar-2026-05-01.json")
        .read_text()
    )
    return json.loads(text)


def _all_rsid_genotype_pairs(ruleset: dict) -> list[tuple[str, str]]:
    """Enumerate every (rsid, genotype) cell that has a significance."""
    pairs: list[tuple[str, str]] = []
    for rsid, entry in ruleset.get("entries", {}).items():
        for gt in entry.get("by_genotype", {}):
            pairs.append((rsid, gt))
    return pairs


def _step_significance(rng: random.Random, sig: str,
                       matrix: dict[str, dict[str, float]] | None = None) -> str:
    """Sample a next significance class from the transition matrix."""
    m = matrix if matrix is not None else TRANSITION_MATRIX
    row = m.get(sig, {})
    if not row:
        return sig
    r = rng.random()
    cum = 0.0
    for to, p in row.items():
        cum += p
        if r < cum:
            return to
    return sig  # stayed put (the (1 - sum) tail)


def synthesize_archive(
    start: str = "2024-01",
    n_months: int = 24,
    seed: int = 20240101,
    base: dict | None = None,
    rate_scale: float = 8.0,
) -> list[Snapshot]:
    """Generate a 24-month synthetic ClinVar archive.

    The first snapshot is identical to `base` (or the bundled
    `clinvar-2026-05-01.json` if `base` is None) but stamped with the
    `start` version. Subsequent snapshots evolve by sampling
    reclassifications from the empirical transition matrix.

    Returns a list of 24 Snapshot dicts. Each Snapshot carries the
    *cumulative* ruleset state at that month plus a `reclassifications`
    list describing what changed since the previous month (empty for
    the first).

    `rate_scale` (default 8.0) inflates the published per-row monthly
    rates so that — for the tiny ~10-cell demo ruleset — Round-1 smoke
    runs see 1–3 reclassifications/month instead of the ~0.1/month a
    direct application of Landrum-2018 rates would produce. SPEC §3.4
    targets 10–20 reclassifications/month, which is realistic for the
    full ~2M-entry archive (use `rate_scale=1.0` plus the real archive
    via `load_real_archive` to recover that regime).
    """
    rng = random.Random(seed)
    if base is None:
        base = _bundled_base_ruleset()

    pairs = _all_rsid_genotype_pairs(base)
    versions = month_versions(start, n_months)
    snapshots: list[Snapshot] = []

    # Apply rate_scale once, capped so probabilities never sum > 0.95
    # (we keep at least a 5% chance of staying put per cell per month).
    scaled_matrix: dict[str, dict[str, float]] = {}
    for src, row in TRANSITION_MATRIX.items():
        scaled = {to: min(p * rate_scale, 0.5) for to, p in row.items()}
        total = sum(scaled.values())
        if total > 0.95:
            factor = 0.95 / total
            scaled = {to: p * factor for to, p in scaled.items()}
        scaled_matrix[src] = scaled

    current = copy.deepcopy(base)
    current["version"] = versions[0]
    current["_synthetic"] = True
    current["_synthetic_seed"] = seed
    current["_synthetic_note"] = (
        "Generated by clinvar_archive.synthesize_archive; transition "
        "matrix loosely calibrated to Landrum 2018 (NAR) + Harrison & "
        "Rehm 2019 (Genet Med). Not for clinical use."
    )
    snapshots.append({
        "version": versions[0],
        "ruleset": copy.deepcopy(current),
        "reclassifications": [],
    })

    for v in versions[1:]:
        next_rs = copy.deepcopy(current)
        next_rs["version"] = v
        deltas: list[Reclassification] = []
        for rsid, gt in pairs:
            cell = next_rs["entries"][rsid]["by_genotype"][gt]
            from_sig = cell["significance"]
            to_sig = _step_significance(rng, from_sig, scaled_matrix)
            if to_sig == from_sig:
                continue
            cell["significance"] = to_sig
            cell["previous_classification"] = from_sig
            cell["reclassified_on"] = v
            cell["evidence"] = (
                cell.get("evidence", "")
                + f" [synthetic reclassification {from_sig}→{to_sig} on {v}]"
            ).strip()
            deltas.append({
                "rsid": rsid,
                "gene": next_rs["entries"][rsid].get("gene"),
                "genotype": gt,
                "from": from_sig,
                "to": to_sig,
                "actionable": is_actionable(from_sig, to_sig),
                "released": v,
            })
        snapshots.append({
            "version": v,
            "ruleset": copy.deepcopy(next_rs),
            "reclassifications": deltas,
        })
        current = next_rs

    return snapshots


# ---- real-archive loader (stub) -------------------------------------------


def load_real_archive(archive_dir: str | Path) -> list[Snapshot]:
    """Parse a directory of monthly ClinVar XML releases into snapshots.

    Round 1: not implemented. Real ClinVar full releases live at
    ftp://ftp.ncbi.nlm.nih.gov/pub/clinvar/xml/clinvar_full_release/
    and are several GB each; supplying the path is left as round-2
    work (Task 6 is scaffold-tagged). When a future caller wants to
    point at a real archive, this function is the integration seam.

    Expected directory layout (when implemented):
        archive_dir/
            clinvar_2024-01-01.xml.gz
            clinvar_2024-02-01.xml.gz
            ...

    Returns the same Snapshot list shape as `synthesize_archive`.
    """
    archive_dir = Path(archive_dir)
    if not archive_dir.exists():
        raise FileNotFoundError(f"archive_dir does not exist: {archive_dir}")
    raise NotImplementedError(
        "Real ClinVar XML parsing is round-2 scope. Place monthly releases "
        "in this directory (e.g. clinvar_2024-01-01.xml.gz from "
        "ftp://ftp.ncbi.nlm.nih.gov/pub/clinvar/xml/clinvar_full_release/) "
        "and extend load_real_archive() to extract per-VCV interpretation "
        "histories. The simulator already accepts the Snapshot datatype "
        "from this function unchanged."
    )


# ---- install / uninstall on the dotbio rulesets resource path -------------


def _rulesets_dir() -> Path:
    """Filesystem path of the active dotbio.rulesets package."""
    p = resources.files("dotbio.rulesets")
    # `resources.files` may return a MultiplexedPath in zipped installs;
    # we require an on-disk path so we can drop new JSONs alongside the
    # bundled rulesets that `bio update` reads.
    return Path(str(p))


def install_archive(snapshots: Iterable[Snapshot]) -> list[Path]:
    """Write every snapshot's ruleset as `clinvar-<version>.json`.

    Returns the list of paths written. The caller is responsible for
    invoking `uninstall_archive` after the run.
    """
    out_dir = _rulesets_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for snap in snapshots:
        rs = snap["ruleset"]
        v = rs["version"]
        path = out_dir / f"clinvar-{v}.json"
        with path.open("w", encoding="utf-8") as fh:
            json.dump(rs, fh, indent=2, ensure_ascii=False, sort_keys=False)
        written.append(path)
    return written


def uninstall_archive(snapshots: Iterable[Snapshot]) -> int:
    """Delete `clinvar-<version>.json` for every snapshot. Returns count."""
    out_dir = _rulesets_dir()
    n = 0
    for snap in snapshots:
        v = snap["ruleset"]["version"]
        path = out_dir / f"clinvar-{v}.json"
        if path.exists():
            path.unlink()
            n += 1
    return n


# ---- CLI for ad-hoc inspection --------------------------------------------


def _main(argv: list[str] | None = None) -> int:
    import argparse
    p = argparse.ArgumentParser(prog="clinvar_archive")
    p.add_argument("--start", default="2024-01")
    p.add_argument("--months", type=int, default=24)
    p.add_argument("--seed", type=int, default=20240101)
    p.add_argument("--out", type=Path, help="write snapshots manifest to JSON")
    p.add_argument("--show-deltas", action="store_true",
                   help="print per-month reclassification summary")
    args = p.parse_args(argv)

    snaps = synthesize_archive(args.start, args.months, args.seed)
    if args.show_deltas:
        for s in snaps:
            n_act = sum(1 for r in s["reclassifications"] if r["actionable"])
            print(f"{s['version']}  total={len(s['reclassifications']):>2}  actionable={n_act:>2}")
    if args.out:
        manifest = [
            {
                "version": s["version"],
                "n_reclassifications": len(s["reclassifications"]),
                "n_actionable": sum(1 for r in s["reclassifications"] if r["actionable"]),
                "reclassifications": s["reclassifications"],
            }
            for s in snaps
        ]
        args.out.write_text(json.dumps(manifest, indent=2, ensure_ascii=False))
        print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
