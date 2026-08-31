"""2066 KEY v1 — turn any removable disk (even an old flashdisk) into a
human authority key (roadmap §31–§33, software-defined preparation).

Design posture, stated honestly (spec/hardware-key.md):

- The disk is a BEARER object: possession grants authority. Like a house
  key, stealing the object defeats it. A flashdisk has no secure element,
  so the secret is PIN-encrypted at rest (AES-256-GCM via HKDF), which
  stops casual copying of a plain file but not imaging of the whole disk.
- Attempt limiting is BEST-EFFORT: after 8 wrong PINs the key destroys
  itself. An attacker who images the disk first can reset the counter —
  documented, not hidden.
- The format is deliberately the same envelope a secure element would
  expose (identity + signing), so a FIDO2/secure-element key can later
  present the same interface (Phase 10) without changing callers.

Directory layout created on the disk (non-destructive — existing files
on the disk are untouched):

    <disk>/.2066key/
        KEYFORMAT    magic + version + created (plain, identifies the disk)
        identity.json  public identity (agent_id, algorithm, public_key)
        secret.enc     salt(16) + nonce(12) + AESGCM(PIN-derived)(seed)
        attempts       decimal wrong-PIN counter
"""

from __future__ import annotations

import getpass
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from . import identity
from .parser import FORMAT_VERSION

MAGIC = "2066KEY1"
KEY_DIR = ".2066key"
MAX_ATTEMPTS = 8
_KDF_INFO = b"2066-key-v1"


class KeyError_(Exception):
    """Raised for every keydisk failure; message is user-facing."""


def _key_dir(disk: Path) -> Path:
    return disk / KEY_DIR


def is_key(disk_path: str | Path) -> bool:
    return (_key_dir(Path(disk_path)) / "KEYFORMAT").exists()


def check_safe_target(disk: Path, force: bool = False) -> None:
    """Refuse obviously catastrophic format targets."""
    resolved = disk.resolve()
    if resolved == Path(resolved.anchor):  # a filesystem root (C:\, /)
        # formatting a drive ROOT is the intended use for removable media,
        # but never the system drive
        if str(resolved.anchor).lower().startswith("c:"):
            raise KeyError_("refusing to place a key on the system drive")
        if not force and not _looks_removable(resolved):
            raise KeyError_(
                f"{resolved} does not look removable; pass --force if you "
                f"really want a key here")
    if resolved == Path.home():
        raise KeyError_("refusing to format the home directory")
    if not resolved.exists() or not resolved.is_dir():
        raise KeyError_(f"{disk} is not an existing directory/mount")


def _looks_removable(resolved: Path) -> bool:
    """Heuristic: Windows drive roots D..Z are typically removable/extra."""
    anchor = str(resolved.anchor)
    if len(anchor) >= 2 and anchor[1] == ":":
        return anchor[0].upper() not in ("C",)
    return False  # non-Windows roots need --force


def format_key(disk_path: str | Path, human_id: str, pin: str,
               force: bool = False) -> dict:
    """Initialize (or reinitialize) a disk as a 2066 key. NON-destructive
    to other files on the disk; overwrites any previous key."""
    disk = Path(disk_path)
    check_safe_target(disk, force)
    directory = _key_dir(disk)
    directory.mkdir(parents=True, exist_ok=True)

    ident, seed_hex = identity.generate_identity(human_id)
    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(pin, salt)
    ciphertext = AESGCM(key).encrypt(nonce, seed_hex.encode("ascii"), None)

    (directory / "KEYFORMAT").write_text(
        f"{MAGIC}\nversion: 1\ncreated: "
        f"{datetime.now(timezone.utc).isoformat(timespec='seconds')}\n"
        f"agent_id: {ident.agent_id}\n", encoding="utf-8")
    (directory / "identity.json").write_text(json.dumps({
        "agent_id": ident.agent_id,
        "algorithm": ident.algorithm,
        "public_key": ident.public_key,
        "created": ident.created,
    }, indent=2) + "\n", encoding="utf-8")
    (directory / "secret.enc").write_bytes(salt + nonce + ciphertext)
    (directory / "attempts").write_text("0", encoding="utf-8")
    return {"agent_id": ident.agent_id, "path": str(directory)}


def inspect_key(disk_path: str | Path) -> dict:
    directory = _key_dir(Path(disk_path))
    fmt = directory / "KEYFORMAT"
    if not fmt.exists():
        raise KeyError_(f"no 2066 key found at {directory}")
    lines = fmt.read_text(encoding="utf-8").splitlines()
    if not lines or lines[0] != MAGIC:
        raise KeyError_("KEYFORMAT magic mismatch — not a 2066 key")
    payload = json.loads((directory / "identity.json").read_text("utf-8"))
    attempts = (directory / "attempts").read_text("utf-8").strip()
    return {"identity": payload, "wrong_pin_attempts": int(attempts),
            "remaining": max(0, MAX_ATTEMPTS - int(attempts))}


