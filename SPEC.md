# dotbio: Specification v0

## Abstract

`dotbio` is a content-addressed, append-only bundle format for representing
biological knowledge about a single subject in a way that is legible to large
language models. A `.bio` bundle is a directory containing immutable facts,
append-only interpretation commits, materialized phenotype-level views, and
git-style refs. The format is designed around three claims: (1) biology is
inherently multi-scale, so the carrier must let a consumer choose the right
scale for the question; (2) every interpretation must carry an evidence chain
back to the underlying facts and the ruleset that produced it; and (3) time is
a first-class dimension — facts are immutable and interpretations are
recomputed by appending new commits, never by mutating prior state. This
document is the formal v0 specification of the bundle layout, schemas, reading
protocol, operations, and canonicalization rules.

## Status

This is `dotbio.v0`, a **draft**. Nothing in this document is stability-bound.
Field names, defaults, and the canonicalization algorithm MAY change between v0
revisions. Implementations are expected to pin to an exact `schema` string
(e.g. `"dotbio.v0"`) and refuse bundles that do not match. There is no upgrade
path guarantee, no wire-compatibility guarantee, and no on-disk-format
guarantee until v1.

This format is **not** validated for clinical use. See **Non-Goals**.

## Design Principles

The format is shaped by three principles. They are normative: a conforming
implementation must preserve the invariants each principle implies, even when
those invariants are inconvenient.

### 1. Multi-scale collapsing

Biological knowledge nests at well-known scales:

```
variant  →  gene  →  haplotype  →  pathway  →  phenotype  →  clinical decision
```

A drug-dosing question can be answered at the **phenotype** level
("CYP2C19 poor metabolizer") without re-deriving from raw variants. A
re-classification question (a variant moved from VUS to Likely Pathogenic)
requires the **variant** level. A pathway-impact question lives somewhere in
between. The format must let a consumer pick a scale that matches the
question's required resolution and budget — not force every consumer to
ingest raw calls.

dotbio expresses this via two layers:

- **Facts** are stored at their natural scale (a variant fact is a single
  variant; a copy-number fact is a single segment).
- **Views** are *materialized* roll-ups at higher scales, generated from
  commits, written to disk as Markdown, and indexed in `manifest.json` with an
  `est_tokens` budget so the consumer can plan its read.

View materialization is part of the format, not an implementation detail.
The bundle ships with views the producer chose; consumers are not expected to
recompute them. When more detail is needed, the consumer drills down through
`claim_id → commit → claim → derivation → target hashes → fact files`.

### 2. Evidence chain as first-class

No claim in a dotbio bundle stands alone. Every claim — at any scale —
carries:

- `targets`: the SHA-256 hashes of the facts it asserts something about.
- `ruleset`: the name and version of the rule system that produced the
  classification.
- `guideline`: the cited external guideline (with version) the rule encodes.
- `derivation`: a human-readable trace of *why* this claim was reached from
  these targets under this ruleset.

This is non-negotiable. A "bare" claim (one with no targets, no ruleset, no
guideline) is malformed. Facts and interpretations are layered, not collapsed:
a reader can always answer "where did this come from?" by walking the chain.
This is what makes the bundle re-derivable when a guideline updates.

### 3. Time as dimension

Facts are content-addressed and therefore immutable. Interpretations change
over time — guidelines are revised, rulesets are versioned, variants are
re-classified — and the format treats this as a **structural** property, not
metadata.

- A `commits/` log is append-only.
- Each commit references a `parent` (or `null` for the root) and a `ruleset`
  version, and contains the claims that ruleset produced over the current fact
  set.
- A re-classification produces a new commit; the old commit and its claims
  remain on disk.
- `refs/` are mutable pointers (text files containing a commit ID) that name
  positions in the commit history. `HEAD` is the current canonical
  interpretation. `stable` (or any other named ref) can pin a previous one.

Two operations are first-class:

- `at(ref)` — read the bundle as of a named commit.
- `diff(ref1, ref2)` — claim-level diff between two commits.

This is why dotbio exists in directory form and not as a flat file: the
git-shape is the point, not an analogy.

## Bundle Layout

A dotbio bundle is a directory. The conventional extension is `.bio`. The
following layout is normative; an implementation MUST produce exactly this
structure and MAY add no top-level entries beyond those listed.

