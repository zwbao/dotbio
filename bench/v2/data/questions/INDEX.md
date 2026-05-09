# Clinical 50-question benchmark — INDEX

**Companion to** `bench/v2/SPEC.md` §3.3 (Experiment 3) and `bench/v2/TASKS.md`
Task 4. Each YAML file (`qNN.yaml`) is the canonical record for one question;
this file is a one-line directory.

**Domains** (10 questions each):

- `pgx` — pharmacogenomics (germline gene → drug recommendation)
- `oncology_somatic` — somatic tumor variant → therapy selection / diagnosis
- `carrier_screening` — preconception / prenatal carrier testing
- `hereditary_risk` — hereditary cancer / cardiomyopathy risk-management
- `dose_adjustment` — drug-dose adjustment by genotype, organ function, or label

**Context-dependent flag**: `q27`, `q50` — these are the deliberately
"depends on X" questions that test whether the format surfaces enough context
(per Task 4 brief).

| #   | Domain                | One-line summary                                                                               | Primary guideline                          |
|-----|-----------------------|------------------------------------------------------------------------------------------------|--------------------------------------------|
| q01 | pgx                   | CYP2C19 *1/*2 (IM) + ACS/PCI: clopidogrel vs alternative P2Y12                                | CPIC clopidogrel 2022 (Lee)                |
| q02 | pgx                   | TPMT *3A/*3A (PM) + 6-MP 75 mg/m² ALL maintenance: dose strategy                              | CPIC thiopurines 2018 (Relling)            |
| q03 | pgx                   | HLA-B*57:01 positive + abacavir-naive HIV: contraindication                                   | CPIC abacavir 2014 (Martin)                |
| q04 | pgx                   | HLA-B*15:02 positive + Han Chinese, new epilepsy: avoid carbamazepine                         | CPIC carbamazepine 2018 (Phillips)         |
| q05 | pgx                   | DPYD *2A heterozygote + 5-FU mCRC: 50% starting-dose reduction                                | CPIC fluoropyrimidines 2017 (Amstutz)      |
| q06 | pgx                   | CYP2D6 UM + pediatric post-tonsillectomy codeine: avoid                                       | CPIC codeine 2014 (Crews) / FDA            |
| q07 | pgx                   | SLCO1B1 rs4149056 T/C + simvastatin 40 mg: avoid >20 mg or switch                             | CPIC statins 2022 (Cooper-DeHoff)          |
| q08 | pgx                   | CYP2C19 *17/*17 (UM) + voriconazole: alternative antifungal                                   | CPIC voriconazole 2017 (Moriyama)          |
| q09 | pgx                   | CYP2D6 *4/*4 (PM) + ER+ early breast cancer adjuvant: AI ± OFS not tamoxifen                 | CPIC tamoxifen 2018 (Goetz)                |
| q10 | pgx                   | CYP3A5 *1/*3 (expresser) + de novo kidney transplant: 1.5–2× tacrolimus dose                  | CPIC tacrolimus 2015 (Birdwell)            |
| q11 | oncology_somatic      | EGFR exon 19 deletion + treatment-naive metastatic NSCLC: osimertinib first-line              | NCCN NSCLC v3.2024; FDA osimertinib        |
| q12 | oncology_somatic      | BRAF V600E + treatment-naive unresectable melanoma: BRAF/MEK combo                            | FDA dabrafenib/trametinib; NCCN Melanoma   |
| q13 | oncology_somatic      | KRAS G12C + post-1L NSCLC: sotorasib or adagrasib                                             | FDA sotorasib 2021 / adagrasib 2022        |
| q14 | oncology_somatic      | HER2 IHC 3+ ER+ metastatic breast cancer: THP regimen first-line                              | NCCN Breast v3.2024 (Category 1)           |
| q15 | oncology_somatic      | MSI-H/dMMR endometrial cancer post-platinum: pembrolizumab tumor-agnostic                     | FDA pembrolizumab 2017 / 2023              |
| q16 | oncology_somatic      | Somatic BRCA2 + platinum-sensitive ovarian CR: olaparib maintenance                           | FDA olaparib 2018; SOLO-1; NCCN Ovarian    |
| q17 | oncology_somatic      | FLT3-ITD + newly diagnosed AML, fit for 7+3: add midostaurin                                  | FDA midostaurin 2017; RATIFY               |
| q18 | oncology_somatic      | ETV6-NTRK3 fusion + pediatric infantile fibrosarcoma: larotrectinib/entrectinib               | FDA larotrectinib 2018 / entrectinib 2019  |
| q19 | oncology_somatic      | EML4-ALK + treatment-naive metastatic NSCLC: alectinib first-line                             | NCCN NSCLC v3.2024; FDA alectinib 2017     |
| q20 | oncology_somatic      | JAK2 V617F + Hb 19, suppressed EPO, BM panmyelosis: polycythemia vera (WHO/ICC 2022)          | WHO 2022 / ICC 2022                        |
| q21 | carrier_screening     | F508del heterozygote female, partner untested: offer partner CFTR screen (≥100 variants)      | ACMG CFTR 2023 (Deignan)                   |
| q22 | carrier_screening     | Both parents 1-copy SMN1: 25% per-pregnancy SMA risk; counseling                              | ACMG 2021 (Gregg); ACOG 691                |
| q23 | carrier_screening     | HBB c.20A>T (HbS trait) + African-ancestry partner untested: partner electrophoresis          | ACOG hemoglobinopathies 2022               |
| q24 | carrier_screening     | FMR1 87 CGG (premutation): 50% transmission, ~100% expansion to full mutation                 | ACMG fragile-X 2013 (Monaghan); ACOG 691   |
| q25 | carrier_screening     | Ashkenazi Jewish couple — universal Tier-3 panel preferred over ancestry-only                 | ACMG 2021 (Gregg)                          |
| q26 | carrier_screening     | HEXA biallelic carriers (AJ): 25% Tay-Sachs risk; PGT-M / prenatal options                    | ACMG 2021 (Gregg); ACOG 691                |
| q27 | carrier_screening     | F508del het mother + 100-variant-negative father: residual risk depends on ancestry           | ACMG CFTR 2023 (Deignan) — context-dependent |
| q28 | carrier_screening     | GBA1 N370S/L444P compound: 25% Gaucher type I risk                                            | ACMG 2021; GeneReviews GBA1                |
| q29 | carrier_screening     | --SEA/αα + --SEA/αα: 25% Hb Bart hydrops fetalis risk; offer prenatal Dx                      | ACOG hemoglobinopathies 2022               |
| q30 | carrier_screening     | DMD del-exon-45-50 carrier mother: 50% affected sons / 50% carrier daughters; cardiac surveil | ACMG 2021; AAP/AHA carrier cardiac guide   |
| q31 | hereditary_risk       | BRCA1 carrier 38 yo, completed childbearing: RRSO at 35–40 yo                                 | NCCN Breast/Ovarian/Pancreatic v3.2024     |
| q32 | hereditary_risk       | BRCA2 carrier 30 yo, plans children: RRSO at 40–45 yo                                         | NCCN Breast/Ovarian/Pancreatic v3.2024     |
| q33 | hereditary_risk       | MSH2 carrier 22 yo: colonoscopy at 20–25 yo, every 1–2 yr                                     | NCCN Colorectal/Endo/Gastric v3.2024       |
| q34 | hereditary_risk       | TP53 missense carrier (LFS) 44 yo: annual whole-body MRI + brain MRI + organ-specific surv.   | NCCN BR/OV/PA v3.2024; Toronto/Villani     |
| q35 | hereditary_risk       | PALB2 carrier 35 yo + family history: annual breast MRI age 30 + mammogram                    | NCCN Breast/Ovarian/Pancreatic v3.2024     |
| q36 | hereditary_risk       | LDLR carrier 44 yo, LDL-C 245: HeFH; high-intensity statin, ≥50% reduction                    | AHA/ACC 2018 cholesterol; NLA              |
| q37 | hereditary_risk       | KCNQ1 LQT1 24 yo, QTc 470: nadolol/propranolol first-line; trigger avoidance                  | ESC 2022; HRS/EHRA/APHRS 2013              |
| q38 | hereditary_risk       | MYH7 HCM with LVWT 28, syncope, FH SCD, apical aneurysm: primary-prevention ICD reasonable    | AHA/ACC HCM 2020 / 2024                    |
| q39 | hereditary_risk       | CDKN2A FAMMM 50 yo + strong FH melanoma: skin + alternating EUS/MRCP from 40                  | CAPS Consortium 2020; NCCN; GeneReviews    |
| q40 | hereditary_risk       | HFE C282Y/C282Y, ferritin 850, TS 65%: phlebotomy; biopsy not routine; family screen          | ACG hereditary hemochromatosis 2019        |
| q41 | dose_adjustment       | Apixaban for AF: 80 yo, 55 kg, SCr 1.6 → 2.5 mg BID (meets all 3 criteria)                    | Eliquis FDA label                          |
| q42 | dose_adjustment       | Enoxaparin 80 kg, CrCl 22 mL/min, DVT: 1 mg/kg SC ONCE daily                                  | Lovenox FDA label                          |
| q43 | dose_adjustment       | UGT1A1 *28/*28 + irinotecan: 1 dose-level reduction (~70%)                                    | FDA irinotecan label; DPWG 2018            |
| q44 | dose_adjustment       | Edoxaban for AF, CrCl 96 mL/min: NOT recommended (boxed warning) — use alternative            | Savaysa FDA label                          |
| q45 | dose_adjustment       | CYP2D6 UM + paroxetine selection: avoid; use non-CYP2D6 SSRI                                  | CPIC SSRI 2023 (Bousman)                   |
| q46 | dose_adjustment       | CYP2D6 *4/*4 PM child + atomoxetine: 0.5 mg/kg/d; titrate after ≥4 weeks                      | CPIC atomoxetine 2019 (Brown)              |
| q47 | dose_adjustment       | CYP2D6 UM + CINV: granisetron over ondansetron/tropisetron                                    | CPIC ondansetron/tropisetron 2017 (Bell)   |
| q48 | dose_adjustment       | Vancomycin for MRSA bacteremia: AUC₂₄ 400–600 (Bayesian), abandon trough-only                 | ASHP/IDSA/PIDS/SIDP 2020 (Rybak)           |
| q49 | dose_adjustment       | CYP2C9 *1/*3 + VKORC1 G/A + new DVT, non-African: pharmacogenetics-guided dosing algorithm    | CPIC warfarin 2017 (Johnson)               |
| q50 | dose_adjustment       | CFTR G551D/F508del: ivacaftor mono vs Trikafta — context-dependent (current SoC: Trikafta)    | FDA Kalydeco / Trikafta — context-dependent |

## Domain counts (acceptance check)

| Domain              | n  |
|---------------------|----|
| pgx                 | 10 |
| oncology_somatic    | 10 |
| carrier_screening   | 10 |
| hereditary_risk     | 10 |
| dose_adjustment     | 10 |
| **Total**           | **50** |

## YAML schema

Each `qNN.yaml` file conforms to the schema defined in `bench/v2/TASKS.md`
Task 4 — minimally:

```yaml
id: qNN
domain: <pgx|oncology_somatic|carrier_screening|hereditary_risk|dose_adjustment>
question: "..."
required_inputs: [...]
gold_answer:
  verdict: "..."
  phenotype: "..."        # only when PGx phenotype is meaningful
  cited_guideline: "..."
  rationale: "..."
scoring_rubric:
  verdict_correct: ...
  phenotype_correct: ...
  guideline_cited_with_version: ...
  variant_evidence_cited: ...
primary_reference_url: <https://...>
context_dependent: true   # only on q27 and q50
```
