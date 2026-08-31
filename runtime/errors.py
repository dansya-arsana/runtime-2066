"""Structured error protocol (spec/errors.md).

Errors are designed for agents (roadmap §13): a stable code, the node and
operation involved, expected vs received types, and machine-usable repair
suggestions. Rendering is deterministic — the same error object always
renders to the same text and JSON.
"""

from __future__ import annotations

import json
from dataclasses import dataclass


@dataclass
class StructuredError(Exception):
    """A deterministic, machine-readable 2066 error."""

    code: str
    detail: str | None = None
    line: int | None = None
    node: str | None = None
    operation: str | None = None
    expected: dict[str, str] | None = None
    received: dict[str, str] | None = None
    allowed_repairs: list[str] | None = None

    def to_dict(self) -> dict:
        out: dict = {"code": self.code}
        for key in ("node", "operation", "line", "detail"):
            value = getattr(self, key)
            if value is not None:
                out[key] = value
        if self.expected:
            out["expected"] = dict(self.expected)
        if self.received:
            out["received"] = dict(self.received)
        if self.allowed_repairs:
            out["allowed_repairs"] = list(self.allowed_repairs)
        return out

    def render(self) -> str:
        lines = [f"ERROR {self.code}", ""]
        meta = []
        if self.node is not None:
            meta.append(f"node: {self.node}")
        if self.operation is not None:
            meta.append(f"operation: {self.operation}")
        if self.line is not None:
            meta.append(f"line: {self.line}")
        lines.extend(meta)
        if meta:
            lines.append("")
        if self.expected:
            lines.append("expected:")
            lines.extend(f"  {k}: {v}" for k, v in self.expected.items())
            lines.append("")
        if self.received:
            lines.append("received:")
            lines.extend(f"  {k}: {v}" for k, v in self.received.items())
            lines.append("")
        if self.detail is not None:
            lines.append(f"detail: {self.detail}")
            lines.append("")
        if self.allowed_repairs:
            lines.append("allowed_repairs:")
            lines.extend(f"  - {r}" for r in self.allowed_repairs)
            lines.append("")
        while lines and lines[-1] == "":
            lines.pop()
        return "\n".join(lines) + "\n"

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True)


def exit_code_for(code: str) -> int:
    """Process exit code: 1 parse/validation (E1xx/E2xx), 2 runtime
    (E3xx/E5xx data), 4 authority denial (E4xx), 1 proposal trust (E6xx)."""
    family = {"1": 1, "2": 1, "3": 2, "4": 4, "5": 2, "6": 1}
    return family.get(code[1], 2)