```
patient.bio/
├── manifest.json                 # entry point — consumers read this first
├── facts/                        # content-addressed store (immutable)
│   └── <2-char>/<rest-of-sha256>.json
├── commits/                      # append-only interpretation log
│   └── <ISO8601 timestamp>.commit.json
├── views/                        # materialized phenotype-level summaries
│   ├── pgx.md
│   ├── germline-clinical.md
│   └── carrier.md
└── refs/                         # text files; content is a commit ID
    ├── HEAD
    └── stable
```

Notes:

- `facts/<2-char>/` is the first two hex characters of the SHA-256, used as a
  directory shard to avoid huge flat directories. The remaining 62 hex
  characters form the file basename; the suffix is `.json`.
- `commits/<id>.commit.json` filenames embed the ISO8601 timestamp ID
  verbatim, including the `Z` UTC suffix. Filesystems that disallow `:` in
  filenames are not supported by v0.
- `views/` MAY contain additional Markdown files beyond the three shown; the
  set of views is producer-defined and enumerated by `manifest.json`.
- `refs/HEAD` is REQUIRED. Other refs are OPTIONAL.

## Schemas

All JSON in a dotbio bundle is encoded in UTF-8. All files MUST end with a
single trailing newline (`\n`). Files inside `facts/` MUST be the canonical
form defined in **Hashing & Canonicalization**; other JSON files SHOULD be
canonical but are not required to be.

### `manifest.json`

The manifest is the entry point. A consumer reads it first and uses its
content to plan every subsequent read.

| Field             | Type           | Required | Description |
|-------------------|----------------|----------|-------------|
| `schema`          | string         | yes      | Schema identifier, e.g. `"dotbio.v0"`. |
| `subject`         | string         | yes      | Opaque subject identifier. The format does not interpret this string. |
| `created`         | string         | yes      | ISO8601 UTC timestamp of bundle creation. |
| `build`           | string         | yes      | Genome reference build, e.g. `"GRCh38"`. |
| `refs`            | object         | yes      | Map of ref name → commit ID. MUST include `HEAD`. |
| `views`           | array<object>  | yes      | Index of materialized views (see below). |
| `active_rulesets` | array<object>  | yes      | Rulesets used by the latest commit. Each: `{name, version, source_url, license}`. |
| `scopes`          | object         | yes      | What is covered by this bundle (e.g. `germline_variant_count`, `somatic_call_count`). Producer-defined keys. |

Each entry in `views` is an object:

| Field         | Type    | Required | Description |
|---------------|---------|----------|-------------|
| `name`        | string  | yes      | View identifier; matches filename stem under `views/`. |
| `title`       | string  | yes      | Human-readable title. |
| `scope`       | string  | yes      | The kind of question this view answers (e.g. `"pgx"`, `"germline_clinical"`, `"carrier"`). |
| `claim_count` | integer | yes      | Number of claim blocks in the view. |
| `path`        | string  | yes      | Path relative to bundle root, e.g. `"views/pgx.md"`. |
| `est_tokens`  | integer | yes      | Producer's estimate of the view's token cost when consumed. |

Example:

```json
{
  "schema": "dotbio.v0",
  "subject": "subject-a1b2",
  "created": "2026-05-08T09:00:00Z",
  "build": "GRCh38",
  "refs": {
    "HEAD": "2026-05-08T09:00:00Z",
    "stable": "2026-04-15T12:00:00Z"
  },
  "views": [
    {
      "name": "pgx",
      "title": "Pharmacogenomic phenotypes",
      "scope": "pgx",
      "claim_count": 7,
      "path": "views/pgx.md",
      "est_tokens": 1800
    },
    {
      "name": "germline-clinical",
      "title": "Germline clinically actionable findings",
      "scope": "germline_clinical",
      "claim_count": 3,
      "path": "views/germline-clinical.md",
      "est_tokens": 1200
    }
  ],
  "active_rulesets": [
    {
      "name": "cpic",
      "version": "2025.10",
      "source_url": "https://example.org/cpic/2025.10",
      "license": "CC-BY-4.0"
    }
  ],
  "scopes": {
    "germline_variant_count": 4812330,
    "somatic_call_count": 0,
    "callable_fraction": 0.962
  }
}
```

### `facts/<hash>.json`

A fact is a single immutable observation. The SHA-256 of the canonical form
of the fact's JSON content (sorted keys, no whitespace, UTF-8) is the fact's
identity. The hash MUST be computed over the file's exact byte content as it
appears on disk.

The first two hex characters of the SHA-256 are the directory shard; the
remaining 62 form the filename stem.

