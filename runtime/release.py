"""Signed release manifests (hardening plan SS28): "no production
binary should be trusted solely because it came from a website".

A release object binds, by hash, WHAT the runtime is:

    release {
        protocol_version, runtime_version,
        files: {runtime module -> sha256},
        conformance_corpus: sha256,
        spec: {spec file -> sha256},
        created_utc, released_by
    }

The envelope is the same signed-envelope format as capability grants
(ed25519 over the canonical payload). `verify-release` re-verifies the
signature AND recomputes the tree: a matching release proves the tree
you are running is the tree that was released — file by file.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

from . import PROTOCOL_VERSION, __version__
from . import identity as identity_mod
from .capabilities import sign_capabilities, verify_envelope

RELEASE_FORMAT = 1


def _tree_root(tree: Path | None) -> Path:
    return Path(tree) if tree else Path(__file__).resolve().parents[1]


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def build_release(now: datetime | None = None,
                  tree: Path | None = None) -> dict:
    """Hash the runtime tree + normative corpus/spec into a release
    payload (unsigned until wrapped by the caller)."""
    now = now or datetime.now(timezone.utc)
    root = _tree_root(tree)

    files = {f"runtime/{p.name}": _sha256(p)
             for p in sorted((root / "runtime").glob("*.py"))}
    corpus = root / "protocol" / "conformance" / "corpus.json"
    spec = {f"spec/{p.name}": _sha256(p)
            for p in sorted((root / "spec").glob("*.md"))}
    payload = {
        "release_format": RELEASE_FORMAT,
        "protocol_version": PROTOCOL_VERSION,
        "runtime_version": __version__,
        "created_utc": now.astimezone(timezone.utc)
        .isoformat(timespec="seconds"),
        "files": files,
        "spec": spec,
    }
    if corpus.exists():
        payload["conformance_corpus"] = _sha256(corpus)
    return payload


def sign_release(payload: dict, issuer, secret_hex: str) -> dict:
    """Wrap a release payload in the standard signed envelope."""
    return sign_capabilities(payload, issuer, secret_hex,
                             payload["created_utc"])


def verify_release(envelope: dict, issuer_public: str,
                   tree: Path | None = None) -> dict:
    """Verify signature, then recompute the tree against the payload.

    Returns {ok, problems[]}; fail closed — any drift from the released
    hashes is listed, never ignored.
    """
    problems: list[str] = []
    try:
        payload = verify_envelope(envelope, require_signed=True)
    except (ValueError, KeyError) as exc:
        return {"ok": False,
                "problems": [f"signature invalid: {exc}"]}
    released_by = envelope.get("issued_by", {})
    if released_by.get("public_key") != issuer_public:
        problems.append("released by a different identity than the one "
                        "pinned (issuer mismatch)")
    root = _tree_root(tree)

    for rel, expected in sorted(payload.get("files", {}).items()):
        path = root / rel
        if not path.exists():
            problems.append(f"missing: {rel}")
        elif _sha256(path) != expected:
            problems.append(f"drifted: {rel}")
    for rel, expected in sorted(payload.get("spec", {}).items()):
        path = root / rel
        if not path.exists():
            problems.append(f"missing: {rel}")
        elif _sha256(path) != expected:
            problems.append(f"drifted: {rel}")
    corpus_hash = payload.get("conformance_corpus")
    if corpus_hash:
        corpus = root / "protocol" / "conformance" / "corpus.json"
        if not corpus.exists():
            problems.append("missing: protocol/conformance/corpus.json")
        elif _sha256(corpus) != corpus_hash:
            problems.append("drifted: conformance corpus")
    return {"ok": not problems, "problems": problems,
            "runtime_version": payload.get("runtime_version"),
            "protocol_version": payload.get("protocol_version")}


def load_identity_files(identity_path: str, key_path: str):
    """Load an issuer identity + secret from their JSON files."""
    issuer = identity_mod.parse_identity(__import__("json").loads(
        Path(identity_path).read_text(encoding="utf-8")))
    secret_payload = __import__("json").loads(
        Path(key_path).read_text(encoding="utf-8"))
    _, secret_hex = identity_mod.load_secret_key(secret_payload)
    return issuer, secret_hex
