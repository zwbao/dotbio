"""Minimal VCF v4.x reader. Stdlib-only.

Not feature-complete — handles single-sample, single-ALT records sufficient
for the demo. For production use, swap in cyvcf2 or pysam.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterator


@dataclass
class VCFRecord:
    chrom: str
    pos: int
    rsid: str | None
    ref: str
    alt: str
    qual: float | None
    filter_: str
    info: dict[str, str | bool]
    sample: dict[str, str]
    raw_gt: str

    @property
    def genotype(self) -> str:
        """Return a normalized genotype like 'C/C' or 'GAG/G'.

        For phased calls we drop the phase information; the AI-native layer
        treats both as the same biological state for variant lookup. (Phasing
        information can be reintroduced when haplotype-aware rules need it.)
        """
        gt = self.raw_gt.replace("|", "/")
        try:
            a, b = gt.split("/", 1)
        except ValueError:
            return gt
        alleles = [self.ref if x == "0" else self.alt for x in (a, b)]
        return "/".join(alleles)

    @property
    def is_homref(self) -> bool:
        return self.raw_gt.replace("|", "/") in {"0/0"}


def parse_vcf(path: Path | str) -> Iterator[VCFRecord]:
    path = Path(path)
    sample_name: str | None = None
    format_keys: list[str] = []

    with path.open() as f:
        for raw_line in f:
            line = raw_line.rstrip("\n")
            if not line:
                continue
            if line.startswith("##"):
                continue
            if line.startswith("#CHROM"):
                cols = line.split("\t")
                if len(cols) > 9:
                    sample_name = cols[9]
                continue
            cols = line.split("\t")
            if len(cols) < 8:
                continue
            chrom, pos, vid, ref, alt, qual, filt, info_s = cols[:8]
            fmt_s = cols[8] if len(cols) > 8 else ""
            sample_s = cols[9] if len(cols) > 9 else ""

            info: dict[str, str | bool] = {}
            for token in info_s.split(";"):
                if not token or token == ".":
                    continue
                if "=" in token:
                    k, v = token.split("=", 1)
                    info[k] = v
                else:
                    info[token] = True

            format_keys = fmt_s.split(":") if fmt_s else []
            sample_vals = sample_s.split(":") if sample_s else []
            sample = dict(zip(format_keys, sample_vals))

            try:
                qual_v: float | None = float(qual) if qual not in {".", ""} else None
            except ValueError:
                qual_v = None

            try:
                pos_i = int(pos)
            except ValueError:
                continue

            yield VCFRecord(
                chrom=chrom,
                pos=pos_i,
                rsid=None if vid in {".", ""} else vid,
                ref=ref,
                alt=alt,
                qual=qual_v,
                filter_=filt,
                info=info,
                sample=sample,
                raw_gt=sample.get("GT", "./."),
            )

    _ = sample_name  # documentation: a future version exposes this
