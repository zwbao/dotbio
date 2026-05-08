"""bio — command-line interface for dotbio bundles.

Subcommands:
  compile  VCF (+ optional metadata) → .bio bundle
  show     Render a view from a bundle
  diff     Show claim-level diff between two refs
  expand   Resolve a claim_id back to its full evidence chain
  update   Apply a new ruleset, append a commit, advance HEAD
  log      List all commits with their refs
  facts    List facts in the bundle
"""

from __future__ import annotations

import argparse
import datetime as dt
import shutil
import sys
import uuid
from pathlib import Path
from typing import Any

from . import SCHEMA, __version__
from .bundle import Bundle
from .engine import (
    apply_clinvar,
    apply_oncokb,
    apply_pharmcat,
    load_ruleset,
)
from .vcfio import parse_vcf
from .views import VIEW_REGISTRY


# ---- helpers -----------------------------------------------------------


def _now_iso() -> str:
    now = dt.datetime.now(dt.timezone.utc)
    return now.strftime("%Y-%m-%dT%H:%M:%S.") + f"{now.microsecond // 1000:03d}Z"


def _vcf_to_facts(vcf_path: Path, build: str) -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for rec in parse_vcf(vcf_path):
        fact: dict[str, Any] = {
            "kind": "variant",
            "build": build,
            "chrom": rec.chrom,
            "pos": rec.pos,
            "ref": rec.ref,
            "alt": rec.alt,
            "genotype": rec.genotype,
            "filter": rec.filter_,
        }
        if rec.rsid:
            fact["rsid"] = rec.rsid
        if rec.qual is not None:
            fact["qual"] = rec.qual
        if "DP" in rec.sample:
            try:
                fact["depth"] = int(rec.sample["DP"])
            except ValueError:
                pass
        if rec.info.get("SOMATIC"):
            fact["somatic"] = True
        if "ANN" in rec.info:
            fact["annotation"] = rec.info["ANN"]
        if "GENE" in rec.info:
            fact["gene_hint"] = rec.info["GENE"]
        if rec.is_homref:
            fact["homref"] = True
        facts.append(fact)
    return facts


