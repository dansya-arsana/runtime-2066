"""Session capabilities (roadmap §4.6, §18): short-lived signed tokens that
bind a subject identity.

Layering is deliberate: programs CANNOT mint tokens (no such op exists —
agents cannot mint authority). The trusted host (the app shell) mints a
token after the engine validates credentials; programs verify tokens via
the `session.verify` op against a runtime-attached public key. Forging a
token requires the server's secret key.

Token format: base64url(canonical_json(payload)) "." hex(ed25519 signature
over those exact bytes). The payload carries the bound subject, an
optional scope, issue/expiry timestamps, and a token id.
"""

from __future__ import annotations

import base64
import binascii
import json
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from . import identity
from .capabilities import parse_timestamp
from .errors import StructuredError

DEFAULT_TTL_MINUTES = 30


class SessionRegistry:
    """The host's memory of minted tokens, so "logout" can revoke ALL
    outstanding sessions for a subject — not just discard the client's
    copy. Backed by a JSON file; the mint path registers, revoke kills.
    Register/revoke are read-modify-write cycles, so they serialize on a
    process-wide lock (parallel logins were dropping registrations).
    """

    _lock = threading.Lock()

    def __init__(self, path: str):
        self.path = Path(path)
        if not self.path.exists():
            self.path.write_text("{}", encoding="utf-8")

    def register(self, subject_id: int, token_id: str) -> None:
        with self._lock:
            data = self._load()
            data.setdefault(str(subject_id), []).append(token_id)
            self._save(data)

    def revoke_all_for(self, subject_id: int) -> list[str]:
        """Revoke every outstanding token_id of the subject. Returns the
        revoked token ids (for the caller to chain into a revocation log)."""
        with self._lock:
            data = self._load()
            ids = data.pop(str(subject_id), [])
            self._save(data)
        return ids

    def outstanding(self, subject_id: int) -> list[str]:
        return list(self._load().get(str(subject_id), []))

    def _load(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        self.path.write_text(json.dumps(data, indent=1, sort_keys=True),
                             encoding="utf-8")


def _b64encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64decode(text: str) -> bytes:
    padding = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + padding)


class SessionVerifier:
    """Runtime-attached public key — the authority for session tokens.
    An optional revocation list kills stolen tokens before expiry."""

    def __init__(self, public_key: str, revocations: object | None = None):
        self.public_key = public_key
        self.revocations = revocations

    @classmethod
    def from_identity_file(cls, path: str) -> "SessionVerifier":
        import json
        with open(path, "r", encoding="utf-8") as handle:
            parsed = identity.parse_identity(json.load(handle))
        return cls(public_key=parsed.public_key)

    def verify(self, node_id: str, token: str,
               now: datetime | None = None) -> int:
        """Validate a session token; return the bound subject id.

        Fail closed: malformed token (E406), bad signature (E406), or an
        expired token (E407) all raise; there is no anonymous fallback.
        """
        if not isinstance(token, str) or token.count(".") != 1:
            raise self._denied(node_id, "malformed session token")
        body_b64, signature_hex = token.split(".")
        try:
            body = _b64decode(body_b64)
            payload = json.loads(body.decode("utf-8"))
            subject = int(payload["subject_id"])
            expires_raw = payload["expires"]
        except (binascii.Error, UnicodeDecodeError, ValueError, KeyError,
                json.JSONDecodeError) as exc:
            raise self._denied(node_id, f"malformed session token: {exc}")
        if not identity.verify(self.public_key, signature_hex, body):
            raise self._denied(node_id, "session token signature FAILED")
        if self.revocations is not None and self.revocations.is_revoked(
                payload.get("token_id", "")):
            raise self._denied(node_id, "session token has been REVOKED")
        moment = now if now is not None else datetime.now(timezone.utc)
        expires = parse_timestamp(expires_raw)
        if moment > expires:
            raise StructuredError(
                code="E407", node=node_id, operation="session.verify",
                detail=f"session expired at {expires_raw}",
            )
        return subject

    def _denied(self, node_id: str, detail: str) -> StructuredError:
        return StructuredError(
            code="E406", node=node_id, operation="session.verify",
            detail=f"denied: {detail}",
        )


def mint_session_token(secret_hex: str, subject_id: int, *,
                       ttl_minutes: int = DEFAULT_TTL_MINUTES,
                       scope: str = "", now: datetime | None = None) -> str:
    """Host-side token minting (the one place authority is granted).

    The secret key stays in the trusted host; programs and users only ever
    see the resulting token string.
    """
    import json
    moment = now if now is not None else datetime.now(timezone.utc)
    issued_at = moment.isoformat(timespec="seconds")
    expires = (moment + timedelta(minutes=ttl_minutes)).isoformat(
        timespec="seconds")
    payload = {
        "subject_id": int(subject_id),
        "scope": scope,
        "issued_at": issued_at,
        "expires": expires,
        "token_id": identity.canonical_json(
            {"s": int(subject_id), "i": issued_at}).hex()[:16],
    }
    body = identity.canonical_json(payload)
    body_b64 = _b64encode(body)
    # sign the raw canonical bytes; verify() decodes b64 back to the same bytes
    signature = identity.sign(secret_hex, body)
    return f"{body_b64}.{signature}"