def unlock(disk_path: str | Path, pin: str) -> tuple[identity.Identity, str]:
    """Verify the PIN and return (public identity, secret seed hex).

    Wrong PINs increment the counter; MAX_ATTEMPTS wrong attempts destroy
    the secret (self-incineration). Best-effort only — see module docstring.
    """
    directory = _key_dir(Path(disk_path))
    blob = directory / "secret.enc"
    if not blob.exists():
        raise KeyError_("key destroyed (no secret present) — reformat needed")
    info = inspect_key(disk_path)
    raw = blob.read_bytes()
    salt, nonce, ciphertext = raw[:16], raw[16:28], raw[28:]
    key = _derive_key(pin, salt)
    try:
        seed_hex = AESGCM(key).decrypt(nonce, ciphertext, None).decode("ascii")
        identity.load_secret_key({"agent_id": info["identity"]["agent_id"],
                                  "algorithm": "ed25519",
                                  "secret_key": seed_hex})
    except Exception:
        attempts = int((directory / "attempts").read_text("utf-8")) + 1
        (directory / "attempts").write_text(str(attempts), "utf-8")
        if attempts >= MAX_ATTEMPTS:
            blob.unlink()
            raise KeyError_(
                f"key destroyed after {MAX_ATTEMPTS} wrong PIN attempts")
        raise KeyError_(
            f"wrong PIN ({attempts}/{MAX_ATTEMPTS} attempts used)")
    (directory / "attempts").write_text("0", encoding="utf-8")
    ident = identity.parse_identity(info["identity"])
    return ident, seed_hex


def prompt_pin(confirm: bool = True) -> str:
    pin = getpass.getpass("key PIN: ")
    if not pin:
        raise KeyError_("empty PIN")
    if confirm:
        again = getpass.getpass("confirm PIN: ")
        if again != pin:
            raise KeyError_("PINs do not match")
    return pin


_ROTATION_LOG = "rotation.log"


def _next_agent_id(agent_id: str) -> str:
    """Successive generation names: human-1 -> human-1#2 -> human-1#3."""
    match = re.match(r"^(.*)#(\d+)$", agent_id)
    if match:
        return f"{match.group(1)}#{int(match.group(2)) + 1}"
    return f"{agent_id}#2"


def _atomic_write(path: Path, data: bytes) -> None:
    """Write-then-replace so a crash never leaves a truncated file."""
    temp = path.with_name(path.name + ".tmp")
    temp.write_bytes(data)
    os.replace(temp, path)


def rotate_key(disk_path: str | Path, old_pin: str, new_pin: str,
               agent_id: str | None = None) -> dict:
    """Rotate the key: a NEW keypair re-encrypted under a NEW PIN.

    The old PIN must unlock the current secret first (wrong PINs count
    against the self-destruct budget as usual). The OLD public key is
    appended to `.2066key/rotation.log` so verifiers holding history can
    see the lineage; pins of the old key keep verifying files it signed
    in the past, while new approvals carry the new key.

    Returns {"old_agent_id", "new_agent_id", "old_public_key",
             "new_public_key", "rotation_log"}.
    """
    if not new_pin:
        raise KeyError_("empty new PIN")
    ident, _seed = unlock(disk_path, old_pin)  # verifies the old PIN
    directory = _key_dir(Path(disk_path))
    new_id = agent_id or _next_agent_id(ident.agent_id)
    new_ident, new_seed = identity.generate_identity(new_id)

    salt = os.urandom(16)
    nonce = os.urandom(12)
    key = _derive_key(new_pin, salt)
    ciphertext = AESGCM(key).encrypt(nonce, new_seed.encode("ascii"), None)

    # preserve the original creation date in KEYFORMAT
    created = datetime.now(timezone.utc).isoformat(timespec="seconds")
    fmt = directory / "KEYFORMAT"
    if fmt.exists():
        for line in fmt.read_text(encoding="utf-8").splitlines():
            if line.startswith("created:"):
                created = line.split(":", 1)[1].strip()
                break

    _atomic_write(directory / "secret.enc", salt + nonce + ciphertext)
    _atomic_write(
        directory / "identity.json",
        (json.dumps({"agent_id": new_ident.agent_id,
                     "algorithm": new_ident.algorithm,
                     "public_key": new_ident.public_key,
                     "created": new_ident.created}, indent=2)
         + "\n").encode("utf-8"))
    _atomic_write(
        directory / "KEYFORMAT",
        (f"{MAGIC}\nversion: 1\ncreated: {created}\n"
         f"rotated: {datetime.now(timezone.utc).isoformat(timespec='seconds')}"
         f"\nagent_id: {new_ident.agent_id}\n").encode("utf-8"))
    _atomic_write(directory / "attempts", b"0")

    record = {
        "timestamp": datetime.now(timezone.utc).isoformat(
            timespec="seconds"),
        "from_agent_id": ident.agent_id,
        "from_public_key": ident.public_key,
        "to_agent_id": new_ident.agent_id,
        "to_public_key": new_ident.public_key,
    }
    log = directory / _ROTATION_LOG
    existing = b"" if not log.exists() else log.read_bytes()
    _atomic_write(log, existing + json.dumps(record, sort_keys=True)
                  .encode("utf-8") + b"\n")
    return {"old_agent_id": ident.agent_id, "new_agent_id": new_ident.agent_id,
            "old_public_key": ident.public_key,
            "new_public_key": new_ident.public_key,
            "rotation_log": str(log)}


def _derive_key(pin: str, salt: bytes) -> bytes:
    return HKDF(algorithm=hashes.SHA256(), length=32, salt=salt,
                info=_KDF_INFO).derive(pin.encode("utf-8"))
