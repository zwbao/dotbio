# Epigenetic age view

> Horvath 2013 DNA-methylation age estimator applied to this
> subject's Illumina 450K β-values. Each claim below carries a
> claim_id; resolve via `bio expand <claim_id>` for the full
> evidence chain back to the contributing CpG probes.

### Predicted epigenetic age: 35.33 years

<!-- claim_id: claim:f80d7fa2649eb352 | level: epigenetic_age | ruleset: horvath_clock@2013 -->

- **Sample**: demo_subject_001
- **Linear score (x)**: 0.730086
- **Intercept**: 0.695500
- **Probe coverage**: 353/353 clock probes (100.0%)
- **Derivation**: Horvath 2013 epigenetic clock applied to 353/353 CpG probes (intercept=0.6955, linear_score=0.7301) → piecewise transform → DNAm age 35.33 y [horvath_clock@2013]
- **Ruleset**: horvath_clock@2013
- **Source**: Horvath S. 2013. DNA methylation age of human tissues and cell types. Genome Biology 14:R115

## Top contributing probes (by |β·coef|)

| probe_id | β | coefficient | contribution |
|---|---|---|---|
| cg7f109455 | 0.9943 | -0.069886 | -0.069491 |
| cg8bcef59c | 1.0000 | -0.068071 | -0.068071 |
| cga2027b00 | 0.9573 | -0.069955 | -0.066969 |
| cg804922fc | 0.9459 | +0.061726 | +0.058386 |
| cg08ee9585 | 0.8266 | +0.069220 | +0.057220 |

- **Targets**: 353 probe facts (see commit for full hash list)
