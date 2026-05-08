# dotbio

[![ci](https://github.com/zwbao/dotbio/actions/workflows/ci.yml/badge.svg)](https://github.com/zwbao/dotbio/actions/workflows/ci.yml)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](LICENSE)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/)

**An AI-native data structure for biology.**

Status: v0 — early, not for clinical use. The format and CLI are alpha.

VCF was designed in 2011 for bioinformaticians. `.genome` (2025) compiles it into LLM-friendly Markdown but freezes the interpretation in time. **dotbio** keeps facts and interpretations in separate, layered, content-addressed structures so an LLM can read them, audit them, and watch them evolve.

Three principles:

1. **Multi-scale collapsing.** Variant → gene → haplotype → phenotype → clinical decision. Different questions want different scales. The bundle exposes all of them and lets the consumer pick.
2. **Evidence chain as first-class data.** Every claim points at the facts it was derived from, the ruleset that derived it, and the guideline it cites. No bare assertions.
3. **Time as a dimension.** Facts are immutable (content-addressed). Interpretations are append-only commits. ClinVar reclassifies a variant? Append a commit. Old refs still resolve. Diff two refs to see what changed.

A `.bio` bundle is a directory shaped like a small git repo:

```
patient.bio/
├── manifest.json                           # entry point — read this first
├── facts/<2>/<rest>.json                   # CAS layer (immutable)
├── commits/<ISO timestamp>.commit.json     # append-only interpretation log
├── views/{pgx,germline-clinical,...}.md    # materialized phenotype-level summaries
└── refs/{HEAD,stable,...}                  # named pointers to commits
```

See [SPEC.md](SPEC.md) for the full schema, [docs/compared-to.md](docs/compared-to.md) for how dotbio differs from VCF, `.genome`, and FHIR Genomics.

---

## 30-second demo

```bash
git clone https://github.com/zwbao/dotbio
cd dotbio
pip install -e .

# 1. Compile a VCF into a .bio bundle.
bio compile examples/synthetic/input.vcf -o /tmp/patient.bio

# 2. Read the LLM-friendly view for drug guidance.
bio show /tmp/patient.bio --view pgx

# 3. Simulate a ClinVar update — append a commit, advance HEAD.
bio update /tmp/patient.bio --ruleset clinvar@2026-05-08

# 4. Diff the old ref against HEAD — see only what was reclassified.
bio diff /tmp/patient.bio stable HEAD
```

That last command is the one that matters. Output:

```
# Diff  stable → HEAD

- 0 added
- 0 removed
- 1 changed (same target, new interpretation)

## Reclassifications

- **BRCA1 c.68_69delAG (185delAG)**
  - was: BRCA1 c.68_69delAG (185delAG) (GAG/G) — likely_pathogenic: ...  (clinvar@2026-05-01)
  - now: BRCA1 c.68_69delAG (185delAG) (GAG/G) — pathogenic: ...           (clinvar@2026-05-08)
  - reason: ruleset reclassified likely_pathogenic → pathogenic on 2026-05-08
```

Same VCF. Same patient. The interpretation changed because the world's knowledge changed. dotbio captured the change without rewriting anything — the old ref `stable` still resolves to the prior interpretation; the new ref `HEAD` resolves to the new one. An LLM asking "did this patient's report change since last visit?" gets a precise answer instead of a re-read of the whole genome.

## Real data: NA12878

The `examples/real-na12878/` directory contains genotypes for **NA12878** (HapMap CEU benchmark genome) extracted from the 1000 Genomes Project 30x high-coverage phased panel (GRCh38). Run:

```bash
bio compile examples/real-na12878/input.vcf -o /tmp/na12878.bio
bio show /tmp/na12878.bio --view pgx
```

dotbio produces two clinically meaningful claims for NA12878 from real public data: **CYP2C19 \*1/\*2 → Intermediate Metabolizer** (with CPIC clopidogrel guidance) and **MTHFR C677T heterozygous** (folate metabolism reduced ~30%). Both match the published profile of this widely-benchmarked individual. See [examples/real-na12878/README.md](examples/real-na12878/README.md) for full provenance.

---

## What's in a view

`bio show patient.bio --view pgx` returns Markdown that an LLM can consume directly:

```markdown
### CYP2C19 phenotype: Ultrarapid Metabolizer

<!-- claim_id: claim:30f90a42db7d2e44 | level: phenotype | ruleset: pharmcat@2025.3 -->

- Derivation: CYP2C19 *17/*17 → Ultrarapid Metabolizer [pharmcat@2025.3 phenotype table]
- Targets: sha256:004be3b31779229d…

### clopidogrel: Standard dose; effective platelet inhibition

<!-- claim_id: claim:e6ac117c75f584d3 | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- Derivation: CYP2C19 *17/*17 → Ultrarapid Metabolizer → drug guidance for clopidogrel [CPIC@2022]
- Guideline: CPIC@2022
- Targets: sha256:004be3b31779229d…
```

The LLM reads the phenotype-level claim and answers a drug question directly. If it wants the underlying call, it follows the `Targets` hash. If it wants the full evidence chain, it expands by `claim_id`:

```bash
bio expand /tmp/patient.bio claim:e6ac117c75f584d3
```

```
# Evidence chain for claim:e6ac117c75f584d3

- Claim: clopidogrel: Standard dose; effective platelet inhibition
- Level: clinical_decision
- Ruleset: pharmcat@2025.3
- Guideline: CPIC@2022
- Derivation: CYP2C19 *17/*17 → Ultrarapid Metabolizer → drug guidance for clopidogrel [CPIC@2022]

## Underlying facts

- sha256:004be3b31779229d… — CYP2C19 rs12248560 chr10:94781859 C>T GT=T/T
```

Three layers, three calls, no opaque inference. The LLM (or auditor, or clinician) can verify each step.

---

## Why not just VCF?

VCF is the right shape for variant calling — it's a flat list of differences from a reference. It is the wrong shape for LLM consumption:

- It carries no interpretation. The LLM has to know which annotation pipeline to run, then run it, then trust the output.
- It has no evidence chain. When a downstream tool says "this is pathogenic", VCF has nowhere to put the citation.
- It is a snapshot. There is no notion of "ClinVar updated last Tuesday" — you simply re-run the pipeline and overwrite.

dotbio doesn't replace VCF as a calling output. The `facts/` layer is essentially a normalized, content-addressed VCF. dotbio sits one layer above as the consumable, queryable, time-aware representation.

## Why not `.genome`?

The Genome Computer Company's `.genome` format ([genome.computer](https://genome.computer/)) tackles the same "AI-native" framing — pre-compile interpretations into LLM-friendly Markdown. Useful, and a real improvement over VCF for read-only LLM use.

Where dotbio diverges:

- `.genome` collapses fact and interpretation into one Markdown layer. Lose the call, lose the evidence. dotbio keeps them separate (`facts/` + `commits/`) — interpretation can be re-derived from facts under any ruleset.
- `.genome` is a snapshot. When ClinVar reclassifies, the file is stale. dotbio's append-only commit log captures the reclassification without losing prior state.
- `.genome` makes evidence implicit. dotbio makes it explicit (every claim → fact hashes + ruleset version + guideline + derivation).
- `.genome` is monoscale. dotbio is multi-scale — the LLM picks how deep to drill.

See [docs/compared-to.md](docs/compared-to.md) for tables and nuance.

---

## Install

```bash
pip install -e .            # editable install, makes the `bio` command available
# or
PYTHONPATH=src python -m dotbio compile ...   # no install needed
```

Stdlib-only, Python ≥ 3.9. No external dependencies for the core CLI.

For real-world VCF reading at scale, swap in [cyvcf2](https://github.com/brentp/cyvcf2) or [pysam](https://github.com/pysam-developers/pysam). The bundled `vcfio.py` is intentionally minimal.

## Tests

```bash
pip install -e ".[test]"
pytest -v
```

54 tests covering hashing/canonicalization, VCF parsing, the rule engine (ClinVar / PharmCAT / OncoKB), the full compile→update→diff pipeline, round-trip determinism, and real-data smoke tests on NA12878 (1000 Genomes 30x).

## Commands

```
bio compile <vcf> -o <bundle.bio>      # VCF → bundle
bio show <bundle> --view <name>         # render a view (or 'manifest')
bio update <bundle> --ruleset name@v    # apply a new ruleset, append a commit
bio diff <bundle> <ref_a> <ref_b>       # claim-level diff
bio expand <bundle> <claim_id>          # full evidence chain for a single claim
bio log <bundle>                        # commit history with refs
bio facts <bundle>                      # list immutable facts
```

## Bundled rulesets

dotbio ships with small illustrative subsets of three rulesets so the demo runs offline:

| Ruleset                | Source                                  | Coverage in v0                       |
|------------------------|-----------------------------------------|--------------------------------------|
| `clinvar@2026-05-01`   | ClinVar (NCBI)                          | 6 germline variants                  |
| `clinvar@2026-05-08`   | same, with one reclassification         | (for the time-travel demo)           |
| `pharmcat@2025.3`      | PharmCAT allele tables                  | CYP2C19, TPMT, DPYD                  |
| `oncokb@2026-04-15`    | OncoKB-style annotations                | TP53 p.R175H                         |

These are **illustrative**. They are not full rulesets and **must not be used for clinical decisions**. Real deployments would point at the upstream sources or use vetted local snapshots.

---

## Status & non-goals

- **v0 is a paradigm sketch.** The schemas may break before v1.
- **Not clinically validated.** dotbio is a data-structure proposal. Clinical decision support requires certified pipelines, end-to-end provenance, and validation that v0 does not provide.
- **Not a database.** A bundle holds one subject. Population queries need a different layer on top.
- **Not a privacy layer.** Carrying the file is the carrier's responsibility. dotbio doesn't encrypt anything by itself.
- **Not a calling output.** dotbio sits above variant calling, not in place of it. Use VCF/BCF as the source of truth from your sequencing pipeline; let dotbio be the consumable surface.

## Roadmap (post-v0)

- Real ClinVar / PharmCAT / OncoKB ingestion (fetch + pin)
- Multi-omics extension: methylation, expression, microbiome — same bundle pattern
- FHIR Genomics export view
- Signed commits (an attestation layer for "this interpretation was produced by lab X with pipeline Y")
- Composability: how do you join bundles from a trio? How do you reference a population baseline?

## Contributing

Issues, PRs, and pointed criticism are welcome. dotbio is a proposal — the value is in the conversation.

## License

[Apache 2.0](LICENSE).

Citation (informal): *dotbio: an AI-native data structure for biology* (2026), Z. Bao, https://github.com/zwbao/dotbio
