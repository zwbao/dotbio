# Adversarial robustness suite — Experiment 7

**Spec section**: `bench/v2/SPEC.md` §3.7
**Task**: `bench/v2/TASKS.md` Task 9
**Output**: `bench/v2/results/exp07_adversarial.json`
**Generated**: 2026-05-09

This suite probes dotbio v0's behavior on inputs the happy path doesn't
exercise: malformed VCFs, conflicting/corrupt rulesets, schema-migration
edges, and the cryptographic robustness of the content-addressed
`facts/` layer. It targets the dotbio CLI **as it currently exists**;
no source-code changes are required.

The runner classifies each case as:

- **PASS** — the documented expected behavior was observed.
- **FAIL (doc'd)** — failed, but the exit code is in the documented
  expected-exit-code set. (Reserved for future cases that we expect to
  fail until v1 lands; currently empty.)
- **UNEXPECTED** — failed outside the documented expectation. These
  block the suite (the runner's process exit is non-zero if any
  UNEXPECTED case occurs).

Run:

    cd /path/to/dotbio
    python bench/v2/scripts/fuzz/runner.py
    # filter:
    python bench/v2/scripts/fuzz/runner.py --filter vcf

The runner writes the full report to
`bench/v2/results/exp07_adversarial.json`.

---

## Summary (latest run)

29 cases, 29 PASS, 0 FAIL, 0 UNEXPECTED, ~3 s wall time on a 2024 M-series.

Per-module breakdown:

| Module           | Cases | Focus                                       |
|------------------|-------|---------------------------------------------|
| `fuzz_vcf`       | 11    | Malformed / pathological VCF inputs         |
| `fuzz_rulesets`  | 7     | Conflicting + corrupt + missing rulesets    |
| `fuzz_schema`    | 7     | Manifest tampering & forward-compat         |
| `fuzz_hashes`    | 4     | SHA-256 collision (in)feasibility           |

---

## Module 1 — `fuzz_vcf.py`

Each case writes a synthetic VCF, runs `bio compile`, and checks
behavior.

| ID    | Title                                     | Expected            |
|-------|-------------------------------------------|---------------------|
| vcf01 | empty file                                 | successful (zero facts) |
| vcf02 | header-only VCF                            | successful (zero facts) |
| vcf03 | missing REF allele (REF='.')               | successful (lookup miss) |
| vcf04 | invalid genotype tokens (`X/Y`)            | successful (no crash; lookup miss) |
| vcf05 | mixed chromosome naming (no `chr` prefix)  | successful (rsID-keyed lookup) |
| vcf06 | truncated record (<8 columns)              | documented data loss (vcfio drops) |
| vcf07 | non-ASCII sample name                      | successful |
| vcf08 | 5 kB ALT allele                            | successful (no OOM) |
| vcf09 | negative POS                               | documented data loss (v0 doesn't validate range; flagged for v1 strict mode) |
| vcf10 | duplicate VCF records                      | successful — CAS deduplicates to 1 fact |
| vcf11 | nonexistent input file path                | graceful failure (rc≠0) |

**Documented data-loss notes**:
- **vcf06** — `vcfio.parse_vcf` requires ≥ 8 columns and silently
  skips shorter lines. v1 should surface a warning per skipped row.
- **vcf09** — POS range is not validated. v1 should add a
  per-build coordinate sanity check.

## Module 2 — `fuzz_rulesets.py`

Each case touches the rule-loading or update path. Where a case needs
a "non-existent ruleset", it relies on the package-resource loader
(`importlib.resources`) refusing to open a missing file — itself a
robustness property.

| ID   | Title                                              | Expected            |
|------|----------------------------------------------------|---------------------|
| rs01 | compile with unknown ruleset name                  | graceful failure    |
| rs02 | update with unknown ruleset version                | graceful failure    |
| rs03 | two real ClinVar versions disagreeing (2026-05-01 → 2026-05-08) | successful — `bio diff` surfaces the reclassification |
| rs04 | corrupt ruleset filename                           | graceful failure    |
| rs05 | made-up ruleset name on update                     | graceful failure    |
| rs06 | double-compile without `--force`                   | graceful failure (rc=2); `--force` then succeeds |
| rs07 | `bio log` on a bundle whose `refs/HEAD` was deleted | graceful failure   |

**rs03 is the canonical reclassification probe.** The two ClinVar
snapshots differ on at least one variant by design; this case asserts
that `bio diff` surfaces the change rather than silently merging.

## Module 3 — `fuzz_schema.py`

Each case mutates a freshly compiled bundle's manifest or invokes a
read command with bad arguments.

| ID   | Title                                              | Expected            |
|------|----------------------------------------------------|---------------------|
| sc01 | manifest stamped with future `schema_version`      | documented data loss — v0 reader is permissive; will be a hard gate in v1 |
| sc02 | unknown manifest top-level field                   | successful — round-trips unchanged (forward-compat) |
| sc03 | missing `active_rulesets` in manifest              | successful — update path uses `.get(default=[])` |
| sc04 | `show --view no-such-view`                         | graceful failure with helpful list of valid views |
| sc05 | `show` on bundle with no `manifest.json`           | graceful failure |
| sc06 | `expand` on unknown claim id                       | graceful failure with explanatory message |
| sc07 | `diff` with non-existent ref                       | graceful failure |

**sc01 / forward-compat note**: dotbio v0 does not yet enforce
`schema_version`. A v1 reader will need to refuse manifests claiming
`schema_version > supported_version`. This case provides the baseline
the v1 PR can test against.

## Module 4 — `fuzz_hashes.py`

Documentation, not an attack. Four cases:

| ID   | Title                                              | What it shows |
|------|----------------------------------------------------|---------------|
| hs01 | full SHA-256 collision is computationally infeasible | Birthday-bound work 2^128 ≈ 3.4 × 10^38 hashes; at 10^10 H/s on a single GPU ≈ 1.1 × 10^21 years ≈ 8 × 10^10× the age of the universe. We rely on this for the CAS layer. |
| hs02 | no public full-SHA-256 collision known (as of 2026-05-09) | Reference: best published attacks are reduced-round (e.g., Mendel-Nad-Schl 2013, 28/64 rounds). Full-round collision: open. |
| hs03 | 16-bit truncation collides quickly (birthday demo) | Birthday-attacks SHA-256 truncated to 16 bits; finds a colliding pair in O(2^8) ≈ 256 random inputs. **Demonstrates why we MUST NOT shorten the content-address.** |
| hs04 | dotbio bundles store the full 256-bit digest        | Inspects `examples/real-na12878/output.bio/facts/` and confirms the on-disk layout uses the full 64-hex-char (256-bit) digest split as `<2-char prefix>/<62-char rest>.json`. |

**Why we document instead of attempt**: a real SHA-256 collision is
worth ≈ $10^17 USD–equivalent of compute by today's prices and would
be a publishable cryptography result on its own. This suite is
benchmarking dotbio, not breaking SHA-256.

---

## Adding new cases

1. Pick the right module (or create a new one named `fuzz_<topic>.py`).
2. Define a callable `_case_<name>(work: Path) -> dict` returning
   `{"ok": bool, "actual_exit": int|None, "stdout": str, "stderr": str, "notes": str, ...}`.
3. Append a `FuzzCase(...)` to that module's `CASES` list with a
   stable `case_id`, the human title, the rationale, the expected-
   behavior tag, and the expected-exit-code set.
4. If you added a new module, register it in `runner.collect_cases`.
5. Re-run `python bench/v2/scripts/fuzz/runner.py` and check the
   summary.

---

## Output schema

`bench/v2/results/exp07_adversarial.json`:

```json
{
  "experiment": "exp07_adversarial",
  "spec_section": "3.7",
  "task": "Task 9 — Adversarial robustness suite",
  "generated": "2026-05-09T...",
  "elapsed_sec": 2.6,
  "summary": {
    "total": 29,
    "pass": 29,
    "fail": 0,
    "unexpected": 0,
    "by_module": { "vcf": {...}, "rulesets": {...}, "schema": {...}, "hashes": {...} }
  },
  "cases": [
    {
      "case_id": "vcf01",
      "module": "vcf",
      "title": "empty file",
      "rationale": "An empty VCF should not crash the parser.",
      "expected_behavior": "successful_handling",
      "expected_exit_codes": [0],
      "actual_exit": 0,
      "status": "PASS",
      "elapsed_sec": 0.123,
      "notes": "..."
    },
    ...
  ]
}
```
