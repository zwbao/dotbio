# Epigenetic age view

> Horvath 2013 DNA-methylation age estimator applied to this
> subject's Illumina 450K β-values. Each claim below carries a
> claim_id; resolve via `bio expand <claim_id>` for the full
> evidence chain back to the contributing CpG probes.

### Predicted epigenetic age: 37.50 years

<!-- claim_id: claim:ec0fb878a8785d0b | level: epigenetic_age | ruleset: horvath_clock@2013 -->

- **Sample**: demo_subject_001
- **Linear score (x)**: 0.833517
- **Intercept**: 0.695500
- **Probe coverage**: 353/353 clock probes (100.0%)
- **Derivation**: Horvath 2013 epigenetic clock applied to 353/353 CpG probes (intercept=0.6955, linear_score=0.8335) → piecewise transform → DNAm age 37.50 y [horvath_clock@2013]
- **Ruleset**: horvath_clock@2013
- **Source**: Horvath S. 2013. DNA methylation age of human tissues and cell types. Genome Biology 14:R115

## Top contributing probes (by |β·coef|)

| probe_id | β | coefficient | contribution |
|---|---|---|---|
| cg04268405 | 0.8953 | -0.416694 | -0.373072 |
| cg09722555 | 0.9660 | -0.346466 | -0.334683 |
| cg03019000 | 0.6892 | -0.459777 | -0.316893 |
| cg02580606 | 0.8976 | +0.349274 | +0.313522 |
| cg24580001 | 0.9083 | +0.339640 | +0.308495 |

- **Targets**: 353 probe facts (see commit for full hash list)
