#!/usr/bin/env python3
"""Real token-count comparison across three formats for the same patient.

Uses the actual Claude tokenizer (Xenova/claude-tokenizer on HuggingFace,
which is a port of the tokenizer the Anthropic SDK uses), and GPT-2 BPE
as a cross-check.

Inputs (all in bench/data/):
  - format_a_vcf.txt                       — raw VCF (1000G NA12878, 8 PGx loci)
  - format_b_genome_reconstructed.md       — .genome faithful reconstruction
  - format_c_bio_view.md                   — .bio manifest.json + pgx.md (concatenated)

Output: bench/results/tokens.json
"""

from __future__ import annotations

import json
from pathlib import Path

from transformers import AutoTokenizer

BENCH = Path(__file__).resolve().parent
DATA = BENCH / "data"
RESULTS = BENCH / "results"
RESULTS.mkdir(parents=True, exist_ok=True)

TOKENIZERS = {
    "claude": "Xenova/claude-tokenizer",
    "gpt2": "gpt2",
}

INPUTS = {
    "A_vcf": DATA / "format_a_vcf.txt",
    "B_genome": DATA / "format_b_genome_reconstructed.md",
    "C_bio_view": DATA / "format_c_bio_view.md",
}


def main() -> None:
    tokenizers = {}
    for name, model in TOKENIZERS.items():
        tok = AutoTokenizer.from_pretrained(model)
        tokenizers[name] = tok

    out: dict = {
        "tokenizers": {name: model for name, model in TOKENIZERS.items()},
        "inputs": {},
    }

    for label, path in INPUTS.items():
        text = path.read_text()
        bytes_ = len(text.encode("utf-8"))
        per_tok = {name: len(tok.encode(text)) for name, tok in tokenizers.items()}
        out["inputs"][label] = {
            "path": str(path.relative_to(BENCH.parent)),
            "bytes": bytes_,
            "tokens": per_tok,
        }
        print(f"{label:12s}  bytes={bytes_:5d}  " + "  ".join(f"{k}={v}" for k, v in per_tok.items()))

    print()
    # Ratios relative to .genome (B)
    base = out["inputs"]["B_genome"]["tokens"]
    for label in INPUTS:
        rel = out["inputs"][label]["tokens"]
        ratio = {k: round(rel[k] / base[k], 2) for k in rel}
        out["inputs"][label]["ratio_to_B_genome"] = ratio
        print(f"{label:12s}  ratio→B = " + "  ".join(f"{k}={v}×" for k, v in ratio.items()))

    (RESULTS / "tokens.json").write_text(json.dumps(out, indent=2))
    print(f"\nwrote {RESULTS / 'tokens.json'}")


if __name__ == "__main__":
    main()
