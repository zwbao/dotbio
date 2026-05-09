# Methylation extension pilot — Task 10

This directory documents Experiment 8 (SPEC §3.8): extending `.bio` to a
non-DNA-variant modality. We pick **Illumina HumanMethylation450 (450K)
β-values** and pilot the **Horvath 2013** epigenetic clock.

## Goal

Demonstrate that the three dotbio principles hold for non-DNA data:

1. **Multi-scale** — probe-level facts (β values per CpG) → tissue-level
   commits (an epigenetic-age claim) → patient-level views.
2. **Evidence chain** — the epigenetic-age claim's `targets` field lists
   every probe fact hash that contributed; `bio expand <claim_id>`
   resolves the chain back to the underlying β values.
3. **Time** — the bundle is a commit DAG just like the DNA case. Re-running
   with a future clock (Hannum, PhenoAge, GrimAge) appends a new commit;
   `bio diff stable HEAD` exposes the age-call delta.

## Files in this pilot

| Artifact | Description |
|---|---|
| `src/dotbio/extensions/methylation/__init__.py` | Public entry points |
| `src/dotbio/extensions/methylation/compile.py` | CSV → `.bio` compiler, Horvath scorer, view renderer |
| `src/dotbio/extensions/methylation/rulesets/horvath_clock.json` | 353-probe ruleset (intercept + per-probe coefficients) |
| `bench/v2/data/methylation_demo/demo_subject_001.csv` | Synthetic 450K input (probe_id, beta_value, sample_id) |
| `bench/v2/data/methylation_demo/demo_subject_001.bio/` | Compiled bundle (committed) |
| `bench/v2/data/format_g_methylation_demo.bio.tar.gz` | Tarball of the bundle, parallel to format_d/format_e |
| `tests/test_methylation_extension.py` | Pytest suite (≥ 5 tests) |

## Horvath clock — math recap

For a sample with β values β_i over 353 CpG probes with coefficients c_i and
intercept b₀ = 0.6955:

```
x   = b₀ + Σ_i β_i · c_i
age = (1 + 20) · exp(x) - 1     if x  < 0
age = (1 + 20) · x  + 20        if x ≥ 0     (linear part, Horvath 2013)
```

Coefficients live in `horvath_clock.json` under `"probes": {probe_id: coef, …}`.

## Source & licence

- **Citation**: Horvath S. (2013). *DNA methylation age of human tissues
  and cell types.* **Genome Biology** 14:R115.
  <https://genomebiology.biomedcentral.com/articles/10.1186/gb-2013-14-10-r115>
- The intercept (0.6955) and the piecewise age transform are taken
  verbatim from the open-access paper. The 353 probe coefficients in this
  pilot are **synthetic but deterministically generated** (seed=2013) to
  plausible magnitudes — see SPEC §3.8 acceptance criteria, which
  explicitly permits synthetic methylation data for the pilot. The
  ruleset's `note` field documents this. **Not for clinical use.**
- The Horvath 2013 paper is published under CC BY 2.0; coefficient tables
  in Additional file 3 are publicly available for reproduction.

## Running the demo

```bash
python -c "
from dotbio.extensions.methylation import compile_methylation_csv
compile_methylation_csv(
    'bench/v2/data/methylation_demo/demo_subject_001.csv',
    'demo.bio',
    force=True,
)
"

# Inspect the bundle
ls demo.bio/                        # facts/ commits/ views/ refs/ manifest.json
cat demo.bio/views/epigenetic-age.md
```

For the synthetic demo subject, the predicted DNAm age is **~35.3 years**
(linear score ≈ 0.730). The number is reproducible because both the
ruleset and the demo β-values are seed-locked.

## Extending further

Adding another clock (Hannum, PhenoAge, GrimAge, principal-components
clocks) is mechanical: drop a `<clock>.json` next to `horvath_clock.json`
with the same `intercept`/`probes`/`transform` schema, then call
`load_horvath_clock(path)` with the override path. Each call appends a new
commit, advancing HEAD, leaving the diff inspectable with `bio diff`.
