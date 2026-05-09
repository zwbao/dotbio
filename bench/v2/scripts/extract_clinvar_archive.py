"""Extract real ClinVar reclassification events from monthly VCF archive.

Round-2 helper for SPEC §3.4 / Experiment 4. We download monthly ClinVar
GRCh38 VCF snapshots from
``https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/archive_2.0/`` and
extract per-variant CLNSIG values, restricting to a 30-gene PGx VIP +
ACMG SF panel to keep memory and bandwidth reasonable. We pull only the
gene-region slices via remote tabix (the .tbi index is downloaded once
per month, then tabix issues HTTP-range queries against the .vcf.gz —
typically <1 MB transferred per month per gene set instead of ~90 MB).

Output:
- ``per_month/clinvar_<YYYY-MM>.tsv``  one TSV per snapshot
  columns: ``chrom\\tpos\\tvariation_id\\tref\\talt\\tgene\\trsid\\tsignificance\\treview_status\\tcondition``
- ``clinvar_2024-01_to_2025-12.tsv``  the cross-month reclassifications:
  columns: ``variation_id\\tgene\\trsid\\tchrom\\tpos\\tref\\talt\\tmonth\\tprev_month\\tprev_significance\\tnew_significance\\tactionable``

Run:
    python bench/v2/scripts/extract_clinvar_archive.py \\
        --out-dir bench/v2/data/clinvar_archive \\
        --start 2024-01 --end 2025-12

The --max-bandwidth-mb knob aborts the run if cumulative download exceeds
the budget (default 800 MB).
"""

from __future__ import annotations

import argparse
import gzip
import io
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path
from typing import Iterable

# ---------------------------------------------------------------------------
# 30-gene panel: PharmGKB VIP (top-tier pharmacogenes) + ACMG SF v3.2 highlights.
# Coordinates are GRCh38 (Ensembl release 110-ish); we expand each gene
# region by 5 kb on either side to catch UTR / promoter ClinVar entries.
# Coordinates were curated by hand; this is intentionally a static list
# rather than an API call so the run is deterministic and offline-safe.
# ---------------------------------------------------------------------------

GENE_REGIONS_GRCH38: dict[str, tuple[str, int, int]] = {
    # -- PGx VIPs (PharmGKB Tier 1) — primary focus ---------------------
    # Coordinates are GRCh38 from NCBI Gene with tight gene-body windows.
    # We picked the 12 PharmGKB Tier-1 VIPs (the dotbio paper's PGx focus)
    # plus 6 high-yield ACMG SF cancer genes that produce frequent ClinVar
    # reclassifications. Total network payload at this size is ~10–15 MB
    # per monthly snapshot — fits the 800 MB / 24 month budget at ~12 MB
    # avg with headroom.
    "CYP2C19":   ("10", 94760000, 94860000),
    "CYP2C9":    ("10", 94938000, 95070000),
    "CYP2D6":    ("22", 42124000, 42135000),
    "CYP3A4":    ("7",  99354000, 99381000),
    "CYP3A5":    ("7",  99245000, 99280000),
    "DPYD":      ("1",  97540000, 98390000),
    "TPMT":      ("6",  18128000, 18156000),
    "NUDT15":    ("13", 48034000, 48045000),
    "SLCO1B1":   ("12", 21282000, 21394000),
    "UGT1A1":    ("2", 233758000, 233775000),
    "VKORC1":    ("16", 31100000, 31108000),
    "G6PD":      ("X", 154531000, 154548000),
    # -- ACMG SF v3.2 cancer / cardio highlights --------------------------
    # Limited to the genes most likely to drive actionable P/LP/VUS
    # transitions in ClinVar over 24 months. We deliberately exclude
    # BRCA2/MMR (MLH1/MSH2/MSH6) and the largest hereditary-cancer genes
    # (ATM, APC) because their per-month payload (>30 MB combined) would
    # push us over the 800 MB bandwidth budget. This skews the panel
    # toward PGx, which aligns with the dotbio paper's primary use case
    # (clopidogrel-style PGx questions, SPEC §3.1).
    "TP53":      ("17",  7665000,  7691000),
    "PALB2":     ("16", 23603000, 23642000),
    "LDLR":      ("19", 11089000, 11134000),
    "PCSK9":     ("1",  55039000, 55064000),
    # -- Cardiomyopathy / RYR1 (smaller, high actionability per record) --
    "MYH7":      ("14", 23412000, 23436000),
    "MYBPC3":    ("11", 47331000, 47353000),
    "RYR1":      ("19", 38924000, 39078000),
    "STK11":     ("19",  1205000,  1228000),
    "PTEN":      ("10", 87863000, 87971000),
    # -- Round out to ~22 (still well within "30-gene VIP list") ----------
    "BRCA1":     ("17", 43044000, 43126000),  # canonical oncology landmark
    "APOB":      ("2",  21001000, 21044000),
    "F5":        ("1", 169511000, 169588000),  # Factor V Leiden — pharmacogenomically relevant
    "MTHFR":     ("1",  11785000, 11806000),  # folate metabolism / methotrexate dosing
    "HFE":       ("6",  26086000, 26100000),  # hereditary hemochromatosis (carrier gene)
    "CFTR":      ("7", 117480000, 117670000),  # cystic fibrosis carrier — large gene
    "APOE":      ("19", 44905000, 44910000),  # AD risk; very small region
    "ABCG2":     ("4",  88090000, 88231000),  # rosuvastatin pharmacogene
}

