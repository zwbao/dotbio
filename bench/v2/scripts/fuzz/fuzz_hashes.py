"""Hash-collision documentation module.

Goal: demonstrate, with code that you can read in 30 seconds, that

  (a) constructing a SHA-256 collision against dotbio's full 256-bit
      content-address is computationally infeasible (≈ 2^128 work by
      birthday bound), and

  (b) if anyone shortened the hash for "convenience", collisions DO
      appear quickly. We illustrate this by birthday-attacking a
      SHA-256 truncated to 16 bits — and we expect a collision in
      O(2^8) ≈ 256 random inputs.

This module is **documentation, not an attack**. We do not search for a
real SHA-256 collision; we cite the public state of the art (Stevens et
al. SHA-1 chosen-prefix `shattered` 2017, the absence of any public
SHA-256 collision as of 2026-05-09) and give a recoverable in-script
proof that 16-bit truncation is unsafe.

The runner's expected behavior: each case "passes" if its assertion
about the collision/non-collision state holds at runtime.
"""

from __future__ import annotations

import hashlib
import secrets
from pathlib import Path

from . import FuzzCase


# Public state-of-the-art reference, in plain text (no live fetch).
_SHA256_NO_KNOWN_COLLISION = (
    "As of 2026-05-09, no SHA-256 collision is publicly known. The best "
    "published collision attacks against SHA-256 are reduced-round, e.g. "
    "Mendel-Nad-Schl 2013 on 28/64 rounds. Full-round collision search "
    "requires ≈ 2^128 hash evaluations by the birthday bound. At 10^10 H/s "
    "(GPU-class), that is ≈ 10^21 years — > 10^11× the age of the universe. "
    "We rely on this for content-addressing the facts/ CAS layer."
)


