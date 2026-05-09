# NA12878 Genomic Report

> **Note**: This is a faithful reconstruction of `.genome` format based on
> the public example shown in The Genome Computer Co.'s materials and the
> Chinese-language article "基因组学还没做好拥抱AI". The actual `.genome`
> file format is proprietary; this reconstruction follows the published
> per-gene block structure (Variant / Genotype / Clinical Significance /
> Impact for variants; Phenotype / Guidance for PGx entries).

## Gene: APOE (Apolipoprotein E)
- **Variant**: rs429358 (T > C)
- **Genotype**: Homozygous Reference (T/T) — ε3/ε3
- **Clinical Significance**: No increased Alzheimer's risk from APOE ε4.
- **Impact**: No missense variant present.

## Gene: F5 (Coagulation Factor V)
- **Variant**: rs6025 (Factor V Leiden, C > T)
- **Genotype**: Homozygous Reference (C/C)
- **Clinical Significance**: No Factor V Leiden; baseline VTE risk.
- **Impact**: No missense variant present.

## Gene: MTHFR (Methylenetetrahydrofolate Reductase)
- **Variant**: rs1801133 (C677T, G > A)
- **Genotype**: Heterozygous (G/A) — C677T heterozygous
- **Clinical Significance**: Folate metabolism reduced ~30%; minimal clinical impact for most.
- **Impact**: Missense variant changing Ala to Val at position 222.

## Gene: CFTR (Cystic Fibrosis Transmembrane Conductance Regulator)
- **Variant**: rs113993960 (ΔF508, ATCT > A)
- **Genotype**: Homozygous Reference (ATCT/ATCT)
- **Clinical Significance**: Not a CF carrier for ΔF508.
- **Impact**: No deletion present.

## Gene: HFE (Homeostatic Iron Regulator)
- **Variant**: rs1800562 (C282Y, G > A)
- **Genotype**: Homozygous Reference (G/G)
- **Clinical Significance**: No HFE-HH (hemochromatosis) carrier status.
- **Impact**: No missense variant present.

## Gene: CYP2C19 (Pharmacogenomics)
- **Phenotype**: Intermediate Metabolizer (*1/*2)
- **Guidance**: Clopidogrel — consider alternative antiplatelet therapy if ACS/PCI; standard dose may have reduced efficacy.

## Gene: DPYD (Dihydropyrimidine Dehydrogenase)
- **Phenotype**: Normal Metabolizer (*1/*1)
- **Guidance**: No dose adjustment required for fluoropyrimidines (5-FU, capecitabine).
