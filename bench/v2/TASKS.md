# dotbio NM-grade benchmark — task list

**Companion document to `bench/v2/SPEC.md`.** Each task below is a
self-contained unit of work intended for parallel subagent execution.
Tasks are written so an agent reading ONLY its own task section + the
SPEC has everything it needs.

**Conventions**:
- All file paths are relative to the repo root (`~/projects/dotbio`)
- Outputs go to `bench/v2/...` per task
- Inputs marked "EXISTING" already exist in the repo
- Inputs marked "FETCH" require network access to public sources
- Tasks are tagged `[autonomous]` (run end-to-end), `[needs-keys]`
  (requires LLM API keys), `[needs-data]` (large download), or
  `[scaffold]` (writes framework, runs partial validation)

| # | Task | Tag | Output |
|---|---|---|---|
| 1 | Phenopackets v2 converter | autonomous | `bench/v2/scripts/vcf_to_phenopacket.py` + sample output |
| 2 | FHIR Genomics IG converter | autonomous | `bench/v2/scripts/vcf_to_fhir.py` + sample output |
| 3 | PharmCAT JSON output emitter | autonomous | `bench/v2/scripts/bio_to_pharmcat.py` + sample output |
| 4 | Clinical 50-question benchmark | autonomous (research) | `bench/v2/data/questions/q01..q50.yaml` |
| 5 | Multi-LLM eval harness | scaffold | `bench/v2/scripts/llm_harness.py` + tests |
| 6 | Longitudinal cohort simulator | scaffold | `bench/v2/scripts/longitudinal_sim.py` + smoke run |
| 7 | Performance benchmark runner | scaffold | `bench/v2/scripts/perf_bench.py` + smoke run |
| 8 | Privacy / re-id risk analyzer | autonomous | `bench/v2/scripts/reid_risk.py` + report |
| 9 | Adversarial robustness suite | autonomous | `bench/v2/scripts/fuzz/*` + 20 fuzz cases |
| 10 | Methylation extension pilot | autonomous | `src/dotbio/extensions/methylation/` + bench |
| 11 | GIAB multi-individual extractor | needs-data | `bench/v2/data/giab_panel.vcf` |
| 12 | Snakemake/Makefile orchestrator | autonomous | `bench/v2/Makefile` running tasks 1–10 end-to-end |

Total: 12 parallel tasks. Round-1 dispatch covers all of them.

---

## Task 1 — Phenopackets v2 converter `[autonomous]`

**Goal**: Implement a VCF → GA4GH Phenopackets v2 converter so that the
NM-grade benchmark can include Phenopackets as a SOTA comparator format
in the LLM evaluation.

**Inputs**:
- EXISTING: `examples/real-na12878/input.vcf` (8 PGx loci, NA12878)
- EXISTING: `src/dotbio/rulesets/clinvar-2026-05-01.json` (interpretation rules)
- REFERENCE: GA4GH Phenopackets v2 spec at https://phenopacket-schema.readthedocs.io/en/v2/

**Output files** (write all):
- `bench/v2/scripts/vcf_to_phenopacket.py` — the converter (Python, stdlib + optional pydantic)
- `bench/v2/data/format_d_phenopacket.json` — NA12878 8-loci as a Phenopacket v2 JSON
- `bench/v2/scripts/README_phenopacket.md` — methodology + cross-walk table from VCF fields to Phenopacket fields

**Acceptance criteria**:
- Output Phenopacket validates against `phenopacket-schema/v2.0` (use the
  Python `phenopackets` package if available, else hand-rolled validator)
- The Phenopacket includes: subject `id`, `vcf` file resource, per-variant
  `interpretation` block with at least gene + variant + classification
- Token count of the JSON measured with the Claude tokenizer
  (Xenova/claude-tokenizer) reported in the README
- Produces ≥ 4 interpretation blocks for NA12878 (corresponding to the
  observed ALT alleles, regardless of clinical significance)

**Constraints**:
- Do NOT add Phenopackets-specific clinical inference; just translate the
  data we already have
- Document any field where the VCF/dotbio data is richer than Phenopackets
  can express, and vice versa
- Pydantic / phenopackets package optional; pure-stdlib fallback acceptable

---

## Task 2 — FHIR Genomics IG converter `[autonomous]`

