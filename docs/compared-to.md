# dotbio: Compared to Existing Formats

Last reviewed: 2026-05-08

This document positions dotbio against the formats and frameworks it is most often confused with. It is not a specification — see `SPEC.md` for the format definition. The goal here is to be honest about where dotbio adds value, where it overlaps, and where another format is the right answer.

A short reminder of what dotbio is, since the comparisons below depend on it:

- A directory-shaped bundle (`.bio`) carrying one individual's biological data.
- Designed for LLM consumption: queries are answered by reading a small slice, not by re-running a pipeline.
- Three principles: **multi-scale collapsing** (variant up to gene up to phenotype up to clinical guidance), **evidence chain as first-class data** (every claim carries fact hashes, ruleset version, guideline reference, derivation path), and **time as a dimension** (content-addressed immutable facts, append-only commit log of interpretations, named refs for time travel).
- Architecture: `facts/` (CAS-keyed JSON, immutable), `commits/` (append-only interpretation log), `views/` (materialized phenotype-level Markdown), `refs/` (named pointers to commits), `manifest.json` (entry point).

The comparisons that follow assume that shape.

---

## 1. dotbio vs VCF (Variant Call Format)

VCF is the de facto interchange format for variant calls. It has been the workhorse of human and population genomics since roughly 2011, and the v4.x line (4.1 through 4.5) has been the stable substrate for everything from 1000 Genomes through gnomAD, UK Biobank, and clinical sequencing pipelines worldwide. It is, by any reasonable measure, a successful format.

It is also a format whose abstractions were chosen for a different consumer than the one we are now optimizing for.

### What VCF is

VCF is a flat, line-oriented text format. Each non-header line is a variant record: a position in a reference genome, the reference allele, one or more alternate alleles, a quality score, a filter status, an `INFO` column carrying semicolon-delimited key/value annotations, and per-sample genotype columns. A typical line looks like:

```
1   17330   .   T   A   3.6     LowQual    AC=2;AF=1.00;AN=2;DP=30;MQ=24.30;...   GT:AD:DP    1/1:0,1:1
```

That single record encodes a variant call at chromosome 1, position 17330, with reference T and alternate A, with `INFO=DP=30` indicating depth of coverage 30, and a single sample homozygous for the alternate allele. To say anything about whether that variant matters — what gene it is in, whether it is annotated in ClinVar, whether it is pharmacogenomically actionable, whether it predicts drug response — you have to run a separate annotation pipeline (VEP, snpEff, ANNOVAR, ClinVar lookup, PharmCAT, OncoKB, CIViC, and so on).

This is by design. VCF is a pure data layer. Interpretation is deferred to downstream tools.

### What VCF was not designed for

VCF assumes its consumer is a bioinformatician with a pipeline. The format has no notion of:

- **Evidence**. An annotation written into `INFO` carries no provenance — no rule, no version, no guideline citation, no derivation path. If a downstream tool dropped `CLINSIG=Pathogenic` into the line, the file does not record where that came from or when.
- **Time**. A VCF is a snapshot. There is no diff against a prior version, no log of when an annotation was added or revised, no way to ask "what did we believe about this variant six months ago?"
- **Multi-scale views**. Everything is at the variant scale. Gene-level, phenotype-level, and clinical-guidance-level views must be reconstructed each query by re-running annotation.
- **LLM consumption**. The format is dense, coordinate-keyed, and meaningless without a reference genome and an annotation pipeline. Asking an LLM "does this person have an actionable variant?" by handing it a VCF is asking the LLM to do a bioinformatics pipeline in its head.

### Side-by-side

