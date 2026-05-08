"""Bundle IO — read/write a .bio directory.

A bundle is a directory:

    patient.bio/
    ├── manifest.json
    ├── facts/<2>/<rest>.json   (CAS layer; immutable)
    ├── commits/<id>.commit.json (append-only)
    ├── views/*.md
    └── refs/<name>             (text file holding a commit id)
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import SCHEMA
from .hashing import canonical_json, fact_hash, hash_path_parts


@dataclass
class Bundle:
    path: Path

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    # ---- Layout helpers ------------------------------------------------

    @property
    def manifest_path(self) -> Path:
        return self.path / "manifest.json"

    @property
    def facts_dir(self) -> Path:
        return self.path / "facts"

    @property
    def commits_dir(self) -> Path:
        return self.path / "commits"

    @property
    def views_dir(self) -> Path:
        return self.path / "views"

    @property
    def refs_dir(self) -> Path:
        return self.path / "refs"

    def init(self) -> None:
        for d in (self.facts_dir, self.commits_dir, self.views_dir, self.refs_dir):
            d.mkdir(parents=True, exist_ok=True)

    # ---- Manifest ------------------------------------------------------

    def read_manifest(self) -> dict[str, Any]:
        with self.manifest_path.open() as f:
            return json.load(f)

    def write_manifest(self, manifest: dict[str, Any]) -> None:
        manifest = {"schema": SCHEMA, **manifest}
        self.manifest_path.write_bytes(canonical_json(manifest) + b"\n")

    # ---- Facts (CAS) ---------------------------------------------------

    def write_fact(self, fact: dict[str, Any]) -> str:
        h = fact_hash(fact)
        prefix, rest = hash_path_parts(h)
        out_dir = self.facts_dir / prefix
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / f"{rest}.json").write_bytes(canonical_json(fact) + b"\n")
        return h

    def read_fact(self, h: str) -> dict[str, Any]:
        prefix, rest = hash_path_parts(h)
        with (self.facts_dir / prefix / f"{rest}.json").open() as f:
            return json.load(f)

    # ---- Commits -------------------------------------------------------

    def write_commit(self, commit: dict[str, Any]) -> str:
        cid = commit["id"]
        path = self.commits_dir / f"{cid}.commit.json"
        path.write_bytes(canonical_json(commit) + b"\n")
        return cid

    def read_commit(self, cid: str) -> dict[str, Any]:
        with (self.commits_dir / f"{cid}.commit.json").open() as f:
            return json.load(f)

    def list_commits(self) -> list[str]:
        out = []
        for p in self.commits_dir.glob("*.commit.json"):
            out.append(p.name.removesuffix(".commit.json"))
        return sorted(out)

    # ---- Refs ----------------------------------------------------------

    def write_ref(self, name: str, commit_id: str) -> None:
        (self.refs_dir / name).write_text(commit_id + "\n")

    def read_ref(self, name: str) -> str:
        return (self.refs_dir / name).read_text().strip()

    def list_refs(self) -> dict[str, str]:
        out: dict[str, str] = {}
        for p in self.refs_dir.iterdir():
            if p.is_file():
                out[p.name] = p.read_text().strip()
        return out

    # ---- Views ---------------------------------------------------------

    def write_view(self, name: str, content: str) -> Path:
        path = self.views_dir / f"{name}.md"
        path.write_text(content)
        return path

    def read_view(self, name: str) -> str:
        return (self.views_dir / f"{name}.md").read_text()

    # ---- Walking the commit chain --------------------------------------

    def commit_ancestry(self, ref_or_id: str) -> list[dict[str, Any]]:
        """Walk from the given commit back to the root via `parent`. Newest first."""
        cid = self._resolve(ref_or_id)
        chain: list[dict[str, Any]] = []
        seen: set[str] = set()
        while cid and cid not in seen:
            seen.add(cid)
            commit = self.read_commit(cid)
            chain.append(commit)
            cid = commit.get("parent")
        return chain

    def _resolve(self, ref_or_id: str) -> str:
        ref_path = self.refs_dir / ref_or_id
        if ref_path.exists():
            return ref_path.read_text().strip()
        return ref_or_id
