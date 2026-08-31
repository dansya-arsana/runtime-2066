"""Evidence protocol (roadmap Appendix C.5): a tamper-evident audit trail.

Every privileged action (data write) appends a record to an append-only
JSONL log. Each record carries a SHA-256 over its canonical content AND
the previous record's hash — a hash chain. Editing or deleting any record
breaks every subsequent link, so "critical evidence cannot silently
disappear" (Constitution invariant) holds without any key management:
tampering is detectable by anyone holding the log.

`verify_evidence` walks the chain and reports the first broken link.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


def _record_hash(record: dict) -> str:
    payload = {k: v for k, v in record.items() if k != "hash"}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


class EvidenceLog:
    def __init__(self, path: str, program: str = "", subject: str = ""):
        self.path = Path(path)
        self.program = program
        self.subject = subject
        self._seq, self._prev = self._tail()

    def _tail(self) -> tuple[int, str]:
        if not self.path.exists():
            return 0, "0" * 64  # genesis link
        lines = [line for line in
                 self.path.read_text(encoding="utf-8").splitlines() if line]
        if not lines:
            return 0, "0" * 64
        last = json.loads(lines[-1])
        return int(last["seq"]), last["hash"]

    def append(self, action: str, resource: str, detail: str = "") -> dict:
        record = {
            "seq": self._seq + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "action": action,
            "resource": resource,
            "subject": self.subject,
            "program": self.program,
            "detail": detail,
            "prev_hash": self._prev,
        }
        record["hash"] = _record_hash(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True,
                                    ensure_ascii=False) + "\n")
        self._seq, self._prev = record["seq"], record["hash"]
        return record


def verify_evidence(path: str) -> dict:
    """Walk the chain; report integrity. Any edit breaks a link."""
    file = Path(path)
    if not file.exists():
        return {"ok": False, "error": "no evidence file", "records": 0}
    records = []
    for line in file.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    if not records:
        return {"ok": True, "records": 0, "note": "empty log"}
    prev = "0" * 64
    for index, record in enumerate(records):
        if record.get("prev_hash") != prev:
            return {"ok": False, "records": len(records),
                    "broken_at": index + 1,
                    "reason": "chain link mismatch"}
        if _record_hash(record) != record.get("hash"):
            return {"ok": False, "records": len(records),
                    "broken_at": index + 1,
                    "reason": "record content does not match its hash"}
        prev = record["hash"]
    return {"ok": True, "records": len(records),
            "last": records[-1]["timestamp"]}