| Dimension | VCF (v4.x) | dotbio |
|---|---|---|
| Data scope | Variants relative to a reference (CHROM, POS, REF, ALT) | Variants, derived gene-level summaries, phenotype views, clinical-guidance views |
| Interpretation | Out-of-band; deferred to downstream tools | First-class; lives in `commits/` and `views/` |
| Evidence | None native; `INFO` carries opaque key/value pairs | Each claim carries fact hashes, ruleset version, guideline reference, derivation path |
| Versioning of interpretation | Not modeled; you re-run the pipeline | Append-only commit log; `refs/` point to specific commits |
| Time semantics | Snapshot; no diff or history | Content-addressed immutable facts; commit log; refs for time travel |
| Format shape | Single flat text file (or BCF binary) | Directory bundle: `facts/`, `commits/`, `views/`, `refs/`, `manifest.json` |
| LLM-readiness | Low — requires full re-annotation pipeline to answer any non-coordinate question | High — phenotype views are Markdown; LLM zooms into hashes only when needed |
| Primary consumer | Bioinformaticians, pipelines, large cohort tools | LLMs, clinicians, individuals carrying their own data |
| Token cost of a typical question | High — must inline annotated VCF or pipeline output | Low — answer comes from a phenotype view; drill-down is opt-in |

### Nuance

VCF is correct as ground truth. It encodes what was actually called from sequencing, with the precision the calling tools assert, in a form that is universal across the field. dotbio does not try to replace that. The `facts/` layer of a dotbio bundle is essentially "VCF normalized into immutable JSON, one fact per file, content-addressed by hash" — same information, different shape, with the addition that derived facts (gene-level rollups, phenotype assignments) live in the same hash space.

dotbio sits one layer above VCF. The pipeline that produces a dotbio bundle starts from VCF (and BAM/CRAM, and array data, and report PDFs, and so on), normalizes the calls into facts, and then layers commits on top to record what those facts were taken to mean. When the bundle is opened later, the consumer does not need the calling pipeline anymore — the calling pipeline's output has been carried along, hashed, and made queryable.

The question is not "VCF or dotbio?" The question is "what is the carriable, queryable, AI-consumable representation of an individual's genome, on top of VCF?" dotbio is a candidate answer to that second question. VCF remains the right answer to the first.

A practical analogy: VCF is to dotbio roughly as raw GeoTIFF tiles are to a vector map tile bundle plus a styled web map. The TIFF is correct and authoritative; you do not throw it away. But you also do not hand it to a phone for navigation.

---

## 2. dotbio vs `.genome` (The Genome Computer Company)

Reference: <https://genome.computer/>

The `.genome` format is, as far as we know, the closest existing project in spirit to dotbio. It compiles VCF plus annotations into LLM-friendly Markdown, and it tackles the same fundamental observation that motivates dotbio: VCF is the wrong abstraction if your consumer is a language model. Interpretation is pre-baked at storage time, so an LLM can answer questions about the file without doing variant lookup.

We want to be careful here. `.genome` is a real attempt at a real problem, and it gets several things right that dotbio agrees with. The differences are in design choices, not in the framing of the problem.

### What `.genome` does well

- **Recognizes that VCF is the wrong abstraction for LLMs.** This is not obvious — the field defaulted to "annotate VCF and feed annotated VCF to the model" for years. Pre-baking interpretation into Markdown is a real shift.
- **Token-efficient at query time.** A `.genome` file at the phenotype scale is small, plain, and answers most consumer-grade questions in a single pass.
- **Personal context framing.** The file is portable, user-owned, and intelligible to a non-bioinformatician. This matters more than it sounds — most existing personal-genomics formats fail this bar by a wide margin.

### Where dotbio diverges

The differences come from four design decisions, each with a tradeoff.

**Fact and interpretation are separated, not collapsed.** A `.genome` file collapses raw calls and their interpretation into one Markdown layer. dotbio keeps them in separate directories: `facts/` is the immutable normalization of what was actually measured, and `commits/` is the (mutable, but append-only) layer of what those facts were taken to mean. The cost is more files. The benefit is that when interpretation needs to change — and it will — you do not rewrite the file. You add a commit.

**Snapshot vs append-only history.** A `.genome` file is a snapshot. When ClinVar reclassifies a variant from VUS to Likely Pathogenic, or when a guideline body issues new dosing recommendations, the existing file is stale; the right move is to recompile from VCF. dotbio's commit log captures the reclassification as a new commit pointing to the same underlying fact, leaving the prior interpretation intact and addressable. You can ask "what did we believe in March?" by checking out an earlier ref.

**Implicit vs explicit evidence.** A `.genome` Markdown paragraph might read:

