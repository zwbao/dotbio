# Real-data example: NA12878

This directory contains genotypes for **NA12878** (HapMap CEU female; the most-validated public human genome) extracted from the 1000 Genomes Project 30x high-coverage phased panel.

## Provenance

- **Sample**: NA12878 (also known as HG001 in some catalogs; CEU lineage; widely used as the de-facto benchmark in clinical sequencing validation)
- **Source dataset**: 1000 Genomes Project 30x high-coverage panel, 20220422 release, phased SNV+INDEL+SV
- **Source URL pattern**: `http://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/1kGP_high_coverage_Illumina.<chr>.filtered.SNV_INDEL_SV_phased_panel.vcf.gz`
- **Reference build**: GRCh38
- **Extraction**: `bcftools view -s NA12878 -r <chr>:<pos>-<pos>` per locus, then the coordinate-style ID field (e.g. `19:44908684:T:C`) was replaced with the canonical rsID.
- **License**: 1000 Genomes data is in the public domain.

## Variants included

Eight loci spanning the categories the bundled rulesets understand:

| rsID         | Gene     | Locus (GRCh38)        | NA12878 GT | Biological meaning                  |
|--------------|----------|-----------------------|------------|-------------------------------------|
| rs429358     | APOE     | chr19:44908684 T>C    | 0\|0       | APOE ε3/ε3 — no AD risk increase    |
| rs6025       | F5       | chr1:169549811 C>T    | 0\|0       | No Factor V Leiden                  |
| rs1801133    | MTHFR    | chr1:11796321 G>A     | 1\|0       | C677T heterozygous                  |
| rs113993960  | CFTR     | chr7:117559590 ATCT>A | 0\|0       | No ΔF508 carrier                    |
| rs1800562    | HFE      | chr6:26092913 G>A     | 0\|0       | No HFE C282Y                        |
| rs12248560   | CYP2C19  | chr10:94761900 C>T    | 0\|0       | No *17 allele                       |
| rs4244285    | CYP2C19  | chr10:94781859 G>A    | 1\|0       | One copy of *2 (loss-of-function)   |
| rs3918290    | DPYD     | chr1:97450058 C>T     | 0\|0       | No *2A allele                       |

## Compile and read

```bash
bio compile input.vcf -o output.bio --subject NA12878 --force
bio show output.bio --view pgx
bio show output.bio --view germline-clinical
```

## Real-data claims emitted

dotbio v0 produces two clinically meaningful claims for NA12878 from this input:

### 1. CYP2C19 *1/*2 — Intermediate Metabolizer

```
### CYP2C19 phenotype: Intermediate Metabolizer
- Derivation: CYP2C19 *1/*2 → Intermediate Metabolizer [pharmcat@2025.3 phenotype table]

### clopidogrel: Consider alternative if ACS/PCI; standard dose otherwise
- Derivation: CYP2C19 *1/*2 → Intermediate Metabolizer → drug guidance for clopidogrel [CPIC@2022]
- Guideline: CPIC@2022
```

This matches the published CYP2C19 status of NA12878 as widely reported in pharmacogenomic benchmarking literature.

### 2. MTHFR C677T heterozygous — drug_response

```
### MTHFR C677T (A/G) — drug_response: Folate metabolism reduced ~30%
- Evidence: Heterozygous: ~30% reduced enzyme activity; minimal clinical impact for most
- Derivation: rs1801133 (MTHFR) genotype=A/G → drug_response for Folate metabolism reduced ~30%
```

## What didn't fire — and why that's also data

Six of the eight included rsIDs are reference for NA12878 and produced no claims. **The facts are still stored** — `bio facts output.bio` lists all eight, including the six negative ones. "We checked rs1800562 and the patient is HFE-negative" is genuinely useful clinical information; dotbio preserves it instead of throwing it away.

This is how the format is supposed to behave: assertions only fire when warranted by the rule, but the underlying observations persist in the CAS layer.

## Reproducing the extraction

```bash
URL_BASE="http://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/working/20220422_3202_phased_SNV_INDEL_SV/1kGP_high_coverage_Illumina"

# Example: fetch rs429358 (APOE) genotype for NA12878
bcftools view -s NA12878 -r chr19:44908684-44908684 \
  "${URL_BASE}.chr19.filtered.SNV_INDEL_SV_phased_panel.vcf.gz"
```

Repeat for each rsID in the table above, then add the rsID back into column 3 (the source uses coordinate-style IDs like `19:44908684:T:C` rather than `rs429358`). The committed `input.vcf` is the result of this process.

## Caveats

- This is a **PGx-focused panel**, not a full WGS callset. NA12878's complete VCF would be ~5 GB.
- The bundled rulesets are illustrative subsets, not full ClinVar / PharmCAT / OncoKB databases. For production use, point the compiler at upstream sources or vetted local snapshots.
- **dotbio is not clinically validated**. These claims are correct in spirit but the rulesets used to derive them are not the certified versions a clinical lab would use.