def _case_full_sha256_infeasibility(work: Path) -> dict:
    """Lower-bound the work needed for a full-256-bit collision and assert
    it is astronomically beyond commodity hardware."""
    BITS = 256
    BIRTHDAY_WORK = 2 ** (BITS // 2)  # 2^128
    GPU_HASHES_PER_SEC = 1e10         # generous H/s for a single modern GPU
    YEARS = BIRTHDAY_WORK / GPU_HASHES_PER_SEC / (60 * 60 * 24 * 365.25)
    AGE_OF_UNIVERSE_YEARS = 13.8e9
    factor = YEARS / AGE_OF_UNIVERSE_YEARS
    ok = factor > 1e10
    notes = (
        f"Birthday-bound work for SHA-256 collision: 2^{BITS // 2} ≈ "
        f"{BIRTHDAY_WORK:.2e} hashes. At {GPU_HASHES_PER_SEC:.0e} H/s that "
        f"is {YEARS:.2e} years, ≈ {factor:.1e}× the age of the universe. "
        f"INFEASIBLE.\n\nReference: {_SHA256_NO_KNOWN_COLLISION}"
    )
    return {"actual_exit": 0, "stdout": "", "stderr": "",
            "ok": ok, "notes": notes,
            "birthday_work": BIRTHDAY_WORK,
            "years_at_1e10_hps": YEARS,
            "factor_universe_age": factor}


def _case_no_known_full_collision(work: Path) -> dict:
    """Document — do not attempt to find — that no public full-SHA-256
    collision is known."""
    return {"actual_exit": 0, "stdout": "", "stderr": "",
            "ok": True,
            "notes": _SHA256_NO_KNOWN_COLLISION}


def _trunc16(x: bytes) -> int:
    """Take SHA-256 then truncate to the leading 16 bits."""
    digest = hashlib.sha256(x).digest()
    return (digest[0] << 8) | digest[1]


def _case_trunc16_collision_demo(work: Path) -> dict:
    """Birthday-attack a 16-bit truncation: O(2^8) ≈ 256 trials.

    We bound the loop at 100k inputs — astronomically more than needed,
    so the test is reliable even on a slow box. We use cryptographic
    randomness to avoid any seed dependence."""
    seen: dict[int, bytes] = {}
    pair: tuple[bytes, bytes] | None = None
    for i in range(100_000):
        x = secrets.token_bytes(32)
        h = _trunc16(x)
        if h in seen and seen[h] != x:
            pair = (seen[h], x)
            break
        seen[h] = x

    ok = pair is not None
    if pair is None:
        return {"actual_exit": 1, "stdout": "", "stderr": "",
                "ok": False,
                "notes": "Did not find a 16-bit-truncation collision in 100k "
                         "trials — astronomically improbable; check RNG."}
    a, b = pair
    ha = hashlib.sha256(a).hexdigest()
    hb = hashlib.sha256(b).hexdigest()
    notes = (
        f"Found a 16-bit-truncation collision in {len(seen)} trials.\n"
        f"  input A = {a.hex()}\n"
        f"  input B = {b.hex()}\n"
        f"  SHA-256(A) = {ha}\n"
        f"  SHA-256(B) = {hb}\n"
        f"  truncated-16 = 0x{_trunc16(a):04x} = 0x{_trunc16(b):04x}\n\n"
        "Conclusion: do NOT truncate the SHA-256 fact hash for storage or "
        "lookup. dotbio v0 stores the full digest in facts/<2>/<rest>.json "
        "(2-char prefix + 62-char rest = 64 hex = full 256 bits)."
    )
    return {"actual_exit": 0, "stdout": "", "stderr": "",
            "ok": ok, "notes": notes,
            "trials_to_collision": len(seen)}


def _case_dotbio_uses_full_hash(work: Path) -> dict:
    """Confirm that dotbio's CAS layer stores the full 256-bit digest by
    inspecting an existing example bundle's facts/ tree."""
    repo_root = Path(__file__).resolve().parents[4]
    example = repo_root / "examples" / "real-na12878" / "output.bio" / "facts"
    if not example.is_dir():
        return {"actual_exit": 1, "stdout": "", "stderr": "",
                "ok": False,
                "notes": f"Example bundle facts dir not found: {example}"}
    samples: list[tuple[str, int]] = []
    for prefix in example.iterdir():
        if not prefix.is_dir():
            continue
        for fact in prefix.glob("*.json"):
            digest = prefix.name + fact.stem
            samples.append((digest, len(digest) * 4))  # hex char = 4 bits
            break
        if samples:
            break
    if not samples:
        return {"actual_exit": 1, "stdout": "", "stderr": "",
                "ok": False, "notes": "No facts found in example bundle."}
    digest, bits = samples[0]
    ok = bits == 256 and len(digest) == 64
    return {"actual_exit": 0, "stdout": "", "stderr": "",
            "ok": ok,
            "notes": f"Sample fact digest: {digest!r} ({bits} bits, "
                     f"{len(digest)} hex chars). Full 256-bit storage = OK."}


CASES: list[FuzzCase] = [
    FuzzCase("hs01", "hashes", "full SHA-256 collision is computationally infeasible",
             "Quantify the birthday-bound work and confirm > age of universe.",
             "infeasibility_proof", (0,), _case_full_sha256_infeasibility),
    FuzzCase("hs02", "hashes", "no public full-SHA-256 collision known (as of 2026-05-09)",
             "Document the reference; do not attempt an attack.",
             "infeasibility_proof", (0,), _case_no_known_full_collision),
    FuzzCase("hs03", "hashes", "16-bit truncation collides quickly (birthday demo)",
             "Illustration of why we MUST NOT truncate the content-address.",
             "successful_handling", (0,), _case_trunc16_collision_demo),
    FuzzCase("hs04", "hashes", "dotbio bundles store the full 256-bit digest",
             "Sanity check on the example bundle's CAS layer.",
             "successful_handling", (0,), _case_dotbio_uses_full_hash),
]


def build_cases() -> list[FuzzCase]:
    return list(CASES)
