# Phenopackets v2 converter — methodology

**Companion document for**: `vcf_to_phenopacket.py` (Task 1 of the dotbio
NM-grade benchmark; see `bench/v2/SPEC.md` §2.3 for the comparator-format
list and `bench/v2/TASKS.md` for the task definition).

## What this is

A pure-stdlib Python script that converts a single-sample VCF plus the
dotbio ClinVar ruleset into a [GA4GH Phenopackets
v2](https://phenopacket-schema.readthedocs.io/en/v2/) JSON document, so
Phenopackets can be evaluated as a SOTA comparator format alongside VCF,
PharmCAT JSON, FHIR, ClinVar dumps, `.genome`, and `.bio` in the
benchmark's LLM evaluation.

## Inputs / outputs

| Role | Path |
|---|---|
| Input VCF (NA12878, 8 PGx loci) | `examples/real-na12878/input.vcf` |
| Input ruleset | `src/dotbio/rulesets/clinvar-2026-05-01.json` |
| Output Phenopacket | `bench/v2/data/format_d_phenopacket.json` |
| Sample input also tested on | `bench/data/format_a_vcf.txt` (same content as the NA12878 VCF) |

## Run it

```bash
python bench/v2/scripts/vcf_to_phenopacket.py \
    --vcf  examples/real-na12878/input.vcf \
    --ruleset src/dotbio/rulesets/clinvar-2026-05-01.json \
    --out  bench/v2/data/format_d_phenopacket.json
```

The script exits non-zero if validation fails. By default it runs the
hand-rolled validator (see below); if the optional `phenopackets` Python
package is installed it additionally tries
`google.protobuf.json_format.Parse` against the official `Phenopacket`
proto for a stricter check.

## VCF → Phenopacket field crosswalk

| VCF source | Phenopacket destination | Notes |
|---|---|---|
| `##fileDate` | `metaData.created` (timestamp), `id` (suffix) | We also stamp the converter's UTC `now`. |
| `##reference` | `files[].fileAttributes.genomeAssembly` and per-variant `vcfRecord.genomeAssembly` | Forced to `GRCh38` per the dotbio benchmark scope. |
| `##source`, `##NOTE` | `metaData.externalReferences[]` (description) | We do not preserve free-text VCF NOTE lines verbatim. |
| `#CHROM` SAMPLE name | `subject.id`, `genomicInterpretations[].subjectOrBiosampleId`, `files[].fileAttributes.sampleName` | NA12878 here. |
| `CHROM`, `POS`, `REF`, `ALT` | `variationDescriptor.vcfRecord.{chrom,pos,ref,alt}` | Pos is stringified per VRSATILE convention. |
| `ID` (rsID) | `variationDescriptor.id` (suffix), `variationDescriptor.xrefs[]` | Non-rs IDs are kept as `chrom:pos:ref:alt`. |
| `INFO/GENE` | `variationDescriptor.geneContext.symbol`, descriptor `label` | HGNC ID is **not** resolved offline (left as `HGNC:?:<symbol>`). |
| `INFO/AC`, `INFO/AF` | `variationDescriptor.extensions[]` (`alleleCount1000G`, `alleleFrequency1000G`) | Extensions are non-normative — fine for benchmark. |
| `FORMAT/GT` | `variationDescriptor.allelicState` (GENO ontology) | `0/0` → GENO:0000036 (homo-ref); `0/1` → GENO:0000135 (het); `1/1` → GENO:0000136 (homo-alt); missing → GENO:0000036 (no call). |
| Ruleset `entries[rsid].by_genotype[gt].significance` | `genomicInterpretations[].variantInterpretation.acmgPathogenicityClassification` (mapped) **and** `variationDescriptor.extensions[].clinvarSignificance` (raw) | See significance map below. |
| Ruleset `condition` | `diagnosis.disease` (free-text label under MONDO root id) | We do not resolve MONDO IDs offline, so the disease label is the textual condition with `id="MONDO:0700096"` (root "rare disease") as a placeholder. |
| Ruleset `evidence`, `review_status`, `consequence` | `variationDescriptor.extensions[]` | Free-text extensions; no info loss. |
| Ruleset `version`, `url` | `metaData.resources[]` (id `clinvar-dotbio`) | Pinned with version + url; SHA-256 of the file goes into `metaData.phenopacketSchemaVersion_x_dotbio.rulesetSha256`. |

### ClinVar significance → ACMG mapping

| ClinVar (dotbio ruleset) | Phenopacket ACMG enum | Rationale |
|---|---|---|
| `pathogenic` | `PATHOGENIC` | direct |
| `likely_pathogenic` | `LIKELY_PATHOGENIC` | direct |
| `uncertain_significance` | `UNCERTAIN_SIGNIFICANCE` | direct |
| `likely_benign` | `LIKELY_BENIGN` | direct |
| `benign` | `BENIGN` | direct |
| `risk_factor` | `NOT_PROVIDED` (full term in extension) | ACMG does not encode risk-factor; ACMG's "risk allele" is non-pathogenic-classification. |
| `drug_response` | `NOT_PROVIDED` (full term in extension) | Pharmacogenomic significance is out-of-scope for ACMG SF. |
| `carrier` | `NOT_PROVIDED` (full term in extension) | Carrier state for AR diseases is not an ACMG class. |

The raw ClinVar significance is preserved verbatim in
`variationDescriptor.extensions[].clinvarSignificance`, so no information
is lost — we only flag that the *closed enum* mandated by Phenopacket is
under-expressive for risk-factor / drug-response / carrier states.

## Where Phenopackets is **richer** than what we put in

- HPO phenotypic features per individual (we have none in NA12878 VCF).
- `MeasurementValue`, `MedicalAction`, `Treatment`, `Pedigree` blocks.
- A full `geneContext` with HGNC ID and `alternateIds[]`.
- Time-series observations on biosamples.

These remain unset; the converter writes nothing under
`phenotypicFeatures`, `measurements`, `medicalActions`, `biosamples`,
`pedigree`, or `diseases` (top-level), because the upstream VCF carries
no such information.

## Where dotbio data is **richer** than Phenopackets v2 expresses

- **Per-variant strand normalisation note** — encoded as
  `_strand_note` in the ruleset (e.g. for *MTHFR*, *F5*). Phenopackets'
  `variationDescriptor.vcfRecord` has only plus-strand coordinates; we
  preserve the strand context in
  `variationDescriptor.extensions[].molecularConsequence` only when the
  ruleset records it. Information is preserved but no longer in a
  schema-typed field.
- **Ruleset version + content hash** — Phenopackets has a `Resource`
  block with `version`, but no canonical place for a content-addressed
  hash. We tuck the SHA-256 of the ruleset file (and the VCF file) into
  a custom `metaData.phenopacketSchemaVersion_x_dotbio` extension,
  prefixed with `x_dotbio` to flag it as a non-standard field.
- **dotbio `commits/` evidence chain** — there is no Phenopackets
  analogue of the `.bio` "commits" notion (a typed, hashed record of
  *how* a fact was derived). The closest analogue is
  `genomicInterpretations[].variantInterpretation` extensions.
- **AC/AF cohort context from 1000G** — Phenopackets' `Resource` block
  does not carry per-variant population frequency natively; we put it
  in extensions.

## Acceptance-criteria checklist

| Criterion (TASKS.md) | How met |
|---|---|
| Validates against Phenopacket v2 | Hand-rolled validator (`validate_phenopacket()`) checks all required v2 fields (`id`, `subject`, `metaData`, `metaData.{created,createdBy,phenopacketSchemaVersion,resources}`, every `interpretations[].diagnosis.genomicInterpretations[].variantInterpretation`, every `variationDescriptor`). The optional `phenopackets` Python package adds protobuf-level validation when installed. |
| Subject `id`, VCF file resource | `subject.id = "NA12878"`; `files[0].uri` points at the VCF; per-variant `vcfRecord` repeats `chrom/pos/ref/alt`. |
| Per-variant `interpretation` with gene + variant + classification | Each `Interpretation.diagnosis.genomicInterpretations[0].variantInterpretation` carries `variationDescriptor.geneContext.symbol`, `variationDescriptor.vcfRecord` and `acmgPathogenicityClassification`. |
| ≥ 4 interpretation blocks for NA12878 | **8 produced** (one per VCF row with a non-empty ALT). |
| Token count reported with Claude tokenizer | See below. |

## Token count (Claude tokenizer)

Using `Xenova/claude-tokenizer` via `transformers.AutoTokenizer.from_pretrained`:

```python
from transformers import AutoTokenizer
tok = AutoTokenizer.from_pretrained("Xenova/claude-tokenizer")
print(len(tok.encode(open("bench/v2/data/format_d_phenopacket.json").read())))
```

| Metric | Value |
|---|---|
| Characters | 16,541 |
| Lines (pretty-printed, indent=2) | 522 |
| **Claude tokens (`Xenova/claude-tokenizer`)** | **4,001** |
| Interpretation blocks | 8 |
| ALT alleles carried by NA12878 | 2 (`rs1801133` G>A het, `rs4244285` G>A het) |

For comparison: the source 8-locus VCF (`format_a_vcf.txt`) is roughly
1.6 KB. The Phenopacket is ~10× larger because it materialises every
ontology resource header, per-variant ACMG enums, and the ruleset
provenance trail — but it carries information the VCF cannot express
(classification, condition, evidence sentence, review status), so the
token-budget comparison is only meaningful relative to a per-claim
metric (Experiment 1 in `SPEC.md` §3.1).

## Constraints honoured

- No Phenopackets-specific clinical inference is added — every
  classification, condition, and evidence string is copied directly from
  the dotbio ruleset, and the rsID / REF / ALT / GT come straight from
  the VCF.
- No external services or networks accessed. The converter runs offline.
- HGNC IDs and MONDO IDs are **not** resolved (we do not have an offline
  ontology mirror); they are written as deterministic placeholders so
  the schema slot is filled.
- Pure stdlib — `pydantic` / `phenopackets` are optional. The script
  imports `phenopackets` only inside `validate_phenopacket()` and
  swallows `ImportError`.

## Reproducibility

Every artifact is produced from two pinned inputs (the ruleset, hashed
into the output's `metaData`) and the converter source. To regenerate:

```bash
git rev-parse HEAD                            # pin the converter
sha256sum src/dotbio/rulesets/clinvar-2026-05-01.json  # pin the ruleset
python bench/v2/scripts/vcf_to_phenopacket.py --vcf examples/real-na12878/input.vcf \
    --ruleset src/dotbio/rulesets/clinvar-2026-05-01.json \
    --out bench/v2/data/format_d_phenopacket.json
```

The output JSON is byte-deterministic except for `metaData.created`,
which is the converter's run timestamp.
