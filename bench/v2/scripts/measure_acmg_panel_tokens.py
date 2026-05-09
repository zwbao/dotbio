#!/usr/bin/env python3
"""
measure_acmg_panel_tokens.py — Round-2 Task R2 of the dotbio NM-grade benchmark.

Generates the six format reconstructions of the ACMG SF v3.2 + PharmGKB VIP
NA12878 panel built by `build_acmg_panel.py`, then measures token cost for
each using the Claude tokenizer (Xenova port) and GPT-2 BPE as a cross-check.

The six formats are:

  1. VCF (raw)                     — bench/v2/data/acmg_panel/HG001_acmg_sf_vip.vcf
  2. .genome reconstruction        — bench/v2/data/acmg_panel/HG001.genome.md
  3. .bio manifest+pgx_view        — bench/v2/data/acmg_panel/HG001.bio_manifest_view.md
                                      (manifest.json + pgx view; what an LLM
                                       actually loads to answer a PGx question)
  3'.bio manifest only             — small bounded reference object
  4. Phenopackets v2               — bench/v2/data/acmg_panel/HG001.phenopacket.json
  5. FHIR R4 Genomics IG bundle    — bench/v2/data/acmg_panel/HG001.fhir.json
  6. PharmCAT-style JSON report    — bench/v2/data/acmg_panel/HG001.pharmcat.json

Outputs:
  bench/v2/results/exp01_tokens_acmg_panel.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPO_ROOT = Path("/Users/baozhiwei/projects/dotbio")
PANEL_DIR = REPO_ROOT / "bench/v2/data/acmg_panel"
RESULTS_DIR = REPO_ROOT / "bench/v2/results"


def parse_vcf(path: Path) -> tuple[list[dict], dict[str, str]]:
    records: list[dict] = []
    meta: dict[str, str] = {}
    sample_name: str | None = None
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.rstrip("\n")
        if not line:
            continue
        if line.startswith("##"):
            if line.startswith("##reference="):
                meta["reference"] = line.split("=", 1)[1]
            elif line.startswith("##fileDate="):
                meta["fileDate"] = line.split("=", 1)[1]
            continue
        if line.startswith("#CHROM"):
            cols = line.lstrip("#").split("\t")
            if len(cols) >= 10:
                sample_name = cols[9]
            continue
        cols = line.split("\t")
        if len(cols) < 10:
            continue
        chrom, pos_s, vid, ref, alt, _qual, _filt, info_s, fmt, sample = cols[:10]
        try:
            pos = int(pos_s)
        except ValueError:
            continue
        info: dict[str, str] = {}
        for kv in info_s.split(";"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                info[k] = v
        fmt_keys = fmt.split(":")
        sample_vals = sample.split(":")
        smap = dict(zip(fmt_keys, sample_vals))
        gt = smap.get("GT", "./.")
        records.append({
            "chrom": chrom,
            "pos": pos,
            "rsid": vid if vid != "." else "",
            "ref": ref,
            "alt": alt,
            "info": info,
            "gt": gt,
        })
    if sample_name:
        meta["sample_name"] = sample_name
    return records, meta


def gt_to_alt_count(gt: str) -> int:
    """How many ALT alleles in this genotype (0, 1, 2, or -1 for missing)."""
    sep = "|" if "|" in gt else "/"
    n = 0
    for tok in gt.split(sep):
        if tok in ("", "."):
            return -1
        try:
            if int(tok) >= 1:
                n += 1
        except ValueError:
            return -1
    return n


def gt_to_zygosity(gt: str) -> str:
    n = gt_to_alt_count(gt)
    if n < 0:
        return "no_call"
    if n == 0:
        return "homozygous_reference"
    if n == 1:
        return "heterozygous"
    return "homozygous_alternate"


# ---------------------------------------------------------------------------
# Format 2 — .genome reconstruction (per-gene Markdown blocks)
# ---------------------------------------------------------------------------

def emit_genome_reconstruction(records: list[dict], out: Path) -> None:
    # Group records by gene
    by_gene: dict[str, list[dict]] = {}
    for r in records:
        g = r["info"].get("GENE", "?")
        by_gene.setdefault(g, []).append(r)

    lines: list[str] = []
    lines.append("# NA12878 (HG001) Genomic Report — ACMG SF v3.2 + PharmGKB VIP\n")
    lines.append("> **Note**: Faithful reconstruction of `.genome` format based on\n")
    lines.append("> the public example shown in The Genome Computer Co.'s materials.\n")
    lines.append("> The actual `.genome` format is proprietary; this reconstruction\n")
    lines.append("> follows the published per-gene block structure (Variant /\n")
    lines.append("> Genotype / Clinical Significance / Impact for every panel locus).\n")
    lines.append("\n")
    lines.append(f"Source: 1000 Genomes Project 30x phased panel (20220422 release).\n")
    lines.append(f"Build: GRCh38. Panel: ACMG SF v3.2 (Miller 2023, PMID:36190193) "
                 f"+ PharmGKB Tier-1 VIP. {len(records)} reportable positions.\n\n")

    for gene in sorted(by_gene.keys()):
        rs = by_gene[gene]
        lines.append(f"## Gene: {gene}\n")
        for r in rs:
            zy = gt_to_zygosity(r["gt"])
            sig = r["info"].get("CLNSIG", "").replace("_", " ")
            cond = r["info"].get("CLNDN", "").replace("_", " ").replace("|", "; ")
            mc = r["info"].get("MC", "").replace("|", "; ")
            rsid = r["rsid"] or f"{r['chrom']}:{r['pos']}:{r['ref']}>{r['alt']}"
            lines.append(f"- **Variant**: {rsid} ({r['ref']} > {r['alt']}) "
                         f"[{r['chrom']}:{r['pos']}]\n")
            lines.append(f"  - **Genotype**: {zy.replace('_', ' ').title()} "
                         f"({r['gt']})\n")
            if sig:
                lines.append(f"  - **Clinical Significance**: {sig}\n")
            if cond:
                lines.append(f"  - **Condition**: {cond}\n")
            if mc:
                lines.append(f"  - **Impact**: {mc}\n")
        lines.append("\n")

    out.write_text("".join(lines), encoding="utf-8")


# ---------------------------------------------------------------------------
# Format 3 — .bio bundle (manifest + pgx_view + facts dir)
# ---------------------------------------------------------------------------

def fact_hash(fact: dict) -> str:
    return hashlib.sha256(
        json.dumps(fact, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def emit_bio_bundle(records: list[dict], bundle_dir: Path) -> dict:
    """Emit a content-addressed .bio bundle directory matching dotbio.v0.

    Returns the manifest dict.
    """
    bundle_dir.mkdir(parents=True, exist_ok=True)
    facts_dir = bundle_dir / "facts"
    views_dir = bundle_dir / "views"
    commits_dir = bundle_dir / "commits"
    refs_dir = bundle_dir / "refs"
    for d in (facts_dir, views_dir, commits_dir, refs_dir):
        d.mkdir(parents=True, exist_ok=True)

    n_alt = 0
    fact_hashes: list[str] = []
    pgx_view_targets: list[str] = []
    germline_view_targets: list[str] = []
    carrier_view_targets: list[str] = []

    for r in records:
        # Build genotype string (ref/alt-base form)
        sep = "|" if "|" in r["gt"] else "/"
        idxs = []
        for tok in r["gt"].split(sep):
            try:
                idxs.append(int(tok))
            except ValueError:
                idxs.append(-1)
        alleles = [r["ref"]] + r["alt"].split(",")
        try:
            geno = f"{alleles[max(idxs[0], 0)]}/{alleles[max(idxs[-1], 0)] if len(idxs) > 1 else alleles[max(idxs[0], 0)]}"
        except IndexError:
            geno = f"{r['ref']}/{r['ref']}"

        if any(i >= 1 for i in idxs):
            n_alt += 1

        fact = {
            "kind": "variant",
            "build": "GRCh38",
            "chrom": r["chrom"],
            "pos": r["pos"],
            "ref": r["ref"],
            "alt": r["alt"],
            "rsid": r["rsid"] or "",
            "gene_hint": r["info"].get("GENE", ""),
            "filter": "PASS",
            "genotype": geno,
        }
        h = fact_hash(fact)
        # Content-addressed path: facts/<first 2 chars>/<rest>.json
        fpath = facts_dir / h[:2] / (h[2:] + ".json")
        fpath.parent.mkdir(parents=True, exist_ok=True)
        if not fpath.exists():
            fpath.write_text(
                json.dumps(fact, separators=(",", ":"), sort_keys=True),
                encoding="utf-8",
            )
        fact_hashes.append(h)
        # Bucket into views by panel & genotype state
        panel = r["info"].get("PANEL", "")
        if panel == "PharmGKB_VIP":
            pgx_view_targets.append(h)
        else:
            if any(i >= 1 for i in idxs):
                germline_view_targets.append(h)
            else:
                carrier_view_targets.append(h)

    # PGx view (compact: only carriers + drug-relevant subset)
    pgx_lines = ["# Pharmacogenomic view\n",
                 "\n",
                 "> Carrier-state PGx variants from PharmGKB Tier-1 VIP panel for NA12878.\n",
                 "> Each claim below carries a content hash; resolve via "
                 "`bio expand <hash>` for full evidence.\n",
                 "\n"]
    pgx_carriers = []
    for r in records:
        if r["info"].get("PANEL") != "PharmGKB_VIP":
            continue
        sep = "|" if "|" in r["gt"] else "/"
        if any(t in ("1", "2", "3") for t in r["gt"].split(sep)):
            pgx_carriers.append(r)
    pgx_lines.append(f"## Carrier variants ({len(pgx_carriers)})\n\n")
    for r in pgx_carriers[:200]:
        rsid = r["rsid"] or f"{r['chrom']}:{r['pos']}"
        gene = r["info"].get("GENE", "?")
        zy = gt_to_zygosity(r["gt"])
        sig = r["info"].get("CLNSIG", "").replace("_", " ")
        pgx_lines.append(f"- **{gene} {rsid}** ({r['ref']}>{r['alt']}, {zy})"
                         f" — {sig}\n")
    if len(pgx_carriers) > 200:
        pgx_lines.append(f"\n_…and {len(pgx_carriers) - 200} more carrier rows; "
                         f"resolve via `bio view pgx --full`._\n")

    germline_lines = ["# Germline-clinical view\n",
                      "\n",
                      "> ACMG SF v3.2 secondary findings — only positions where NA12878 carries the ALT allele.\n",
                      "\n"]
    germline_carriers = []
    for r in records:
        if r["info"].get("PANEL") != "ACMG_SF_v3.2":
            continue
        sep = "|" if "|" in r["gt"] else "/"
        if any(t in ("1", "2") for t in r["gt"].split(sep)):
            germline_carriers.append(r)
    germline_lines.append(f"## Pathogenic / Likely-pathogenic ALT carriers ({len(germline_carriers)})\n\n")
    if not germline_carriers:
        germline_lines.append("_None — sample is homozygous reference at all P/LP positions._\n")
    else:
        for r in germline_carriers[:100]:
            rsid = r["rsid"] or f"{r['chrom']}:{r['pos']}"
            gene = r["info"].get("GENE", "?")
            zy = gt_to_zygosity(r["gt"])
            sig = r["info"].get("CLNSIG", "").replace("_", " ")
            cond = r["info"].get("CLNDN", "").replace("_", " ").replace("|", "; ")
            germline_lines.append(f"- **{gene} {rsid}** ({zy}) — {sig} — {cond}\n")

    (views_dir / "pgx.md").write_text("".join(pgx_lines), encoding="utf-8")
    (views_dir / "germline-clinical.md").write_text(
        "".join(germline_lines), encoding="utf-8"
    )
    (views_dir / "carrier.md").write_text(
        "# Carrier status view\n\n_See `views/germline-clinical.md` and `views/pgx.md`._\n",
        encoding="utf-8",
    )
    (views_dir / "somatic.md").write_text(
        "# Somatic oncology view\n\n_No somatic calls in this benchmark._\n",
        encoding="utf-8",
    )

    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")

    manifest = {
        "active_rulesets": [
            {
                "license": "public domain (NCBI)",
                "name": "clinvar",
                "source": "ClinVar (panel-filtered subset; not for clinical use)",
                "source_url": "https://www.ncbi.nlm.nih.gov/clinvar/",
                "type": "germline_clinical",
                "version": "2026-05-01",
            },
            {
                "license": "Mozilla Public License 2.0 (PharmCAT)",
                "name": "pharmcat",
                "source": "PharmCAT-style allele tables (illustrative subset)",
                "source_url": "https://pharmcat.org/",
                "type": "pharmacogenomic",
                "version": "2025.3",
            },
        ],
        "build": "GRCh38",
        "claim_count": len(germline_carriers) + len(pgx_carriers),
        "created": now,
        "panel": "ACMG SF v3.2 (Miller 2023, PMID:36190193) + PharmGKB Tier-1 VIP",
        "refs": {"HEAD": now, "stable": now},
        "schema": "dotbio.v0",
        "scopes": {
            "germline_variant_count": sum(1 for r in records
                                          if r["info"].get("PANEL") == "ACMG_SF_v3.2"),
            "pgx_variant_count": sum(1 for r in records
                                     if r["info"].get("PANEL") == "PharmGKB_VIP"),
            "alt_carrier_count": n_alt,
        },
        "subject": "NA12878",
        "views": [
            {
                "claim_count": len(pgx_carriers),
                "name": "pgx",
                "path": "views/pgx.md",
                "scope": "pgx",
                "title": "Pharmacogenomic",
            },
            {
                "claim_count": len(germline_carriers),
                "name": "germline-clinical",
                "path": "views/germline-clinical.md",
                "scope": "germline-clinical",
                "title": "Germline clinical",
            },
            {
                "claim_count": 0,
                "name": "carrier",
                "path": "views/carrier.md",
                "scope": "carrier",
                "title": "Carrier status",
            },
            {
                "claim_count": 0,
                "name": "somatic",
                "path": "views/somatic.md",
                "scope": "somatic",
                "title": "Somatic oncology",
            },
        ],
    }
    (bundle_dir / "manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True), encoding="utf-8"
    )
    # Commit + refs
    commit = {
        "schema": "dotbio.commit.v0",
        "created": now,
        "fact_hashes": fact_hashes[:1000] + (
            [f"...truncated to first 1000 of {len(fact_hashes)}"] if len(fact_hashes) > 1000 else []
        ),
        "n_facts_total": len(fact_hashes),
    }
    (commits_dir / f"{now}.commit.json").write_text(
        json.dumps(commit, separators=(",", ":"), sort_keys=True), encoding="utf-8"
    )
    (refs_dir / "HEAD").write_text(f"{now}\n", encoding="utf-8")
    (refs_dir / "stable").write_text(f"{now}\n", encoding="utf-8")

    return manifest


# ---------------------------------------------------------------------------
# Format 4 — Phenopackets v2
# ---------------------------------------------------------------------------

def emit_phenopacket(records: list[dict], out: Path) -> None:
    proband_id = "NA12878"
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    interpretations = []
    for idx, r in enumerate(records, start=1):
        gt = r["gt"]
        sep = "|" if "|" in gt else "/"
        idxs = []
        for tok in gt.split(sep):
            try:
                idxs.append(int(tok))
            except ValueError:
                idxs.append(-1)
        alt_count = sum(1 for i in idxs if i >= 1)
        if all(i < 0 for i in idxs):
            zy = ("GENO:0000036", "no genotype call")
        elif alt_count == 0:
            zy = ("GENO:0000036", "homozygous reference")
        elif alt_count == len(idxs):
            zy = ("GENO:0000136", "homozygous alternate")
        else:
            zy = ("GENO:0000135", "heterozygous")
        gene = r["info"].get("GENE", "?")
        clnsig = r["info"].get("CLNSIG", "")
        if "Pathogenic" in clnsig:
            acmg = "PATHOGENIC"
        elif "Likely_pathogenic" in clnsig:
            acmg = "LIKELY_PATHOGENIC"
        else:
            acmg = "NOT_PROVIDED"
        rsid = r["rsid"] or f"{r['chrom']}_{r['pos']}_{r['ref']}_{r['alt']}"
        descriptor = {
            "id": f"var.{rsid}.{r['ref']}>{r['alt']}",
            "moleculeContext": "genomic",
            "vcfRecord": {
                "genomeAssembly": "GRCh38",
                "chrom": r["chrom"],
                "pos": str(r["pos"]),
                "ref": r["ref"],
                "alt": r["alt"],
            },
            "allelicState": {"id": zy[0], "label": zy[1]},
            "label": f"{gene}:{rsid} {r['ref']}>{r['alt']}",
            "xrefs": [f"dbSNP:{r['rsid']}"] if r["rsid"].startswith("rs") else [],
            "geneContext": {"valueId": f"HGNC:?:{gene}", "symbol": gene},
        }
        extensions = []
        if clnsig:
            extensions.append({"name": "clinvarSignificance", "value": clnsig})
        if r["info"].get("CLNDN"):
            extensions.append({"name": "clinvarCondition", "value": r["info"]["CLNDN"]})
        if r["info"].get("MC"):
            extensions.append({"name": "molecularConsequence", "value": r["info"]["MC"]})
        if extensions:
            descriptor["extensions"] = extensions

        gi = {
            "subjectOrBiosampleId": proband_id,
            "interpretationStatus": (
                "CAUSATIVE" if acmg in ("PATHOGENIC", "LIKELY_PATHOGENIC") and alt_count > 0
                else "CONTRIBUTORY" if alt_count > 0 else "REJECTED"
            ),
            "variantInterpretation": {
                "acmgPathogenicityClassification": acmg,
                "therapeuticActionability": "UNKNOWN_ACTIONABILITY",
                "variationDescriptor": descriptor,
            },
        }
        interpretations.append({
            "id": f"interpretation.{idx:05d}.{rsid}",
            "progressStatus": "SOLVED" if alt_count > 0 else "IN_PROGRESS",
            "diagnosis": {
                "disease": {"id": "MONDO:0700096",
                             "label": r["info"].get("CLNDN", "Phenotype, not specified")},
                "genomicInterpretations": [gi],
            },
        })

    pp = {
        "id": f"phenopacket.{proband_id}.acmg_panel.{now[:10]}",
        "subject": {
            "id": proband_id,
            "timeAtLastEncounter": {"age": {"iso8601duration": "P0Y"}},
            "karyotypicSex": "XX",
        },
        "interpretations": interpretations,
        "metaData": {
            "created": now,
            "createdBy": "dotbio-bench-r2/measure_acmg_panel_tokens.py",
            "submittedBy": "dotbio NM-grade benchmark (R2)",
            "phenopacketSchemaVersion": "2.0",
            "resources": [
                {"id": "geno", "name": "Genotype Ontology", "namespacePrefix": "GENO",
                 "url": "http://purl.obolibrary.org/obo/geno.owl",
                 "version": "2023-10-08",
                 "iriPrefix": "http://purl.obolibrary.org/obo/GENO_"},
                {"id": "mondo", "name": "Mondo Disease Ontology", "namespacePrefix": "MONDO",
                 "url": "http://purl.obolibrary.org/obo/mondo.owl",
                 "version": "2024-09-03",
                 "iriPrefix": "http://purl.obolibrary.org/obo/MONDO_"},
                {"id": "dbsnp", "name": "dbSNP", "namespacePrefix": "dbSNP",
                 "url": "https://www.ncbi.nlm.nih.gov/snp",
                 "version": "build_156",
                 "iriPrefix": "https://www.ncbi.nlm.nih.gov/snp/"},
                {"id": "clinvar", "name": "ClinVar", "namespacePrefix": "ClinVar",
                 "url": "https://www.ncbi.nlm.nih.gov/clinvar/",
                 "version": "2026-05-01",
                 "iriPrefix": "https://www.ncbi.nlm.nih.gov/clinvar/variation/"},
            ],
        },
    }
    out.write_text(json.dumps(pp, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Format 5 — FHIR R4 Genomics IG bundle
# ---------------------------------------------------------------------------

def emit_fhir_bundle(records: list[dict], out: Path) -> None:
    proband_id = "NA12878"
    entries: list[dict] = [
        {
            "fullUrl": f"urn:uuid:patient-{proband_id}",
            "resource": {
                "resourceType": "Patient",
                "id": proband_id,
                "identifier": [{"value": proband_id}],
                "active": True,
            },
        }
    ]
    for idx, r in enumerate(records, start=1):
        gene = r["info"].get("GENE", "?")
        clnsig = r["info"].get("CLNSIG", "")
        zy = gt_to_zygosity(r["gt"])
        rsid = r["rsid"] or f"{r['chrom']}:{r['pos']}"
        obs_id = f"obs-{idx:05d}-{r['chrom']}-{r['pos']}"
        # Map ClinVar significance to LOINC clinical-significance answer-list.
        if "Pathogenic" in clnsig and "Likely" not in clnsig:
            sig_code, sig_disp = "LA6668-3", "Pathogenic"
        elif "Likely_pathogenic" in clnsig:
            sig_code, sig_disp = "LA26332-9", "Likely pathogenic"
        else:
            sig_code, sig_disp = "LA26333-7", "Uncertain significance"
        entries.append({
            "fullUrl": f"urn:uuid:{obs_id}",
            "resource": {
                "resourceType": "Observation",
                "id": obs_id,
                "status": "final",
                "category": [{"coding": [{
                    "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                    "code": "laboratory",
                }]}],
                "code": {
                    "coding": [{
                        "system": "http://loinc.org",
                        "code": "69548-6",
                        "display": "Genetic variant assessment",
                    }],
                    "text": f"{gene} variant {rsid}",
                },
                "subject": {"reference": f"urn:uuid:patient-{proband_id}"},
                "valueCodeableConcept": {
                    "coding": [{
                        "system": "http://loinc.org",
                        "code": "LA9633-4",
                        "display": "Present",
                    }],
                },
                "component": [
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "48005-3",
                                              "display": "Amino acid change"}]},
                        "valueString": r["info"].get("MC", ""),
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "48018-6",
                                              "display": "Gene studied [ID]"}]},
                        "valueCodeableConcept": {"text": gene},
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "53034-5",
                                              "display": "Allelic state"}]},
                        "valueString": zy,
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "53037-8",
                                              "display": "Genetic variation clinical significance"}]},
                        "valueCodeableConcept": {
                            "coding": [{"system": "http://loinc.org",
                                         "code": sig_code, "display": sig_disp}],
                            "text": clnsig,
                        },
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "81254-5",
                                              "display": "Genomic alteration HGVS"}]},
                        "valueString": f"{r['chrom']}:g.{r['pos']}{r['ref']}>{r['alt']}",
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "62374-4",
                                              "display": "Human reference sequence assembly"}]},
                        "valueCodeableConcept": {
                            "coding": [{"system": "http://loinc.org",
                                         "code": "LA26806-2", "display": "GRCh38"}],
                        },
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "81252-9",
                                              "display": "Discrete genetic variant"}]},
                        "valueString": r["rsid"] or "",
                    },
                    {
                        "code": {"coding": [{"system": "http://loinc.org", "code": "81258-6",
                                              "display": "Sample variant ID"}]},
                        "valueString": rsid,
                    },
                ],
                "extension": [
                    {"url": "http://hl7.org/fhir/StructureDefinition/observation-genetics-condition",
                     "valueString": r["info"].get("CLNDN", "")},
                ],
            },
        })

    bundle = {
        "resourceType": "Bundle",
        "id": f"fhir-bundle-{proband_id}-acmg-panel",
        "type": "collection",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "entry": entries,
    }
    out.write_text(json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Format 6 — PharmCAT-style JSON report
# ---------------------------------------------------------------------------

def emit_pharmcat_report(records: list[dict], out: Path) -> None:
    proband_id = "NA12878"
    pgx_records = [r for r in records if r["info"].get("PANEL") == "PharmGKB_VIP"]
    by_gene: dict[str, list[dict]] = {}
    for r in pgx_records:
        by_gene.setdefault(r["info"].get("GENE", "?"), []).append(r)

    genes_block = []
    for gene, rs in sorted(by_gene.items()):
        positions = []
        for r in rs:
            zy = gt_to_zygosity(r["gt"])
            positions.append({
                "rsid": r["rsid"],
                "chrom": r["chrom"],
                "pos": r["pos"],
                "ref": r["ref"],
                "alt": r["alt"],
                "gt": r["gt"],
                "zygosity": zy,
                "clinvarSig": r["info"].get("CLNSIG", ""),
                "moleculeConsequence": r["info"].get("MC", ""),
            })
        # Synthesise a coarse phenotype call (Normal Metabolizer if no ALT)
        any_alt = any(gt_to_alt_count(r["gt"]) > 0 for r in rs)
        phenotype = "Indeterminate" if any_alt else "Normal Metabolizer"
        genes_block.append({
            "gene": gene,
            "diplotype": "*1/*1" if not any_alt else "(diplotype call requires PharmCAT engine)",
            "phenotype": phenotype,
            "uncalledAlleles": [],
            "n_panel_positions": len(rs),
            "positions": positions,
        })

    report = {
        "title": "PharmCAT-style PGx Report (panel-scale reconstruction)",
        "subject": proband_id,
        "build": "GRCh38",
        "panel": "PharmGKB Tier-1 VIP (subset of dotbio R2 ACMG panel)",
        "pharmcatVersion": "2025.3 (illustrative)",
        "reportDate": datetime.now(timezone.utc).isoformat(),
        "genes": genes_block,
        "drugRecommendations": [
            # Skeletal placeholder — full PharmCAT recommendations would come
            # from the engine. This is what an LLM would actually consume.
            {"drug": "clopidogrel", "guideline": "CPIC 2022",
             "recommendation": "Standard dose if NM/RM; consider alternative if IM/PM",
             "appliesToGenes": ["CYP2C19"]},
            {"drug": "warfarin", "guideline": "CPIC 2017",
             "recommendation": "Use CYP2C9/VKORC1-aware dose calculator",
             "appliesToGenes": ["CYP2C9", "VKORC1", "CYP4F2"]},
            {"drug": "azathioprine", "guideline": "CPIC 2018",
             "recommendation": "Reduce dose if TPMT or NUDT15 IM/PM",
             "appliesToGenes": ["TPMT", "NUDT15"]},
            {"drug": "fluoropyrimidines", "guideline": "CPIC 2017",
             "recommendation": "Reduce dose if DPYD IM/PM",
             "appliesToGenes": ["DPYD"]},
            {"drug": "abacavir", "guideline": "CPIC 2014",
             "recommendation": "Avoid if HLA-B*57:01 positive",
             "appliesToGenes": ["HLA-B"]},
        ],
    }
    out.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")


# ---------------------------------------------------------------------------
# Token measurement
# ---------------------------------------------------------------------------

def count_tokens(text: str) -> dict[str, int]:
    out = {}
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained("Xenova/claude-tokenizer")
        out["claude"] = len(tok.encode(text))
    except Exception as e:
        out["claude_error"] = str(e)
    try:
        from transformers import AutoTokenizer
        tok = AutoTokenizer.from_pretrained("gpt2")
        out["gpt2"] = len(tok.encode(text))
    except Exception as e:
        out["gpt2_error"] = str(e)
    return out


def gather_bio_view_text(bundle_dir: Path, scope: str = "pgx") -> str:
    """Concatenate manifest + scope-relevant view (the LLM-facing slice)."""
    parts: list[str] = []
    parts.append((bundle_dir / "manifest.json").read_text(encoding="utf-8"))
    parts.append("\n")
    if scope == "pgx":
        parts.append((bundle_dir / "views/pgx.md").read_text(encoding="utf-8"))
    elif scope == "germline":
        parts.append((bundle_dir / "views/germline-clinical.md").read_text(encoding="utf-8"))
    return "".join(parts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vcf", type=Path,
                        default=PANEL_DIR / "HG001_acmg_sf_vip.vcf")
    parser.add_argument("--out-results", type=Path,
                        default=RESULTS_DIR / "exp01_tokens_acmg_panel.json")
    parser.add_argument("--skip-tokens", action="store_true")
    args = parser.parse_args(argv)

    if not args.vcf.exists():
        print(f"ERROR: panel VCF not found: {args.vcf}", file=sys.stderr)
        return 2

    records, meta = parse_vcf(args.vcf)
    print(f"[+] parsed {len(records)} variants from {args.vcf}", file=sys.stderr)

    PANEL_DIR.mkdir(parents=True, exist_ok=True)

    # Format 2: .genome reconstruction
    genome_path = PANEL_DIR / "HG001.genome.md"
    emit_genome_reconstruction(records, genome_path)
    print(f"[+] wrote .genome reconstruction -> {genome_path} "
          f"({genome_path.stat().st_size} bytes)", file=sys.stderr)

    # Format 3: .bio bundle
    bundle_dir = PANEL_DIR / "HG001.bio"
    emit_bio_bundle(records, bundle_dir)
    print(f"[+] wrote .bio bundle -> {bundle_dir}", file=sys.stderr)

    # Format 4: Phenopackets
    pp_path = PANEL_DIR / "HG001.phenopacket.json"
    emit_phenopacket(records, pp_path)
    print(f"[+] wrote Phenopacket -> {pp_path} ({pp_path.stat().st_size} bytes)",
          file=sys.stderr)

    # Format 5: FHIR
    fhir_path = PANEL_DIR / "HG001.fhir.json"
    emit_fhir_bundle(records, fhir_path)
    print(f"[+] wrote FHIR bundle -> {fhir_path} ({fhir_path.stat().st_size} bytes)",
          file=sys.stderr)

    # Format 6: PharmCAT
    pharmcat_path = PANEL_DIR / "HG001.pharmcat.json"
    emit_pharmcat_report(records, pharmcat_path)
    print(f"[+] wrote PharmCAT report -> {pharmcat_path} ({pharmcat_path.stat().st_size} bytes)",
          file=sys.stderr)

    # Tar.gz the bio bundle
    import tarfile
    bio_tarball = PANEL_DIR / "HG001_acmg_sf_vip.bio.tar.gz"
    with tarfile.open(bio_tarball, "w:gz") as tar:
        tar.add(bundle_dir, arcname="HG001.bio")
    print(f"[+] wrote bio tarball -> {bio_tarball} "
          f"({bio_tarball.stat().st_size} bytes)", file=sys.stderr)

    # ---- Token measurement ----
    inputs = {
        "VCF_raw": args.vcf,
        "genome_reconstruction": genome_path,
        "phenopacket_v2": pp_path,
        "fhir_genomics_bundle": fhir_path,
        "pharmcat_report": pharmcat_path,
        "bio_manifest_only": bundle_dir / "manifest.json",
    }

    results: dict[str, Any] = {
        "panel": {
            "name": "ACMG SF v3.2 + PharmGKB VIP",
            "n_positions": len(records),
            "subject": "NA12878",
            "build": "GRCh38",
        },
        "tokenizers": {"claude": "Xenova/claude-tokenizer", "gpt2": "gpt2"},
        "inputs": {},
    }

    for label, path in inputs.items():
        text = path.read_text(encoding="utf-8")
        b = len(text.encode("utf-8"))
        if args.skip_tokens:
            tokens = {"claude": None, "gpt2": None}
        else:
            tokens = count_tokens(text)
        rel = path.relative_to(REPO_ROOT) if path.is_absolute() else path
        results["inputs"][label] = {
            "path": str(rel),
            "bytes": b,
            "tokens": tokens,
        }
        print(f"  {label:30s} bytes={b:>9d} tokens.claude="
              f"{tokens.get('claude', 'NA')}", file=sys.stderr)

    # Composite: bio manifest + pgx view (what an LLM actually loads for a
    # PGx question) and bio manifest + germline view
    pgx_text = gather_bio_view_text(bundle_dir, scope="pgx")
    germ_text = gather_bio_view_text(bundle_dir, scope="germline")
    for label, text in [
        ("bio_manifest_plus_pgx_view", pgx_text),
        ("bio_manifest_plus_germline_view", germ_text),
    ]:
        b = len(text.encode("utf-8"))
        if args.skip_tokens:
            tokens = {"claude": None, "gpt2": None}
        else:
            tokens = count_tokens(text)
        results["inputs"][label] = {
            "path": "bench/v2/data/acmg_panel/HG001.bio/{manifest.json + views/pgx.md}"
                if "pgx" in label else
                "bench/v2/data/acmg_panel/HG001.bio/{manifest.json + views/germline-clinical.md}",
            "bytes": b,
            "tokens": tokens,
        }
        print(f"  {label:30s} bytes={b:>9d} tokens.claude="
              f"{tokens.get('claude', 'NA')}", file=sys.stderr)

    args.out_results.parent.mkdir(parents=True, exist_ok=True)
    args.out_results.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(f"\n[+] wrote {args.out_results}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
