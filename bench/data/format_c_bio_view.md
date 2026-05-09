{"active_rulesets":[{"license":"public domain (NCBI)","name":"clinvar","source":"ClinVar (illustrative subset; not for clinical use)","source_url":"https://www.ncbi.nlm.nih.gov/clinvar/","type":"germline_clinical","version":"2026-05-01"},{"license":"Mozilla Public License 2.0 (PharmCAT)","name":"pharmcat","source":"PharmCAT-style allele tables (illustrative subset; not for clinical use)","source_url":"https://pharmcat.org/","type":"pharmacogenomic","version":"2025.3"},{"license":"academic — see oncokb.org/terms","name":"oncokb","source":"OncoKB-style annotations (illustrative subset; not for clinical use)","source_url":"https://www.oncokb.org/","type":"somatic_oncology","version":"2026-04-15"}],"build":"GRCh38","claim_count":4,"created":"2026-05-08T16:20:08.605Z","refs":{"HEAD":"2026-05-08T16:20:08.605Z","stable":"2026-05-08T16:20:08.605Z"},"schema":"dotbio.v0","scopes":{"germline_variant_count":8,"somatic_call_count":0},"subject":"NA12878","views":[{"claim_count":2,"est_tokens":241,"name":"pgx","path":"views/pgx.md","scope":"pgx","title":"Pharmacogenomic"},{"claim_count":1,"est_tokens":165,"name":"germline-clinical","path":"views/germline-clinical.md","scope":"germline-clinical","title":"Germline clinical"},{"claim_count":0,"est_tokens":17,"name":"carrier","path":"views/carrier.md","scope":"carrier","title":"Carrier status"},{"claim_count":0,"est_tokens":18,"name":"somatic","path":"views/somatic.md","scope":"somatic","title":"Somatic oncology"}]}
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