```markdown
## CYP2C19
You are a CYP2C19 *2/*2 (poor metabolizer). Clopidogrel is unlikely to be effective; consider prasugrel or ticagrelor.
```

The conclusion is there. The evidence is implicit — a reader has to trust that the compiler did the right lookups. A dotbio claim attached to the same phenotype view points to the underlying fact hashes (the `*2/*2` diplotype), the ruleset version (e.g. CPIC clopidogrel guideline 2022), the guideline citation, and the derivation path that took the diplotype to "poor metabolizer" to "clopidogrel unlikely effective." An LLM (or auditor, or clinician) can follow that chain rather than trust it.

**Monoscale vs multi-scale.** `.genome` lives mostly at the phenotype scale, which is the right default for the consumer use case. dotbio also defaults to phenotype-level views, but the LLM can zoom in by following hash chains: phenotype to claim to ruleset to fact to underlying call. The same bundle answers "should I take clopidogrel?" cheaply, and "show me every fact and rule that justified that recommendation" expensively, without needing a different file.

### Side-by-side

| Dimension | `.genome` | dotbio |
|---|---|---|
| Data fidelity (round-trip to raw calls) | Partial — Markdown is a lossy compile target; raw VCF is the source of truth | Round-trippable — `facts/` preserves normalized calls; original VCF can be retained as a fact |
| Interpretation freshness | Stale on guideline updates; recompile from VCF | New commit captures the update; prior commits remain queryable |
| Evidence chain | Implicit in prose | Explicit: fact hashes + ruleset version + guideline ref + derivation |
| Audit trail | Not modeled — file is a snapshot | Append-only commit log; signatures optional but supported |
| Time travel | None native | `refs/` point to commits; check out any historical state |
| File size | Small (single Markdown, often a few KB to tens of KB) | Larger (directory; tens to low hundreds of KB typical) |
| LLM token cost — single query at phenotype scale | Low | Low (views/ phenotype Markdown is the entry point) |
| LLM token cost — multi-turn drill-down | Same as single query (everything is loaded) | Lower at the margin — drill-down loads only the facts/commits referenced |
| Compiler complexity | Lower | Higher — fact normalization, hash discipline, commit log |
| Consumer simplicity | Higher — one file, opens in any Markdown reader | Slightly higher friction — directory bundle, but still human-readable |

### Fair framing

`.genome` solves a real problem, and it is simpler to ship. If your goal is "give a person a portable file their LLM can read," you can build `.genome` end-to-end in less time than you can build a dotbio compiler that respects the evidence-chain invariants. We do not pretend otherwise.

dotbio takes a stronger position on auditability and time. Those positions matter most when the bundle is going to be read by something other than the original compiler — by a different LLM, by a clinician at a later visit, by an auditor reconstructing a past recommendation, by the same person three years later when a guideline has shifted. The cost is more complexity in the compiler. The benefit, if you accept the framing, is that the bundle keeps being trustworthy as the world around it changes.

A reasonable reading is that the two formats target overlapping but distinct points on the same design surface: `.genome` optimizes for "smallest portable file an LLM can answer questions about today," dotbio optimizes for "smallest portable bundle that stays answerable, auditable, and updatable for years."

---

## 3. dotbio vs FHIR Genomics

FHIR Genomics — the genomics-specific resources in the HL7 FHIR standard, principally `MolecularSequence` (and its successor `Genomics` profiles), and the `Observation` resource with genetics extensions — is the standard answer for moving genomic information between healthcare systems. It is not really a competitor to dotbio. It is solving a different problem.

FHIR's design center is system-to-system EHR exchange: a hospital lab needs to send a structured genetic test result to an outside ordering provider, a registry needs to ingest a normalized variant observation, a CDS hook needs to query a patient's PGx status from the EHR. The audience is healthcare IT systems with deterministic schemas and credentialed APIs. The schemas are correspondingly verbose, code-system-heavy (LOINC, SNOMED CT, HGNC, HGVS), and structured for transactional reliability rather than narrative readability.

dotbio's design center is AI consumption plus individual portability. The audience is an LLM reading a file the user carries with them, plus the human or clinician reading the same file with their own eyes. The schema is structured for cheap reads at multiple scales, narrative-friendly output, and append-only history rather than transactional updates.

