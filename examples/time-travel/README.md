# Time-travel demo

Demonstrates the `time as dimension` principle: when a ruleset reclassifies a variant, dotbio captures the reclassification as a new commit without rewriting any prior state.

## Setup

```bash
cd ../synthetic
bio compile input.vcf -o /tmp/patient.bio --force
```

After compile, the bundle has one commit. `HEAD` and `stable` both point to it. The active ClinVar version is `2026-05-01`. The BRCA1 c.68_69delAG variant is interpreted as **likely_pathogenic**.

```bash
bio show /tmp/patient.bio --view germline-clinical | grep -A2 BRCA1
```

```
### BRCA1 c.68_69delAG (185delAG) (GAG/G) — likely_pathogenic: Hereditary breast and ovarian cancer syndrome
```

## Apply the new ruleset

ClinVar 2026-05-08 reclassifies BRCA1 c.68_69delAG to **pathogenic** following an ENIGMA panel review (this is a synthetic update for the demo).

```bash
bio update /tmp/patient.bio --ruleset clinvar@2026-05-08
```

`HEAD` advances to the new commit. `stable` still points at the old one. The view is regenerated.

```bash
bio log /tmp/patient.bio
```

```
2026-05-08T15:46:29.546Z  (HEAD)
    rulesets: clinvar@2026-05-08, pharmcat@2025.3, oncokb@2026-04-15
    claims:   18
2026-05-08T15:46:29.498Z  (stable)
    rulesets: clinvar@2026-05-01, pharmcat@2025.3, oncokb@2026-04-15
    claims:   18
```

## See what changed

```bash
bio diff /tmp/patient.bio stable HEAD
```

```
- 0 added
- 0 removed
- 1 changed (same target, new interpretation)

## Reclassifications

- BRCA1 c.68_69delAG (185delAG)
  - was: BRCA1 c.68_69delAG (185delAG) (GAG/G) — likely_pathogenic: ...
  - now: BRCA1 c.68_69delAG (185delAG) (GAG/G) — pathogenic: ...
  - reason: ruleset reclassified likely_pathogenic → pathogenic on 2026-05-08
```

The diff is **claim-level**, not file-level. No churn from cosmetic ruleset version bumps — only substantive interpretation changes are surfaced.

## Why this matters

A traditional VCF + annotation pipeline would solve this by re-running the entire annotation chain and producing a new flat report. The clinician (or LLM) then has to do the diff in their head.

A `.genome`-style frozen Markdown file would solve this by re-baking. The prior interpretation is gone — there is no audit trail showing what was thought before.

dotbio captures the change without losing prior state. The patient (or their AI agent) can answer:

- "What was my BRCA1 status at the time of my last consult?" → `bio show patient.bio --view germline-clinical` after `git checkout`-style ref switching at the bundle level (not implemented in v0; the data is there)
- "What changed in my report since then?" → `bio diff patient.bio stable HEAD`
- "Why did it change?" → look at the commit's `previous_classification` and `reclassified_on` fields, both carried in the claim payload
