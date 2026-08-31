"""SBOM generation (hardening plan SS26): SPDX 2.3 JSON, stdlib only.

Every release can state exactly what it is built from: the runtime
package, its one cryptographic dependency, and the interpreter.
Deterministic given `now` (injected clock, SS39).
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

from . import PROTOCOL_VERSION, __version__

SPDX_VERSION = "SPDX-2.3"
LICENSE = "MIT"
NAMESPACE = "https://github.com/dansya-arsana/runtime-2066"


def _dependency_version(name: str) -> str:
    try:
        from importlib.metadata import version
        return version(name)
    except Exception:  # noqa: BLE001 — metadata is optional at runtime
        return "unknown"


def _text_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build_sbom(now: datetime | None = None,
               tree: Path | None = None) -> dict:
    """SPDX 2.3 document for this runtime tree (default: the installed
    or checkout copy containing this module)."""
    now = now or datetime.now(timezone.utc)
    tree = Path(tree) if tree else Path(__file__).resolve().parents[1]
    runtime_files = sorted(tree.glob("*.py"))
    verification = hashlib.sha256()
    for path in runtime_files:
        verification.update(path.name.encode("utf-8"))
        verification.update(_text_sha256(path).encode("ascii"))
    document_id = ("SPDXRef-DOCUMENT-" + hashlib.sha256(
        f"{__version__}/{PROTOCOL_VERSION}".encode()).hexdigest()[:16])

    packages = [
        {
            "SPDXID": "SPDXRef-Package-runtime2066",
            "name": "runtime-2066",
            "versionInfo": __version__,
            "downloadLocation": f"{NAMESPACE}#v{__version__}",
            "licenseConcluded": LICENSE,
            "licenseDeclared": LICENSE,
            "copyrightText": "2026 2066 contributors",
            "primaryPackagePurpose": "APPLICATION",
            "summaryText": "AI-native semantic execution runtime",
            "externalRefs": [{
                "referenceCategory": "PERSISTENT-ID",
                "referenceType": "https://2066.dev/protocol",
                "referenceLocator": PROTOCOL_VERSION,
            }],
            "packageVerificationCode": {
                "packageVerificationCodeValue":
                    verification.hexdigest(),
            },
        },
        {
            "SPDXID": "SPDXRef-Package-cryptography",
            "name": "cryptography",
            "versionInfo": _dependency_version("cryptography"),
            "downloadLocation": ("https://pypi.org/project/"
                                 "cryptography/"),
            "licenseConcluded": "Apache-2.0 OR BSD-3-Clause",
            "licenseDeclared": "Apache-2.0 OR BSD-3-Clause",
            "primaryPackagePurpose": "LIBRARY",
            "summaryText": "ed25519 signing for identities and grants "
                           "(isolated behind runtime/identity.py)",
        },
        {
            "SPDXID": "SPDXRef-Package-python",
            "name": "CPython",
            "versionInfo": _dependency_version("Python"),
            "downloadLocation": "https://python.org",
            "licenseConcluded": "PSF-2.0",
            "licenseDeclared": "PSF-2.0",
            "primaryPackagePurpose": "FRAMEWORK",
        },
    ]
    return {
        "spdxVersion": SPDX_VERSION,
        "dataLicense": "CC0-1.0",
        "SPDXID": "SPDXRef-DOCUMENT",
        "name": f"runtime-2066-{__version__}",
        "documentNamespace": f"{NAMESPACE}/spdx/{__version__}",
        "creationInfo": {
            "created": now.astimezone(timezone.utc)
            .isoformat(timespec="seconds"),
            "creators": ["Tool: 2066-sbom"],
        },
        "documentDescribes": [p["SPDXID"] for p in packages],
        "packages": packages,
    }


def render_sbom(sbom: dict) -> str:
    return json.dumps(sbom, indent=1, sort_keys=True) + "\n"