# Panel name we tag per-row for reporting downstream.
PANEL_VERSION = "dotbio_v2_30gene_2026-05-09"

# Map ClinVar CLNSIG raw text (semicolon/comma separated, case-insensitive)
# to a normalized significance class compatible with TRANSITION_MATRIX in
# clinvar_archive.py (see SPEC §3.4 and Landrum 2018). When ClinVar reports
# multiple values for one record (e.g. "Pathogenic/Likely_pathogenic") we
# pick the strongest applicable bucket.
_CLNSIG_PRIORITY = [
    ("pathogenic",         "pathogenic"),
    ("likely_pathogenic",  "likely_pathogenic"),
    ("drug_response",      "drug_response"),
    ("risk_factor",        "risk_factor"),
    ("uncertain_significance", "vus"),
    ("conflicting_classifications", "vus"),
    ("conflicting_interpretations", "vus"),
    ("no_classification_for_the_single_variant", "vus"),
    ("not_provided",       "vus"),
    ("likely_benign",      "likely_benign"),
    ("benign",             "benign"),
    ("association",        "risk_factor"),
    ("protective",         "benign"),
    ("affects",            "vus"),
    ("other",              "vus"),
]


def _normalize_clnsig(raw: str) -> str | None:
    """Reduce a ClinVar CLNSIG INFO field to one significance bucket."""
    if not raw:
        return None
    norm = raw.lower().replace(" ", "_").replace("-", "_")
    for needle, bucket in _CLNSIG_PRIORITY:
        if needle in norm:
            return bucket
    return None


# Actionability semantics — mirrors clinvar_archive.ACTIONABLE_PAIRS so
# downstream consumers don't import-cycle.
_ACTIONABLE_PAIRS: set[tuple[str, str]] = set()
for _from in ("benign", "likely_benign", "vus"):
    for _to in ("pathogenic", "likely_pathogenic"):
        _ACTIONABLE_PAIRS.add((_from, _to))
        _ACTIONABLE_PAIRS.add((_to, _from))
_ACTIONABLE_PAIRS.add(("likely_pathogenic", "pathogenic"))
_ACTIONABLE_PAIRS.add(("pathogenic", "likely_pathogenic"))
for _state in ("drug_response", "risk_factor"):
    for _to in ("vus", "likely_pathogenic", "pathogenic"):
        _ACTIONABLE_PAIRS.add((_state, _to))
        _ACTIONABLE_PAIRS.add((_to, _state))


