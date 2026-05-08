# Synthetic example

A hand-crafted VCF covering the variant categories the demo rulesets understand:

| rsID         | Gene     | Genotype  | Why it's here                                     |
|--------------|----------|-----------|---------------------------------------------------|
| rs429358     | APOE     | C/C       | Late-onset Alzheimer's risk (ε4/ε4 homozygous)    |
| rs6025       | F5       | C/T       | Factor V Leiden — VTE risk (plus-strand)          |
| rs1801133    | MTHFR    | G/A       | C677T heterozygous (plus-strand) — folate metab.  |
| rs113993960  | CFTR     | ATCT/A    | ΔF508 carrier — partner screening relevant        |
| rs1800562    | HFE      | G/G       | Negative — demonstrates "checked but absent"      |
| rs80357906   | BRCA1    | GAG/G     | Founder mutation — used in the time-travel demo   |
| rs28934578   | TP53     | G/A (somatic) | OncoKB hotspot p.R175H                        |
| rs12248560   | CYP2C19  | T/T       | *17/*17 — Ultrarapid Metabolizer                  |
| rs4244285    | CYP2C19  | G/G       | *2 absent — pins the diplotype                    |
| rs1142345    | TPMT     | T/C       | *1/*3C — Intermediate Metabolizer                 |
| rs3918290    | DPYD     | C/T       | *1/*2A — Intermediate Metabolizer                 |

Run the full pipeline:

```bash
bio compile input.vcf -o output.bio --force
bio show output.bio --view pgx
bio show output.bio --view germline-clinical
bio show output.bio --view carrier
bio show output.bio --view somatic
bio show output.bio --view manifest
```

Then trigger the time-travel demo (see `../time-travel/README.md`).

## Caveat

Coordinates and rsIDs are illustrative. The genomic positions are approximately correct for GRCh38 but a few may differ from current assembly coordinates. Do not treat this VCF as production data.
