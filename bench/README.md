# dotbio benchmarks

Empirical comparison of three genomic data formats for LLM consumption:

- **A. VCF** — raw 1000 Genomes 30x output (the de-facto interchange format since 2011)
- **B. `.genome`** — a faithful reconstruction of The Genome Computer Co.'s LLM-friendly markdown format (the actual file format is proprietary; see note below)
- **C. `.bio` bundle** — dotbio's git-like bundle (manifest + views)

All three formats are populated with the same patient: **NA12878** (HapMap CEU female; the most-validated public benchmark genome). Eight PGx loci were extracted from the 1000 Genomes 30x phased panel. See `data/` for the actual inputs.

## What's measured

The benchmarks address three questions:

1. **Initial-query cost** — How many tokens does an LLM read to answer "can NA12878 take clopidogrel safely at standard dose?"
2. **Update cost** — When ClinVar reclassifies one variant (BRCA1 c.68_69delAG: likely_pathogenic → pathogenic), how many tokens must be re-read to learn what changed?
3. **End-to-end correctness** — Given each format and the question (with NO tool access), does a fresh LLM produce the right phenotype, the right diplotype, the right guideline citation, the right evidence?

## How to reproduce

```bash
pip install transformers tokenizers     # for the Claude tokenizer (Xenova port)
python bench/compare_tokens.py          # writes results/tokens.json
python bench/compare_storage.py         # writes results/storage.json (also exercises real `bio diff`)
```

The LLM-evaluation step (`results/llm_eval.json`) was produced by spawning fresh Claude general-purpose agents with strict no-tools instructions and the format content embedded inline. To reproduce, see the prompts in `prompts/` and re-run via your preferred LLM API. (We did not script this because of API-key portability concerns; the JSON results record the exact responses received.)

## What the results show

### Initial-query token cost (Claude tokenizer)

| Format                              | tokens |
|-------------------------------------|-------:|
| A1. VCF only                        |    676 |
| A2. VCF + PharmCAT ruleset (in-context haplotype calling) | 1,866 |
| B. `.genome` reconstruction         |    663 |
| C. `.bio` (manifest + pgx view)     |    834 |
| C'. `.bio` (manifest only — multi-step navigation entry) |    489 |

Take-aways:
- For an 8-locus PGx panel, `.genome` and `.bio` are within ~26% of each other. Raw token count is **not** the dimension where they meaningfully differ.
- VCF alone is small (676) but uninterpretable without external knowledge. VCF + ruleset (1,866) is 2.3× the cost of `.bio`.

### Update cost (BRCA1 LP→P reclassification)

| Format     | tokens to detect "what changed" | Method                                        | Native time travel |
|------------|--------------------------------:|-----------------------------------------------|--------------------|
| VCF        |                           1,866 | Re-run full annotation pipeline; manual diff  | No                 |
| `.genome`  |                             663 | Rebake whole file; user mentally diffs        | No                 |
| `.bio`     |                         **170** | `bio diff stable HEAD` — only substantive changes | Yes            |

`.bio` is **~4× cheaper** than `.genome` and **~11× cheaper** than VCF for detecting what changed after a single ruleset update. This advantage grows linearly with file size — `.genome`'s update cost scales with file size; `.bio`'s scales with the number of substantive changes.

### Audit / explicit-citation density

Counting explicit citations (rsIDs, ruleset@version strings, guideline references, fact hashes, claim IDs) in each input:

| Format               | rsIDs | ruleset@version | guidelines | fact hashes | claim IDs |
|----------------------|------:|----------------:|-----------:|------------:|----------:|
| VCF                  |     8 |               0 |          0 |           0 |         0 |
| `.genome`            |     5 |               0 |          0 |           0 |         0 |
| `.bio` pgx view      |     0 |               3 |          2 |           2 |         2 |
| `.bio` manifest      |     0 |               0 |          0 |           0 |         0 |

`.bio` is the only format that carries explicit ruleset versions, guideline references, and content-addressed fact hashes inline.

### LLM end-to-end (does the format actually let the model answer?)

Same question to four fresh agents, no tools, only the format text:

| Format        | Verdict | Phenotype called      | Diplotype | Guideline cited (with version) | Variant evidence in answer | Confidence | Hallucination required |
|---------------|---------|------------------------|-----------|--------------------------------|----------------------------|------------|------------------------|
| A1 VCF        | depends | unknown                | unknown   | ❌ unknown                       | rsIDs (raw)                | low        | yes (would need to invent CYP2C19 calling) |
| A2 VCF+rule   | depends | Intermediate Metabolizer | *1/*2   | ✓ CPIC@2022                    | rsIDs                      | high       | no                     |
| B `.genome`   | depends | Intermediate Metabolizer | *1/*2   | ❌ unknown                       | ❌ no rsID in prose          | high       | no                     |
| C `.bio`      | depends | Intermediate Metabolizer | *1/*2   | ✓ CPIC@2022                    | (fact hashes; not rsIDs)   | high       | no                     |

Verdict for all four: "depends" — correct (CYP2C19 IM has context-dependent guidance: alternative if ACS/PCI, standard otherwise). All four agents reached the right verdict; the difference is in **what they could cite**.

The notable findings:

- **VCF alone is unanswerable without external knowledge.** Agent A1 honestly returned `phenotype: unknown` and self-reported the inference it would need to make. An LLM with weaker truthfulness training would have hallucinated.
- **`.genome` produces the right verdict but loses the guideline reference.** The reconstructed prose says "consider alternative antiplatelet therapy" without citing CPIC by name and version. The agent could not cite a guideline.
- **`.bio` produces the right verdict AND the explicit guideline citation** (CPIC@2022) and includes content-addressed fact hashes that an agent with tool access could resolve back to the underlying call. In a single-shot setting (no tools) the rsID itself is not visible — that's the multi-step trade-off.

## Honest caveats

- `.genome` is proprietary; format B is our **best-faith reconstruction** based on the public examples in The Genome Computer Co.'s materials. If their actual format includes guideline-version citations or fact-level pointers, our reconstruction underrepresents it. If they only include positive findings (not the negative-screening blocks our reconstruction has), our token count is an overestimate.
- Claude-tokenizer counts are from the Xenova/claude-tokenizer HuggingFace port (a published port of the actual Anthropic tokenizer). GPT-2 BPE was used as a cross-check (within ±5% of Claude's counts on these inputs).
- The single-shot LLM eval was run once per condition. Replication with N≥10 across multiple LLMs would tighten confidence on the answer-shape findings; the token / storage measurements are deterministic and need no replication.
- The 8-locus panel is small. As panel size grows, `.genome`'s O(N) full-read cost grows linearly while `.bio`'s view-based query cost stays bounded — but we have not measured this on full-panel data here.

## Files

```
bench/
├── README.md                                   ← this file
├── compare_tokens.py                           ← real Claude/GPT-2 tokenization
├── compare_storage.py                          ← initial-query, update, and audit-density measurements
├── data/
│   ├── format_a_vcf.txt                        ← 8 NA12878 loci from 1000G 30x panel
│   ├── format_b_genome_reconstructed.md        ← faithful .genome reconstruction
│   └── format_c_bio_view.md                    ← .bio manifest.json + pgx.md (concatenated)
└── results/
    ├── tokens.json
    ├── storage.json
    └── llm_eval.json                            ← raw agent responses + scoring
```