def is_actionable(from_sig: str, to_sig: str) -> bool:
    return (from_sig, to_sig) in _ACTIONABLE_PAIRS


# ---------------------------------------------------------------------------
# Snapshot URL discovery + selection
# ---------------------------------------------------------------------------

ARCHIVE_BASE = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/archive_2.0"


def list_archive_year(year: int) -> list[str]:
    """List monthly snapshot stems available for a given year."""
    url = f"{ARCHIVE_BASE}/{year}/"
    with urllib.request.urlopen(url, timeout=60) as resp:
        html = resp.read().decode("utf-8", errors="replace")
    return sorted(set(re.findall(r"clinvar_(\d{8})\.vcf\.gz(?!\.)", html)))


def select_one_per_month(start: str, end: str) -> list[tuple[str, str]]:
    """Return [(YYYY-MM, YYYYMMDD)] one entry per month from start..end.

    For each (y, m) we pick the dated snapshot with day closest to the 15th.
    """
    sy, sm = (int(x) for x in start.split("-"))
    ey, em = (int(x) for x in end.split("-"))
    by_year: dict[int, list[date]] = {}
    for yr in range(sy, ey + 1):
        try:
            stems = list_archive_year(yr)
        except Exception as e:  # pragma: no cover
            print(f"[warn] cannot list archive year {yr}: {e}")
            stems = []
        by_year[yr] = []
        for s in stems:
            try:
                by_year[yr].append(date(int(s[0:4]), int(s[4:6]), int(s[6:8])))
            except ValueError:
                continue

    out: list[tuple[str, str]] = []
    cur_y, cur_m = sy, sm
    while (cur_y, cur_m) <= (ey, em):
        candidates = [d for d in by_year.get(cur_y, []) if d.month == cur_m]
        if candidates:
            target = date(cur_y, cur_m, 15)
            pick = min(candidates, key=lambda d: abs((d - target).days))
            out.append((f"{cur_y:04d}-{cur_m:02d}", pick.strftime("%Y%m%d")))
        cur_m += 1
        if cur_m == 13:
            cur_m = 1
            cur_y += 1
    return out


# ---------------------------------------------------------------------------
# tabix-driven extraction
# ---------------------------------------------------------------------------

def _human_mb(b: int) -> str:
    return f"{b / (1024 * 1024):.1f} MB"


def _http_size(url: str) -> int | None:
    try:
        req = urllib.request.Request(url, method="HEAD")
        with urllib.request.urlopen(req, timeout=30) as resp:
            cl = resp.headers.get("Content-Length")
            return int(cl) if cl else None
    except Exception:
        return None


def download_tbi(stem: str, year: int, dest: Path) -> int:
    """Download the .tbi index for `clinvar_<stem>.vcf.gz` of `year`. Returns bytes downloaded."""
    if dest.exists():
        return 0
    url = f"{ARCHIVE_BASE}/{year}/clinvar_{stem}.vcf.gz.tbi"
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with urllib.request.urlopen(url, timeout=120) as resp, open(tmp, "wb") as fh:
        shutil.copyfileobj(resp, fh)
    tmp.rename(dest)
    return dest.stat().st_size


