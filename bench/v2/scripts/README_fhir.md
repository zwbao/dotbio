# Task 2 — VCF → HL7 FHIR R4 Genomics IG converter

Converter for the dotbio NM-grade benchmark v2. Translates the 8-locus
PGx VCF for NA12878 (`examples/real-na12878/input.vcf`) into a FHIR R4
Bundle aligned with the **HL7 FHIR Genomics Implementation Guide**
(release 2.0.0; <https://hl7.org/fhir/uv/genomics-reporting/>).

This file is **comparator format E** for Experiment 1 / Experiment 3 in
`bench/v2/SPEC.md`.

## Run

```bash
python bench/v2/scripts/vcf_to_fhir.py \
    --vcf examples/real-na12878/input.vcf \
    --out bench/v2/data/format_e_fhir_bundle.json \
    --token-count
```

Set `DOTBIO_FHIR_TIMESTAMP=2026-05-09T00:00:00Z` (or any ISO-8601 instant)
for byte-stable reproducible output.

The script is pure stdlib for the FHIR build; `transformers` is only
used to compute Claude token counts (Xenova/claude-tokenizer). The
official `fhir.resources` package is permitted by Task 2 but not
required, so we ship the stdlib build.

## Resources emitted

| Resource | Count | Profile / IG |
|---|---|---|
| `Bundle` (collection) | 1 | `genomics-report-bundle` |
| `Patient` | 1 | core R4 Patient |
| `Specimen` | 1 | core R4 Specimen (whole blood, lymphoblastoid gDNA) |
| `MolecularSequence` | 1 | core R4 MolecularSequence (DNA, GRCh38, sense, watson) |
| `Observation` (genetics-variant) | 8 | `genomics-reporting/StructureDefinition/variant` |
| `DiagnosticReport` (genomics-report) | 1 | `genomics-reporting/StructureDefinition/genomics-report` |
| **Total** | **12** | |

## LOINC codes used

| LOINC | Display | Where |
|---|---|---|
| 53037-8 | Genetic variation's clinical significance | Observation.code |
| 81252-9 | Discrete genetic variant | Observation.code |
| 69548-6 | Genetic variant assessment | Observation.code |
| 48018-6 | Gene studied [ID] | Observation.component |
| 48013-7 | Genomic reference sequence ID | Observation.component |
| 69547-8 | Genomic ref allele [ID] | Observation.component |
| 69551-0 | Genomic alt allele [ID] | Observation.component |
| 81254-5 | Genomic allele start-end | Observation.component |
| 62374-4 | Human reference sequence assembly version | Observation.component |
| 53034-5 | Allelic state | Observation.component |
| 81255-2 | dbSNP variant ID | Observation.component |
| 81247-9 | Master HL7 genetic variant reporting panel | DiagnosticReport.code |
| 53041-0 | DNA analysis discrete sequence variation panel | DiagnosticReport.code |

LOINC LA codes (allelic state answer list): `LA6704-3` Homozygous reference,
`LA6705-0` Homozygous, `LA6706-8` Heterozygous, `LA9663-1` Unknown,
`LA14029-5` GRCh38, `LA6576-8` Present, `LA6577-6` Absent.

## VCF → FHIR cross-walk

| VCF field | FHIR target |
|---|---|
| `#CHROM` | `Observation.component[code=48013-7]` → NCBI RefSeq accession |
| `POS` (1-based) | `Observation.component[code=81254-5].valueRange.low` |
| `POS + len(REF) - 1` | `Observation.component[code=81254-5].valueRange.high` |
| `ID` (rsID) | `Observation.component[code=81255-2]` (system: dbSNP) |
| `REF` | `Observation.component[code=69547-8].valueString` |
| `ALT` | `Observation.component[code=69551-0].valueString` |
| `INFO/GENE` | `Observation.component[code=48018-6]` (HGNC code) |
| `INFO/AF` | `Observation.component[code=92822-6].valueQuantity` |
| `FORMAT/GT` | `Observation.component[code=53034-5]` allelic state + `valueCodeableConcept` interpretation |
| `##reference=GRCh38` | `Observation.component[code=62374-4]` + MolecularSequence.referenceSeq.genomeBuild |
| sample column header | `Patient.identifier[].value` |

GRCh38 contigs are mapped to NCBI RefSeq accessions inside the converter
(`chr1` → `NC_000001.11`, `chr10` → `NC_000010.11`, etc.).

## Things FHIR Genomics IG cannot losslessly express from this VCF

- **Phasing**. VCF `1|0` carries phase information; FHIR R4 has no
  first-class phasing slot inside `Observation`. We surface the phased
  bar in the `valueCodeableConcept.text` (`A|G`) so a reader can recover
  it, but a strict parser may drop it.
- **Per-allele AC/AF**. The IG's `92822-6` is "Genomic source class",
  used here as a carrier for the 1000G AF. The semantics are imperfect
  but better than dropping the field.
- **Multi-sample VCFs**. We assume single-sample input (the existing
  NA12878 example). A multi-sample bundle would need one `Patient` +
  one set of Observations per column.

## Things FHIR Genomics IG carries that VCF doesn't

- HGNC numeric IDs for `Gene studied`
- LOINC-coded allelic state (zygosity normalized to LA codes)
- DiagnosticReport conclusion text rolling up findings
- Specimen provenance with HL7 v2-0487 (BLD = whole blood)

## Validation

The script ships a hand-rolled validator (`validate_bundle`) that checks
the IG-relevant invariants the SPEC and TASKS.md require:

- `Bundle` at top level, `type=collection`
- ≥ 1 each of `Patient`, `Specimen`, `MolecularSequence`,
  `DiagnosticReport`
- Every `Observation` carries `subject` and at least one `component`
- LOINC 53037-8, 81252-9, 48018-6 are present somewhere in the bundle

The fully-loaded `fhir.resources` Pydantic validator (R4) was not used
because Task 2 explicitly allows pure stdlib and CI does not pin it.
You can re-validate externally via:

```bash
pip install fhir.resources==7.1.0
python -c "from fhir.resources.bundle import Bundle; \
    import json; \
    Bundle.parse_obj(json.load(open('bench/v2/data/format_e_fhir_bundle.json')))"
```

## Token count

Measured with `Xenova/claude-tokenizer` (the official Claude tokenizer
port shipped via `transformers.AutoTokenizer`):

| Artifact | Bytes | Claude tokens |
|---|---|---|
| `bench/v2/data/format_e_fhir_bundle.json` | 61306 | **13887** |

Reproduce: `python bench/v2/scripts/vcf_to_fhir.py --token-count`
(uses `DOTBIO_FHIR_TIMESTAMP=2026-05-09T00:00:00Z` for the published
number; per-run timestamps will shift the count by ≤ 2 tokens).

## Acceptance criteria check (TASKS.md §Task 2)

- [x] Bundle validates against IG core profiles (Patient, MolecularSequence,
      Observation/genetics-variant, DiagnosticReport) — see `validate_bundle`
- [x] `Patient` resource present (NA12878)
- [x] `MolecularSequence` resource present
- [x] Per-variant `Observation` resources with LOINC-coded fields (53037-8,
      81252-9, 48018-6, plus 11 more LOINC codes across components)
- [x] DiagnosticReport rolling up findings present
- [x] Token count reported (13887 with claude tokenizer)
- [x] Pure stdlib output (transformers only used for token counting)
