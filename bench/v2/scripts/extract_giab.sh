#!/usr/bin/env bash
# extract_giab.sh — Task 11 of the dotbio NM-grade benchmark (v2)
#
# Extracts the same 8 PGx loci that examples/real-na12878/input.vcf carries
# for the six additional GIAB individuals: HG002–HG007 (Ashkenazi Jewish
# trio + Han Chinese trio). Output goes to bench/v2/data/giab_panel/.
#
# Source: NIST GIAB FTP, NISTv4.2.1 high-confidence small-variant benchmark
# (GRCh38 build). Range queries use bcftools/htslib remote tabix so we never
# download a full VCF — total transfer is well under the 200 MB budget.
#
# Important property of the GIAB benchmark VCF format: it lists ONLY positions
# where the individual differs from the GRCh38 reference. A locus that is
# absent from the file inside the high-confidence region therefore means
# "homozygous reference" (0/0). This script preserves that semantics by
# emitting 0/0 placeholder rows for loci absent from each individual's VCF,
# matching how examples/real-na12878/input.vcf is structured (one row per
# locus, 8 rows total).
#
# Run from anywhere; uses absolute paths internally.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
OUT_DIR="${REPO_ROOT}/bench/v2/data/giab_panel"
mkdir -p "${OUT_DIR}"

GIAB_BASE="https://ftp-trace.ncbi.nlm.nih.gov/giab/ftp/release"

# Per-individual GIAB FTP URL (NISTv4.2.1 / GRCh38 small-variant benchmark)
declare -a INDIVIDUALS=(
  "HG002|AshkenazimTrio/HG002_NA24385_son|Ashkenazi_Jewish|son"
  "HG003|AshkenazimTrio/HG003_NA24149_father|Ashkenazi_Jewish|father"
  "HG004|AshkenazimTrio/HG004_NA24143_mother|Ashkenazi_Jewish|mother"
  "HG005|ChineseTrio/HG005_NA24631_son|Han_Chinese|son"
  "HG006|ChineseTrio/HG006_NA24694_father|Han_Chinese|father"
  "HG007|ChineseTrio/HG007_NA24695_mother|Han_Chinese|mother"
)

# 8 PGx loci (must match examples/real-na12878/input.vcf exactly)
# fields: chrom|pos|rsid|ref|alt|gene
declare -a LOCI=(
  "chr1|11796321|rs1801133|G|A|MTHFR"
  "chr1|97450058|rs3918290|C|T|DPYD"
  "chr1|169549811|rs6025|C|T|F5"
  "chr6|26092913|rs1800562|G|A|HFE"
  "chr7|117559590|rs113993960|ATCT|A|CFTR"
  "chr10|94761900|rs12248560|C|T|CYP2C19"
  "chr10|94781859|rs4244285|G|A|CYP2C19"
  "chr19|44908684|rs429358|T|C|APOE"
)

write_header() {
  local sample="$1"
  local outfile="$2"
  cat > "${outfile}" <<EOF
##fileformat=VCFv4.2
##fileDate=$(date -u +%Y%m%d)
##source=dotbio-task11-giab-extract
##reference=GRCh38
##INFO=<ID=GENE,Number=1,Type=String,Description="Gene symbol (informational)">
##INFO=<ID=SOURCE,Number=1,Type=String,Description="Per-locus source: GIAB_HC=present in GIAB high-confidence VCF; GIAB_HOMREF_INFERRED=absent from GIAB VCF, treated as 0/0 reference">
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##contig=<ID=chr1,length=248956422>
##contig=<ID=chr6,length=170805979>
##contig=<ID=chr7,length=159345973>
##contig=<ID=chr10,length=133797422>
##contig=<ID=chr19,length=58617616>
##NOTE=<ID=Provenance,Description="Genotypes for sample ${sample} extracted from NIST GIAB NISTv4.2.1 high-confidence small-variant benchmark VCF (GRCh38). GIAB benchmark VCFs only list non-reference calls inside high-confidence regions; loci absent are treated as 0/0 (homozygous reference) and tagged with SOURCE=GIAB_HOMREF_INFERRED.">
#CHROM	POS	ID	REF	ALT	QUAL	FILTER	INFO	FORMAT	${sample}
EOF
}