These are complementary rather than competitive. A dotbio bundle could expose a FHIR-shaped view alongside its phenotype Markdown view — `views/fhir/` would materialize the relevant `Observation` and `MolecularSequence` resources from the same underlying facts and commits, so a healthcare system can ingest the bundle without learning a new format. Going the other direction, a FHIR Bundle resource could carry a dotbio `.bio` directory as an attachment (DocumentReference or Binary), giving the patient a portable, AI-consumable artifact alongside the EHR-native record. The two formats can ride in the same envelope.

The honest summary is that "FHIR vs dotbio" is mostly a category error. FHIR is a healthcare interoperability protocol; dotbio is a personal data bundle. They share genomic content but optimize for different consumers, and a mature ecosystem will probably have both, with adapters between them.

---

## 4. When dotbio is the wrong choice

A format is only worth taking seriously if it is honest about where it does not fit. dotbio is not the right answer for several real workloads.

**High-throughput population studies.** If you are calling variants across ten thousand samples, doing GWAS, or running gnomAD-style aggregate analyses, you want VCF/BCF (and probably Hail tables, Plink2, or Zarr-backed array stores). dotbio's per-individual bundle shape is the wrong granularity, and the evidence-chain machinery is overhead you will not benefit from. Use VCF/BCF directly and reach for dotbio, if at all, only at the per-individual reporting layer.

**Real-time clinical decision support requiring certified pipelines.** dotbio v0 is a data format and a compiler. It is not a clinically validated pipeline, it is not certified under any regulatory regime (CLIA, CAP, IVDR, NMPA), and it is not a substitute for one. If your use case is "my EHR's CDS hook needs to fire a pharmacogenomic alert at order entry," you need a certified PGx pipeline behind that hook — possibly with FHIR Genomics as the wire format — not a dotbio bundle. dotbio can carry an audit-friendly record of what such a pipeline output, but it does not replace the pipeline.

**Storage of raw read data.** Sequencing reads belong in BAM/CRAM. dotbio is a derived-and-interpreted layer, not a primary archive. You can include a BAM/CRAM checksum as a fact in `facts/` to anchor provenance, but you would not store the reads inside a `.bio` bundle.

**Trio and family analyses requiring joint genotyping.** dotbio v0 is single-individual by design. Trio analyses (de novo variant calling, segregation analysis, parent-of-origin phasing) require joint VCFs and family-aware tools. A future version could plausibly model family relationships across linked bundles, but v0 does not, and trying to force it is the wrong choice. Use the joint-calling toolchain.

**Workloads where token cost is not a constraint.** A surprising amount of dotbio's design is justified by "the consumer is paying per token to read this." If your consumer is a server-side analysis with no token budget — say, a Spark job consuming structured records — most of dotbio's multi-scale collapsing buys you nothing. Use a flatter, more analytic-friendly representation.

The pattern in all four cases is the same: dotbio is optimized for one individual, one bundle, an LLM-or-clinician reader, and a time horizon measured in years. When any of those four assumptions break, a different format is the right tool.

---

## Summary

| If your priority is... | Reach for... |
|---|---|
| Authoritative variant calls from a sequencing pipeline | VCF / BCF |
| Population-scale joint analyses | VCF / BCF, Hail, Plink2, Zarr |
| EHR-to-EHR interoperability | FHIR Genomics |
| Smallest LLM-readable personal genomics file | `.genome` |
| Auditable, time-aware, multi-scale personal bundle for AI and clinician consumption | dotbio |
| Raw reads | BAM / CRAM |
| Trio / family joint analyses | Joint-called VCF + family-aware tools |
| Certified clinical decision support | A certified pipeline (regardless of carrier format) |

dotbio is not a replacement for the formats above. It is a layer above the calling output, designed for a consumer the existing formats were not built for. Where that consumer matters — an LLM reading an individual's bundle, a clinician revisiting a recommendation a year later, an auditor reconstructing why a claim was made — the design choices in this document are the case for using dotbio. Where that consumer does not matter, one of the alternatives above is the right answer, and we would rather you use it than force-fit dotbio.
