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

import os
import stat
import sys
from datetime import datetime

from .capabilities import GrantSet, normalize_path
from .errors import StructuredError

_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)  # unavailable on some platforms


def _resolve(path_value: str, node_id: str, op: str) -> str:
    """Symlink-aware authorization target: the capability scope must
    cover where the path ACTUALLY points, not where it is spelled
    (a symlink inside an allowed directory cannot smuggle reads/writes
    outside the scope). Returned in the capability scope's canonical
    form (forward slashes) so scope matching stays uniform."""
    normalized = normalize_path(path_value)
    try:
        resolved = os.path.realpath(normalized)
    except OSError as exc:  # pragma: no cover - realpath rarely fails
        raise _io_error(node_id, op, normalized, exc) from exc
    resolved = resolved.replace(os.sep, "/")
    if os.altsep:  # windows may also use '/'
        resolved = resolved.replace(os.altsep, "/")
    return resolved


def _open_regular(resolved: str, node_id: str, op: str, flags: int):
    """Open the RESOLVED path (never the original spelling) refusing a
    swapped-in symlink on the final component, and verify the opened
    object is a regular file — authorization and the open act on the
    same object, with size limits enforced on the SAME handle (no
    check-then-open TOCTOU window)."""
    try:
        fd = os.open(resolved, flags | _NOFOLLOW, 0o644)
    except OSError as exc:
        raise _io_error(node_id, op, resolved, exc) from exc
    try:
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            raise StructuredError(
                code="E305", node=node_id, operation=op,
                detail=f"refusing non-regular file object: {resolved}",
            )
    except OSError:
        os.close(fd)
        raise
    return fd


def read_file(grants: GrantSet | None, node_id: str, path_value: str,
              now: datetime | None) -> str:
    op = "filesystem.read"
    _require_authority(grants, node_id, op)
    resolved = _resolve(path_value, node_id, op)
    capability = grants.check(op, resolved, now, node=node_id)
    fd = _open_regular(resolved, node_id, op, os.O_RDONLY)
    try:
        limit = capability.max_bytes
        if limit is not None:
            # bounded read on the open handle: the size that matters is
            # the size we actually read, from the object we authorized
            data = os.read(fd, limit + 1)
            if len(data) > limit:
                raise grants.check(op, resolved, now, nbytes=len(data),
                                   node=node_id)  # E403
        else:
            data = os.read(fd, 2 ** 62)
    except OSError as exc:
        raise _io_error(node_id, op, resolved, exc) from exc
    finally:
        os.close(fd)
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise _io_error(node_id, op, resolved, exc) from exc


def write_file(grants: GrantSet | None, node_id: str, path_value: str,
               content: str, now: datetime | None) -> int:
    op = "filesystem.write"
    _require_authority(grants, node_id, op)
    resolved = _resolve(path_value, node_id, op)
    encoded = content.encode("utf-8")
    # scope + expiry + size limit all checked BEFORE anything is written,
    # against the symlink-resolved target
    grants.check(op, resolved, now, nbytes=len(encoded), node=node_id)
    fd = _open_regular(resolved, node_id, op,
                       os.O_WRONLY | os.O_CREAT | os.O_TRUNC)
    try:
        os.write(fd, encoded)
    except OSError as exc:
        raise _io_error(node_id, op, resolved, exc) from exc
    finally:
        os.close(fd)
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
