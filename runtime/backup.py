"""Backup and restore (hardening plan SS60): sovereign state portability.

A backup is a directory of copied state files plus ``manifest.json``
recording each file's SHA-256. Restore verifies EVERY hash first and
copies nothing on any mismatch (fail closed). Private signing keys are
excluded by default and listed in the manifest's ``excluded`` section —
"private signing keys should not be casually included".

Clock is injected (``now``) — no ambient wall-time reads (SS39).
"""

from __future__ import annotations

import hashlib
import shutil
from datetime import datetime, timezone
from pathlib import Path

MANIFEST_NAME = "manifest.json"
FORMAT_VERSION = 1
SECRET_PATTERNS = ("*.key", "*secret*", "*.pem", "secret.enc",
                   "*registry*.json", "*revocation*.jsonl")


def _is_secret(path: Path) -> bool:
    name = path.name.lower()
    return any(path.match(pattern) or pattern in name
               for pattern in SECRET_PATTERNS)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def collect_sources(db: Path | None = None, evidence: Path | None = None,
                    programs: Path | None = None,
                    policies: Path | None = None) -> list[tuple[str, Path]]:
    """Explicit (relative-name, path) pairs — no implicit crawling of
    anything the caller did not name."""
    sources: list[tuple[str, Path]] = []
    if db is not None:
        sources.append((f"data/{db.name}", db))
    if evidence is not None:
        sources.append((f"evidence/{evidence.name}", evidence))
    for root, prefix in ((programs, "programs"), (policies, "policies")):
        if root is None or not Path(root).is_dir():
            continue
        for path in sorted(Path(root).rglob("*")):
            if path.is_file():
                rel = f"{prefix}/{path.relative_to(root).as_posix()}"
                sources.append((rel, path))
    return sources


def create_backup(out_dir: Path, sources: list[tuple[str, Path]],
                  now: datetime | None = None,
                  allow_secrets: bool = False) -> dict:
    """Copy sources into out_dir and write the hash manifest."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    now = now or datetime.now(timezone.utc)
    files: dict[str, str] = {}
    excluded: list[str] = []
    for rel, source in sources:
        source = Path(source)
        if not source.exists():
            raise FileNotFoundError(f"backup source missing: {source}")
        if _is_secret(source) and not allow_secrets:
            excluded.append(rel)
            continue
        target = out_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.resolve() != target.resolve():
            shutil.copyfile(source, target)
        files[rel] = _sha256(target)
    manifest = {
        "format_version": FORMAT_VERSION,
        "tool": "2066-backup",
        "created_utc": now.astimezone(timezone.utc)
        .isoformat(timespec="seconds"),
        "files": files,
        "excluded": sorted(excluded),
        "excluded_reason": "secret-bearing files are never backed up "
                           "by default (plan SS60); relist with "
                           "allow_secrets after explicit approval",
    }
    (out_dir / MANIFEST_NAME).write_text(
        _render(manifest), encoding="utf-8")
    return manifest


def _render(manifest: dict) -> str:
    import json
    return json.dumps(manifest, indent=1, sort_keys=True) + "\n"


def _load_manifest(bundle: Path) -> dict:
    import json
    manifest = json.loads((bundle / MANIFEST_NAME)
                          .read_text(encoding="utf-8"))
    if manifest.get("format_version") != FORMAT_VERSION:
        raise ValueError(f"unsupported backup format "
                         f"{manifest.get('format_version')!r}")
    return manifest


def verify_backup(bundle_dir: Path) -> dict:
    """Verify every recorded hash. Returns {ok, problems, files}."""
    bundle = Path(bundle_dir)
    manifest = _load_manifest(bundle)
    problems = []
    for rel, expected in sorted(manifest.get("files", {}).items()):
        path = bundle / rel
        if not path.exists():
            problems.append(f"missing: {rel}")
        elif _sha256(path) != expected:
            problems.append(f"hash mismatch: {rel}")
    for rel in sorted(manifest.get("excluded", [])):
        if (bundle / rel).exists():
            problems.append(f"secret material present in bundle: {rel}")
    return {"ok": not problems, "problems": problems,
            "files": len(manifest.get("files", {}))}


def restore_backup(bundle_dir: Path, to_dir: Path) -> dict:
    """Verify-then-restore: on ANY problem, copy NOTHING (fail closed)."""
    verification = verify_backup(bundle_dir)
    if not verification["ok"]:
        return verification
    bundle = Path(bundle_dir)
    manifest = _load_manifest(bundle)
    to_dir = Path(to_dir)
    restored = []
    for rel in sorted(manifest.get("files", {})):
        target = to_dir / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(bundle / rel, target)
        restored.append(rel)
    return {"ok": True, "restored": restored,
            "excluded": manifest.get("excluded", [])}