Required fields on every fact:

| Field   | Type   | Description |
|---------|--------|-------------|
| `kind`  | string | Discriminator. v0 defines `"variant"`. Other kinds are reserved. |

Required fields when `kind == "variant"`:

| Field             | Type    | Required | Description |
|-------------------|---------|----------|-------------|
| `chrom`           | string  | yes      | Chromosome name as in the build (e.g. `"chr7"`). |
| `pos`             | integer | yes      | 1-based position of the reference allele's first base. |
| `ref`             | string  | yes      | Reference allele. Uppercase ACGT, or `"-"` for pure insertions. |
| `alt`             | string  | yes      | Alternate allele. Uppercase ACGT, or `"-"` for pure deletions. |
| `build`           | string  | yes      | Genome reference build, e.g. `"GRCh38"`. MUST match `manifest.build`. |
| `rsid`            | string  | no       | dbSNP rsID if known. |
| `genotype`        | string  | no       | VCF-style genotype string, e.g. `"0/1"`, `"1/1"`. |
| `qual`            | number  | no       | Variant quality score from the upstream caller. |
| `depth`           | integer | no       | Read depth at the site. |
| `callable_region` | boolean | no       | Whether the site lies in the callable region of the upstream pipeline. |

Example (logical content; the on-disk form is the canonical form):

```json
{
  "alt": "T",
  "build": "GRCh38",
  "callable_region": true,
  "chrom": "chr10",
  "depth": 38,
  "genotype": "0/1",
  "kind": "variant",
  "pos": 94781859,
  "qual": 412.7,
  "ref": "C",
  "rsid": "rs4244285"
}
```

If this object is canonicalized and SHA-256'd, the resulting hash determines
its on-disk path. For instance, if the hash were
`a3f1c9e8…62d4`, the file would live at:

```
facts/a3/f1c9e8…62d4.json
```

### `commits/<id>.commit.json`

A commit is one application of a ruleset to the current fact set, producing a
set of claims. Commits form a parent-pointer chain: the root commit has
`parent: null`; every subsequent commit names exactly one parent.

| Field      | Type           | Required | Description |
|------------|----------------|----------|-------------|
| `id`       | string         | yes      | ISO8601 UTC timestamp, e.g. `"2026-05-08T09:00:00Z"`. Filenames embed this verbatim. Must be unique within the bundle. |
| `parent`   | string \| null | yes      | Parent commit's `id`, or `null` for the root commit. |
| `created`  | string         | yes      | ISO8601 UTC timestamp at which the commit was produced. May equal `id`. |
| `ruleset`  | string         | yes      | Ruleset reference in the form `"name@version"`, e.g. `"cpic@2025.10"`. |
| `claims`   | array<object>  | yes      | The claims produced by this commit. May be empty. |

Each entry in `claims` is an object:

| Field                    | Type           | Required | Description |
|--------------------------|----------------|----------|-------------|
| `id`                     | string         | yes      | Stable claim identifier. UUIDv4, or a deterministic hash of `(targets, ruleset, level, claim)`. |
| `claim`                  | string         | yes      | One-line natural-language statement. |
| `targets`                | array<string>  | yes      | SHA-256 fact hashes this claim is about. MUST be non-empty. |
| `level`                  | string         | yes      | One of `"variant"`, `"gene"`, `"haplotype"`, `"phenotype"`, `"clinical_decision"`. |
| `guideline`              | string         | yes      | Cited external guideline with version, e.g. `"CPIC clopidogrel 2022"`. |
| `derivation`             | string         | yes      | Human-readable trace from targets to claim under the named ruleset. |
| `previous_classification`| string         | no       | When this claim re-classifies a prior claim, the prior claim's wording or category. Present on reclassification commits. |

Example:

```json
{
  "id": "2026-05-08T09:00:00Z",
  "parent": "2026-04-15T12:00:00Z",
  "created": "2026-05-08T09:00:00Z",
  "ruleset": "cpic@2025.10",
  "claims": [
    {
      "id": "9b7d3a2e-7c11-4f3e-9a15-2d8a2c0e51d4",
      "claim": "CYP2C19 intermediate metabolizer (*1/*2).",
      "targets": [
        "a3f1c9e8…62d4"
      ],
      "level": "phenotype",
      "guideline": "CPIC CYP2C19 2022",
      "derivation": "rs4244285 heterozygous → *1/*2 diplotype → IM phenotype per CPIC table A."
    },
    {
      "id": "c61f0a99-3a4d-4d2e-b3f0-77f4d1c6a2b1",
      "claim": "BRCA2 c.5946delT — Pathogenic (reclassified from Likely Pathogenic).",
      "targets": [
        "5d2c…f0e1"
      ],
      "level": "variant",
      "guideline": "ACMG/AMP 2015 + ClinGen BRCA2 VCEP 2025",
      "derivation": "PVS1_strong (frameshift in established LoF gene) + PM2 + PS4 → Pathogenic.",
      "previous_classification": "Likely Pathogenic (ACMG/AMP 2015 default weights, 2024-08)"
    }
  ]
}
```