def _materialize_views(bundle: Bundle, claims: list[dict]) -> list[dict[str, Any]]:
    view_summaries: list[dict[str, Any]] = []
    for vid, (title, renderer) in VIEW_REGISTRY.items():
        content = renderer(claims)
        bundle.write_view(vid, content)
        # rough token estimate: 1 token ≈ 4 chars
        n_claims = sum(1 for line in content.splitlines() if line.startswith("### "))
        view_summaries.append({
            "name": vid,
            "title": title,
            "scope": vid,
            "path": f"views/{vid}.md",
            "claim_count": n_claims,
            "est_tokens": max(1, len(content) // 4),
        })
    return view_summaries


# ---- compile -----------------------------------------------------------


def cmd_compile(args: argparse.Namespace) -> int:
    vcf = Path(args.vcf)
    out = Path(args.out)
    if out.exists():
        if not args.force:
            print(f"refusing to overwrite existing bundle at {out} (use --force)", file=sys.stderr)
            return 2
        shutil.rmtree(out)

    bundle = Bundle(out)
    bundle.init()

    facts = _vcf_to_facts(vcf, build=args.build)
    facts_with_hashes: list[tuple[str, dict]] = []
    for f in facts:
        # exclude the homref records from claims-producing input but still
        # store the fact (so "we checked rs1800562 and it's negative" is
        # preserved as data)
        h = bundle.write_fact(f)
        if not f.get("homref"):
            facts_with_hashes.append((h, f))

    rulesets = args.rulesets or [
        "clinvar@2026-05-01",
        "pharmcat@2025.3",
        "oncokb@2026-04-15",
    ]

    all_claims: list[dict] = []
    used_rulesets: list[dict[str, Any]] = []
    for rs_id in rulesets:
        rs = load_ruleset(rs_id)
        used_rulesets.append({
            "name": rs["name"],
            "version": rs["version"],
            "type": rs.get("type"),
            "source_url": rs.get("url"),
            "source": rs.get("source"),
            "license": rs.get("license"),
        })
        if rs["name"] == "clinvar":
            all_claims.extend(apply_clinvar(facts_with_hashes, rs))
        elif rs["name"] == "pharmcat":
            all_claims.extend(apply_pharmcat(facts_with_hashes, rs))
        elif rs["name"] == "oncokb":
            all_claims.extend(apply_oncokb(facts_with_hashes, rs))

    commit_id = _now_iso()
    commit = {
        "id": commit_id,
        "parent": None,
        "created": commit_id,
        "rulesets": [f"{rs['name']}@{rs['version']}" for rs in used_rulesets],
        "claims": all_claims,
    }
    bundle.write_commit(commit)
    bundle.write_ref("HEAD", commit_id)
    bundle.write_ref("stable", commit_id)

    view_summaries = _materialize_views(bundle, all_claims)

    bundle.write_manifest({
        "subject": args.subject or _subject_id(facts),
        "created": commit_id,
        "build": args.build,
        "refs": bundle.list_refs(),
        "views": view_summaries,
        "active_rulesets": used_rulesets,
        "scopes": {
            "germline_variant_count": sum(1 for f in facts if not f.get("somatic")),
            "somatic_call_count": sum(1 for f in facts if f.get("somatic")),
        },
        "claim_count": len(all_claims),
    })

    print(f"wrote bundle: {out}")
    print(f"  facts:   {len(facts)}")
    print(f"  claims:  {len(all_claims)}")
    print(f"  views:   {len(view_summaries)}  ({', '.join(v['name'] for v in view_summaries)})")
    print(f"  ref HEAD = {commit_id}")
    return 0


def _subject_id(facts: list[dict]) -> str:
    return "subject:" + uuid.uuid5(uuid.NAMESPACE_OID, str(len(facts))).hex[:12]


# ---- show ---------------------------------------------------------------


def cmd_show(args: argparse.Namespace) -> int:
    bundle = Bundle(args.bundle)
    if args.view == "manifest":
        m = bundle.read_manifest()
        import json as _json
        print(_json.dumps(m, indent=2, ensure_ascii=False))
        return 0
    if args.view in VIEW_REGISTRY:
        print(bundle.read_view(args.view), end="")
        return 0
    print(f"unknown view: {args.view}", file=sys.stderr)
    print(f"available: manifest, {', '.join(VIEW_REGISTRY)}", file=sys.stderr)
    return 2


# ---- update ------------------------------------------------------------


def cmd_update(args: argparse.Namespace) -> int:
    bundle = Bundle(args.bundle)
    head_id = bundle.read_ref("HEAD")
    head_commit = bundle.read_commit(head_id)

    # Reload all facts from the existing CAS layer
    facts_with_hashes: list[tuple[str, dict]] = []
    for prefix_dir in bundle.facts_dir.iterdir():
        if not prefix_dir.is_dir():
            continue
        for fact_file in prefix_dir.glob("*.json"):
            import json as _json
            with fact_file.open() as fh:
                f = _json.load(fh)
            h = f"sha256:{prefix_dir.name}{fact_file.stem}"
            if not f.get("homref"):
                facts_with_hashes.append((h, f))

    rs = load_ruleset(args.ruleset)
    if rs["name"] == "clinvar":
        new_claims = apply_clinvar(facts_with_hashes, rs)
    elif rs["name"] == "pharmcat":
        new_claims = apply_pharmcat(facts_with_hashes, rs)
    elif rs["name"] == "oncokb":
        new_claims = apply_oncokb(facts_with_hashes, rs)
    else:
        print(f"unsupported ruleset: {rs['name']}", file=sys.stderr)
        return 2

    # Carry forward claims from rulesets we are NOT updating
    other_claims = [c for c in head_commit["claims"] if not c["ruleset"].startswith(rs["name"] + "@")]
    merged_claims = other_claims + new_claims

    commit_id = _now_iso()
    new_commit = {
        "id": commit_id,
        "parent": head_id,
        "created": commit_id,
        "rulesets": [args.ruleset] + [r for r in head_commit.get("rulesets", []) if not r.startswith(rs["name"] + "@")],
        "claims": merged_claims,
    }
    bundle.write_commit(new_commit)
    bundle.write_ref("HEAD", commit_id)

    # Refresh views for the new HEAD
    _materialize_views(bundle, merged_claims)

    # Update manifest active_rulesets to reflect the new active version
    manifest = bundle.read_manifest()
    new_active: list[dict[str, Any]] = []
    seen = set()
    for r in manifest.get("active_rulesets", []):
        if r["name"] == rs["name"]:
            continue
        new_active.append(r)
        seen.add(r["name"])
    new_active.append({
        "name": rs["name"],
        "version": rs["version"],
        "type": rs.get("type"),
        "source_url": rs.get("url"),
        "source": rs.get("source"),
        "license": rs.get("license"),
    })
    manifest["active_rulesets"] = new_active
    manifest["refs"] = bundle.list_refs()
    manifest["claim_count"] = len(merged_claims)
    bundle.write_manifest(manifest)

    print(f"appended commit {commit_id}")
    print(f"  parent: {head_id}")
    print(f"  ruleset applied: {args.ruleset}")
    print(f"  claims: {len(other_claims)} carried + {len(new_claims)} new = {len(merged_claims)} total")
    return 0


# ---- diff --------------------------------------------------------------


def cmd_diff(args: argparse.Namespace) -> int:
    bundle = Bundle(args.bundle)
    a = bundle.read_commit(bundle._resolve(args.ref_a))
    b = bundle.read_commit(bundle._resolve(args.ref_b))

    by_claim_a = {c["claim"]: c for c in a["claims"]}
    by_claim_b = {c["claim"]: c for c in b["claims"]}

    # Group "reclassified" cases — where the variant target set is the same
    # but the claim text differs. We use (level, sorted targets) as the key.
    def key(c: dict) -> tuple:
        return (c["level"], tuple(sorted(c["targets"])), c.get("gene"), c.get("alteration") or c.get("variant_name"))

    by_key_a = {key(c): c for c in a["claims"]}
    by_key_b = {key(c): c for c in b["claims"]}

    added = [c for k, c in by_key_b.items() if k not in by_key_a]
    removed = [c for k, c in by_key_a.items() if k not in by_key_b]
    changed: list[tuple[dict, dict]] = []

    def substantive(c: dict) -> tuple:
        # Compare on the interpretive payload, not on cosmetic fields like
        # the embedded ruleset version. Ruleset bumps that don't change any
        # interpretation should NOT show up in the diff.
        return (
            c.get("significance"),
            c.get("oncogenicity"),
            c.get("phenotype"),
            c.get("diplotype"),
            c.get("condition"),
        )

    for k, ca in by_key_a.items():
        cb = by_key_b.get(k)
        if cb is None:
            continue
        if substantive(ca) != substantive(cb):
            changed.append((ca, cb))

    out: list[str] = []
    out.append(f"# Diff  {args.ref_a} → {args.ref_b}")
    out.append("")
    out.append(f"- {len(added)} added")
    out.append(f"- {len(removed)} removed")
    out.append(f"- {len(changed)} changed (same target, new interpretation)")
    out.append("")

    if changed:
        out.append("## Reclassifications")
        out.append("")
        for ca, cb in changed:
            out.append(f"- **{cb.get('gene','?')} {cb.get('variant_name') or cb.get('alteration','')}**")
            out.append(f"  - was: {ca['claim']}  ({ca['ruleset']})")
            out.append(f"  - now: {cb['claim']}  ({cb['ruleset']})")
            if cb.get("previous_classification"):
                out.append(f"  - reason: ruleset reclassified {cb['previous_classification']} → {cb.get('significance','?')} on {cb.get('reclassified_on','?')}")
        out.append("")
    if added:
        out.append("## Added")
        out.append("")
        for c in added:
            out.append(f"- {c['claim']}  ({c['ruleset']})")
        out.append("")
    if removed:
        out.append("## Removed")
        out.append("")
        for c in removed:
            out.append(f"- {c['claim']}  ({c['ruleset']})")
        out.append("")

    print("\n".join(out).rstrip())
    return 0


# ---- expand ------------------------------------------------------------


def cmd_expand(args: argparse.Namespace) -> int:
    bundle = Bundle(args.bundle)
    head = bundle.read_commit(bundle._resolve(args.ref))
    target = None
    for c in head["claims"]:
        if c["id"] == args.claim_id:
            target = c
            break
    if target is None:
        print(f"claim_id not found at ref {args.ref}: {args.claim_id}", file=sys.stderr)
        return 2

    print(f"# Evidence chain for {args.claim_id}")
    print()
    print(f"- **Claim**: {target['claim']}")
    print(f"- **Level**: {target['level']}")
    print(f"- **Ruleset**: {target['ruleset']}")
    if target.get("guideline"):
        print(f"- **Guideline**: {target['guideline']}")
    print(f"- **Derivation**: {target['derivation']}")
    if target.get("evidence"):
        print(f"- **Evidence (from ruleset)**: {target['evidence']}")
    print()
    print("## Underlying facts")
    print()
    for h in target["targets"]:
        f = bundle.read_fact(h)
        loc = f"{f.get('chrom','?')}:{f.get('pos','?')} {f.get('ref','?')}>{f.get('alt','?')}"
        rsid = f.get("rsid", "")
        gt = f.get("genotype", "")
        gene = f.get("gene_hint", "")
        print(f"- `{h[:23]}…` — {gene} {rsid} {loc} GT={gt}")
    return 0


# ---- log ---------------------------------------------------------------


def cmd_log(args: argparse.Namespace) -> int:
    bundle = Bundle(args.bundle)
    refs = bundle.list_refs()
    head = bundle.read_ref("HEAD")
    chain = bundle.commit_ancestry("HEAD")
    by_id_refs: dict[str, list[str]] = {}
    for name, cid in refs.items():
        by_id_refs.setdefault(cid, []).append(name)
    for c in chain:
        marks = ""
        if c["id"] in by_id_refs:
            marks = "  (" + ", ".join(by_id_refs[c["id"]]) + ")"
        print(f"{c['id']}{marks}")
        print(f"    rulesets: {', '.join(c.get('rulesets', []))}")
        print(f"    claims:   {len(c.get('claims', []))}")
    return 0


# ---- facts -------------------------------------------------------------


def cmd_facts(args: argparse.Namespace) -> int:
    bundle = Bundle(args.bundle)
    rows: list[tuple[str, str, str, str, str, str]] = []
    for prefix_dir in sorted(bundle.facts_dir.iterdir()):
        if not prefix_dir.is_dir():
            continue
        for fact_file in sorted(prefix_dir.glob("*.json")):
            import json as _json
            with fact_file.open() as fh:
                f = _json.load(fh)
            h = f"sha256:{prefix_dir.name}{fact_file.stem}"
            rows.append((
                h[:23] + "…",
                f.get("gene_hint", ""),
                f.get("rsid", ""),
                f"{f.get('chrom','?')}:{f.get('pos','?')}",
                f"{f.get('ref','')}>{f.get('alt','')}",
                f.get("genotype", ""),
            ))
    rows.sort(key=lambda r: (r[1], r[2]))
    fmt = "{:<26} {:<10} {:<14} {:<18} {:<10} {:<8}"
    print(fmt.format("hash", "gene", "rsid", "locus", "ref>alt", "GT"))
    print(fmt.format("-" * 26, "-" * 10, "-" * 14, "-" * 18, "-" * 10, "-" * 8))
    for r in rows:
        print(fmt.format(*r))
    return 0


# ---- main --------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="bio", description="dotbio CLI")
    p.add_argument("--version", action="version", version=f"dotbio {__version__} (schema {SCHEMA})")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("compile", help="VCF → .bio bundle")
    sp.add_argument("vcf", help="input VCF path")
    sp.add_argument("-o", "--out", required=True, help="output bundle directory (e.g. patient.bio)")
    sp.add_argument("--build", default="GRCh38", help="genome build")
    sp.add_argument("--subject", default=None, help="opaque subject id (default: derived)")
    sp.add_argument("--ruleset", dest="rulesets", action="append", help="ruleset name@version (repeatable)")
    sp.add_argument("--force", action="store_true", help="overwrite existing bundle")
    sp.set_defaults(func=cmd_compile)

    sp = sub.add_parser("show", help="render a view")
    sp.add_argument("bundle", help="bundle path")
    sp.add_argument("--view", default="pgx", help="view name or 'manifest'")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("update", help="apply a new ruleset and append a commit")
    sp.add_argument("bundle", help="bundle path")
    sp.add_argument("--ruleset", required=True, help="ruleset name@version")
    sp.set_defaults(func=cmd_update)

    sp = sub.add_parser("diff", help="claim-level diff between two refs")
    sp.add_argument("bundle", help="bundle path")
    sp.add_argument("ref_a", help="first ref/commit")
    sp.add_argument("ref_b", help="second ref/commit")
    sp.set_defaults(func=cmd_diff)

    sp = sub.add_parser("expand", help="resolve a claim_id to its evidence chain")
    sp.add_argument("bundle", help="bundle path")
    sp.add_argument("claim_id", help="claim id from a view")
    sp.add_argument("--ref", default="HEAD", help="ref to resolve against")
    sp.set_defaults(func=cmd_expand)

    sp = sub.add_parser("log", help="list commits and refs")
    sp.add_argument("bundle", help="bundle path")
    sp.set_defaults(func=cmd_log)

    sp = sub.add_parser("facts", help="list facts in the bundle")
    sp.add_argument("bundle", help="bundle path")
    sp.set_defaults(func=cmd_facts)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
