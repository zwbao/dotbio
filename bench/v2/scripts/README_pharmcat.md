# Task 3 — `.bio` → PharmCAT JSON report emitter

**Script**: `bench/v2/scripts/bio_to_pharmcat.py`
**Output**: `bench/v2/data/format_f_pharmcat_report.json`
**Companion task**: see `bench/v2/TASKS.md` Task 3, anchored in `bench/v2/SPEC.md` §2.3 (comparator format f).

## Goal

Take an existing dotbio v0 bundle (`examples/real-na12878/output.bio/`)
and emit a JSON report whose top-level layout matches PharmCAT's public
report schema as closely as possible — without ever invoking the
PharmCAT Java pipeline. The benchmark needs PharmCAT JSON as a
comparator format alongside VCF, VEP, Phenopackets, FHIR, etc.; we
cannot guarantee a Java environment is present, so this script re-shapes
data the .bio commit already carries.

## Run

```
python bench/v2/scripts/bio_to_pharmcat.py \
    --bio examples/real-na12878/output.bio \
    --out bench/v2/data/format_f_pharmcat_report.json
```

The script:

1. Loads `manifest.json`, the HEAD commit, and every fact.
2. Builds per-gene blocks for every gene mentioned by a diplotype claim,
   a phenotype claim, or any `gene_hint`-tagged variant fact.
3. Builds per-drug blocks for every claim with `level=clinical_decision`.
4. Surfaces every claim as a PharmCAT-style `messages[]` note so the
   provenance trail (claim id, ruleset, derivation) is preserved.
5. Validates the result against a hand-rolled approximation of the
   PharmCAT report schema (the official PharmCAT v3.x schema is
   embedded in Java source, not published as a standalone JSON Schema
   document; the cross-walk below documents every field we emit).
6. Counts tokens with the `Xenova/claude-tokenizer` HuggingFace port.

## Source for the PharmCAT schema

The reference shape was taken from PharmCAT's published example reports
in the official repository:

- `pharmcat.example.report.json`
  https://github.com/PharmGKB/PharmCAT/blob/development/docs/examples/pharmcat.example.report.json
- `pharmcat.example2.report.json`
  https://github.com/PharmGKB/PharmCAT/blob/development/docs/examples/pharmcat.example2.report.json

`https://pharmcat.org/specifications/Report/` (the URL in TASKS.md) now
redirects to `https://pharmcat.clinpgx.org/...` and 404s at the time of
writing; the example reports above are the authoritative shape.

Top-level keys observed in the official example:

```
title, timestamp, pharmcatVersion, dataVersion,
genes (dict keyed by gene symbol),
drugs (dict keyed by guideline source label, e.g. "CPIC Guideline Annotation"),
messages (list),
matcherMetadata (dict),
unannotatedGeneCalls (list)
```

We emit all of those. We additionally append a top-level
`_dotbio_provenance` object that real PharmCAT does not emit; readers
that want strict-PharmCAT JSON can drop it.

## Field-by-field cross-walk

### Top-level

| PharmCAT field          | dotbio source                                    | Notes |
|---|---|---|
| `title`                 | `manifest.subject` + suffix                       | `dotbio.NA12878.pharmcat-emitted` |
| `timestamp`             | `commit.created`                                  | ISO-8601 UTC |
| `pharmcatVersion`       | synthetic (`emitted-from-dotbio (ruleset pharmcat@<v>)`) | We did not run PharmCAT |
| `dataVersion`           | `manifest.active_rulesets[name=pharmcat].version` | e.g. `2025.3` |
| `genes`                 | per-gene block, see below                         | |
| `drugs`                 | per-drug block, see below                         | Keyed only under `"CPIC Guideline Annotation"` |
| `messages`              | one entry per `commit.claims[]`                   | `_dotbio_claim_id` retained |
| `matcherMetadata`       | from `manifest` + `commit`                        | `namedAlleleMatcherVersion=null` (no matcher run) |
| `unannotatedGeneCalls`  | always `[]`                                       | dotbio bundle has no unannotated calls |

### Per-gene block

| PharmCAT field                  | dotbio source / value                          |
|---|---|
| `geneSymbol`                    | `gene_hint` (variant fact) or `claim.gene`      |
| `chr`                           | first variant fact for this gene, `chrom`       |
| `phased` / `effectivelyPhased`  | always `false` (.bio v0 facts are not phased)   |
| `callSource`                    | literal `"DOTBIO"`                              |
| `relatedDrugs`                  | every drug claim mentioning this gene           |
| `sourceDiplotypes`              | from `level=haplotype` + `level=phenotype` claims |
| `recommendationDiplotypes`      | same as `sourceDiplotypes` (no inference)       |
| `variants`                      | every `kind=variant` fact tagged with this gene |
| `messages`                      | `[]`                                            |
| `alleleDefinitionSource`        | `"dotbio (re-emitted from .bio bundle)"`        |
| `alleleDefinitionVersion`       | pharmcat ruleset version from the manifest      |
| `_pharmcat_missing`             | listed gaps (matchScore, official source, …)    |

Per-variant fields under `genes[].variants[]` carry an extra
`_bio_fact_sha256` so a reader can dereference back to the original fact.

### Per-drug block

