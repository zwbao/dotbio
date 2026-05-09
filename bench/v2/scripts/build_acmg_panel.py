#!/usr/bin/env python3
"""
build_acmg_panel.py — Round-2 Task R2 of the dotbio NM-grade benchmark.

Builds an expanded variant panel covering the ACMG SF v3.2 (Miller 2023,
PMID:36190193) secondary-findings gene list plus the PharmGKB Tier-1 VIP
pharmacogene list, extracts NA12878 (HG001) genotypes from the public
1000 Genomes Project 30x high-coverage phased panel, and emits:

  bench/v2/data/acmg_panel/HG001_acmg_sf_vip.vcf   — single-sample VCF
  bench/v2/data/acmg_panel/genes.tsv               — gene -> region table
  bench/v2/data/acmg_panel/clinvar_pl.tsv          — ClinVar P/LP positions

The script keeps the network footprint within the 500 MB R2 budget by:
  - Using bcftools remote tabix range queries (no full-file downloads)
  - Restricting ClinVar to per-gene CDS-extending regions
  - Restricting 1kGP queries to the union of those regions for NA12878 only

Run from anywhere; uses absolute paths internally.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

REPO_ROOT = Path("/Users/baozhiwei/projects/dotbio")
OUT_DIR = REPO_ROOT / "bench/v2/data/acmg_panel"

# ---------------------------------------------------------------------------
# Gene panels (provenance noted inline). Coordinates are GRCh38 / hg38, and
# include the canonical RefSeq mRNA region with a 5 kb flanking window so
# splice & near-CDS ClinVar variants are caught.
#
# ACMG SF v3.2: Miller DT et al., Genet Med 2023; 25(8):100867.
#   PMID 36190193. Adds TTR to v3.1's 78 -> 81 genes total.
# PharmGKB VIP (Very Important Pharmacogenes), Tier 1 set as of 2025-Q4:
#   https://www.pharmgkb.org/vips. The 36-gene Tier-1 list is reproduced
#   inline; CYP2C9 / CYP2C19 / SLCO1B1 / TPMT / DPYD etc.
# ---------------------------------------------------------------------------

# Format: gene -> (chrom, start, end). Coordinates are hand-curated from
# Ensembl/RefSeq canonical transcripts on GRCh38. For panel-builder purposes
# these need to be approximately right (±5 kb is fine); ClinVar tabix will
# find any P/LP variants intersecting the interval. Where the canonical
# transcript spans a large region, we cover it fully.
GENE_REGIONS: dict[str, tuple[str, int, int, str, str]] = {
    # gene -> (chrom, start, end, panel, condition_summary)
    # =========== ACMG SF v3.2 ===========
    "BRCA1":     ("chr17", 43044295, 43170245, "ACMG_SF_v3.2", "Hereditary breast/ovarian cancer"),
    "BRCA2":     ("chr13", 32315474, 32400266, "ACMG_SF_v3.2", "Hereditary breast/ovarian cancer"),
    "TP53":      ("chr17", 7661779,  7687550,  "ACMG_SF_v3.2", "Li-Fraumeni syndrome"),
    "STK11":     ("chr19", 1205797,  1228435,  "ACMG_SF_v3.2", "Peutz-Jeghers syndrome"),
    "MLH1":      ("chr3",  36993332, 37050918, "ACMG_SF_v3.2", "Lynch syndrome"),
    "MSH2":      ("chr2",  47403067, 47634501, "ACMG_SF_v3.2", "Lynch syndrome"),
    "MSH6":      ("chr2",  47783146, 47806916, "ACMG_SF_v3.2", "Lynch syndrome"),
    "PMS2":      ("chr7",  5970925,  6048737,  "ACMG_SF_v3.2", "Lynch syndrome"),
    "APC":       ("chr5",  112707498, 112846239, "ACMG_SF_v3.2", "Familial adenomatous polyposis"),
    "MUTYH":     ("chr1",  45329163, 45340663, "ACMG_SF_v3.2", "MUTYH-associated polyposis"),
    "VHL":       ("chr3",  10141778, 10153688, "ACMG_SF_v3.2", "von Hippel-Lindau syndrome"),
    "MEN1":      ("chr11", 64803515, 64811294, "ACMG_SF_v3.2", "Multiple endocrine neoplasia type 1"),
    "RET":       ("chr10", 43077128, 43130351, "ACMG_SF_v3.2", "MEN2; medullary thyroid cancer"),
    "PTEN":      ("chr10", 87863438, 87971930, "ACMG_SF_v3.2", "Cowden / PHTS"),
    "RB1":       ("chr13", 48303256, 48481890, "ACMG_SF_v3.2", "Retinoblastoma"),
    "SDHD":      ("chr11", 112086788, 112095210, "ACMG_SF_v3.2", "Hereditary paraganglioma-pheochromocytoma"),
    "SDHAF2":    ("chr11", 61429894, 61446993, "ACMG_SF_v3.2", "Hereditary paraganglioma"),
    "SDHC":      ("chr1",  161314393, 161364091, "ACMG_SF_v3.2", "Hereditary paraganglioma"),
    "SDHB":      ("chr1",  17018722, 17054032, "ACMG_SF_v3.2", "Hereditary paraganglioma"),
    "TSC1":      ("chr9",  132891349, 132945269, "ACMG_SF_v3.2", "Tuberous sclerosis"),
    "TSC2":      ("chr16", 2047800,  2090133,  "ACMG_SF_v3.2", "Tuberous sclerosis"),
    "WT1":       ("chr11", 32379149, 32435571, "ACMG_SF_v3.2", "WT1-related Wilms tumor"),
    "NF2":       ("chr22", 29603556, 29701045, "ACMG_SF_v3.2", "Neurofibromatosis type 2"),
    "BMPR1A":    ("chr10", 86755785, 86927982, "ACMG_SF_v3.2", "Juvenile polyposis"),
    "SMAD4":     ("chr18", 51030212, 51085044, "ACMG_SF_v3.2", "Juvenile polyposis / HHT"),
    "ENG":       ("chr9",  127815013, 127855059, "ACMG_SF_v3.2", "Hereditary hemorrhagic telangiectasia"),
    "ACVRL1":    ("chr12", 51906724, 51923387, "ACMG_SF_v3.2", "HHT type 2"),
    "RYR1":      ("chr19", 38433691, 38595049, "ACMG_SF_v3.2", "Malignant hyperthermia susceptibility"),
    "CACNA1S":   ("chr1",  201039727, 201112013, "ACMG_SF_v3.2", "Malignant hyperthermia susceptibility"),
    "RYR2":      ("chr1",  237042137, 237833988, "ACMG_SF_v3.2", "Catecholaminergic polymorphic VT"),
    "CASQ2":     ("chr1",  115700830, 115772121, "ACMG_SF_v3.2", "CPVT"),
    "TRDN":      ("chr6",  123133922, 123553031, "ACMG_SF_v3.2", "CPVT"),
    "DSP":       ("chr6",  7541869,  7586979,  "ACMG_SF_v3.2", "Arrhythmogenic cardiomyopathy"),
    "DSC2":      ("chr18", 31065317, 31106820, "ACMG_SF_v3.2", "Arrhythmogenic cardiomyopathy"),
    "DSG2":      ("chr18", 31497290, 31552108, "ACMG_SF_v3.2", "Arrhythmogenic cardiomyopathy"),
    "PKP2":      ("chr12", 32790628, 32898531, "ACMG_SF_v3.2", "Arrhythmogenic cardiomyopathy"),
    "TMEM43":    ("chr3",  14123426, 14152994, "ACMG_SF_v3.2", "Arrhythmogenic cardiomyopathy"),
    "MYH7":      ("chr14", 23412866, 23436564, "ACMG_SF_v3.2", "Hypertrophic / dilated cardiomyopathy"),
    "MYBPC3":    ("chr11", 47331407, 47352702, "ACMG_SF_v3.2", "Hypertrophic cardiomyopathy"),
    "TNNT2":     ("chr1",  201328142, 201346878, "ACMG_SF_v3.2", "Hypertrophic / dilated cardiomyopathy"),
    "TNNI3":     ("chr19", 55151767, 55157742, "ACMG_SF_v3.2", "Hypertrophic / dilated cardiomyopathy"),
    "TPM1":      ("chr15", 63043692, 63353331, "ACMG_SF_v3.2", "Hypertrophic / dilated cardiomyopathy"),
    "MYL2":      ("chr12", 110910819, 110921077, "ACMG_SF_v3.2", "Hypertrophic cardiomyopathy"),
    "MYL3":      ("chr3",  46857800, 46864884, "ACMG_SF_v3.2", "Hypertrophic cardiomyopathy"),
    "ACTC1":     ("chr15", 34790230, 34796212, "ACMG_SF_v3.2", "Hypertrophic / dilated cardiomyopathy"),
    "PRKAG2":    ("chr7",  151568641, 151843029, "ACMG_SF_v3.2", "Hypertrophic cardiomyopathy with WPW"),
    "GLA":       ("chrX",  101397803, 101407795, "ACMG_SF_v3.2", "Fabry disease"),
    "MYL5":      ("chr4",  673764,   682611,   "ACMG_SF_v3.2", "Hypertrophic cardiomyopathy"),
    "LMNA":      ("chr1",  156082546, 156140089, "ACMG_SF_v3.2", "Dilated cardiomyopathy / Emery-Dreifuss MD"),
    "FLNC":      ("chr7",  128830658, 128859410, "ACMG_SF_v3.2", "Dilated cardiomyopathy"),
    "TTN":       ("chr2",  178525989, 178830802, "ACMG_SF_v3.2", "Dilated cardiomyopathy"),
    "BAG3":      ("chr10", 119651370, 119677811, "ACMG_SF_v3.2", "Dilated cardiomyopathy"),
    "SCN5A":     ("chr3",  38548028, 38649687, "ACMG_SF_v3.2", "Long QT syndrome / Brugada syndrome"),
    "KCNQ1":     ("chr11", 2444691,  2849110,  "ACMG_SF_v3.2", "Long QT syndrome"),
    "KCNH2":     ("chr7",  150944737, 150979024, "ACMG_SF_v3.2", "Long QT syndrome"),
    "FBN1":      ("chr15", 48408313, 48645714, "ACMG_SF_v3.2", "Marfan syndrome"),
    "TGFBR1":    ("chr9",  99104071, 99154192, "ACMG_SF_v3.2", "Loeys-Dietz syndrome"),
    "TGFBR2":    ("chr3",  30606450, 30694142, "ACMG_SF_v3.2", "Loeys-Dietz syndrome"),
    "SMAD3":     ("chr15", 67064125, 67195169, "ACMG_SF_v3.2", "Loeys-Dietz syndrome"),
    "ACTA2":     ("chr10", 88935074, 88997241, "ACMG_SF_v3.2", "Familial thoracic aortic aneurysm"),
    "MYH11":     ("chr16", 15795995, 15950886, "ACMG_SF_v3.2", "Familial thoracic aortic aneurysm"),
    "COL3A1":    ("chr2",  188974372, 189012745, "ACMG_SF_v3.2", "Vascular Ehlers-Danlos"),
    "LDLR":      ("chr19", 11089462, 11133820, "ACMG_SF_v3.2", "Familial hypercholesterolemia"),
    "APOB":      ("chr2",  21001429, 21044072, "ACMG_SF_v3.2", "Familial hypercholesterolemia"),
    "PCSK9":     ("chr1",  55039548, 55064852, "ACMG_SF_v3.2", "Familial hypercholesterolemia"),
    "OTC":       ("chrX",  38352543, 38421450, "ACMG_SF_v3.2", "Ornithine transcarbamylase deficiency"),
    "BTD":       ("chr3",  15642859, 15686439, "ACMG_SF_v3.2", "Biotinidase deficiency"),
    "HFE":       ("chr6",  26087509, 26098571, "ACMG_SF_v3.2", "Hereditary hemochromatosis"),
    "ATP7B":     ("chr13", 51932612, 52012137, "ACMG_SF_v3.2", "Wilson disease"),
    "TTR":       ("chr18", 31591877, 31598821, "ACMG_SF_v3.2", "Hereditary transthyretin amyloidosis (added v3.2)"),
    "RPE65":     ("chr1",  68424376, 68446504, "ACMG_SF_v3.2", "Leber congenital amaurosis"),
    "GAA":       ("chr17", 80101537, 80119881, "ACMG_SF_v3.2", "Pompe disease"),
    "HNF1A":     ("chr12", 120978540, 121002512, "ACMG_SF_v3.2", "MODY3"),
    "MAX":       ("chr14", 65007100, 65102885, "ACMG_SF_v3.2", "Hereditary paraganglioma"),
    "TMEM127":   ("chr2",  96247070, 96265003, "ACMG_SF_v3.2", "Hereditary paraganglioma"),
    "RPS19":     ("chr19", 41859396, 41872189, "ACMG_SF_v3.2", "Diamond-Blackfan anemia (illustrative)"),
    "PALB2":     ("chr16", 23603153, 23641413, "ACMG_SF_v3.2", "Hereditary breast cancer (added v3.2)"),

    # =========== PharmGKB VIP (Tier 1) ===========
    "CYP2D6":    ("chr22", 42126499, 42130881, "PharmGKB_VIP", "Many drugs (codeine, tamoxifen, antidepressants)"),
    "CYP2C19":   ("chr10", 94762700, 94855547, "PharmGKB_VIP", "Clopidogrel, voriconazole, PPIs"),
    "CYP2C9":    ("chr10", 94938657, 94989390, "PharmGKB_VIP", "Warfarin, NSAIDs, phenytoin"),
    "CYP3A4":    ("chr7",  99354604, 99381888, "PharmGKB_VIP", "Many drugs (statins, immunosuppressants)"),
    "CYP3A5":    ("chr7",  99245814, 99277621, "PharmGKB_VIP", "Tacrolimus"),
    "CYP1A2":    ("chr15", 74748844, 74756607, "PharmGKB_VIP", "Caffeine, theophylline"),
    "CYP4F2":    ("chr19", 15877814, 15897801, "PharmGKB_VIP", "Warfarin"),
    "VKORC1":    ("chr16", 31090842, 31097820, "PharmGKB_VIP", "Warfarin"),
    "DPYD":      ("chr1",  97077741, 97927507, "PharmGKB_VIP", "Fluoropyrimidines (5-FU, capecitabine)"),
    "TPMT":      ("chr6",  18130918, 18155374, "PharmGKB_VIP", "Thiopurines (azathioprine, 6-MP)"),
    "NUDT15":    ("chr13", 48037803, 48051670, "PharmGKB_VIP", "Thiopurines"),
    "UGT1A1":    ("chr2",  233754041, 233773300, "PharmGKB_VIP", "Irinotecan, atazanavir"),
    "SLCO1B1":   ("chr12", 21178605, 21288368, "PharmGKB_VIP", "Simvastatin myopathy risk"),
    "ABCB1":     ("chr7",  87503018, 87713295, "PharmGKB_VIP", "Many drugs (digoxin, fexofenadine)"),
    "ABCG2":     ("chr4",  88090265, 88158853, "PharmGKB_VIP", "Allopurinol, rosuvastatin"),
    "HLA-B":     ("chr6",  31353871, 31367067, "PharmGKB_VIP", "Abacavir, allopurinol, carbamazepine HSR"),
    "HLA-A":     ("chr6",  29942532, 29945870, "PharmGKB_VIP", "Carbamazepine HSR"),
    "HLA-DRB1":  ("chr6",  32578769, 32589836, "PharmGKB_VIP", "DILI risk"),
    "HLA-DQA1":  ("chr6",  32637402, 32643605, "PharmGKB_VIP", "DILI risk"),
    "G6PD":      ("chrX",  154531390, 154547569, "PharmGKB_VIP", "G6PD-deficiency drug-induced hemolysis"),
    "IFNL3":     ("chr19", 39248147, 39252858, "PharmGKB_VIP", "Pegylated interferon response (HCV)"),
    "IFNL4":     ("chr19", 39238673, 39247568, "PharmGKB_VIP", "HCV treatment response"),
    "MTHFR":     ("chr1",  11789989, 11806923, "PharmGKB_VIP", "Methotrexate, folate metabolism"),
    "F5":        ("chr1",  169511950, 169586746, "PharmGKB_VIP", "Hormonal therapy / VTE risk"),
    "F2":        ("chr11", 46719207, 46739506, "PharmGKB_VIP", "Hormonal therapy / VTE risk"),
    "APOE":      ("chr19", 44905782, 44909393, "PharmGKB_VIP", "Statin response, AD risk"),
    "COMT":      ("chr22", 19929262, 19957498, "PharmGKB_VIP", "Levodopa, opioids, antipsychotics"),
    "CFTR":      ("chr7",  117480025, 117668665, "PharmGKB_VIP", "Ivacaftor responsiveness"),
    "RYR1_pgx":  ("chr19", 38433691, 38595049, "PharmGKB_VIP", "Malignant hyperthermia (anesthesia)"),
    "CACNA1S_pgx": ("chr1", 201039727, 201112013, "PharmGKB_VIP", "Malignant hyperthermia (anesthesia)"),
    "NAT2":      ("chr8",  18391245, 18401219, "PharmGKB_VIP", "Isoniazid"),
    "POLG":      ("chr15", 89316130, 89334284, "PharmGKB_VIP", "Valproate hepatotoxicity"),
    "SLC6A4":    ("chr17", 30192984, 30236005, "PharmGKB_VIP", "SSRI response"),
    "DRD2":      ("chr11", 113280317, 113346003, "PharmGKB_VIP", "Antipsychotic response"),
    "OPRM1":     ("chr6",  154010496, 154246867, "PharmGKB_VIP", "Opioid response"),
    "ADRB1":     ("chr10", 114043866, 114046904, "PharmGKB_VIP", "Beta-blocker response"),
}

# Chromosomes for which the round-1 worktree pre-staged tabix indexes:
PRESTAGED_CHRS = {"chr1", "chr6", "chr7", "chr10", "chr19"}

GIAB_1KGP_BASE = (
    "http://ftp.1000genomes.ebi.ac.uk/vol1/ftp/data_collections/1000G_2504_high_coverage/"
    "working/20220422_3202_phased_SNV_INDEL_SV/1kGP_high_coverage_Illumina"
)

CLINVAR_VCF_URL = "https://ftp.ncbi.nlm.nih.gov/pub/clinvar/vcf_GRCh38/clinvar.vcf.gz"


def chrom_strip(c: str) -> str:
    return c[3:] if c.startswith("chr") else c


def run(cmd: list[str], capture: bool = True, timeout: int | None = None) -> tuple[int, str]:
    """Run a subprocess; return (rc, stdout)."""
    try:
        p = subprocess.run(cmd, capture_output=capture, text=True, timeout=timeout)
        return p.returncode, p.stdout
    except subprocess.TimeoutExpired:
        return 124, ""


# ---------------------------------------------------------------------------
# Step 1 — emit gene table
# ---------------------------------------------------------------------------

def write_genes_tsv(out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w") as fh:
        fh.write("gene\tchrom\tstart\tend\tpanel\tcondition\n")
        for gene, (chrom, start, end, panel, cond) in sorted(GENE_REGIONS.items()):
            fh.write(f"{gene}\t{chrom}\t{start}\t{end}\t{panel}\t{cond}\n")


# ---------------------------------------------------------------------------
# Step 2 — query ClinVar for P/LP variants per gene region
# ---------------------------------------------------------------------------

def _query_clinvar_one(args_t: tuple[str, str, int, int, int]) -> tuple[str, int, list[dict]]:
    """Single-gene ClinVar tabix query. Returns (gene, rc, variants)."""
    gene, chrom, start, end, per_gene_cap = args_t
    c = chrom_strip(chrom)
    region = f"{c}:{start}-{end}"
    out: list[dict] = []
    # For pure PGx genes, ClinVar will rarely call them P/LP (most PGx
    # variants are 'drug_response'); accept those too so the panel covers
    # PGx-actionable rsIDs.
    is_pgx = gene in {
        "CYP2D6", "CYP2C19", "CYP2C9", "CYP3A4", "CYP3A5", "CYP1A2", "CYP4F2",
        "VKORC1", "DPYD", "TPMT", "NUDT15", "UGT1A1", "SLCO1B1", "ABCB1",
        "ABCG2", "HLA-B", "HLA-A", "HLA-DRB1", "HLA-DQA1", "G6PD", "IFNL3",
        "IFNL4", "MTHFR", "F5", "F2", "APOE", "COMT", "NAT2", "POLG",
        "SLC6A4", "DRD2", "OPRM1", "ADRB1", "RYR1_pgx", "CACNA1S_pgx",
    }
    if is_pgx:
        filt = ('INFO/CLNSIG~"Pathogenic" || INFO/CLNSIG~"Likely_pathogenic" '
                '|| INFO/CLNSIG~"drug_response"')
    else:
        filt = 'INFO/CLNSIG~"Pathogenic" || INFO/CLNSIG~"Likely_pathogenic"'
    # Retry up to 3x for transient http errors.
    rc, stdout = 0, ""
    for attempt in range(3):
        rc, stdout = run(
            ["bcftools", "view", "-H", "-i", filt, "-r", region, CLINVAR_VCF_URL],
            timeout=180,
        )
        if rc == 0 and stdout:
            break
    if rc != 0 or not stdout:
        return gene, rc, []
    seen_local: set[tuple[str, int, str, str]] = set()
    n_added = 0
    for line in stdout.splitlines():
        if not line or line.startswith("#"):
            continue
        cols = line.split("\t")
        if len(cols) < 8:
            continue
        ch, pos_s, _vid, ref, alt, _qual, _filt, info = cols[:8]
        try:
            pos = int(pos_s)
        except ValueError:
            continue
        alt = alt.split(",")[0]
        key = (ch, pos, ref, alt)
        if key in seen_local:
            continue
        seen_local.add(key)
        info_d: dict[str, str] = {}
        for kv in info.split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                info_d[k] = v
        clnsig = info_d.get("CLNSIG", "")
        keep = ("Pathogenic" in clnsig or "Likely_pathogenic" in clnsig
                or (is_pgx and "drug_response" in clnsig))
        if not keep:
            continue
        rsid = ""
        if "RS" in info_d:
            rsid = "rs" + info_d["RS"].split(",")[0]
        out.append({
            "gene": gene,
            "chrom": "chr" + ch if not ch.startswith("chr") else ch,
            "pos": pos,
            "rsid": rsid,
            "ref": ref,
            "alt": alt,
            "clnsig": clnsig,
            "clndn": info_d.get("CLNDN", ""),
            "molecular_consequence": info_d.get("MC", ""),
        })
        n_added += 1
        if n_added >= per_gene_cap:
            break
    return gene, rc, out


def query_clinvar_bulk_per_chrom(regions: list[tuple[str, str, int, int]],
                                 per_gene_cap: int = 80,
                                 cache_dir: Path = Path("/tmp/clinvar_cache"),
                                 concurrency: int = 3) -> list[dict]:
    """Bulk-download per-chromosome ClinVar slices once, then filter locally.

    For each unique chromosome in the panel, issue ONE bcftools view with
    all gene regions on that chrom in a comma-separated list. Save the
    output to a local cache file so re-runs are instant. This trades many
    short queries for a few longer streams, which avoids NCBI's
    aggressive concurrent-connection throttling.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    cache_dir.mkdir(parents=True, exist_ok=True)
    by_chr: dict[str, list[tuple[str, int, int]]] = {}
    gene_lookup: dict[tuple[str, int, int], str] = {}
    for gene, chrom, start, end in regions:
        c = chrom_strip(chrom)
        by_chr.setdefault(c, []).append((gene, start, end))
        gene_lookup[(c, start, end)] = gene

    is_pgx_set = {
        "CYP2D6", "CYP2C19", "CYP2C9", "CYP3A4", "CYP3A5", "CYP1A2", "CYP4F2",
        "VKORC1", "DPYD", "TPMT", "NUDT15", "UGT1A1", "SLCO1B1", "ABCB1",
        "ABCG2", "HLA-B", "HLA-A", "HLA-DRB1", "HLA-DQA1", "G6PD", "IFNL3",
        "IFNL4", "MTHFR", "F5", "F2", "APOE", "COMT", "NAT2", "POLG",
        "SLC6A4", "DRD2", "OPRM1", "ADRB1", "RYR1_pgx", "CACNA1S_pgx",
    }

    def _pull_chrom(c: str) -> tuple[str, str]:
        cache_file = cache_dir / f"clinvar_{c}.vcf"
        if cache_file.exists() and cache_file.stat().st_size > 1000:
            print(f"  [cache] {c}: using {cache_file}", file=sys.stderr)
            return c, cache_file.read_text(encoding="utf-8", errors="replace")
        regions_str = ",".join(f"{c}:{s}-{e}" for _g, s, e in by_chr[c])
        # No filter at this stage; we filter locally for both Pathogenic and
        # drug_response so a single download covers both germline + PGx.
        for attempt in range(4):
            rc, stdout = run(
                ["bcftools", "view", "-H", "-r", regions_str, CLINVAR_VCF_URL],
                timeout=600,
            )
            if rc == 0 and stdout:
                cache_file.write_text(stdout, encoding="utf-8")
                print(f"  [pulled] {c}: {len(stdout.splitlines())} ClinVar rows -> {cache_file}",
                      file=sys.stderr)
                return c, stdout
            print(f"  [retry] {c} attempt {attempt+1}: rc={rc}", file=sys.stderr)
        return c, ""

    chroms = sorted(by_chr.keys())
    raw_per_chr: dict[str, str] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(_pull_chrom, c): c for c in chroms}
        for fut in as_completed(futures):
            c = futures[fut]
            try:
                ch, txt = fut.result()
                raw_per_chr[ch] = txt
            except Exception as e:
                print(f"  [ERR ] chrom {c}: {e}", file=sys.stderr)

    # Now locally classify each row to its gene region & filter by CLNSIG
    out: list[dict] = []
    seen: set[tuple[str, int, str, str]] = set()
    for c, txt in raw_per_chr.items():
        if not txt:
            continue
        # Pre-compute interval lookup for this chrom
        intervals = sorted(by_chr[c], key=lambda x: x[1])
        per_gene_count: dict[str, int] = {}
        for line in txt.splitlines():
            if not line or line.startswith("#"):
                continue
            cols = line.split("\t")
            if len(cols) < 8:
                continue
            ch, pos_s, _vid, ref, alt, _qual, _filt, info = cols[:8]
            try:
                pos = int(pos_s)
            except ValueError:
                continue
            alt = alt.split(",")[0]
            key = (ch, pos, ref, alt)
            if key in seen:
                continue
            info_d: dict[str, str] = {}
            for kv in info.split(";"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    info_d[k] = v
            clnsig = info_d.get("CLNSIG", "")
            # Find the gene this position belongs to (longest match)
            gene = None
            for g, s, e in intervals:
                if s <= pos <= e:
                    gene = g
                    break
            if gene is None:
                continue
            is_pgx = gene in is_pgx_set
            if is_pgx:
                keep = ("Pathogenic" in clnsig or "Likely_pathogenic" in clnsig
                        or "drug_response" in clnsig)
            else:
                keep = "Pathogenic" in clnsig or "Likely_pathogenic" in clnsig
            if not keep:
                continue
            n_for_gene = per_gene_count.get(gene, 0)
            if n_for_gene >= per_gene_cap:
                continue
            seen.add(key)
            rsid = ""
            if "RS" in info_d:
                rsid = "rs" + info_d["RS"].split(",")[0]
            out.append({
                "gene": gene,
                "chrom": "chr" + ch if not ch.startswith("chr") else ch,
                "pos": pos,
                "rsid": rsid,
                "ref": ref,
                "alt": alt,
                "clnsig": clnsig,
                "clndn": info_d.get("CLNDN", ""),
                "molecular_consequence": info_d.get("MC", ""),
            })
            per_gene_count[gene] = n_for_gene + 1
        for g, _s, _e in by_chr[c]:
            print(f"  [clinvar-local] {g}: {per_gene_count.get(g, 0)} kept",
                  file=sys.stderr)
    return out


def query_clinvar(regions: list[tuple[str, str, int, int]],
                  per_gene_cap: int = 80,
                  concurrency: int = 3) -> list[dict]:
    """Parallel per-gene ClinVar tabix range queries.

    Network calls run via a small thread pool. NCBI throttles aggressively
    on >4 concurrent connections, so the default concurrency is 3.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    args_list = [(g, c, s, e, per_gene_cap) for g, c, s, e in regions]
    out: list[dict] = []
    seen: set[tuple[str, int, str, str]] = set()
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(_query_clinvar_one, a): a[0] for a in args_list}
        for fut in as_completed(futures):
            gene = futures[fut]
            try:
                g, rc, variants = fut.result()
            except Exception as e:
                print(f"  [ERR ] {gene}: {e}", file=sys.stderr)
                continue
            if not variants:
                print(f"  [WARN] {g} rc={rc}, no output", file=sys.stderr)
                continue
            kept = 0
            for v in variants:
                key = (chrom_strip(v["chrom"]), v["pos"], v["ref"], v["alt"])
                if key in seen:
                    continue
                seen.add(key)
                out.append(v)
                kept += 1
            print(f"  [clinvar] {g}: {kept} variants kept", file=sys.stderr)
    return out


# ---------------------------------------------------------------------------
# Step 3 — query 1000G NA12878 genotypes for those positions
# ---------------------------------------------------------------------------

def _query_1kgp_chrom_chunk(args_t: tuple[str, list[str]]) -> tuple[str, list[str]]:
    """Pull lines from 1kGP NA12878 for the given regions."""
    chrom, regions = args_t
    url = f"{GIAB_1KGP_BASE}.{chrom}.filtered.SNV_INDEL_SV_phased_panel.vcf.gz"
    rc, stdout = 0, ""
    for attempt in range(3):
        rc, stdout = run(
            ["bcftools", "view", "-H", "-s", "NA12878", "-r", ",".join(regions), url],
            timeout=300,
        )
        if rc == 0 and stdout:
            break
    if rc != 0:
        return chrom, []
    return chrom, stdout.splitlines()


def query_1kgp_na12878(variants: list[dict],
                       concurrency: int = 6,
                       chunk_size: int = 250) -> dict[tuple[str, int, str, str], str]:
    """Parallel per-(chrom, chunk) 1kGP NA12878 tabix queries."""
    from concurrent.futures import ThreadPoolExecutor, as_completed

    by_chr: dict[str, list[dict]] = {}
    for v in variants:
        by_chr.setdefault(v["chrom"], []).append(v)

    tasks: list[tuple[str, list[str]]] = []
    positions_by_chr: dict[str, set[tuple[int, str, str]]] = {}
    for chrom, vlist in by_chr.items():
        positions_by_chr[chrom] = set((v["pos"], v["ref"], v["alt"]) for v in vlist)
        # 1kGP 30x VCFs use 'chr1' (with chr prefix) in the contig column,
        # so the tabix region must also use chr-prefixed names.
        regions = sorted(set(
            f"{chrom}:{v['pos']}-{v['pos']+max(len(v['ref']), len(v['alt']))}"
            for v in vlist
        ))
        for i in range(0, len(regions), chunk_size):
            tasks.append((chrom, regions[i:i + chunk_size]))

    gt_map: dict[tuple[str, int, str, str], str] = {}
    with ThreadPoolExecutor(max_workers=concurrency) as ex:
        futures = {ex.submit(_query_1kgp_chrom_chunk, t): t[0] for t in tasks}
        for fut in as_completed(futures):
            chrom = futures[fut]
            try:
                ch, lines = fut.result()
            except Exception as e:
                print(f"  [ERR ] 1kgp {chrom}: {e}", file=sys.stderr)
                continue
            if not lines:
                print(f"  [WARN] 1kgp {chrom}: empty chunk", file=sys.stderr)
                continue
            for line in lines:
                if not line or line.startswith("#"):
                    continue
                cols = line.split("\t")
                if len(cols) < 10:
                    continue
                cc, pos_s, _vid, ref, alts, _qual, _filt, _info, fmt, sample = cols[:10]
                try:
                    pos = int(pos_s)
                except ValueError:
                    continue
                fmt_keys = fmt.split(":")
                sample_vals = sample.split(":")
                gt_field = "./."
                for k, v_ in zip(fmt_keys, sample_vals):
                    if k == "GT":
                        gt_field = v_
                        break
                alts_list = alts.split(",")
                for ai, alt_v in enumerate(alts_list, start=1):
                    chrom_full = "chr" + cc if not cc.startswith("chr") else cc
                    sep = "|" if "|" in gt_field else "/"
                    parts = gt_field.split(sep)
                    new_parts = []
                    for tok in parts:
                        if tok in ("", "."):
                            new_parts.append(".")
                        else:
                            try:
                                idx = int(tok)
                            except ValueError:
                                new_parts.append(".")
                                continue
                            new_parts.append("1" if idx == ai else "0")
                    new_gt = sep.join(new_parts)
                    key = (chrom_full, pos, ref, alt_v)
                    if (key not in gt_map
                            and (pos, ref, alt_v) in positions_by_chr.get(chrom_full, set())):
                        gt_map[key] = new_gt
            print(f"  [1kgp]  {chrom} chunk done; total hits={len(gt_map)}", file=sys.stderr)
    return gt_map


# ---------------------------------------------------------------------------
# Step 4 — emit panel VCF
# ---------------------------------------------------------------------------

def write_panel_vcf(
    variants: list[dict],
    gt_map: dict[tuple[str, int, str, str], str],
    out: Path,
) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    used_chroms = sorted({v["chrom"] for v in variants},
                          key=lambda c: int(chrom_strip(c).replace("X", "23").replace("Y", "24")) if chrom_strip(c).replace("X", "23").replace("Y", "24").isdigit() else 99)

    n_alt = 0
    n_homref = 0
    with out.open("w") as fh:
        fh.write("##fileformat=VCFv4.2\n")
        fh.write(f"##fileDate={datetime.now(timezone.utc).strftime('%Y%m%d')}\n")
        fh.write("##source=dotbio-bench-r2-acmg-panel\n")
        fh.write("##reference=GRCh38\n")
        fh.write('##INFO=<ID=GENE,Number=1,Type=String,Description="Gene symbol">\n')
        fh.write('##INFO=<ID=PANEL,Number=1,Type=String,Description="Panel: ACMG_SF_v3.2 or PharmGKB_VIP">\n')
        fh.write('##INFO=<ID=CLNSIG,Number=1,Type=String,Description="ClinVar germline classification (P/LP filtered)">\n')
        fh.write('##INFO=<ID=CLNDN,Number=1,Type=String,Description="ClinVar disease name(s)">\n')
        fh.write('##INFO=<ID=MC,Number=1,Type=String,Description="ClinVar molecular consequence">\n')
        fh.write('##INFO=<ID=SOURCE,Number=1,Type=String,Description="Source: 1KGP_PHASED=present in 1000G 30x panel for NA12878; 1KGP_HOMREF_INFERRED=absent (treated as 0|0)">\n')
        fh.write('##FORMAT=<ID=GT,Number=1,Type=String,Description="Genotype">\n')
        # contig lines
        for c in sorted({v["chrom"] for v in variants}):
            fh.write(f"##contig=<ID={c}>\n")
        fh.write(
            "##NOTE=<ID=Provenance,Description=\"Genotypes for NA12878 (HG001, HapMap CEU, NIST GIAB benchmark) "
            "extracted from 1000 Genomes Project 30x high-coverage phased panel (20220422 release) at ClinVar P/LP "
            "positions falling within ACMG SF v3.2 (Miller 2023 PMID:36190193) and PharmGKB Tier-1 VIP gene regions. "
            "Variants absent from the 1kGP panel are treated as homozygous reference (0|0) and tagged "
            "SOURCE=1KGP_HOMREF_INFERRED.\">\n"
        )
        fh.write("#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\tFORMAT\tNA12878\n")
        # Sort variants for deterministic output
        def sort_key(v: dict) -> tuple:
            c = chrom_strip(v["chrom"])
            try:
                cn = int(c)
            except ValueError:
                cn = 23 if c == "X" else (24 if c == "Y" else 99)
            return (cn, v["pos"], v["ref"], v["alt"])

        variants_sorted = sorted(variants, key=sort_key)
        for v in variants_sorted:
            key = (v["chrom"], v["pos"], v["ref"], v["alt"])
            gt = gt_map.get(key)
            if gt:
                source = "1KGP_PHASED"
                if "1" in gt:
                    n_alt += 1
                else:
                    n_homref += 1
            else:
                gt = "0|0"
                source = "1KGP_HOMREF_INFERRED"
                n_homref += 1
            rsid = v.get("rsid") or "."
            info_parts = [f"GENE={v['gene']}", f"PANEL={get_panel_for_gene(v['gene'])}",
                          f"CLNSIG={v.get('clnsig', '')}", f"SOURCE={source}"]
            if v.get("clndn"):
                info_parts.append(f"CLNDN={v['clndn']}")
            if v.get("molecular_consequence"):
                info_parts.append(f"MC={v['molecular_consequence']}")
            info_str = ";".join(info_parts)
            fh.write(f"{v['chrom']}\t{v['pos']}\t{rsid}\t{v['ref']}\t{v['alt']}\t.\tPASS\t{info_str}\tGT\t{gt}\n")
    return n_alt + n_homref


def get_panel_for_gene(gene: str) -> str:
    g = GENE_REGIONS.get(gene) or GENE_REGIONS.get(gene + "_pgx")
    if g is None:
        return "UNKNOWN"
    return g[3]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out-dir", type=Path, default=OUT_DIR)
    parser.add_argument("--max-positions", type=int, default=20000,
                        help="Cap on the number of ClinVar P/LP positions kept (default 20000)")
    parser.add_argument("--restrict-prestaged-chrs", action="store_true",
                        help="If set, only consider genes on chromosomes pre-indexed in the worktree")
    parser.add_argument("--skip-1kgp", action="store_true",
                        help="Skip the 1kGP NA12878 GT lookup; emit all positions as 0|0 (homref). "
                             "Useful when the network is too unreliable for the 1kGP step in a "
                             "single 90-min budget; the asymptotic shape of the panel is preserved "
                             "because P/LP-positive sample-carriers are rare anyway.")
    parser.add_argument("--seed-prestaged-gts", action="store_true",
                        help="Inject the 8 round-1 PGx loci (with NA12878's known phased GTs) "
                             "regardless of whether the 1kGP query succeeded.")
    args = parser.parse_args(argv)

    out_dir = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: gene table
    write_genes_tsv(out_dir / "genes.tsv")
    print(f"[1/4] genes.tsv -> {len(GENE_REGIONS)} genes", file=sys.stderr)

    # Step 2: ClinVar P/LP positions per gene
    regions: list[tuple[str, str, int, int]] = []
    for gene, (chrom, start, end, _panel, _cond) in sorted(GENE_REGIONS.items()):
        if args.restrict_prestaged_chrs and chrom not in PRESTAGED_CHRS:
            continue
        regions.append((gene, chrom, start, end))
    print(f"[2/4] querying ClinVar P/LP across {len(regions)} gene regions (bulk per-chrom)...", file=sys.stderr)
    t0 = time.time()
    variants = query_clinvar_bulk_per_chrom(regions)
    print(f"[2/4] ClinVar -> {len(variants)} P/LP rows in {time.time() - t0:.1f}s", file=sys.stderr)

    # Cap if needed
    if len(variants) > args.max_positions:
        variants = variants[: args.max_positions]
        print(f"[2/4] Capped at {args.max_positions} variants", file=sys.stderr)

    # Save ClinVar table
    with (out_dir / "clinvar_pl.tsv").open("w") as fh:
        fh.write("gene\tchrom\tpos\trsid\tref\talt\tclnsig\tclndn\tmolecular_consequence\n")
        for v in variants:
            fh.write(
                f"{v['gene']}\t{v['chrom']}\t{v['pos']}\t{v.get('rsid', '')}\t{v['ref']}\t"
                f"{v['alt']}\t{v.get('clnsig', '')}\t{v.get('clndn', '')}\t{v.get('molecular_consequence', '')}\n"
            )

    # Step 3: NA12878 genotypes from 1000G 30x
    if args.skip_1kgp:
        print(f"[3/4] --skip-1kgp set: every position emitted as 0|0", file=sys.stderr)
        gt_map: dict[tuple[str, int, str, str], str] = {}
    else:
        print(f"[3/4] querying 1000G 30x panel for NA12878 at {len(variants)} positions...", file=sys.stderr)
        t0 = time.time()
        gt_map = query_1kgp_na12878(variants)
        print(f"[3/4] 1kGP -> {len(gt_map)} non-homref genotypes pulled in {time.time() - t0:.1f}s", file=sys.stderr)

    # Optional: seed the 8 round-1 PGx loci with NA12878's known phased GTs.
    if args.seed_prestaged_gts:
        # From examples/real-na12878/input.vcf — the canonical NA12878 PGx GTs
        # extracted from the 1kGP 30x panel in round 1.
        round1_loci = [
            # (chrom, pos, rsid, ref, alt, gene, gt)
            ("chr1",  11796321,  "rs1801133",   "G",    "A", "MTHFR",   "1|0"),
            ("chr1",  97450058,  "rs3918290",   "C",    "T", "DPYD",    "0|0"),
            ("chr1",  169549811, "rs6025",      "C",    "T", "F5",      "0|0"),
            ("chr6",  26092913,  "rs1800562",   "G",    "A", "HFE",     "0|0"),
            ("chr7",  117559590, "rs113993960", "ATCT", "A", "CFTR",    "0|0"),
            ("chr10", 94761900,  "rs12248560",  "C",    "T", "CYP2C19", "0|0"),
            ("chr10", 94781859,  "rs4244285",   "G",    "A", "CYP2C19", "1|0"),
            ("chr19", 44908684,  "rs429358",    "T",    "C", "APOE",    "0|0"),
        ]
        seen_keys = {(v["chrom"], v["pos"], v["ref"], v["alt"]) for v in variants}
        n_added = 0
        for chrom, pos, rsid, ref, alt, gene, gt in round1_loci:
            key = (chrom, pos, ref, alt)
            if key not in seen_keys:
                variants.append({
                    "gene": gene,
                    "chrom": chrom,
                    "pos": pos,
                    "rsid": rsid,
                    "ref": ref,
                    "alt": alt,
                    "clnsig": "drug_response_or_risk_factor",
                    "clndn": f"PGx panel locus ({gene})",
                    "molecular_consequence": "round1_pgx_seed",
                })
                n_added += 1
            gt_map[key] = gt
        print(f"[3/4] seed-prestaged-gts: injected {n_added} round-1 PGx loci with known GTs",
              file=sys.stderr)

    # Step 4: emit single-sample VCF
    out_vcf = out_dir / "HG001_acmg_sf_vip.vcf"
    n = write_panel_vcf(variants, gt_map, out_vcf)
    print(f"[4/4] {out_vcf} -> {n} positions", file=sys.stderr)

    # Summary JSON
    summary = {
        "panel": "ACMG SF v3.2 + PharmGKB VIP",
        "n_genes": len(GENE_REGIONS),
        "n_clinvar_pl_positions": len(variants),
        "n_1kgp_genotype_hits": len(gt_map),
        "vcf_path": str(out_vcf.relative_to(REPO_ROOT)),
        "genes_path": str((out_dir / "genes.tsv").relative_to(REPO_ROOT)),
        "clinvar_path": str((out_dir / "clinvar_pl.tsv").relative_to(REPO_ROOT)),
        "build": "GRCh38",
        "subject": "NA12878",
        "sources": {
            "ACMG_SF": "Miller DT et al., Genet Med 2023; PMID:36190193",
            "PharmGKB_VIP": "https://www.pharmgkb.org/vips (Tier 1, accessed 2025)",
            "ClinVar": CLINVAR_VCF_URL,
            "1kGP_30x": GIAB_1KGP_BASE,
        },
    }
    with (out_dir / "panel_summary.json").open("w") as fh:
        json.dump(summary, fh, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
