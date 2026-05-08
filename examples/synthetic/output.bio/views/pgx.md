# Pharmacogenomic view

> Pharmacogenomic phenotype calls and per-drug guidance derived from
> the active PharmCAT-style ruleset. Each claim below carries a
> claim_id; resolve via `bio expand <claim_id>` for full evidence.

## Phenotypes

### CYP2C19 phenotype: Ultrarapid Metabolizer

<!-- claim_id: claim:30f90a42db7d2e44 | level: phenotype | ruleset: pharmcat@2025.3 -->

- **Derivation**: CYP2C19 *17/*17 → Ultrarapid Metabolizer [pharmcat@2025.3 phenotype table]
- **Targets**: sha256:004be3b31779229d85ac8d08fae702a03514806924b9c042930248364e32e875

### TPMT phenotype: Intermediate Metabolizer

<!-- claim_id: claim:feb35c3de6f24e36 | level: phenotype | ruleset: pharmcat@2025.3 -->

- **Derivation**: TPMT *1/*3C → Intermediate Metabolizer [pharmcat@2025.3 phenotype table]
- **Targets**: sha256:e38c02553eca9fbf1e57922f8e0e3c49ef2a44d984d8d7ee0a87f17ac5e3f621

## Drug guidance

### clopidogrel: Standard dose; effective platelet inhibition

<!-- claim_id: claim:e6ac117c75f584d3 | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- **Derivation**: CYP2C19 *17/*17 → Ultrarapid Metabolizer → drug guidance for clopidogrel [CPIC@2022]
- **Guideline**: CPIC@2022
- **Targets**: sha256:004be3b31779229d85ac8d08fae702a03514806924b9c042930248364e32e875

### voriconazole: Standard dose may be subtherapeutic; consider alternative azole or therapeutic drug monitoring

<!-- claim_id: claim:3b4680fd578f5491 | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- **Derivation**: CYP2C19 *17/*17 → Ultrarapid Metabolizer → drug guidance for voriconazole [CPIC@2017]
- **Guideline**: CPIC@2017
- **Targets**: sha256:004be3b31779229d85ac8d08fae702a03514806924b9c042930248364e32e875

### amitriptyline: Avoid; consider alternative not metabolized by CYP2C19

<!-- claim_id: claim:7cbf74ca5a7ddbea | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- **Derivation**: CYP2C19 *17/*17 → Ultrarapid Metabolizer → drug guidance for amitriptyline [CPIC@2023]
- **Guideline**: CPIC@2023
- **Targets**: sha256:004be3b31779229d85ac8d08fae702a03514806924b9c042930248364e32e875

### citalopram: Reduced exposure; consider alternative SSRI

<!-- claim_id: claim:c6fa694d6adf1e02 | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- **Derivation**: CYP2C19 *17/*17 → Ultrarapid Metabolizer → drug guidance for citalopram [CPIC@2015]
- **Guideline**: CPIC@2015
- **Targets**: sha256:004be3b31779229d85ac8d08fae702a03514806924b9c042930248364e32e875

### escitalopram: Reduced exposure; consider alternative SSRI

<!-- claim_id: claim:34f20bc053e431a8 | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- **Derivation**: CYP2C19 *17/*17 → Ultrarapid Metabolizer → drug guidance for escitalopram [CPIC@2015]
- **Guideline**: CPIC@2015
- **Targets**: sha256:004be3b31779229d85ac8d08fae702a03514806924b9c042930248364e32e875

### azathioprine: Reduce starting dose 30-50%; monitor myelosuppression

<!-- claim_id: claim:0c67452d4d19ca0e | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- **Derivation**: TPMT *1/*3C → Intermediate Metabolizer → drug guidance for azathioprine [CPIC@2018]
- **Guideline**: CPIC@2018
- **Targets**: sha256:e38c02553eca9fbf1e57922f8e0e3c49ef2a44d984d8d7ee0a87f17ac5e3f621

### mercaptopurine: Reduce starting dose 30-50%

<!-- claim_id: claim:b22a4cb655280c52 | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- **Derivation**: TPMT *1/*3C → Intermediate Metabolizer → drug guidance for mercaptopurine [CPIC@2018]
- **Guideline**: CPIC@2018
- **Targets**: sha256:e38c02553eca9fbf1e57922f8e0e3c49ef2a44d984d8d7ee0a87f17ac5e3f621

### thioguanine: Reduce starting dose 50%

<!-- claim_id: claim:44dd04bbf1e4569c | level: clinical_decision | ruleset: pharmcat@2025.3 -->

- **Derivation**: TPMT *1/*3C → Intermediate Metabolizer → drug guidance for thioguanine [CPIC@2018]
- **Guideline**: CPIC@2018
- **Targets**: sha256:e38c02553eca9fbf1e57922f8e0e3c49ef2a44d984d8d7ee0a87f17ac5e3f621
