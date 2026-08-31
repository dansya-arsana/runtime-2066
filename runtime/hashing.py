"""Deterministic program identity (roadmap §15, Appendix C.1).

The canonical serialization is the primary artifact; its SHA-256 is the
program's identity for signatures, provenance, and reproducibility.
Because the serializer canonicalizes layout, the hash is insensitive to
comments, whitespace, and field order — source text is a view, the
canonical form is the truth.
"""

from __future__ import annotations

import hashlib

from .parser import Program
from .serialize import serialize_program

ALGORITHM = "sha256"


def program_hash(program: Program) -> str:
    canonical = serialize_program(program).encode("utf-8")
    return f"{ALGORITHM}:{hashlib.sha256(canonical).hexdigest()}"
