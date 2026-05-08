"""Hashing / canonicalization tests."""

from __future__ import annotations

import json

from dotbio.hashing import canonical_json, fact_hash, hash_path_parts


def test_canonical_json_sorts_keys() -> None:
    a = {"z": 1, "a": 2, "m": 3}
    b = {"a": 2, "m": 3, "z": 1}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_sorts_nested() -> None:
    a = {"outer": {"z": 1, "a": 2}, "list": [{"y": 1, "x": 2}]}
    b = {"list": [{"x": 2, "y": 1}], "outer": {"a": 2, "z": 1}}
    assert canonical_json(a) == canonical_json(b)


def test_canonical_json_no_whitespace() -> None:
    out = canonical_json({"a": 1, "b": [1, 2, 3]})
    assert b" " not in out
    assert b"\n" not in out


def test_canonical_json_utf8() -> None:
    out = canonical_json({"name": "ΔF508"})
    decoded = json.loads(out.decode("utf-8"))
    assert decoded["name"] == "ΔF508"


def test_fact_hash_is_deterministic() -> None:
    fact = {
        "kind": "variant",
        "chrom": "chr19",
        "pos": 44908684,
        "ref": "T",
        "alt": "C",
        "rsid": "rs429358",
        "genotype": "C/C",
        "build": "GRCh38",
    }
    assert fact_hash(fact) == fact_hash(fact)


def test_fact_hash_invariant_to_key_order() -> None:
    a = {"chrom": "chr1", "pos": 100, "ref": "A", "alt": "G"}
    b = {"alt": "G", "pos": 100, "ref": "A", "chrom": "chr1"}
    assert fact_hash(a) == fact_hash(b)


def test_fact_hash_differs_for_different_content() -> None:
    a = {"chrom": "chr1", "pos": 100, "ref": "A", "alt": "G"}
    b = {"chrom": "chr1", "pos": 101, "ref": "A", "alt": "G"}
    assert fact_hash(a) != fact_hash(b)


def test_fact_hash_starts_with_sha256_prefix() -> None:
    h = fact_hash({"x": 1})
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_hash_path_parts_splits() -> None:
    p, r = hash_path_parts("sha256:abcdef0123456789" + "0" * 48)
    assert p == "ab"
    assert r == "cdef0123456789" + "0" * 48
    assert len(p) + len(r) == 64


def test_hash_path_parts_accepts_bare_digest() -> None:
    p, r = hash_path_parts("ab" + "f" * 62)
    assert p == "ab"