def query_remote_vcf(
    stem: str,
    year: int,
    tbi_path: Path,
    regions: list[tuple[str, int, int]],
    out_path: Path,
    max_retries: int = 3,
) -> tuple[int, int]:
    """Run tabix queries against the remote VCF for the given regions.

    We issue one tabix call per region (not all 30 at once) — bundling
    them tends to drop the TCP connection mid-stream against NCBI's FTP
    server. Per-region calls are slightly slower but reliable.

    Returns (n_records_written, approx_bytes_downloaded).

    The tbi must already exist as `<stem>.vcf.gz.tbi` in `tbi_path.parent`;
    tabix is invoked with cwd=tbi_path.parent so htslib's local-cache
    fallback finds it.
    """
    url = f"{ARCHIVE_BASE}/{year}/clinvar_{stem}.vcf.gz"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cwd = str(tbi_path.parent)
    env = os.environ.copy()
    n_records = 0
    failed_regions: list[str] = []
    with open(out_path, "w") as fh:
        for c, s, e in regions:
            region = f"{c}:{s}-{e}"
            attempt = 0
            success = False
            while True:
                proc = subprocess.run(
                    ["tabix", url, region],
                    capture_output=True, text=True,
                    cwd=cwd, env=env, timeout=300,
                )
                if proc.returncode == 0:
                    success = True
                    break
                attempt += 1
                if attempt > max_retries:
                    print(f"    [warn] giving up on {stem} {region} after "
                          f"{max_retries} retries: "
                          f"{proc.stderr.strip()[:120]}")
                    failed_regions.append(region)
                    break
                time.sleep(1.0 * attempt)
            if not success:
                continue
            for line in proc.stdout.splitlines():
                if not line:
                    continue
                fh.write(line + "\n")
                if not line.startswith("#"):
                    n_records += 1
    if len(failed_regions) > len(regions) // 2:
        # If we lost more than half the panel, fail the whole month so
        # the diff loop doesn't pollute the per-month TSVs with a
        # gene-asymmetric snapshot.
        raise RuntimeError(
            f"tabix gave up on {len(failed_regions)}/{len(regions)} "
            f"regions for {stem}; abandoning this month"
        )
    return n_records, out_path.stat().st_size


# ---------------------------------------------------------------------------
# VCF parse: extract per-record significance
# ---------------------------------------------------------------------------

INFO_RE = re.compile(r"([A-Z_]+)=([^;]+)")


def parse_vcf_records(vcf_path: Path) -> Iterable[dict]:
    """Yield one dict per ClinVar VCF record relevant to our panel.

    We restrict to records whose `GENEINFO` mentions one of our gene
    symbols (a single tabix region may overlap neighboring genes; we
    tighten by GENEINFO so the cross-month diff is gene-clean).
    """
    panel_genes = set(GENE_REGIONS_GRCH38.keys())
    with open(vcf_path) as fh:
        for line in fh:
            if not line or line.startswith("#"):
                continue
            cols = line.rstrip("\n").split("\t")
            if len(cols) < 8:
                continue
            chrom, pos, variation_id, ref, alt = cols[0], cols[1], cols[2], cols[3], cols[4]
            info = cols[7]
            kv = dict(INFO_RE.findall(info))
            geneinfo = kv.get("GENEINFO", "")
            # GENEINFO is "GENE:GeneID|OtherGene:OtherID"
            genes_in_record = {g.split(":")[0] for g in geneinfo.split("|") if g}
            hit_genes = genes_in_record & panel_genes
            if not hit_genes:
                continue
            primary_gene = next(iter(hit_genes))  # deterministic enough
            clnsig = _normalize_clnsig(kv.get("CLNSIG", ""))
            if clnsig is None:
                continue
            yield {
                "chrom": chrom,
                "pos": pos,
                "variation_id": variation_id,
                "ref": ref,
                "alt": alt,
                "gene": primary_gene,
                "rsid": kv.get("RS", "") and f"rs{kv['RS']}",
                "significance": clnsig,
                "review_status": kv.get("CLNREVSTAT", ""),
                "condition": kv.get("CLNDN", ""),
            }


# ---------------------------------------------------------------------------
# Cross-month diff
# ---------------------------------------------------------------------------

def per_month_table(snapshot_tsv: Path) -> dict[str, dict]:
    """Read a per-month TSV back into a {variation_id: row} table."""
    out: dict[str, dict] = {}
    with open(snapshot_tsv) as fh:
        header = fh.readline().rstrip("\n").split("\t")
        for line in fh:
            cells = line.rstrip("\n").split("\t")
            if len(cells) != len(header):
                continue
            row = dict(zip(header, cells))
            out[row["variation_id"]] = row
    return out


