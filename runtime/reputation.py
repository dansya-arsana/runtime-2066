"""Reputation ledger (Phase 14): trust computed from verifiable events.

An agent's reputation is NOT what the agent claims — it is what the
runtime OBSERVED. Every reputation-relevant event (a proposal accepted,
a red-team verification failed, a fuzzer crash) is appended to an
append-only JSONL ledger hash-chained exactly like the evidence log
(compare runtime/evidence.py): each record carries a SHA-256 over its
canonical content plus the previous record's hash, so rewriting or
deleting history breaks every subsequent link.

The score is only ever computed by replaying events from the chained
ledger — a tampered ledger is detectable via verify_chain(), and a
self-reported "I am trustworthy" claim has no code path into the score.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

# The closed set of reputation events. Anything else is refused: an
# open event vocabulary invites agents to invent flattering events.
EVENT_TYPES = frozenset({
    "proposal_accepted",
    "proposal_rejected",
    "proposal_conflict",
    "verification_passed",
    "verification_failed",
    "security_finding",
    "fuzz_crash",
})

# Points per event. Merit is asymmetric by design: finding bugs is GOOD
# (a security_finding means someone probed the runtime and reported a
# real flaw), while shipping a program that crashes the runtime is the
# worst outcome — crashes are never acceptable.
SCORES: dict[str, int] = {
    "proposal_accepted": 1,
    "proposal_rejected": -1,
    "proposal_conflict": -2,
    "verification_passed": 1,
    "verification_failed": -2,
    "security_finding": 5,
    "fuzz_crash": -10,
}

GENESIS = "0" * 64


def _record_hash(record: dict) -> str:
    payload = {k: v for k, v in record.items() if k != "hash"}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(body).hexdigest()


class ReputationLedger:
    """Hash-chained, append-only record of agent reputation events."""

    def __init__(self, path: str):
        self.path = Path(path)
        self._seq, self._prev = self._tail()

    # ------------------------------------------------------------------
    # reading

    def _records(self) -> list[dict]:
        if not self.path.exists():
            return []
        records = []
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                records.append(json.loads(line))
        return records

    def _tail(self) -> tuple[int, str]:
        records = self._records()
        if not records:
            return 0, GENESIS
        last = records[-1]
        return int(last["seq"]), last["hash"]

    # ------------------------------------------------------------------
    # writing

    def record(self, agent_id: str, event_type: str, detail: str = "") -> dict:
        """Append one chained event; the record is returned (with hash)."""
        if not agent_id:
            raise ValueError("agent_id must be a non-empty string")
        if event_type not in EVENT_TYPES:
            raise ValueError(
                f"unknown reputation event {event_type!r} "
                f"(allowed: {', '.join(sorted(EVENT_TYPES))})")
        record = {
            "seq": self._seq + 1,
            "timestamp": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "agent_id": agent_id,
            "event_type": event_type,
            "detail": detail,
            "prev_hash": self._prev,
        }
        record["hash"] = _record_hash(record)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, sort_keys=True,
                                    ensure_ascii=False) + "\n")
        self._seq, self._prev = record["seq"], record["hash"]
        return record

    # ------------------------------------------------------------------
    # queries

    def reputation(self, agent_id: str) -> dict:
        """Score computed ONLY from events replayed out of the ledger."""
        breakdown: dict[str, int] = {}
        score = 0
        events = 0
        for record in self._records():
            if record.get("agent_id") != agent_id:
                continue
            events += 1
            event_type = record.get("event_type", "")
            breakdown[event_type] = breakdown.get(event_type, 0) + 1
            score += SCORES.get(event_type, 0)
        return {
            "agent_id": agent_id,
            "score": float(score),
            "breakdown": breakdown,
            "events": events,
        }

    def agents(self) -> list[str]:
        """Every agent with at least one event, sorted."""
        return sorted({record["agent_id"] for record in self._records()})

    def verify_chain(self) -> dict:
        """Walk the chain; report the first broken link (evidence pattern)."""
        records = self._records()
        if not records:
            return {"ok": True, "records": 0, "note": "empty ledger"}
        prev = GENESIS
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
