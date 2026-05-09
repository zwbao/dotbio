# Privacy / re-identification risk analyzer (Experiment 6)

**Implements**: `bench/v2/SPEC.md §3.6` and `bench/v2/TASKS.md` — Task 8.
**Outputs**: `bench/v2/results/exp06_reid_risk.json`.
**Reference**: Erlich, Y. & Narayanan, A. *Routes for breaching and protecting
genetic privacy.* Nat Rev Genet **15**, 409–421 (2014). doi:10.1038/nrg3723.

This is a **theoretical** analysis. We do **not** attempt re-identification
against any real public database; that would be legally and ethically
gray. We compute the *worst-case attack surface* implied by each format,
following the Erlich–Narayanan framework.

---

## 1. Why this experiment matters

The dotbio paper claims (SPEC §1, H1–H3) that the `.bio` representation
trades raw genotypes for **content-addressed facts plus a published
ruleset**. A natural privacy hypothesis follows: if facts are SHA-256
hashed and views are phenotype-level, then a leaked `.bio` should leak
*less* per-individual information than a leaked VCF.

This is testable. We measure three things per format:

1. **Marker count** — how many independent variants an attacker can
   recover from the leak.
2. **Information-theoretic entropy** — the Shannon entropy of the
   recoverable fingerprint, in bits.
3. **Re-identification probability** in a reference population of
   N = 10⁵, with bootstrap 95% CIs over 1,000 iterations.

---

## 2. Threat model

We follow the Erlich–Narayanan "identity tracing attack" template
(Box 1 of their paper).

- The attacker holds a **reference panel of N = 10⁵ individuals** with
  known genotypes at every locus that appears in the leak.
- Loci are assumed **independent** (no LD); ALT-allele frequencies under
  Hardy–Weinberg equilibrium. This is a worst-case-for-the-defender
  assumption — real LD reduces effective marker count, so independence
  *upper-bounds* the attacker's power.
- The probability that a random individual in the panel matches the
  leaked fingerprint exactly is

  ```
  P_match = ∏_i  Pr( genotype_i = observed_i | ALT freq p_i, HWE )
  ```

  where the per-locus probabilities are `(1−p)², 2p(1−p), p²` for
  dosages `0, 1, 2`.
- The probability that the target is **uniquely** re-identified, given
  the target is in the panel, is

  ```
  P_reid = (1 − P_match)^(N − 1)
  ```

  and the expected number of matches in the panel is

  ```
  E[matches] = 1 + (N − 1) · P_match.
  ```

These are the standard formulae in Erlich & Narayanan (their equations
1–3). The bootstrap (1,000 iters) resamples loci with replacement to
quantify uncertainty due to *which* subset of loci ends up in the leak;
this matters because not every leak exposes every locus equally.

---

## 3. Per-format leakage modelling

### 3.1 Raw VCF (single-sample)

A 1000G-style single-sample VCF exposes, per locus: chromosome, position,
rsID, REF, ALT, ALT-allele frequency, and the per-sample genotype. The
attacker recovers full dosage (0/1/2). All M loci in the file are usable.
**This is our worst-case baseline.**

### 3.2 `.genome` reconstruction