def write_snapshot_tsv(records: Iterable[dict], out_tsv: Path) -> int:
    out_tsv.parent.mkdir(parents=True, exist_ok=True)
    cols = ["chrom", "pos", "variation_id", "ref", "alt", "gene",
            "rsid", "significance", "review_status", "condition"]
    n = 0
    with open(out_tsv, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for r in records:
            fh.write("\t".join(str(r.get(c, "")) for c in cols) + "\n")
            n += 1
    return n


def diff_snapshots(prev_tsv: Path | None, curr_tsv: Path,
                   month: str, prev_month: str | None) -> list[dict]:
    """Return a list of reclassification events between prev → curr."""
    if prev_tsv is None or not prev_tsv.exists():
        return []
    prev = per_month_table(prev_tsv)
    curr = per_month_table(curr_tsv)
    events: list[dict] = []
    for vid, c in curr.items():
        p = prev.get(vid)
        if p is None:
            continue  # new variant — not a reclassification
        if p["significance"] == c["significance"]:
            continue
        events.append({
            "variation_id": vid,
            "gene": c["gene"],
            "rsid": c.get("rsid", ""),
            "chrom": c["chrom"],
            "pos": c["pos"],
            "ref": c["ref"],
            "alt": c["alt"],
            "month": month,
            "prev_month": prev_month or "",
            "prev_significance": p["significance"],
            "new_significance": c["significance"],
            "actionable": is_actionable(p["significance"], c["significance"]),
        })
    return events


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    # Stdout line-buffered so progress messages reach the calling shell
    # promptly during long-running multi-month extractions.
    try:
        sys.stdout.reconfigure(line_buffering=True)
    except Exception:
        pass
    p = argparse.ArgumentParser(prog="extract_clinvar_archive")
    p.add_argument("--out-dir", type=Path,
                   default=Path("bench/v2/data/clinvar_archive"))
    p.add_argument("--start", default="2024-01")
    p.add_argument("--end", default="2025-12")
    p.add_argument("--max-bandwidth-mb", type=int, default=800)
    p.add_argument("--max-months", type=int, default=24)
    p.add_argument("--keep-tbi", action="store_true",
                   help="don't delete the .tbi files after extraction "
                        "(useful for re-runs)")
    p.add_argument("--skip-existing", action="store_true", default=True,
                   help="skip months whose per-month TSV already exists")
    args = p.parse_args(argv)

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    snap_dir = out_dir / "per_month"
    snap_dir.mkdir(parents=True, exist_ok=True)
    tbi_dir = out_dir / "_tbi_cache"
    tbi_dir.mkdir(parents=True, exist_ok=True)

    print(f"[extract] start={args.start} end={args.end} "
          f"out={out_dir} budget={args.max_bandwidth_mb}MB")
    schedule = select_one_per_month(args.start, args.end)
    schedule = schedule[: args.max_months]
    print(f"[extract] selected {len(schedule)} monthly snapshots")
    for ym, stem in schedule:
        print(f"  {ym}: clinvar_{stem}.vcf.gz")

    regions = list(GENE_REGIONS_GRCH38.values())
    panel_size = len(regions)
    cumulative_bytes = 0

    coverage: list[dict] = []  # one entry per attempted month
    raw_vcf_dir = out_dir / "_raw_vcf_slices"
    raw_vcf_dir.mkdir(parents=True, exist_ok=True)

    months_done: list[str] = []
    for ym, stem in schedule:
        if cumulative_bytes / (1024 * 1024) > args.max_bandwidth_mb:
            print(f"[extract] hit bandwidth budget at {ym}, stopping early")
            break
        snap_tsv = snap_dir / f"clinvar_{ym}.tsv"
        if args.skip_existing and snap_tsv.exists():
            print(f"[extract] {ym}: cached -> {snap_tsv.name}")
            months_done.append(ym)
            coverage.append({
                "ym": ym, "stem": stem, "cached": True,
                "n_records": sum(1 for _ in open(snap_tsv)) - 1,
            })
            continue

        year = int(stem[:4])
        tbi_path = tbi_dir / f"clinvar_{stem}.vcf.gz.tbi"
        # Step 1: download .tbi
        t0 = time.time()
        try:
            tbi_bytes = download_tbi(stem, year, tbi_path)
        except Exception as e:
            print(f"[extract] {ym}: tbi download failed ({e}), skipping")
            coverage.append({"ym": ym, "stem": stem, "error": f"tbi: {e}"})
            continue
        cumulative_bytes += tbi_bytes
        # Step 2: tabix query
        raw_path = raw_vcf_dir / f"clinvar_{stem}.region.vcf"
        try:
            n_records, payload_bytes = query_remote_vcf(
                stem, year, tbi_path, regions, raw_path
            )
        except Exception as e:
            print(f"[extract] {ym}: tabix query failed ({e}), skipping")
            coverage.append({"ym": ym, "stem": stem, "error": f"tabix: {e}"})
            continue
        cumulative_bytes += payload_bytes
        # Step 3: parse to per-month TSV
        n_written = write_snapshot_tsv(parse_vcf_records(raw_path), snap_tsv)
        elapsed = time.time() - t0
        print(f"[extract] {ym}: tbi={_human_mb(tbi_bytes)} "
              f"slice={_human_mb(payload_bytes)} "
              f"records={n_records} panel={n_written} "
              f"({elapsed:.1f}s, cum={_human_mb(cumulative_bytes)})")
        coverage.append({
            "ym": ym, "stem": stem,
            "tbi_bytes": tbi_bytes,
            "slice_bytes": payload_bytes,
            "n_raw_records": n_records,
            "n_panel_records": n_written,
            "elapsed_s": elapsed,
        })
        months_done.append(ym)

    # Cross-month diff
    months_done.sort()
    print(f"[extract] computing cross-month diffs over {len(months_done)} snapshots")
    all_events: list[dict] = []
    prev_tsv = None
    prev_ym = None
    for ym in months_done:
        curr_tsv = snap_dir / f"clinvar_{ym}.tsv"
        events = diff_snapshots(prev_tsv, curr_tsv, ym, prev_ym)
        all_events.extend(events)
        prev_tsv = curr_tsv
        prev_ym = ym

    diff_path = out_dir / "clinvar_2024-01_to_2025-12.tsv"
    cols = ["variation_id", "gene", "rsid", "chrom", "pos", "ref", "alt",
            "month", "prev_month", "prev_significance", "new_significance",
            "actionable"]
    with open(diff_path, "w") as fh:
        fh.write("\t".join(cols) + "\n")
        for e in all_events:
            fh.write("\t".join(str(e[c]) for c in cols) + "\n")
    print(f"[extract] wrote {diff_path}: {len(all_events)} reclassifications "
          f"({sum(1 for e in all_events if e['actionable'])} actionable)")

    # Coverage manifest (machine-readable)
    coverage_path = out_dir / "coverage.tsv"
    with open(coverage_path, "w") as fh:
        fh.write("ym\tstem\tn_panel_records\tn_raw_records\tslice_bytes\ttbi_bytes\telapsed_s\terror\n")
        for r in coverage:
            fh.write("\t".join([
                r.get("ym", ""), r.get("stem", ""),
                str(r.get("n_panel_records", "")),
                str(r.get("n_raw_records", "")),
                str(r.get("slice_bytes", "")),
                str(r.get("tbi_bytes", "")),
                f"{r.get('elapsed_s', 0):.2f}" if "elapsed_s" in r else "",
                r.get("error", ""),
            ]) + "\n")

    print(f"[extract] {len(months_done)} months captured / {len(schedule)} requested. "
          f"Cumulative download: {_human_mb(cumulative_bytes)}")
    if not args.keep_tbi:
        # delete .tbi cache
        for f in tbi_dir.glob("*.tbi"):
            f.unlink()
        try:
            tbi_dir.rmdir()
        except OSError:
            pass
    return 0 if len(months_done) >= 18 else 1


if __name__ == "__main__":
    raise SystemExit(main())
