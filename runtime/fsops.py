"""Effectful operations, shared by both adapters (Phase 3–4).

Filesystem calls are capability-checked by the runtime before any effect
happens (§4.3 Rule 3, §17). Default deny: `grants=None` means no authority
exists at all — even reading an existing file is denied (§20 forbidden
defaults). Denials are structured errors (E401/E402/E403, exit code 4);
IO failures are E305.

Stdio calls (`read_line`/`write_str`) are SYSTEM effects with an implicit
grant — like `emit`, they are the program's own input/output channels and
carry no authority over shared resources.
"""

from __future__ import annotations

import sys
from datetime import datetime

from .capabilities import GrantSet, normalize_path
from .errors import StructuredError


def read_file(grants: GrantSet | None, node_id: str, path_value: str,
              now: datetime | None) -> str:
    op = "filesystem.read"
    _require_authority(grants, node_id, op)
    path = normalize_path(path_value)
    capability = grants.check(op, path, now, node=node_id)
    try:
        with open(path, "rb") as handle:
            data = handle.read()
    except OSError as exc:
        raise _io_error(node_id, op, path, exc) from exc
    if capability.max_bytes is not None and len(data) > capability.max_bytes:
        grants.check(op, path, now, nbytes=len(data), node=node_id)  # E403
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _io_error(node_id, op, path, exc) from exc


def write_file(grants: GrantSet | None, node_id: str, path_value: str,
               content: str, now: datetime | None) -> int:
    op = "filesystem.write"
    _require_authority(grants, node_id, op)
    path = normalize_path(path_value)
    encoded = content.encode("utf-8")
    # scope + expiry + size limit are all checked BEFORE anything is written
    grants.check(op, path, now, nbytes=len(encoded), node=node_id)
    try:
        with open(path, "wb") as handle:
            handle.write(encoded)
    except OSError as exc:
        raise _io_error(node_id, op, path, exc) from exc
    return len(encoded)


def _require_authority(grants: GrantSet | None, node_id: str, op: str) -> None:
    if grants is None:
        raise StructuredError(
            code="E401", node=node_id, operation=op,
            detail="denied: no capability system attached; "
                   "effects require explicit grants (default deny)",
        )


def _io_error(node_id: str, op: str, path: str, exc: Exception) -> StructuredError:
    return StructuredError(
        code="E305", node=node_id, operation=op,
        detail=f"filesystem error on {path}: {exc}",
    )


def read_line(node_id: str) -> str:
    """`system.read`: one line from stdin (no trailing newline); EOF -> \"\"."""
    line = sys.stdin.readline()
    if line == "":
        return ""  # EOF is total, not an error
    return line[:-1] if line.endswith("\n") else line


def write_str(node_id: str, text: str) -> int:
    """`system.write`: immediate stdout write; returns characters written."""
    return sys.stdout.write(text)


def concat(a: str, b: str) -> str:
    return a + b
