#!/usr/bin/env python3
"""Storage / update-cost comparison across formats.

Measures real bytes and tokens an LLM (or audit system) needs to (re-)read
under three scenarios:

  1. Initial query — what the LLM reads to answer one question
  2. After a single ClinVar reclassification (BRCA1 LP→P) — what changes,
     what gets re-read
  3. Time-travel ("what did we believe last month?") — is it natively
     supported

For .bio we use the actual synthetic example bundle (which has stable + HEAD
refs from a real `bio update`). For .genome we use the reconstruction in
bench/data/. For VCF we use the input VCF; an LLM also needs the relevant
ruleset to actually answer, so we report both VCF-only and VCF+ruleset.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from transformers import AutoTokenizer

REPO = Path(__file__).resolve().parent.parent
BENCH = REPO / "bench"
DATA = BENCH / "data"
RESULTS = BENCH / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

CLAUDE_TOK = AutoTokenizer.from_pretrained("Xenova/claude-tokenizer")


def tokens(text: str) -> int:
    return len(CLAUDE_TOK.encode(text))


def run_bio(*args: str) -> str:
    r = subprocess.run(
        [sys.executable, "-m", "dotbio", *args],
        cwd=REPO,
        env={"PYTHONPATH": str(REPO / "src"), "PATH": "/usr/bin:/bin"},
        capture_output=True,
        text=True,
        check=True,
    )
    return r.stdout


def main() -> None:
    out: dict = {}

    # === Scenario 1: initial query ===

    vcf = (DATA / "format_a_vcf.txt").read_text()
    pharmcat_ruleset = (REPO / "src/dotbio/rulesets/pharmcat-2025.3.json").read_text()
    genome = (DATA / "format_b_genome_reconstructed.md").read_text()
    manifest = (REPO / "examples/real-na12878/output.bio/manifest.json").read_text()
    pgx_view = (REPO / "examples/real-na12878/output.bio/views/pgx.md").read_text()

    out["scenario_1_initial_query"] = {
        "VCF_only": {
            "bytes": len(vcf.encode()),
            "tokens": tokens(vcf),
            "note": "LLM cannot answer without external annotation knowledge",
        },
        "VCF_plus_pharmcat_ruleset": {
            "bytes": len(vcf.encode()) + len(pharmcat_ruleset.encode()),
            "tokens": tokens(vcf) + tokens(pharmcat_ruleset),
            "note": "LLM does in-context PharmCAT-style haplotype calling",
        },
        "genome_full": {
            "bytes": len(genome.encode()),
            "tokens": tokens(genome),
            "note": "Pre-baked summary; reads everything",
        },
        "bio_manifest_plus_pgx_view": {
            "bytes": len(manifest.encode()) + len(pgx_view.encode()),
            "tokens": tokens(manifest) + tokens(pgx_view),
            "note": "Two-step: read manifest, then load relevant view",
        },
        "bio_manifest_only": {
            "bytes": len(manifest.encode()),
            "tokens": tokens(manifest),
            "note": "Manifest alone tells the LLM which view to load and current refs",
        },
    }

    # === Scenario 2: ClinVar reclassification (BRCA1 LP → P) ===
    # Use the synthetic example which has a real `bio update` history.

    synth_bundle = REPO / "examples/synthetic/output.bio"

    # The diff output produced by `bio diff stable HEAD` on the synthetic bundle.
    diff_text = run_bio("diff", str(synth_bundle), "stable", "HEAD")

    # The new commit file (the .bio cost: appending one commit).
    commit_files = sorted(synth_bundle.glob("commits/*.commit.json"))
    new_commit_bytes = commit_files[-1].stat().st_size
    new_commit_text = commit_files[-1].read_text()

    # For .genome the equivalent is a full re-bake. We measure the size of the
    # reconstructed .genome file as the proxy (since this is the only public
    # reference for what a .genome update produces).
    out["scenario_2_reclassification"] = {
        "VCF": {
            "bytes_to_redetect": len(vcf.encode()) + len(pharmcat_ruleset.encode()),
            "tokens_to_redetect": tokens(vcf) + tokens(pharmcat_ruleset),
            "method": "re-run full annotation pipeline; manually diff outputs",
            "time_travel_native": False,
        },
        "genome_full_rebake": {
            "bytes_rewritten": len(genome.encode()),
            "tokens_to_redetect": tokens(genome),
            "method": "rebake whole file from VCF + new ruleset; user mentally diffs",
            "time_travel_native": False,
        },
        "bio_diff": {
            "diff_output_bytes": len(diff_text.encode()),
            "diff_output_tokens": tokens(diff_text),
            "new_commit_bytes_on_disk": new_commit_bytes,
            "new_commit_tokens_if_read": tokens(new_commit_text),
            "method": "bio diff stable HEAD — reads only substantive changes",
            "time_travel_native": True,
        },
    }

    # === Scenario 3: information yield per token ===
    # Count explicit citations (anchored references that make a claim auditable):
    # rsIDs, ruleset versions, guideline names+versions, fact hashes.

    import re

    def count_citations(text: str) -> dict[str, int]:
        return {
            "rsIDs": len(re.findall(r"rs\d{4,}", text)),
            "ruleset_versions": len(re.findall(r"(?:clinvar|pharmcat|oncokb)@[0-9.\-]+", text, re.I)),
            "guideline_versions": len(re.findall(r"(?:CPIC|ACMG|CSCO|NCCN|ENIGMA|CDC)@?[\w\-\d]*", text)),
            "fact_hashes": len(re.findall(r"sha256:[a-f0-9]+", text)),
            "claim_ids": len(re.findall(r"claim:[a-f0-9]+", text)),
        }

    out["scenario_3_audit_density"] = {
        "VCF": count_citations(vcf),
        "genome_reconstruction": count_citations(genome),
        "bio_view_pgx": count_citations(pgx_view),
        "bio_manifest": count_citations(manifest),
    }

    (RESULTS / "storage.json").write_text(json.dumps(out, indent=2))

    # Pretty print
    print("=" * 70)
    print("Scenario 1: initial query")
    print("=" * 70)
    for k, v in out["scenario_1_initial_query"].items():
        print(f"  {k:34s}  bytes={v['bytes']:6d}  tokens={v['tokens']:5d}")
        print(f"    └── {v['note']}")

    print()
    print("=" * 70)
    print("Scenario 2: BRCA1 LP→P reclassification")
    print("=" * 70)
    for k, v in out["scenario_2_reclassification"].items():
        print(f"  {k}:")
        for kk, vv in v.items():
            print(f"    {kk}: {vv}")

    print()
    print("=" * 70)
    print("Scenario 3: explicit-citation density per format")
    print("=" * 70)
    for fmt, counts in out["scenario_3_audit_density"].items():
        print(f"  {fmt}:")
        for k, v in counts.items():
            print(f"    {k:25s} = {v}")

    print()
    print(f"wrote {RESULTS / 'storage.json'}")


if __name__ == "__main__":
    main()