The reconstructed `.genome` document (`bench/data/format_b_*.md`) splits
into per-gene blocks. Variant blocks expose rsID and a textual genotype
(e.g., "Heterozygous (G/A)") which is recoverable. PGx blocks **collapse
multiple loci** into a single phenotype label (e.g., "CYP2C19
Intermediate Metabolizer"). The collapsed phenotype is treated as a
single coarse marker with phenotype-level entropy.

For CYP2C19 in a 1000G EUR-ish reference we use the 4-bin prior
NM ≈ 0.55 / IM ≈ 0.30 / PM ≈ 0.05 / RM-or-UM ≈ 0.10 (Bertilsson 2002,
Mizutani 2003 — see `notes` field in the JSON). This gives ≈ 1.59 bits
per phenotype call, vs. ≈ 1–2 bits per typical SNV genotype. **PGx
collapse is roughly entropy-neutral but reduces marker count**, which
is why .genome reads as slightly higher entropy but fewer markers in
our Table 1.

### 3.3 `.bio` bundle — `facts/` leaked, attacker holds ruleset

This is the **realistic** `.bio` threat. Two facts about dotbio v0:

1. Each fact is stored as `facts/<sha2[:2]>/<sha2[2:]>.json` containing
   the **plaintext** canonical JSON (rsID, chrom, pos, dosage, etc.) —
   the SHA-256 is the *filename*, not an opaque container around the
   payload. So once `facts/` is leaked the genotypes are plaintext-
   recoverable.
2. Even if the dotbio compiler had stored opaque hashes alone, the
   per-locus enumeration space is tiny (at most 3 dosages × the small
   set of (chrom, pos, ref, alt) combinations consistent with the
   public ruleset). An attacker holding the ruleset can brute-force
   the pre-image in microseconds. SHA-256 is one-way at the bit level,
   not at the *information* level when the input space is enumerable.

So under our threat model **`.bio` facts/ leakage is information-
theoretically equivalent to VCF leakage** on the loci that have facts
entries. We report this as `bio_facts_with_public_ruleset`.

### 3.4 `.bio` bundle — `facts/` leaked, ruleset withheld

Hypothetical: dotbio could distribute proprietary rulesets that an
attacker does not hold. In that case the attacker sees only opaque
SHA-256 file names; pre-image resistance dominates and the leak is
essentially information-free. We report this as `bio_facts_hash_only`.

This is *not* the dotbio v0 default. Our v0 ruleset is public; we
include this scenario only to make the trade explicit so the
manuscript can argue for it as a deployment option.

### 3.5 `.bio` bundle — only `views/` leaked

The minimum-leak scenario. Only the rendered `views/*.md` files are
exposed; `facts/` is kept private. Each top-level claim in a view
collapses one or more underlying loci into a phenotype-level statement
("CYP2C19 IM", "clopidogrel — consider alternative if ACS/PCI"). Drug-
guidance claims are a deterministic function of the phenotype claim
they cite, so they contribute **no independent entropy**.

Germline-clinical claims that name a single rsID (e.g., a Pathogenic
ClinVar variant) leak that one locus in plaintext. We model this by
assigning the rarest VCF loci to those claims (worst case).

---

## 4. Math — VCF→`.bio` cross-walk

Per-locus genotype entropy under HWE at ALT freq p:

```
H_locus(p) = − [(1−p)² · log₂((1−p)²)
              + 2p(1−p) · log₂(2p(1−p))
              + p² · log₂(p²)]
```

For p = 0.5 this is the maximum, ≈ 1.5 bits. For rare variants
(p ≈ 0.005, e.g., F5 Leiden / DPYD\*2A in 1000G) it's ≈ 0.07 bits.

Total fingerprint entropy:

```
H_total = Σ_i  H_locus(p_i)
```

For the NA12878 8-locus PGx VIP panel:

| Format                            | Markers | H (bits) | log₁₀ P_match | E[matches] in N=10⁵ |
|-----------------------------------|--------:|---------:|--------------:|--------------------:|
| `vcf_raw`                         |       8 |    4.744 |        −1.216 |               6 084 |
| `genome_reconstruction`           |       7 |    5.620 |        −1.111 |               7 742 |
| `bio_facts_with_public_ruleset`   |       8 |    4.744 |        −1.216 |               6 084 |
| `bio_facts_hash_only`             |       0 |    0.000 |             0 |             100 000 |
| `bio_views_only`                  |       2 |    1.592 |        −0.262 |              54 709 |

(Numbers are point estimates from the run committed to
`bench/v2/results/exp06_reid_risk.json`. Bootstrap 95% CIs are stored
alongside each value in the JSON.)

**Key result.** With only 8 PGx loci, P_match is too high (5–8 % of the
panel matches the fingerprint) for unique re-identification in
N = 10⁵: every format reports point P_reid ≈ 0. This is consistent with
Erlich & Narayanan's finding that **30–80 unlinked SNPs** are required
before P_reid → 1 in a 10⁵-person panel — 8 PGx loci are nowhere near
that threshold.

The *meaningful* per-format comparison at this panel size is therefore
the **expected number of matches**, **the marker count**, and **the
fingerprint entropy**, not the (≈0) point P_reid. On those:

- **VCF and `.bio` facts/ (with public ruleset) are equivalent** —
  same marker count, same entropy, same E[matches]. This confirms that
  content-addressing the facts does **not** give a privacy win when
  the ruleset is public.
- **`.bio` views-only** is roughly an order of magnitude better:
  marker count drops from 8 to 2, fingerprint entropy from 4.7 to 1.6
  bits, and E[matches] grows from ~6,000 to ~55,000.
- **`.bio` facts/ with a withheld ruleset** is the only configuration
  that reaches the SHA-256 pre-image-resistance regime (P_reid ≡ 0,
  the leak is information-free).

The SPEC's hypothesis ("`.bio` predicted lowest") is **partially
vindicated**: it holds when only views/ is exposed, or when the ruleset
is withheld. It does **not** hold when facts/ is leaked AND the ruleset
is public — the realistic dotbio v0 deployment. This is honest and
worth flagging in the manuscript.

---

## 5. Bootstrap procedure

For each format the analyzer:

1. Builds the list of usable loci (with ALT freq + observed dosage).
2. For phenotype-collapsed scenarios, synthesises one ALT-freq-0.5
   pseudo-locus per phenotype claim (so the resampling has something
   to draw from with the correct phenotype-level entropy).
3. Runs 1,000 resamples with replacement. Each resample recomputes
   H, P_match, P_reid, and E[matches].
4. Reports mean + 2.5%/97.5% percentile interval per metric.

Seed is fixed (`seed_base = 42`) for reproducibility.

---

## 6. Limitations

- **Independence assumption.** We treat all loci as in linkage
  equilibrium. Real LD reduces effective marker count and would lower
  P_reid; our numbers are upper-bound-attacker-power.
- **Population stratification.** ALT-frequency from the input VCF is
  a global panel-level estimate; an attacker who matched against the
  correct super-population (e.g., EUR for NA12878) would have *more*
  power on rare-in-EUR / common-in-EAS variants and *less* on the
  reverse.
- **Auxiliary attack vectors not modelled.** We deliberately only model
  the public-fingerprint match attack of Erlich–Narayanan §3. We do
  not model surname inference (their §5), cell-line cross-reference,
  GEDmatch-style relative finding, or beacon-style "Bustamante attack"
  (Shringarpure & Bustamante 2015). These are out of scope; some are
  flagged for v3.
- **Eight-locus panel is not representative.** The conclusions here
  generalise qualitatively to larger panels but the *magnitude* of
  re-id probability is not yet meaningful at N=8. A follow-up run on
  a 5,000-variant ACMG SF v3.2 panel (SPEC §2.2 Panel B) is the
  natural next step.

---

## 7. Reproduce

```bash
cd ~/projects/dotbio
python bench/v2/scripts/reid_risk.py
# writes bench/v2/results/exp06_reid_risk.json
```

The script defaults to NA12878 inputs at the canonical paths above.
Override with `--vcf`, `--genome`, `--bio`, `--population`,
`--bootstrap`, and `--out`.

Pure stdlib; no network, no external dependencies, deterministic given
the seed.
