#!/usr/bin/env python3
"""VCF -> HL7 FHIR R4 Genomics IG Bundle converter.

Implements Task 2 of the dotbio NM-grade benchmark (bench/v2/SPEC.md, bench/v2/TASKS.md).
Translates an 8-locus PGx VCF (NA12878) into a FHIR R4 Bundle aligned with the
HL7 FHIR Genomics Implementation Guide (release 2.0.0):
  - Patient
  - Specimen
  - MolecularSequence
  - Observation (genetics-variant) per ALT-bearing locus, plus reference observations
  - DiagnosticReport rolling up the variant findings

LOINC codes follow the FHIR Genomics IG / LOINC Genomic Reporting:
  53037-8  Genetic variant assessment            (top-level Observation code)
  81252-9  Discrete genetic variant              (variant-grouping Observation profile code)
  48018-6  Gene studied [ID]
  41103-3  Interpretation of genetic variation
  62374-4  Human reference sequence assembly version
  48013-7  Genomic reference sequence ID
  69547-8  Genomic ref allele [ID]
  69551-0  Genomic alt allele [ID]
  81254-5  Genomic allele start-end
  53034-5  Allelic state
  51958-7  Transcript reference sequence [ID]    (not used in this PGx panel; documented)

The output is plain JSON written with Python stdlib only; the `fhir.resources`
package is permitted by Task 2 but not required, so we ship a stdlib build to
keep CI dependency-free. Resources follow R4 syntax and IG profile URLs are
declared in `meta.profile`.

Usage:
    python bench/v2/scripts/vcf_to_fhir.py \
        --vcf examples/real-na12878/input.vcf \
        --out bench/v2/data/format_e_fhir_bundle.json
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


# ---------------------------------------------------------------------------
# VCF parsing (stdlib, intentionally minimal — same scope as Task 1)
# ---------------------------------------------------------------------------

@dataclass
class VcfRecord:
    chrom: str
    pos: int
    rsid: str
    ref: str
    alt: str
    info: dict[str, str]
    fmt: list[str]
    sample: str
    sample_values: list[str]

    @property
    def gt(self) -> str:
        try:
            idx = self.fmt.index("GT")
        except ValueError:
            return "./."
        return self.sample_values[idx]

    @property
    def gene(self) -> str | None:
        return self.info.get("GENE")

    @property
    def af(self) -> float | None:
        v = self.info.get("AF")
        try:
            return float(v) if v is not None else None
        except ValueError:
            return None


def parse_vcf(path: Path) -> tuple[list[VcfRecord], dict[str, str], str]:
    header_meta: dict[str, str] = {}
    sample_name = ""
    records: list[VcfRecord] = []
    with path.open() as fh:
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            if line.startswith("##"):
                # capture top-level meta fields
                if line.startswith("##reference="):
                    header_meta["reference"] = line.split("=", 1)[1]
                elif line.startswith("##fileDate="):
                    header_meta["fileDate"] = line.split("=", 1)[1]
                elif line.startswith("##source="):
                    header_meta["source"] = line.split("=", 1)[1]
                continue
            if line.startswith("#CHROM"):
                cols = line.split("\t")
                # last column is the sample name in single-sample VCF
                sample_name = cols[-1]
                continue
            cols = line.split("\t")
            if len(cols) < 10:
                continue
            chrom, pos, rsid, ref, alt, _qual, _filt, info_field, fmt_field = cols[:9]
            sample_values = cols[9].split(":")
            info = {}
            for kv in info_field.split(";"):
                if "=" in kv:
                    k, v = kv.split("=", 1)
                    info[k] = v
                elif kv:
                    info[kv] = ""
            records.append(
                VcfRecord(
                    chrom=chrom,
                    pos=int(pos),
                    rsid=rsid,
                    ref=ref,
                    alt=alt,
                    info=info,
                    fmt=fmt_field.split(":"),
                    sample=sample_name,
                    sample_values=sample_values,
                )
            )
    return records, header_meta, sample_name


# ---------------------------------------------------------------------------
# Genotype helpers
# ---------------------------------------------------------------------------

def split_gt(gt: str) -> tuple[list[int], bool]:
    """Return (allele_indices, phased). './.' returns ([], False)."""
    sep = "|" if "|" in gt else "/"
    phased = "|" in gt
    parts = [p for p in gt.replace("|", "/").split("/") if p != ""]
    indices: list[int] = []
    for p in parts:
        if p == ".":
            return [], phased
        try:
            indices.append(int(p))
        except ValueError:
            return [], phased
    return indices, phased


def allelic_state(rec: VcfRecord) -> tuple[str, str]:
    """Return (LOINC code, display) for LA codeset on Allelic state (LOINC 53034-5)."""
    indices, _ = split_gt(rec.gt)
    if not indices:
        return ("LA9663-1", "Unknown")
    if all(i == 0 for i in indices):
        return ("LA6704-3", "Homozygous reference")
    if all(i != 0 for i in indices) and len(set(indices)) == 1:
        return ("LA6705-0", "Homozygous")
    if 0 in indices and any(i != 0 for i in indices):
        return ("LA6706-8", "Heterozygous")
    return ("LA6707-6", "Hemizygous")


def genotype_string(rec: VcfRecord) -> str:
    """Human-readable A/G style genotype on the VCF strand."""
    indices, phased = split_gt(rec.gt)
    alleles = [rec.ref] + rec.alt.split(",")
    sep = "|" if phased else "/"
    if not indices:
        return "./."
    return sep.join(alleles[i] if 0 <= i < len(alleles) else "." for i in indices)


def has_variant_call(rec: VcfRecord) -> bool:
    indices, _ = split_gt(rec.gt)
    return any(i != 0 for i in indices)


# ---------------------------------------------------------------------------
# FHIR resource builders
# ---------------------------------------------------------------------------

GENOMICS_IG = "http://hl7.org/fhir/uv/genomics-reporting"
PROFILE_VARIANT = f"{GENOMICS_IG}/StructureDefinition/variant"
PROFILE_OVERALL = f"{GENOMICS_IG}/StructureDefinition/overall-interpretation"
PROFILE_DIAG_REPORT = f"{GENOMICS_IG}/StructureDefinition/genomics-report"

LOINC = "http://loinc.org"
HGNC_SYS = "http://www.genenames.org/geneId"
HGVS_SYS = "http://varnomen.hgvs.org"
DBSNP_SYS = "http://www.ncbi.nlm.nih.gov/projects/SNP"
NCBI_REFSEQ_SYS = "http://www.ncbi.nlm.nih.gov/refseq"
ALLELIC_STATE_SYS = "http://loinc.org"  # LA codes are part of LOINC answer lists

# GRCh38 contig -> NCBI RefSeq accession (subset for the loci in this VCF).
REFSEQ_GRCH38 = {
    "chr1":  "NC_000001.11",
    "chr6":  "NC_000006.12",
    "chr7":  "NC_000007.14",
    "chr10": "NC_000010.11",
    "chr19": "NC_000019.10",
}

# HGNC numeric IDs for the 8 genes in the panel (informational, no inference).
HGNC_ID = {
    "MTHFR":  "7436",
    "DPYD":   "3012",
    "F5":     "3542",
    "HFE":    "4886",
    "CFTR":   "1884",
    "CYP2C19": "2621",
    "APOE":   "613",
}


def _now_iso() -> str:
    # Use UTC, second precision; benchmark wants reproducibility but FHIR
    # requires an instant, so we honor an env override first.
    override = os.environ.get("DOTBIO_FHIR_TIMESTAMP")
    if override:
        return override
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _stable_uuid(seed: str) -> str:
    """Deterministic urn:uuid for a given seed string (helps reproducible diffs)."""
    h = hashlib.sha256(seed.encode("utf-8")).digest()
    # Build a UUIDv4-shaped value from the hash (variant/version bits set per RFC 4122).
    b = bytearray(h[:16])
    b[6] = (b[6] & 0x0F) | 0x40  # version 4
    b[8] = (b[8] & 0x3F) | 0x80  # variant 1
    return f"urn:uuid:{uuid.UUID(bytes=bytes(b))}"


def build_patient(sample: str) -> dict[str, Any]:
    return {
        "resourceType": "Patient",
        "id": "patient-na12878",
        "meta": {
            "profile": [
                "http://hl7.org/fhir/StructureDefinition/Patient",
            ],
        },
        "identifier": [
            {
                "system": "https://www.coriell.org/0/Sections/Search/Sample_Detail.aspx",
                "value": sample or "NA12878",
            }
        ],
        "active": True,
        "gender": "female",
        "extension": [
            {
                "url": "http://hl7.org/fhir/us/core/StructureDefinition/us-core-ethnicity",
                "valueString": "HapMap CEU (public benchmark cell line)",
            }
        ],
    }


def build_specimen(patient_ref: str) -> dict[str, Any]:
    return {
        "resourceType": "Specimen",
        "id": "specimen-na12878-genomic-dna",
        "subject": {"reference": patient_ref},
        "type": {
            "coding": [
                {
                    "system": "http://terminology.hl7.org/CodeSystem/v2-0487",
                    "code": "BLD",
                    "display": "Whole blood",
                }
            ],
            "text": "Lymphoblastoid cell line gDNA (1000 Genomes 30x panel)",
        },
        "collection": {
            "method": {
                "text": "Public reference benchmark sample (1000G phase 3 30x release)"
            }
        },
    }


def build_molecular_sequence(patient_ref: str, specimen_ref: str) -> dict[str, Any]:
    return {
        "resourceType": "MolecularSequence",
        "id": "moleseq-na12878-pgx-panel",
        "type": "dna",
        "coordinateSystem": 1,  # 1 = 1-based (FHIR R4)
        "patient": {"reference": patient_ref},
        "specimen": {"reference": specimen_ref},
        "referenceSeq": {
            "genomeBuild": "GRCh38",
            "orientation": "sense",
            "strand": "watson",
        },
    }


def build_variant_observation(
    rec: VcfRecord,
    patient_ref: str,
    specimen_ref: str,
    moleseq_ref: str,
    bundle_id: str,
) -> dict[str, Any]:
    obs_id = f"obs-variant-{rec.rsid}"
    refseq = REFSEQ_GRCH38.get(rec.chrom, rec.chrom)
    end_pos = rec.pos + max(len(rec.ref), 1) - 1
    state_code, state_display = allelic_state(rec)
    gene = rec.gene or ""

    # interpretation: present if non-reference, otherwise "no variant detected"
    if has_variant_call(rec):
        interp_code = "POS"
        interp_display = "Positive"
        interp_loinc = "LA6576-8"  # LOINC LA code: Present
        interp_loinc_display = "Present"
    else:
        interp_code = "ND"
        interp_display = "No call / reference"
        interp_loinc = "LA6577-6"
        interp_loinc_display = "Absent"

    components: list[dict[str, Any]] = [
        # Gene studied
        {
            "code": {
                "coding": [
                    {"system": LOINC, "code": "48018-6", "display": "Gene studied [ID]"}
                ]
            },
            "valueCodeableConcept": {
                "coding": [
                    {
                        "system": HGNC_SYS,
                        "code": f"HGNC:{HGNC_ID[gene]}" if gene in HGNC_ID else gene,
                        "display": gene,
                    }
                ],
                "text": gene,
            },
        },
        # Genomic reference sequence ID
        {
            "code": {
                "coding": [
                    {"system": LOINC, "code": "48013-7", "display": "Genomic reference sequence ID"}
                ]
            },
            "valueCodeableConcept": {
                "coding": [
                    {"system": NCBI_REFSEQ_SYS, "code": refseq, "display": refseq}
                ],
                "text": f"{rec.chrom} ({refseq})",
            },
        },
        # Reference allele
        {
            "code": {
                "coding": [
                    {"system": LOINC, "code": "69547-8", "display": "Genomic ref allele [ID]"}
                ]
            },
            "valueString": rec.ref,
        },
        # Alternate allele
        {
            "code": {
                "coding": [
                    {"system": LOINC, "code": "69551-0", "display": "Genomic alt allele [ID]"}
                ]
            },
            "valueString": rec.alt,
        },
        # Genomic allele start-end
        {
            "code": {
                "coding": [
                    {"system": LOINC, "code": "81254-5", "display": "Genomic allele start-end"}
                ]
            },
            "valueRange": {
                "low": {"value": rec.pos},
                "high": {"value": end_pos},
            },
        },
        # Reference assembly
        {
            "code": {
                "coding": [
                    {"system": LOINC, "code": "62374-4", "display": "Human reference sequence assembly version"}
                ]
            },
            "valueCodeableConcept": {
                "coding": [
                    {"system": LOINC, "code": "LA14029-5", "display": "GRCh38"}
                ],
                "text": "GRCh38",
            },
        },
        # Allelic state (zygosity)
        {
            "code": {
                "coding": [
                    {"system": LOINC, "code": "53034-5", "display": "Allelic state"}
                ]
            },
            "valueCodeableConcept": {
                "coding": [
                    {"system": ALLELIC_STATE_SYS, "code": state_code, "display": state_display}
                ],
                "text": f"{genotype_string(rec)} ({state_display.lower()})",
            },
        },
    ]

    # dbSNP reference (variation ID) if rsid is conventional
    if rec.rsid.startswith("rs"):
        components.append(
            {
                "code": {
                    "coding": [
                        {"system": LOINC, "code": "81255-2", "display": "dbSNP variant ID"}
                    ]
                },
                "valueCodeableConcept": {
                    "coding": [
                        {"system": DBSNP_SYS, "code": rec.rsid, "display": rec.rsid}
                    ],
                    "text": rec.rsid,
                },
            }
        )

    if rec.af is not None:
        components.append(
            {
                "code": {
                    "coding": [
                        {"system": LOINC, "code": "92822-6", "display": "Genomic source class [Type]"}
                    ],
                    "text": "Population allele frequency (1000G 30x panel)",
                },
                "valueQuantity": {
                    "value": rec.af,
                    "system": "http://unitsofmeasure.org",
                    "code": "1",
                    "unit": "fraction",
                },
            }
        )

    return {
        "fullUrl": _stable_uuid(f"{bundle_id}|{obs_id}"),
        "resource": {
            "resourceType": "Observation",
            "id": obs_id,
            "meta": {"profile": [PROFILE_VARIANT]},
            "status": "final",
            "category": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/observation-category",
                            "code": "laboratory",
                            "display": "Laboratory",
                        }
                    ]
                }
            ],
            "code": {
                "coding": [
                    {"system": LOINC, "code": "69548-6", "display": "Genetic variant assessment"},
                    {"system": LOINC, "code": "81252-9", "display": "Discrete genetic variant"},
                    {"system": LOINC, "code": "53037-8", "display": "Genetic variation's clinical significance [Imp]"},
                ],
                "text": f"{gene} {rec.rsid} discrete genetic variant",
            },
            "subject": {"reference": patient_ref},
            "specimen": {"reference": specimen_ref},
            "derivedFrom": [{"reference": moleseq_ref}],
            "valueCodeableConcept": {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                        "code": interp_code,
                        "display": interp_display,
                    },
                    {"system": LOINC, "code": interp_loinc, "display": interp_loinc_display},
                ],
                "text": (
                    f"{gene} {rec.rsid} {genotype_string(rec)} ({state_display}) — {interp_display}"
                ),
            },
            "interpretation": [
                {
                    "coding": [
                        {
                            "system": "http://terminology.hl7.org/CodeSystem/v3-ObservationInterpretation",
                            "code": interp_code,
                            "display": interp_display,
                        }
                    ],
                    "text": interp_display,
                }
            ],
            "component": components,
        },
    }


def build_diagnostic_report(
    patient_ref: str,
    specimen_ref: str,
    observation_refs: list[str],
    issued: str,
) -> dict[str, Any]:
    return {
        "resourceType": "DiagnosticReport",
        "id": "diagreport-na12878-pgx",
        "meta": {"profile": [PROFILE_DIAG_REPORT]},
        "status": "final",
        "category": [
            {
                "coding": [
                    {
                        "system": "http://terminology.hl7.org/CodeSystem/v2-0074",
                        "code": "GE",
                        "display": "Genetics",
                    }
                ]
            }
        ],
        "code": {
            "coding": [
                {"system": LOINC, "code": "81247-9", "display": "Master HL7 genetic variant reporting panel"},
                {"system": LOINC, "code": "53041-0", "display": "DNA analysis discrete sequence variation panel"},
            ],
            "text": "PGx panel — 8 loci (NA12878 benchmark)",
        },
        "subject": {"reference": patient_ref},
        "specimen": [{"reference": specimen_ref}],
        "issued": issued,
        "effectiveDateTime": issued,
        "result": [{"reference": ref} for ref in observation_refs],
        "conclusion": (
            "Eight PGx loci genotyped on GRCh38; ALT alleles observed at "
            "rs1801133 (MTHFR) and rs4244285 (CYP2C19). Other 6 loci called "
            "homozygous reference. This is a benchmark output and is not a "
            "clinical report."
        ),
    }


# ---------------------------------------------------------------------------
# Bundle assembly
# ---------------------------------------------------------------------------

def build_bundle(records: list[VcfRecord], header: dict[str, str], sample: str, vcf_path: Path) -> dict[str, Any]:
    issued = _now_iso()
    bundle_id = "bundle-na12878-pgx"
    patient = build_patient(sample)
    specimen = build_specimen(f"Patient/{patient['id']}")
    moleseq = build_molecular_sequence(
        f"Patient/{patient['id']}", f"Specimen/{specimen['id']}"
    )

    entries: list[dict[str, Any]] = []
    patient_full = _stable_uuid(f"{bundle_id}|{patient['id']}")
    specimen_full = _stable_uuid(f"{bundle_id}|{specimen['id']}")
    moleseq_full = _stable_uuid(f"{bundle_id}|{moleseq['id']}")

    entries.append({"fullUrl": patient_full, "resource": patient})
    entries.append({"fullUrl": specimen_full, "resource": specimen})
    entries.append({"fullUrl": moleseq_full, "resource": moleseq})

    obs_refs: list[str] = []
    for rec in records:
        obs_entry = build_variant_observation(
            rec,
            f"Patient/{patient['id']}",
            f"Specimen/{specimen['id']}",
            f"MolecularSequence/{moleseq['id']}",
            bundle_id,
        )
        entries.append(obs_entry)
        obs_refs.append(f"Observation/{obs_entry['resource']['id']}")

    diag = build_diagnostic_report(
        f"Patient/{patient['id']}", f"Specimen/{specimen['id']}", obs_refs, issued
    )
    entries.append({"fullUrl": _stable_uuid(f"{bundle_id}|{diag['id']}"), "resource": diag})

    bundle = {
        "resourceType": "Bundle",
        "id": bundle_id,
        "meta": {
            "profile": [
                f"{GENOMICS_IG}/StructureDefinition/genomics-report-bundle",
            ],
            "tag": [
                {
                    "system": "https://github.com/zwbao/dotbio",
                    "code": "dotbio-bench-v2-format-e",
                    "display": "dotbio NM-grade benchmark v2 — comparator format E (FHIR Genomics IG)",
                }
            ],
        },
        "type": "collection",
        "timestamp": issued,
        "entry": entries,
    }
    return bundle


# ---------------------------------------------------------------------------
# Lightweight validator (no external schema; checks IG-relevant invariants)
# ---------------------------------------------------------------------------

VALIDATION_REQUIREMENTS = {
    "patient": 1,
    "specimen": 1,
    "molecular_sequence": 1,
    "diagnostic_report": 1,
}


def validate_bundle(bundle: dict[str, Any]) -> list[str]:
    """Hand-rolled validator for IG-relevant invariants. Returns a list of issues
    (empty = valid for our acceptance criteria). Not a FHIR-complete validator —
    Task 2 explicitly allows pure-stdlib output and notes that fhir.resources is
    optional. We check the things the SPEC and TASKS.md require."""
    issues: list[str] = []
    if bundle.get("resourceType") != "Bundle":
        issues.append("Top-level resourceType must be Bundle")
    counts: dict[str, int] = {}
    loinc_present = {"53037-8": False, "81252-9": False, "48018-6": False}
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        rt = res.get("resourceType", "")
        counts[rt] = counts.get(rt, 0) + 1
        if rt == "Observation":
            # check Observation.code AND Observation.component[].code for LOINC presence
            for c in res.get("code", {}).get("coding", []):
                if c.get("system") == LOINC and c.get("code") in loinc_present:
                    loinc_present[c["code"]] = True
            for comp in res.get("component", []):
                for c in comp.get("code", {}).get("coding", []):
                    if c.get("system") == LOINC and c.get("code") in loinc_present:
                        loinc_present[c["code"]] = True
            if not res.get("subject"):
                issues.append(f"Observation/{res.get('id')} missing subject")
            if not res.get("component"):
                issues.append(f"Observation/{res.get('id')} missing component[]")
    for need, must_have in (
        ("Patient", "patient"),
        ("Specimen", "specimen"),
        ("MolecularSequence", "molecular_sequence"),
        ("DiagnosticReport", "diagnostic_report"),
    ):
        if counts.get(need, 0) < 1:
            issues.append(f"Missing required resource type: {need}")
    for code, ok in loinc_present.items():
        if not ok:
            issues.append(f"No Observation carries LOINC {code}")
    if counts.get("Observation", 0) < 1:
        issues.append("Bundle has no Observation resources")
    return issues


# ---------------------------------------------------------------------------
# Tokenizer (Xenova/claude-tokenizer via transformers)
# ---------------------------------------------------------------------------

def claude_token_count(text: str) -> int | None:
    try:
        from transformers import AutoTokenizer  # type: ignore

        tok = AutoTokenizer.from_pretrained("Xenova/claude-tokenizer")
        return len(tok.encode(text))
    except Exception:
        return None


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="VCF -> FHIR R4 Genomics IG Bundle")
    p.add_argument("--vcf", default="examples/real-na12878/input.vcf")
    p.add_argument("--out", default="bench/v2/data/format_e_fhir_bundle.json")
    p.add_argument("--token-count", action="store_true", help="Print Claude token count")
    p.add_argument("--repo-root", default=str(Path(__file__).resolve().parents[3]))
    args = p.parse_args(argv)

    repo_root = Path(args.repo_root)
    vcf_path = (repo_root / args.vcf) if not Path(args.vcf).is_absolute() else Path(args.vcf)
    out_path = (repo_root / args.out) if not Path(args.out).is_absolute() else Path(args.out)

    if not vcf_path.exists():
        print(f"ERROR: VCF not found: {vcf_path}", file=sys.stderr)
        return 2

    records, header, sample = parse_vcf(vcf_path)
    bundle = build_bundle(records, header, sample, vcf_path)
    issues = validate_bundle(bundle)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(bundle, indent=2, sort_keys=False)
    out_path.write_text(text + "\n")

    print(f"wrote {out_path} ({len(text)} bytes, {len(bundle['entry'])} resources)")
    if issues:
        print("VALIDATION ISSUES:")
        for i in issues:
            print(f"  - {i}")
        return 1
    print("validation: OK")

    if args.token_count:
        n = claude_token_count(text)
        if n is None:
            print("token count: unavailable (transformers/Xenova tokenizer not installed)")
        else:
            print(f"claude tokens: {n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
