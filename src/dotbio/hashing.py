"""Canonical JSON hashing for content-addressed facts.

We use sha256 over a deterministic JSON encoding (sorted keys, no whitespace,
UTF-8). Two structurally identical facts always produce the same hash regardless
of input field order.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json(obj: Any) -> bytes:
    return json.dumps(
        obj,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def fact_hash(fact: dict) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(fact)).hexdigest()


def hash_path_parts(hash_str: str) -> tuple[str, str]:
    """Split a sha256 hash into (prefix, rest) for git-style sharded storage."""
    if hash_str.startswith("sha256:"):
        digest = hash_str[len("sha256:"):]
    else:
        digest = hash_str
    return digest[:2], digest[2:]
