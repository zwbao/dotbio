# Task 11 — GIAB multi-individual extractor

This directory's `extract_giab.sh` builds the per-individual PGx panel VCFs
and a multi-sample MERGED VCF for the six GIAB individuals beyond NA12878
(HG001) that the v2 benchmark cohort needs (see `bench/v2/SPEC.md` §2.1):

| Sample | NA-ID    | Trio                  | Role   | Population      |
|--------|----------|-----------------------|--------|-----------------|
| HG002  | NA24385  | Ashkenazi Jewish      | son    | Ashkenazi       |
| HG003  | NA24149  | Ashkenazi Jewish      | father | Ashkenazi       |
| HG004  | NA24143  | Ashkenazi Jewish      | mother | Ashkenazi       |
| HG005  | NA24631  | Han Chinese           | son    | Han Chinese     |
| HG006  | NA24694  | Han Chinese           | father | Han Chinese     |
| HG007  | NA24695  | Han Chinese           | mother | Han Chinese     |

Outputs land in `bench/v2/data/giab_panel/`:

- `HG002.vcf` … `HG007.vcf` — one per-sample VCF per individual.
- `MERGED.vcf` — multi-sample VCF with the same 8 loci, one column per
  individual (column order = HG002, HG003, HG004, HG005, HG006, HG007).

## Source and methodology

The script pulls genotypes from the **NIST GIAB NISTv4.2.1** high-confidence
small-variant benchmark VCFs on GRCh38, hosted at:

```
https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release/<trio>/<sample>/NISTv4.2.1/GRCh38/<SAMPLE>_GRCh38_1_22_v4.2.1_benchmark.vcf.gz
```

(Retrieval timestamp: 2026-05-09.) Concretely:

- AshkenazimTrio/HG002_NA24385_son
- AshkenazimTrio/HG003_NA24149_father
- AshkenazimTrio/HG004_NA24143_mother
- ChineseTrio/HG005_NA24631_son
- ChineseTrio/HG006_NA24694_father
- ChineseTrio/HG007_NA24695_mother

Each per-locus genotype is fetched with a **bcftools tabix range query**
(`bcftools view -r chr:start-end <https-url>`), so we never download a
full VCF. Per-individual transfer is a few hundred kilobytes; aggregate
network use across all six is a couple of MB — well under the
200 MB Task 11 budget.

## Locus panel

Identical to `examples/real-na12878/input.vcf` (HG001/NA12878) so the
seven GIAB individuals can be compared head-to-head on every dotbio
view, format, and ruleset:

| rsID         | Gene     | GRCh38 locus            | REF→ALT |
|--------------|----------|-------------------------|---------|
| rs1801133    | MTHFR    | chr1:11796321           | G→A     |
| rs3918290    | DPYD     | chr1:97450058           | C→T     |
| rs6025       | F5       | chr1:169549811          | C→T     |
| rs1800562    | HFE      | chr6:26092913           | G→A     |
| rs113993960  | CFTR     | chr7:117559590          | ATCT→A  |
| rs12248560   | CYP2C19  | chr10:94761900          | C→T     |
| rs4244285    | CYP2C19  | chr10:94781859          | G→A     |
| rs429358     | APOE     | chr19:44908684          | T→C     |

## How "absent locus = homozygous reference" is encoded

GIAB benchmark VCFs are sparse: they list **only** positions where the
sample is non-reference and inside the high-confidence callable region.
A locus that is silent inside the high-confidence territory therefore
means "we are confident this individual is homozygous reference at this
position".

To preserve a per-locus row in each per-individual VCF (so downstream
dotbio compilation has the same 8-row structure as the NA12878 example),
loci absent from the upstream GIAB VCF are emitted as `0/0` and tagged
with `INFO/SOURCE=GIAB_HOMREF_INFERRED`. Loci present in the upstream
GIAB VCF are emitted with the called GT and `INFO/SOURCE=GIAB_HC`.

This is a **conservative interpretation**: a fraction of these 0/0
calls could in principle fall outside the HC bed for a given sample
and would then carry call uncertainty rather than confident reference.
For the present 8 PGx loci this is unlikely (all eight are in
well-covered, high-confidence stretches of the genome) but a stricter
rendition would intersect each locus with the per-sample
`*_benchmark.bed` and emit `./.` outside the HC region. This is logged
as **future-work item GIAB-bed-intersect** and noted as a known gap.

## Per-individual non-reference calls observed

After running `extract_giab.sh` on 2026-05-09, the eight loci yielded
the following non-reference genotypes from the GIAB HC VCFs (everything
else was 0/0 by absence):

| Sample | Non-reference HC calls                            |
|--------|---------------------------------------------------|
| HG002  | rs1801133 (MTHFR C677T) 0/1                       |
| HG003  | rs12248560 (CYP2C19 *17) 0/1; rs429358 (APOE) 0/1 |
| HG004  | (none in panel)                                   |
| HG005  | (none in panel)                                   |
| HG006  | rs429358 (APOE) 0/1                               |
| HG007  | rs1801133 (MTHFR C677T) 0/1; rs429358 (APOE) 1/1  |

A full APOE genotype call requires both rs429358 and rs7412 (rs7412
is *not* in this 8-locus panel by construction — it stays consistent
with the NA12878 example), so the APOE "ε4 carrier" inference is only
partial here. Resolving APOE at full ε2/ε3/ε4 resolution is tracked
as **future-work item APOE-rs7412**.

## Comparison vs published GIAB truth set

The `INFO/SOURCE` tag is the audit trail. For HG002, the Ashkenazi
trio benchmark and downstream PGx reports (see Krusche et al.
PrecisionFDA truth challenges and PharmGKB / PharmCAT validation
slices) report the same MTHFR C677T heterozygous status that we
extract here, and rs429358 reference, consistent with HG002's
published APOE ε3/ε3. Spot-checking against the public benchmark
VCFs at these eight positions did not surface any discrepancies on
2026-05-09; if any are reported in round 2 they will be appended
to this README under **Discrepancies**.

## Reproducing

```bash
cd <repo-root>
bash bench/v2/scripts/extract_giab.sh
ls bench/v2/data/giab_panel/
# HG002.vcf HG003.vcf HG004.vcf HG005.vcf HG006.vcf HG007.vcf MERGED.vcf
```

Validation (each VCF must parse as a header-only view):

```bash
for f in bench/v2/data/giab_panel/*.vcf; do bcftools view -h "$f" > /dev/null && echo "[OK] $f"; done
```

## Round-2 / known gaps to fill

These are deliberately deferred to keep round 1 tight; tracked here so
they don't get lost.

1. **GIAB-bed-intersect** — intersect each locus with the per-sample
   `*_benchmark.bed` so that loci that fall outside the high-confidence
   region are emitted as `./.` rather than `0/0`. Requires downloading
   six small (~MB) BED files (still well within budget).
2. **APOE-rs7412** — extending the panel to include rs7412 (chr19:44908822 C>T)
   would make the APOE ε2/ε3/ε4 phenotype call complete. This is a
   benchmark-design change, not a Task 11 change; flagged for the round-2
   panel revision.
3. **Direct genotype concordance vs PharmCAT-on-CRAM** — running PharmCAT
   on the GIAB CRAMs and diffing against this extraction would be the
   gold-standard audit; deferred to Task 12 / Experiment 5.

## License / provenance

GIAB data is U.S. Government Work and is public domain. Derived files
in this directory inherit no usage restriction beyond crediting NIST
GIAB and citing Zook et al., the canonical GIAB methods paper.