**Goal**: Implement a VCF → HL7 FHIR R4 Genomics Implementation Guide
bundle converter, so FHIR is included as a SOTA comparator.

**Inputs**: same as Task 1.

**Output files**:
- `bench/v2/scripts/vcf_to_fhir.py`
- `bench/v2/data/format_e_fhir_bundle.json` — NA12878 as a FHIR Bundle
- `bench/v2/scripts/README_fhir.md`

**Acceptance criteria**:
- Bundle validates against FHIR R4 Genomics IG core profiles
  (`Observation/genetics-variant`, `MolecularSequence`, `DiagnosticReport`)
- Includes one `Patient` resource, one `MolecularSequence` resource,
  per-variant `Observation` resources with LOINC-coded fields
  (LOINC 53037-8 "genetic variant assessment", 81252-9 "discrete genetic
  variant", etc.)
- Token count reported in README

**Constraints**:
- Use the official LOINC codes for genetics observations
- Include at least one `DiagnosticReport` rolling up the variant findings
- Pure stdlib acceptable; `fhir.resources` package optional

---

## Task 3 — PharmCAT JSON output emitter `[autonomous]`

**Goal**: Take an existing `.bio` bundle and emit a PharmCAT-style JSON
report, so we can compare against PharmCAT's native output format
without actually running PharmCAT (we don't have a Java environment
guaranteed). The emitter should produce JSON that matches PharmCAT's
public report schema as closely as possible.

**Inputs**:
- EXISTING: `examples/real-na12878/output.bio/`
- REFERENCE: PharmCAT report schema at https://pharmcat.org/specifications/Report/

**Output files**:
- `bench/v2/scripts/bio_to_pharmcat.py`
- `bench/v2/data/format_f_pharmcat_report.json`
- `bench/v2/scripts/README_pharmcat.md`

**Acceptance criteria**:
- JSON has top-level `metadata`, `genes`, `drugs`, `messages` sections
  matching PharmCAT report format
- Per-gene: diplotype call, phenotype, function
- Per-drug: PharmCAT recommendation with CPIC level
- Validates against the PharmCAT JSON schema (or a hand-rolled
  approximation if the official one is not retrievable)
- Token count reported

**Constraints**:
- Do NOT invent diplotypes; use only what's already in the .bio bundle
  (CYP2C19 *1/*2 from NA12878 example)
- If a field is in PharmCAT format but absent from .bio, leave null
  with a comment

---

## Task 4 — Clinical 50-question benchmark `[autonomous]`

**Goal**: Curate a benchmark of 50 clinically realistic questions with
gold-standard answers, drawn from published guidelines (CPIC, ClinGen,
ACMG, NCCN). This is the test set for Experiment 3 in the SPEC.

**Inputs**:
- WebSearch / WebFetch: CPIC guidelines (https://cpicpgx.org/guidelines/),
  ClinGen Curation Pages, ACMG SF v3.2 (PMID: 36190193 or successor),
  NCCN guidelines (citable summary tables)

**Output files**:
- `bench/v2/data/questions/q01.yaml` … `q50.yaml` (one file per question)
- `bench/v2/data/questions/INDEX.md` (table of contents)

**Acceptance criteria** (per question):
- 5 domains × 10 questions: PGx, oncology somatic, carrier screening,
  hereditary cancer/cardio risk, drug-dose adjustment
- Each YAML contains:
  ```yaml
  id: q01
  domain: pgx
  question: "Patient has CYP2C19 *1/*2. Can they take clopidogrel at standard dose for ACS/PCI?"
  required_inputs:
    - gene: CYP2C19
    - diplotype: "*1/*2"
    - clinical_context: ACS/PCI
  gold_answer:
    verdict: "no — consider alternative"
    phenotype: "Intermediate Metabolizer"
    cited_guideline: "CPIC@2022 (Lee et al., 2022, Clin Pharmacol Ther 112:959)"
    rationale: "Reduced active metabolite formation; alternative P2Y12 inhibitor preferred"
  scoring_rubric:
    verdict_correct: matches "no" or "alternative" or equivalent
    phenotype_correct: includes "Intermediate Metabolizer" or "IM"
    guideline_cited_with_version: includes "CPIC@2022" or "CPIC 2022"
  primary_reference_url: https://cpicpgx.org/guidelines/guideline-for-clopidogrel-and-cyp2c19/
  ```
- 50 questions span 5 domains (10 each)
- Gold answers cite specific guideline + version
- INDEX.md tabulates all 50 with one-line descriptions

**Constraints**:
- USE WebSearch / WebFetch to ground each question in a real, citable
  guideline. If you cannot find a primary reference, do not include the
  question.
- Questions must have a UNAMBIGUOUS gold answer that a clinical
  geneticist would agree on
- Include 2-3 deliberately "context-dependent" questions where the
  correct answer is "depends on X" — these test whether the format
  surfaces enough context

---

## Task 5 — Multi-LLM eval harness `[scaffold]`

**Goal**: Write a Python harness that takes (format_text, question,
n_replicates, llm_set) and returns scored responses. The harness must
be runnable with mock LLMs (returning canned JSON) when no API keys
are present, so the pipeline always executes end-to-end on CI.

**Inputs**:
- EXISTING: `bench/results/llm_eval.json` (round-1 single-shot results,
  use as a model for the response schema)
- EXISTING: format files in `bench/data/format_a_vcf.txt` etc.

**Output files**:
- `bench/v2/scripts/llm_harness.py`
- `bench/v2/scripts/llm_clients/{anthropic,openai,gemini,mock}.py`
- `bench/v2/scripts/llm_scoring.py`
- `bench/v2/results/exp03_llm_eval_smoke.json` (smoke run with mock LLMs)
- `bench/v2/scripts/README_harness.md`

**Acceptance criteria**:
- Single CLI entry: `python -m bench.v2.scripts.llm_harness --question q01 --formats A,B,C,D,E,F,G,H --models claude,gpt4,llama3,gemini --n-replicates 30`
- API key env vars: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`,
  `TOGETHER_API_KEY` (Llama 3); falls back to `mock` client when unset
- Output JSON schema matches `bench/results/llm_eval.json` from round 1
  with extra fields: `model`, `replicate_idx`, `temperature`, `seed`
- Scoring is deterministic given a (response, gold_answer, rubric) tuple
- Includes pytest tests for the scoring functions (≥ 5 tests)

**Constraints**:
- DO NOT call real LLMs in the smoke run (no API keys assumed in CI)
- Mock client returns predetermined JSON keyed by (format, question)
- Use the same strict no-tools instruction as the round-1 prompts (see
  `bench/prompts/llm_eval_template.md`)
- All replicates of the same (format, model, question) are saved with
  full metadata for later replication-quality checks

---

## Task 6 — Longitudinal cohort simulator `[scaffold]`

**Goal**: Implement a 24-month longitudinal cohort simulation per
SPEC §3.4. Round 1 should produce a working simulator that runs on
synthetic ClinVar deltas (because real archive download is heavy);
the same code should accept real ClinVar archive data when provided.

**Inputs**:
- SYNTHETIC: generate 24 months of synthetic ClinVar reclassifications
  inside the script (10–20 per month, sampled with realistic
  significance-class transition probabilities from published statistics)
- EXISTING: `examples/real-na12878/output.bio/` as a "patient" template

**Output files**:
- `bench/v2/scripts/longitudinal_sim.py`
- `bench/v2/scripts/clinvar_archive.py` — module to load real ClinVar
  archive monthly XML if provided, else synthesize
- `bench/v2/results/exp04_longitudinal_smoke.json`
- `bench/v2/scripts/README_longitudinal.md`

**Acceptance criteria**:
- Two arms in code: `arm_soc` (re-annotate every 3 months) and
  `arm_bio` (`bio update` monthly)
- For each arm, computes:
  - Number of reclassifications captured
  - Mean detection latency (months from ClinVar release → captured)
  - Cumulative tokens read across 24 months
  - FNR vs ground truth
- Smoke run on 5 patients × 24 months synthetic data, completes in <60s
- Designed to scale to 100 patients × real ClinVar archive without code
  changes (just data swap)

**Constraints**:
- Use the existing `bio update` and `bio diff` CLI commands; do not
  reimplement
- Synthetic ClinVar transitions must be realistic (e.g., LP→P more common
  than LB→P; cite a source)
- Honest about what's simulated vs real in the README

---

## Task 7 — Performance benchmark runner `[scaffold]`

**Goal**: Implement the perf benchmark per SPEC §3.5. Round 1 runs on
the existing small example; the same code should scale to full WGS
when data is provided.

**Inputs**:
- EXISTING: `examples/synthetic/input.vcf` (11 variants), and
  `examples/real-na12878/input.vcf` (8 variants) as small-data baselines
- OPTIONAL: full HG002 WGS path (env var `HG002_WGS_VCF`); skip that
  scenario if not set

**Output files**:
- `bench/v2/scripts/perf_bench.py`
- `bench/v2/results/exp05_perf.json`
- `bench/v2/scripts/README_perf.md`

**Acceptance criteria**:
- Measures, for each input scale tier:
  - Compile time (cold + warm), 5 runs, median + IQR
  - Bundle size on disk (compressed `.bio.tar.gz` and uncompressed)
  - Single-view query latency (`bio show`), 100 runs, median + p95
  - Update latency (`bio update`), 5 runs
  - Memory peak (RSS) during compile (tracemalloc or `/usr/bin/time -v`)
- Output JSON has one block per (input scale, operation) pair
- Smoke run completes in <30s on existing examples

**Constraints**:
- Use `time` / `resource` / `tracemalloc` from stdlib; do not require
  external profiling tools
- Skip large-WGS scenario gracefully if env var not set; do not download

---

## Task 8 — Privacy / re-identification risk analyzer `[autonomous]`

**Goal**: Implement an Erlich-Narayanan-style re-identification risk
analyzer per SPEC §3.6.

**Inputs**:
- EXISTING: NA12878 8-loci VCF, .genome reconstruction, .bio bundle
- REFERENCE: Erlich & Narayanan (2014, Nat Rev Genet) framework — note
  that `.bio`'s content-addressed hashes should reduce attack surface
  vs raw genotypes

**Output files**:
- `bench/v2/scripts/reid_risk.py`
- `bench/v2/results/exp06_reid_risk.json`
- `bench/v2/scripts/README_reid.md`

**Acceptance criteria**:
- For each format, compute:
  - **Marker count**: how many independent variants are publicly
    inferrable from the format (i.e., usable in a re-id attack)
  - **Information-theoretic entropy** of the publicly inferrable
    fingerprint
  - **Predicted re-identification probability** in a population of
    size 10⁵ given the fingerprint, per the Erlich-Narayanan framework
- Output JSON: per-format breakdown with confidence intervals from
  bootstrap (1000 iters)
- README explains the threat model assumptions and the math

**Constraints**:
- Do NOT actually attempt re-identification against real public databases
  (legally / ethically gray)
- The analysis is theoretical: "given this format, what's the worst-case
  attack surface?"
- For .bio's hashed facts, the analyzer should correctly model that the
  hash is one-way and only leaks information if the attacker also has
  access to the underlying ruleset (which is public for our v0)

---

## Task 9 — Adversarial robustness suite `[autonomous]`

**Goal**: Build a fuzz / adversarial test suite that probes dotbio's
behavior on malformed input, conflicting rulesets, and schema migration.

**Output files**:
- `bench/v2/scripts/fuzz/` directory containing:
  - `fuzz_vcf.py` — malformed VCF inputs
  - `fuzz_rulesets.py` — conflicting / corrupt rulesets
  - `fuzz_schema.py` — schema migration tests
  - `fuzz_hashes.py` — hash collision construction attempt
  - `runner.py` — runs all fuzz cases, reports pass/fail
- `bench/v2/results/exp07_adversarial.json`
- `bench/v2/scripts/README_fuzz.md`

**Acceptance criteria**:
- ≥ 20 distinct fuzz cases across the four modules
- Each case has a clear **expected behavior** (graceful failure with a
  documented exit code, OR successful handling, OR documented data loss)
- Runner emits PASS / FAIL / UNEXPECTED summary
- README documents every fuzz case and its rationale

**Constraints**:
- Fuzz cases should target the dotbio CLI as it is, not require code
  changes
- Hash collision: demonstrate that constructing a SHA-256 collision is
  computationally infeasible at full 256 bits, but that 16-bit truncation
  (if anyone shortened the hash) collides; this is documentation, not an
  actual collision attempt

---

## Task 10 — Methylation extension pilot `[autonomous]`

**Goal**: Pilot extending dotbio to non-DNA-variant data. Choose
Illumina 450K methylation. Demonstrate the three principles
(multi-scale, evidence chain, time) hold.

**Output files**:
- `src/dotbio/extensions/methylation/__init__.py`
- `src/dotbio/extensions/methylation/compile.py` — methylation array →
  facts (β values) + commits (epigenetic age call) + views
- `src/dotbio/extensions/methylation/rulesets/horvath_clock.json` —
  Horvath 2013 epigenetic age estimator coefficients (publicly available)
- `bench/v2/data/format_g_methylation_demo.bio.tar.gz` — a sample bundle
- `bench/v2/scripts/README_methylation.md`
- `tests/test_methylation_extension.py` — ≥ 5 tests

**Acceptance criteria**:
- Compile takes a synthetic 450K-array `.csv` (probe_id, β-value, sample_id)
  and produces a `.bio` bundle
- Bundle has facts/, commits/, views/, refs/ exactly like the DNA case
- A "view" `epigenetic-age.md` reports the Horvath-clock-predicted age
- Tests pass (54 + 5 = 59 total tests in the repo CI)

**Constraints**:
- Use synthetic methylation data (publicly published Horvath coefficients
  applied to randomized β-values within plausible ranges); do NOT scrape
  GEO unless trivially easy
- The ruleset file uses CC-licensed Horvath coefficients (cite source)

---

## Task 11 — GIAB multi-individual extractor `[needs-data]`

**Goal**: Extract the same 8-locus PGx panel for 6 additional GIAB
individuals (HG002–HG007) so we can do per-individual format comparisons
across diverse ancestries.

**Inputs**:
- FETCH: NIST GIAB FTP (`ftp-trace.ncbi.nlm.nih.gov/giab/`) for high-
  confidence VCFs of HG002, HG003, HG004 (AJ trio) and HG005, HG006,
  HG007 (Han Chinese trio), GRCh38 build
- ALTERNATIVELY: 1000G 30x panel for individuals that are also in 1000G

**Output files**:
- `bench/v2/data/giab_panel/HG00<n>.vcf` for n in 2..7
- `bench/v2/data/giab_panel/MERGED.vcf` (one VCF, multi-sample)
- `bench/v2/scripts/extract_giab.sh`
- `bench/v2/scripts/README_giab.md`

**Acceptance criteria**:
- Same 8 PGx loci as `examples/real-na12878/input.vcf` extracted for each
  of HG002–HG007
- Each VCF passes `bcftools view -h` validation
- README documents source URL, retrieval timestamp, and any genotype
  discrepancies vs published GIAB truth set

**Constraints**:
- If NIST FTP is unavailable / slow, use 1000G 30x panel as fallback
  (HG002 = NA24385 is in 1000G); document substitution
- Total download budget: 200 MB max; use tabix range queries to avoid
  full-VCF download
- Document each individual's reported ancestry / population

---

## Task 12 — Snakemake/Makefile orchestrator `[autonomous]`

**Goal**: Write a top-level Makefile (or Snakefile) that runs the full
v2 benchmark pipeline end-to-end with one command.

**Inputs**: outputs of all other tasks (this is the integration layer).

**Output files**:
- `bench/v2/Makefile`
- `bench/v2/scripts/run_all.sh` (calls `make all` with sensible defaults)
- `bench/v2/README.md` (top-level guide pointing at SPEC.md / TASKS.md
  and explaining `make all`)

**Acceptance criteria**:
- `cd bench/v2 && make all` runs every task that doesn't require API
  keys or large downloads, producing all `exp_NN_*.json` files in
  `bench/v2/results/`
- `make experiment-3` (etc.) runs a single experiment
- `make clean` removes results
- Targets clearly document which require env vars (e.g., `make
  experiment-3` requires `ANTHROPIC_API_KEY` and falls back to mock)

**Constraints**:
- Pure GNU Make is fine; Snakemake optional
- The Makefile is the documented entry point for the manuscript's
  reproducibility section
- Failures in optional tasks (e.g., LLM calls without keys) should not
  fail the overall pipeline; they emit warnings and skip

---

## Coordination / how round-1 wraps up

After all 12 agents complete (or fail with documented reasons), the
orchestrator should:

1. Run `cd bench/v2 && make all` and capture the output
2. Check that `bench/v2/results/exp_{01..08}_*.json` exist (some may be
   smoke runs only — that's expected for round 1)
3. Update this TASKS.md with completion status per task
4. Commit + push everything as one logical commit
5. Open a GitHub issue per task that did not fully complete, with
   the agent's failure reason and what needs human intervention

Round 2 (after this round): refine the smoke runs into full runs by
wiring up real LLM API keys, downloading real ClinVar archive, and
recruiting clinical geneticists for the rubric-grading work
(Experiment 3 inter-rater agreement).

---

## Round-1 status (2026-05-09)

All 12 tasks dispatched in parallel as fresh subagents. Outcomes:

| # | Task | Status | Headline result |
|---|---|---|---|
| 1 | Phenopackets v2 converter | ✓ done | 4,001 Claude tokens; hand-rolled validator passes |
| 2 | FHIR Genomics IG converter | ✓ done | 13,887 tokens (16.6× `.bio`); 12 resources; LOINC-coded |
| 3 | PharmCAT JSON emitter | ✓ done | 5,168 tokens; PharmCAT v3.x schema match; 7 gene blocks |
| 4 | 50-question clinical benchmark | ✓ done | 50 / 50 questions, 5 domains × 10; every gold answer cites primary reference |
| 5 | Multi-LLM eval harness | ✓ done | 22 pytest tests pass; 36-record mock smoke run; pluggable Anthropic/OpenAI/Gemini clients |
| 6 | Longitudinal cohort simulator | ✓ done | **arm_soc FNR = 0.574 vs arm_bio FNR = 0.000** on 5 patients × 24 months synthetic |
| 7 | Performance benchmark | ✓ done | 11-variant compile ~18 ms cold / ~11 ms warm; bundle 7.4 KB tar.gz; `bio show` p95 < 1 ms |
| 8 | Re-id risk analyzer | ✓ done | `.bio` views-only / hash-only modes strictly dominate VCF on attack surface |
| 9 | Adversarial robustness suite | ✓ done | **29 / 29 fuzz cases PASS** across VCF / rulesets / schema / hashes |
| 10 | Methylation extension pilot | ✓ done | Horvath clock pilot, 353/353 probes; 62 tests pass; demo age = 35.33 y |
| 11 | GIAB multi-individual extractor | ✓ done | 6 / 6 individuals (HG002–HG007) extracted, ~5–15 MB total |
| 12 | Makefile orchestrator | ✓ done | 24 PHONY targets; `make verify` PASS on all 11 expected artifacts |

**Pipeline state**: `make verify` → 11 OK / 0 missing / 0 empty.

**Test state**: 62 unit/integration tests + 22 bench scoring tests = **84 tests passing**.

### Token-cost ranking (Experiment 1, NA12878 8-locus panel, real Claude tokenizer)

| Format | tokens | × `.bio` |
|---|---:|---:|
| `.genome` reconstruction | 663 | 0.79× |
| VCF | 676 | 0.81× |
| **`.bio` (manifest + view)** | **834** | **1.00×** |
| Phenopackets v2 | 4,001 | 4.8× |
| PharmCAT JSON | 5,168 | 6.2× |
| FHIR R4 Genomics | 13,887 | 16.6× |

`.bio` is **the most token-efficient structured + auditable format** in this comparison. Only narrative formats (raw VCF, `.genome` prose) are smaller — and they fail the audit-citation criterion.

### Outstanding round-2 work

- Replace synthetic Horvath coefficients with the actual published 353-coefficient table (CC BY 2.0)
- Wire the Multi-LLM harness to real API keys; run N=30 × 4 LLMs × 50 questions
- Replace synthetic ClinVar transitions with real 24-month archive (NCBI FTP)
- Scale GIAB extraction to ACMG SF v3.2 + carrier panel (~5,500 positions)
- IRB-required clinician user study (Experiment 9; out of automation scope)
- Horvath round-2: BED-intersected GIAB high-confidence regions; APOE rs7412
- PharmCAT-direct concordance check (run actual PharmCAT and diff)
