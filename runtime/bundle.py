"""Offline update bundles (plan SS24): sovereign distribution.

A bundle is a directory carrying everything an air-gapped machine needs
to adopt a release — semantic programs, policies, the SBOM, and the
SIGNED release manifest — plus a bundle manifest hashing every file.

Installation order is exactly the plan's:

    verify signature -> verify hashes -> (human approves) -> install
    -> evidence record

`install_bundle` refuses on any hash mismatch or bad signature (fail
closed), and appends an evidence event recording WHAT was installed
(from which release hash) so the machine's own audit chain answers
"what am I running?".
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

from .backup import _sha256, create_backup, verify_backup
from .release import verify_release

BUNDLE_MANIFEST = "bundle.json"
BUNDLE_FORMAT = 1


def pack_bundle(out_dir: Path, programs: Path, policies: Path,
                release_path: Path | None = None,
                sbom_path: Path | None = None,
                now: datetime | None = None) -> dict:
    """Assemble programs + policies (+ signed release + SBOM) into a
    verifiable offline bundle."""
    out_dir = Path(out_dir)
    now = now or datetime.now(timezone.utc)
    sources = []
    for root, prefix in ((programs, "programs"), (policies, "policies")):
        root = Path(root)
        if not root.is_dir():
            raise FileNotFoundError(f"bundle source missing: {root}")
        for path in sorted(root.rglob("*")):
            if path.is_file():
                sources.append(
                    (f"{prefix}/{path.relative_to(root).as_posix()}", path))
    if release_path is not None:
        sources.append(("release.json", Path(release_path)))
    if sbom_path is not None:
        sources.append(("sbom.json", Path(sbom_path)))
    create_backup(out_dir, sources, now=now)  # secrets refused, hashes

    bundle = {
        "bundle_format": BUNDLE_FORMAT,
        "kind": "2066-update-bundle",
        "packed_utc": now.astimezone(timezone.utc)
        .isoformat(timespec="seconds"),
        "files_sha256": {
            rel: _sha256(out_dir / rel)
            for rel in json.loads(
                (out_dir / "manifest.json").read_text(encoding="utf-8"))
            ["files"]},
        "release": "release.json" if release_path else None,
        "sbom": "sbom.json" if sbom_path else None,
    }
    (out_dir / BUNDLE_MANIFEST).write_text(
        json.dumps(bundle, indent=1, sort_keys=True) + "\n",
        encoding="utf-8")
    return bundle


def verify_bundle(bundle_dir: Path, release_identity_path: Path | None,
                  tree: Path | None = None) -> dict:
    """SS24 install order step 1+2: signature, then every hash."""
    bundle_dir = Path(bundle_dir)
    problems: list[str] = []
    try:
        bundle = json.loads((bundle_dir / BUNDLE_MANIFEST)
                            .read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"ok": False,
                "problems": [f"unreadable bundle manifest: {exc}"]}
    if bundle.get("bundle_format") != BUNDLE_FORMAT:
        return {"ok": False,
                "problems": [f"unknown bundle format "
                             f"{bundle.get('bundle_format')!r}"]}
    content = verify_backup(bundle_dir)          # hashes every file
    problems.extend(content.get("problems", []))

    release_info = {"verified": False}
    if bundle.get("release"):
        if release_identity_path is None:
            problems.append("bundle carries a signed release but no "
                            "--agent identity was given to verify it")
        else:
            from .identity import parse_identity
            issuer = parse_identity(json.loads(
                Path(release_identity_path).read_text(encoding="utf-8")))
            envelope = json.loads((bundle_dir / "release.json")
                                  .read_text(encoding="utf-8"))
            result = verify_release(envelope, issuer.public_key,
                                    tree=tree)
            problems.extend(f"release: {p}" for p in result["problems"])
            release_info = {"verified": result["ok"],
                            "runtime_version": result.get(
                                "runtime_version"),
                            "protocol_version": result.get(
                                "protocol_version")}
    return {"ok": not problems, "problems": problems,
            "files": len(bundle.get("files_sha256", {})),
            "release": release_info}


def install_bundle(bundle_dir: Path, to_programs: Path,
                   to_policies: Path, evidence_log_path: Path | None,
                   release_identity_path: Path | None,
                   tree: Path | None = None) -> dict:
    """Verify EVERYTHING; only then install programs+policies; record
    what was installed into the evidence chain."""
    verification = verify_bundle(bundle_dir, release_identity_path, tree)
    if not verification["ok"]:
        return {"installed": False, **verification}
    bundle_dir = Path(bundle_dir)
    bundle = json.loads((bundle_dir / BUNDLE_MANIFEST)
                        .read_text(encoding="utf-8"))
    installed = {"programs": 0, "policies": 0}
    for rel in sorted(bundle.get("files_sha256", {})):
        source = bundle_dir / rel
        if rel.startswith("programs/"):
            target = Path(to_programs) / rel[len("programs/"):]
            installed["programs"] += 1
        elif rel.startswith("policies/"):
            target = Path(to_policies) / rel[len("policies/"):]
            installed["policies"] += 1
        else:
            continue  # release.json / sbom.json stay with the bundle
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    release = verification["release"]
    if evidence_log_path is not None:
        from .evidence import EvidenceLog
        EvidenceLog(str(evidence_log_path)).append(
            "release.install", "bundle",
            f"files={sum(installed.values())} "
            f"runtime={release.get('runtime_version')} "
            f"protocol={release.get('protocol_version')} "
            f"verified_signature={release.get('verified')}")
    return {"installed": True, **verification, "counts": installed}