### `refs/<name>`

A ref is a plain UTF-8 text file. Its content is exactly one line: a commit
ID, followed by a single trailing newline (`\n`).

```
2026-05-08T09:00:00Z
```

`refs/HEAD` is REQUIRED. Other refs (`stable`, `pre-reclassification-2026-04`,
etc.) are OPTIONAL and producer-defined. Names MUST match
`[A-Za-z0-9._-]+`. Symbolic refs (a ref pointing at another ref) are NOT
supported in v0.

### `views/*.md`

A view is a Markdown document — human-readable prose intended for direct
consumption by an LLM (or a human). Views are generated by rolling up the
claims of one commit (typically `HEAD`) at the scale named by the view.

A view MUST be self-contained: a consumer reading the view alone, without the
commits, should be able to act on it. Each claim block in a view MUST embed
an HTML comment containing the corresponding `claim_id`, so the consumer can
resolve back to the commit when more detail is needed:

```markdown
## Pharmacogenomics

### Clopidogrel — reduced response expected

<!-- claim_id: 9b7d3a2e-7c11-4f3e-9a15-2d8a2c0e51d4 -->

The subject is a CYP2C19 intermediate metabolizer (`*1/*2`). CPIC guidance
recommends an alternative P2Y12 inhibitor (prasugrel or ticagrelor) where
clinically appropriate.

**Guideline:** CPIC CYP2C19 2022.
**Targets:** 1 variant.
```

A `claim_id` comment MUST appear inside the block describing that claim and
MUST exactly match an `id` in some commit's `claims` array. Producers MAY
embed multiple `claim_id` comments in a single block when the prose
summarizes multiple claims.

## Reading Protocol

This section defines the canonical flow for an LLM consuming a dotbio
bundle. The protocol is designed so that a small read at the top of the funnel
(`manifest.json`) suffices to answer most coarse-grained questions, and
deeper reads are only required when the question demands them.

1. **Read `manifest.json`.** This is always small (target: ~500 tokens). Use
   it to identify available views, their scopes, their token costs, and the
   active rulesets. Decide which view answers the user's question.

2. **Read the chosen view at `views/<name>.md`.** For most questions this is
   sufficient. The view contains prose suitable for direct quotation, with
   `claim_id` HTML comments anchoring each claim.

3. **When more detail is needed, resolve `claim_id → commit → claim →
   derivation`.** Read `refs/HEAD` to get the current commit ID, open
   `commits/<id>.commit.json`, and locate the claim by its `id`. The claim's
   `derivation`, `guideline`, and `ruleset` answer "why does this view say
   this?".

4. **When the raw fact is needed, follow `targets`.** Each target hash names
   a file at `facts/<2-char>/<rest>.json`. This is the bottom of the funnel:
   the immutable observation the claim rests on.

5. **For time travel, read `refs/<name>` to resolve a commit ID, then walk
   `parent` pointers backward.** A consumer asked "what did we say last
   month?" reads `refs/stable`, opens that commit, and proceeds as in step
   3. To reach an arbitrary historical commit, follow `parent` from any
   anchor.

6. **For diff, walk both commit chains and set-diff the `claims` arrays by
   `id`.** Three buckets result: claims only in `ref1`, claims only in
   `ref2`, and claims present in both whose contents differ (typically a
   reclassification, where `previous_classification` will be populated on the
   newer side).

A conforming consumer MUST NOT short-circuit the funnel by reading `facts/`
without first resolving through `commits/`. The fact layer is the substrate;
claims are the only sanctioned interface to it.

## Operations

The following operations form the v0 API surface. They are described
abstractly; an implementation is free to choose CLI shape, library shape, or
both, provided the semantics hold.

### `compile(vcf, metadata, rulesets) → bundle`

Takes upstream variant calls and metadata, plus one or more rulesets, and
produces a fresh bundle:

1. Materialize each input call as a fact (one fact per variant), canonicalize,
   hash, and write to `facts/<shard>/<rest>.json`.
2. Run each ruleset over the fact set; collect resulting claims.
3. Write a single root commit at `commits/<id>.commit.json` with
   `parent: null` and the collected claims. `id` is the ISO8601 UTC timestamp
   at compile time.
4. Materialize the producer-chosen views to `views/*.md`, embedding
   `claim_id` HTML comments.
5. Write `refs/HEAD` containing the root commit's `id`.
6. Write `manifest.json` summarizing the bundle, including `views[]`,
   `active_rulesets[]`, `scopes`, and `refs`.

### `update(bundle, new_ruleset) → bundle`

Re-runs interpretation under a new ruleset, without rewriting facts:

1. Resolve `refs/HEAD` to the current commit ID; this becomes the new
   commit's `parent`.
2. Run `new_ruleset` over the existing fact set (`facts/`) — facts are not
   modified.
3. Write a new commit at `commits/<id>.commit.json` with the resulting
   claims. Reclassifications MUST set `previous_classification` on affected
   claims.
4. Re-materialize affected `views/*.md`, refreshing their `claim_id` anchors.
5. Update `refs/HEAD` to the new commit's `id`. Other refs (e.g. `stable`)
   are not touched and continue to point at their previous targets.
6. Update `manifest.json`: `refs.HEAD`, `active_rulesets`, `views[].claim_count`
   and `views[].est_tokens` for refreshed views, and `created` if the producer
   treats the bundle as re-issued.

### `show(bundle, view) → markdown`

Emits the Markdown for a named view. Equivalent to reading
`views/<view>.md` directly; provided as an operation so that producers and
consumers can agree on a single calling convention.

### `diff(bundle, ref1, ref2) → markdown`

Produces a claim-level diff between two refs. Algorithm:

1. Resolve `ref1` and `ref2` to commit IDs via `refs/`.
2. Walk each commit chain back to the most recent common ancestor (or to the
   root if disjoint).
3. Set-diff the union of claim IDs in scope: emit added, removed, and
   changed claims (where "changed" means same `id`, different `claim`,
   `level`, `targets`, or `guideline`).
4. For changed claims, render `previous_classification` when present.

The output is Markdown intended for direct LLM consumption.

### `expand(bundle, claim_id) → markdown`

Given a `claim_id`, emit the full evidence chain:

1. Locate the claim in the latest commit reachable from `HEAD` (or in the
   commit whose ID the caller specifies).
2. Emit: the claim text, the `level`, the cited `guideline`, the `ruleset`
   that produced it, the human-readable `derivation`, and a list of resolved
   target facts (each fact's hash and key fields).
3. If `previous_classification` is set, emit it alongside.

`expand` is the canonical drill-down primitive used in step 3 of the
**Reading Protocol**.

## Hashing & Canonicalization

Fact identity in dotbio is the SHA-256 of the canonical JSON form of the
fact's content. The canonical form is defined as follows. The rules are
inspired by RFC 8785 (JSON Canonicalization Scheme, JCS); v0 specifies a
narrower profile sufficient for this format:

1. **Encoding.** UTF-8.
2. **Whitespace.** No insignificant whitespace. No spaces between tokens. No
   indentation. The file ends with a single trailing `\n` after the closing
   `}`. The trailing `\n` is part of the file but is NOT part of the bytes
   hashed: the SHA-256 is computed over the canonical JSON value bytes only,
   not the trailing newline.
3. **Object keys.** All object keys MUST be sorted lexicographically by their
   UTF-8 byte sequence (equivalent to sorting by Unicode code point for
   BMP-only keys, which v0 fields are).
4. **No duplicate keys.** Implementations MUST reject input with duplicate
   keys.
5. **Numbers.** Integers are emitted without leading zeros, without a `+`
   sign, without a decimal point. Non-integers are emitted in the shortest
   round-trip ECMAScript form (the "Number.prototype.toString" canonical
   form). `NaN`, `+Infinity`, and `-Infinity` are not permitted.
6. **Strings.** Strings are emitted with `\"`, `\\`, `\b`, `\f`, `\n`, `\r`,
   `\t` for the standard control characters, and `\u00XX` for other control
   characters below `0x20`. All other characters are emitted as their literal
   UTF-8 bytes. The forward slash `/` is NOT escaped.
7. **Booleans / null.** `true`, `false`, `null` literally.
8. **Arrays.** Element order is preserved (arrays are not sorted).

The hash is then:

```
sha256( canonical_bytes( fact_object ) )  →  64 hex chars (lowercase)
```

The first two hex characters become the directory shard; the remaining 62
become the filename stem. The on-disk file is exactly
`canonical_bytes(fact_object) + "\n"`.

Commits, refs, and views are NOT content-addressed. The canonical form
SHOULD still be used for `commits/*.commit.json` and `manifest.json` to make
diffs between bundle revisions stable, but this is a recommendation, not a
requirement, in v0.

## Versioning

Three things are versioned independently in dotbio.

### Schema version

The `schema` field of `manifest.json` carries the format version, e.g.
`"dotbio.v0"`. A consumer that does not recognize the schema string MUST
refuse to read the bundle. There is no compatibility window between major
schema versions in v0 — a `v0` consumer does not read a hypothetical
`v1` bundle and vice versa.

### Ruleset version

Every commit names exactly one ruleset in the form `"name@version"`. The
`active_rulesets[]` array in `manifest.json` enumerates the rulesets used by
the latest commit; older commits' rulesets are recoverable by reading the
commits themselves. A reclassification produced by upgrading a ruleset MUST
be recorded as a new commit, never as an in-place edit of the old commit.

### Refs

Refs are mutable. `HEAD` advances on every `update`. Producers MAY introduce
named refs at any commit (`stable`, `pre-reclassification-2026-04`, etc.).
v0 does not specify a reflog: history of where a ref previously pointed is
not preserved by the format. Consumers that need that history must record it
out of band.

## Non-Goals

dotbio is deliberately small. The following are out of scope for v0 and any
implementation that pretends otherwise is not conforming.

- **Not a database.** dotbio bundles are read-mostly artifacts. There is no
  query language, no index files beyond `manifest.json`, no server protocol.
  Build a database on top if you need one.
- **Not a privacy layer.** Bundles contain biological data about a subject.
  Privacy — at-rest encryption, access control, redaction, key escrow — is
  the responsibility of the carrier (the filesystem, archive format, or
  transport that holds the bundle), not the format. dotbio specifies neither
  encryption envelopes nor access tokens.
- **Not for clinical use without validation.** This is a v0 draft. The format
  has no validation, certification, or regulatory clearance. Implementations
  used in patient care are responsible for their own clinical validation.
- **Not a multi-subject format.** A bundle describes one subject. Combining
  subjects is out of scope; see **Open Questions**.
- **Not a raw-data archive.** Facts are derived observations, not source
  reads. The upstream BAM/FASTQ live elsewhere; the bundle does not embed
  them.

## Open Questions

The following are known unresolved areas. They are listed so that consumers
of v0 can plan around them and so that v1 work has a starting list.

- **Composability across subjects.** A cohort or family is several bundles.
  Should there be a higher-level container with cross-bundle refs? What
  happens to fact deduplication across subjects (the same canonical
  variant fact has the same hash everywhere)?
- **Multi-omics extensions.** v0 defines `kind: "variant"`. Expression,
  methylation, proteomics, and microbiome facts have different natural
  scales. What does the `kind` discriminator look like at v1, and do views
  need scope vocabularies beyond the current ad-hoc producer choice?
- **Signing and attestation.** Should commits be signed? Should the
  `ruleset` reference be a content hash of the ruleset rather than a
  `name@version` string? Is there a need for a third-party attestation that
  a given commit was produced by a given ruleset on a given fact set?
- **Reflog.** Refs are mutable but their history is not preserved. Some
  consumers will want to know "what did `HEAD` point at before today's
  `update`?" — a `refs/logs/<name>` directory analogous to git's reflog
  is one candidate.
- **View staleness.** When `update` produces new claims, the format requires
  re-materializing affected views, but does not specify *how* a producer
  decides which views are affected. A view dependency declaration in
  `manifest.json` may be needed.
- **Canonicalization of commits.** v0 only requires canonicalization for
  facts. Commits are recommended-canonical. Promoting that to required would
  let commits also be content-addressed, at the cost of a commit ID scheme
  change.
- **Deletion / redaction.** Facts are immutable by construction, which is
  the point — but it conflicts with right-to-be-forgotten regimes. A
  redaction protocol (replace fact content with a tombstone of the same
  hash? remove the file and accept that downstream commits dangle?) is not
  specified.