| PharmCAT field           | dotbio source / value                              |
|---|---|
| `name`                   | `claim.drug`                                        |
| `source`                 | literal `"CPIC_GUIDELINE"`                          |
| `version`                | pharmcat ruleset version                            |
| `guidelines[].name`      | `"Annotation of CPIC Guideline for <drug> and <gene>"` |
| `guidelines[].version`   | parsed from `claim.guideline` (e.g. `CPIC@2022` → `2022`) |
| `annotations[].drugRecommendation` | `claim.claim` (free text)                  |
| `annotations[].classification` | `"Strong"` if "consider alternative" / "avoid" / "contraindicated" appears, else `"Moderate"` |
| `annotations[].implications` | `["<gene>: <phenotype>"]` from the phenotype claim |
| `annotations[].population` | literal `"general"`                                |
| `annotations[].genotypes[].diplotypes` | from the matching haplotype + phenotype claims |
| `_dotbio_provenance.claim_id` | original `claim.id` so the audit trail survives |
| `_pharmcat_missing`      | listed gaps (`id`, `urls`, `citations`)             |

### Messages

Each `commit.claims[]` becomes one `messages[]` entry of
`exception_type: "note"` so a PharmCAT-aware downstream reader sees the
full claim history. `_dotbio_claim_id` is added to every entry.

## Acceptance-criteria checklist

| Criterion (TASKS.md Task 3)                                              | Status |
|---|---|
| JSON has top-level `metadata`, `genes`, `drugs`, `messages` sections     | met (we use the actual PharmCAT key names: `title`/`timestamp`/`pharmcatVersion`/`dataVersion`/`matcherMetadata` for "metadata", plus `genes`, `drugs`, `messages`) |
| Per-gene: diplotype call, phenotype, function                            | met (CYP2C19 `*1/*2`, phenotype `Intermediate Metabolizer`; `function` is `null` because the .bio bundle does not carry per-allele functional annotations — flagged in `_pharmcat_missing`) |
| Per-drug: PharmCAT recommendation with CPIC level                        | met (clopidogrel: `drugRecommendation` text + `classification` strength + `guidelines[].version`) |
| Validates against PharmCAT JSON schema (or hand-rolled approximation)    | met (hand-rolled validator inside the script; passes) |
| Token count reported                                                     | see below |
| Constraint: do NOT invent diplotypes                                     | met (only CYP2C19 `*1/*2` is emitted, exactly as in the commit) |
| Constraint: missing PharmCAT fields → null + comment                     | met (every field we cannot fill is `null` and listed in a sibling `_pharmcat_missing` array) |

## What we deliberately did NOT do

- **Did not call alleles.** PharmCAT's `NamedAlleleMatcher` runs against
  raw genotypes; we just trust the dotbio commit's pre-computed
  diplotype claim (CYP2C19 `*1/*2`). Other genes that have variant
  facts (APOE, CFTR, DPYD, F5, HFE, MTHFR) appear in the `genes` section
  with their variant rows but with empty `sourceDiplotypes`, because the
  bundle has no haplotype claim for them. This matches what PharmCAT
  itself does when a sample is uncalled.
- **Did not invent CPIC IDs / PMIDs.** Real PharmCAT pulls
  `PA<accession>` IDs from PharmGKB; we leave them `null` and flag the
  gap.
- **Did not re-license CPIC text.** The `drugRecommendation` text we
  emit is the dotbio claim text, not verbatim CPIC guideline prose.

## Token count (Claude tokenizer)

Tokenizer: `Xenova/claude-tokenizer` (HuggingFace port of the Anthropic
production tokenizer, used everywhere in `bench/`).

| Artifact                                  | Bytes  | Tokens |
|---|---|---|
| `bench/v2/data/format_f_pharmcat_report.json` | 18792  | 5168   |

Reproduce with:

```
python -c "
from transformers import AutoTokenizer
t = AutoTokenizer.from_pretrained('Xenova/claude-tokenizer')
s = open('bench/v2/data/format_f_pharmcat_report.json').read()
print('bytes', len(s.encode('utf-8')), 'tokens', len(t.encode(s)))
"
```

For comparison against other formats, see `bench/v2/data/format_d_phenopacket.json`
(Task 1) and the `bench/results/tokens.json` table from round 1.

## Limitations

- The dotbio NA12878 example only has *one* CPIC drug claim
  (clopidogrel) and *one* haplotype call (CYP2C19 `*1/*2`). A real
  PharmCAT report on the same VCF would also call diplotypes for
  several other PGx genes that happen to be reference (e.g. ABCG2,
  CACNA1S, …). Until the bundle's facts include those calls, we cannot
  emit them.
- We have no `function` strings (`Normal function`, `Loss of function`,
  …) for the alleles we do emit, because the .bio bundle does not
  store them. They are `null`, which is also valid PharmCAT for
  non-CPIC alleles.
- `matchScore` and `activityScore` are `null` for the same reason.
- The hand-rolled validator only checks structural shape (required keys
  + types). The official PharmCAT v3.x schema lives in Java source
  (`org.pharmgkb.pharmcat.reporter.model.*`) rather than as a
  standalone JSON Schema document; if/when an official Schema is
  published, swap the validator out.