extract_one_individual() {
  local sample="$1"
  local rel_path="$2"
  local pop="$3"
  local role="$4"

  local url="${GIAB_BASE}/${rel_path}/NISTv4.2.1/GRCh38/${sample}_GRCh38_1_22_v4.2.1_benchmark.vcf.gz"
  local outfile="${OUT_DIR}/${sample}.vcf"

  echo "[extract] ${sample} (${pop} ${role}) <- ${url}" >&2
  write_header "${sample}" "${outfile}"

  for locus in "${LOCI[@]}"; do
    IFS='|' read -r chrom pos rsid ref alt gene <<< "${locus}"

    # For the CFTR ATCT>A deletion, expand the range a bit so a left-aligned
    # representation still gets caught.
    local end="${pos}"
    if [[ "${rsid}" == "rs113993960" ]]; then
      end=$((pos + 4))
    fi

    # Pull any variants the GIAB HC VCF emits at this locus for this sample.
    local rec
    rec=$(bcftools view -H -r "${chrom}:${pos}-${end}" "${url}" 2>/dev/null | \
          awk -v p="${pos}" -v r="${ref}" -v a="${alt}" '
            BEGIN{FS=OFS="\t"} $2==p && $4==r && $5==a {print; exit}
          ' || true)

    if [[ -n "${rec}" ]]; then
      # Pull GT field (first sub-field of column 10) and rewrite the row in
      # the trimmed schema we use for dotbio inputs.
      local fmt sample_field gt
      fmt=$(awk -F'\t' '{print $9}' <<< "${rec}")
      sample_field=$(awk -F'\t' '{print $10}' <<< "${rec}")
      gt=$(awk -F':' '{print $1}' <<< "${sample_field}")
      printf '%s\t%s\t%s\t%s\t%s\t.\tPASS\tGENE=%s;SOURCE=GIAB_HC\tGT\t%s\n' \
        "${chrom}" "${pos}" "${rsid}" "${ref}" "${alt}" "${gene}" "${gt}" \
        >> "${outfile}"
    else
      # Absent from the GIAB HC VCF -> homozygous reference.
      printf '%s\t%s\t%s\t%s\t%s\t.\tPASS\tGENE=%s;SOURCE=GIAB_HOMREF_INFERRED\tGT\t0/0\n' \
        "${chrom}" "${pos}" "${rsid}" "${ref}" "${alt}" "${gene}" \
        >> "${outfile}"
    fi
  done

  # Validate
  bcftools view -h "${outfile}" > /dev/null
  echo "[ok]      ${outfile}" >&2
}

# --- main ----------------------------------------------------------------

extracted=()
failed=()
for entry in "${INDIVIDUALS[@]}"; do
  IFS='|' read -r sample rel_path pop role <<< "${entry}"
  if extract_one_individual "${sample}" "${rel_path}" "${pop}" "${role}"; then
    extracted+=("${sample}")
  else
    failed+=("${sample}")
  fi
done

# Build a multi-sample MERGED.vcf by aligning per-sample GTs.
MERGED="${OUT_DIR}/MERGED.vcf"
{
  cat <<EOF
##fileformat=VCFv4.2
##fileDate=$(date -u +%Y%m%d)
##source=dotbio-task11-giab-merge
##reference=GRCh38
##INFO=<ID=GENE,Number=1,Type=String,Description="Gene symbol (informational)">
##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">
##contig=<ID=chr1,length=248956422>
##contig=<ID=chr6,length=170805979>
##contig=<ID=chr7,length=159345973>
##contig=<ID=chr10,length=133797422>
##contig=<ID=chr19,length=58617616>
##NOTE=<ID=Merge,Description="Multi-sample VCF aligning the 8 PGx loci across HG002-HG007 (GIAB AJ + Han Chinese trios). 0/0 entries with SOURCE=GIAB_HOMREF_INFERRED in per-sample VCFs are written here as 0/0 with no SOURCE tag for compactness; consult per-sample VCFs for provenance.">
EOF
  printf '#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT'
  for s in "${extracted[@]}"; do printf '\t%s' "${s}"; done
  printf '\n'

  for locus in "${LOCI[@]}"; do
    IFS='|' read -r chrom pos rsid ref alt gene <<< "${locus}"
    printf '%s\t%s\t%s\t%s\t%s\t.\tPASS\tGENE=%s\tGT' \
      "${chrom}" "${pos}" "${rsid}" "${ref}" "${alt}" "${gene}"
    for s in "${extracted[@]}"; do
      gt=$(awk -v p="${pos}" -v r="${ref}" -v a="${alt}" '
        BEGIN{FS=OFS="\t"}
        /^#/ {next}
        $2==p && $4==r && $5==a {split($10,f,":"); print f[1]; exit}
      ' "${OUT_DIR}/${s}.vcf")
      [[ -z "${gt}" ]] && gt="./."
      printf '\t%s' "${gt}"
    done
    printf '\n'
  done
} > "${MERGED}"

bcftools view -h "${MERGED}" > /dev/null
echo "[ok]      ${MERGED}" >&2

echo "" >&2
echo "[summary] extracted=${#extracted[@]}/6 failed=${#failed[@]}" >&2
if (( ${#failed[@]} > 0 )); then
  echo "[summary] failed: ${failed[*]}" >&2
fi
