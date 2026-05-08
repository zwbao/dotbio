# Pharmacogenomic view

> Pharmacogenomic phenotype calls and per-drug guidance derived from
> the active PharmCAT-style ruleset. Each claim below carries a
> claim_id; resolve via `bio expand <claim_id>` for full evidence.

## Phenotypes

### CYP2C19 phenotype: Intermediate Metabolizer

<!-- claim_id: claim:84517b7499ccd781 | level: phenotype | ruleset: pharmcat@2025.3 -->

- **Derivation**: CYP2C19 *1/*2 → Intermediate Metabolizer [pharmcat@2025.3 phenotype table]
- **Targets**: sha256:d0de615c55d9bfc6d176c1c9fca7f184ad566aa53293403f7839645e82f16ded

## Drug guidance

### clopidogrel: Consider alternative if ACS/PCI; standard dose otherwise

<!-- claim_id: claim:95a9dd8f6a48770b | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- **Derivation**: CYP2C19 *1/*2 → Intermediate Metabolizer → drug guidance for clopidogrel [CPIC@2022]
- **Guideline**: CPIC@2022
- **Targets**: sha256:d0de615c55d9bfc6d176c1c9fca7f184ad566aa53293403f7839645e82f16ded
