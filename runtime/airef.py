"""Machine-readable 2066 reference for AI agents (docs/ai/).

Generated from the live runtime tables so it cannot drift: `python -m
runtime reference` emits the operations, types, effects, and error codes
exactly as this build implements them. A committed snapshot lives at
docs/ai/reference.json, and a test fails if the snapshot goes stale —
the docs-for-AI are compiled, not written.
"""

from __future__ import annotations

from .validator import EFFECT_OF, _OPS

# Per-operation machine reference. `out` describes the result type;
# "cap" is the capability action required at runtime (None = implicit/no
# grant). Cross-checked against validator._OPS by tests.
_OPS_REFERENCE = [
    {"op": "const", "effect": "PURE", "inputs": 0, "out": "declared `type`",
     "fields": {"required": ["type", "value"]}, "cap": None,
     "note": "literal; type in bool|i64|f64|string|bytes|null"},
    {"op": "copy", "effect": "PURE", "inputs": 1, "out": "input type",
     "fields": {"optional": ["output"]}, "cap": None, "note": "identity"},
    {"op": "add", "effect": "PURE", "inputs": 2, "out": "i64|f64 (same type)",
     "fields": {"optional": ["output"]}, "cap": None,
     "note": "i64 overflow E302"},
    {"op": "subtract", "effect": "PURE", "inputs": 2, "out": "i64|f64",
     "fields": {"optional": ["output"]}, "cap": None, "note": ""},
    {"op": "multiply", "effect": "PURE", "inputs": 2, "out": "i64|f64",
     "fields": {"optional": ["output"]}, "cap": None, "note": ""},
    {"op": "divide", "effect": "PURE", "inputs": 2, "out": "i64|f64",
     "fields": {"optional": ["output"]}, "cap": None,
     "note": "i64: trunc toward zero, /0 E301, overflow E302; f64: IEEE"},
    {"op": "compare", "effect": "PURE", "inputs": 2, "out": "bool",
     "fields": {"required": ["mode"]}, "cap": None,
     "note": "mode in eq|ne|lt|le|gt|ge; ordered modes need i64|f64|string"},
    {"op": "branch", "effect": "PURE", "inputs": 3, "out": "arm type",
     "fields": {"optional": ["output"]}, "cap": None,
     "note": "pure select: input[1] if input[0] (bool) else input[2]; ALL inputs still evaluate"},
    {"op": "cast", "effect": "PURE", "inputs": 1, "out": "declared `output`",
     "fields": {"optional": ["output"]}, "cap": None,
     "note": "pairs: i64<->f64, string->i64/f64, i64/f64/bool->string; E303/E304"},
    {"op": "call", "effect": "PURE", "inputs": "one per param",
     "out": "callee return", "fields": {"required": ["callee"]}, "cap": None,
     "note": "recursion rejected (E212); manifest inherits callee effects"},
    {"op": "param", "effect": "PURE", "inputs": 0, "out": "declared `type`",
     "fields": {"required": ["type", "index"]}, "cap": None,
     "note": "func scope only (E214)"},
    {"op": "return", "effect": "PURE", "inputs": 1, "out": "input type",
     "fields": {}, "cap": None, "note": "func scope only, exactly one (E215)"},
    {"op": "emit", "effect": "SYSTEM", "inputs": 1, "out": "none",
     "fields": {}, "cap": None, "note": "main only; batch output channel"},
    {"op": "concat", "effect": "PURE", "inputs": 2, "out": "string",
     "fields": {"optional": ["output"]}, "cap": None,
     "note": "string concatenation; chains build documents"},
    {"op": "system.read", "effect": "SYSTEM", "inputs": 0, "out": "string",
     "fields": {"optional": ["output"]}, "cap": None,
     "note": "one stdin line, no newline; EOF -> empty string"},
    {"op": "system.write", "effect": "SYSTEM", "inputs": 1, "out": "i64",
     "fields": {"optional": ["output"]}, "cap": None,
     "note": "immediate stdout write, no newline added"},
    {"op": "crypto.digest", "effect": "PURE", "inputs": 1, "out": "string",
     "fields": {"required": ["algorithm"]}, "cap": None,
     "note": "algorithm sha256; hex output"},
    {"op": "filesystem.read", "effect": "FILESYSTEM_READ", "inputs": 1,
     "out": "string", "fields": {"required": [], "optional": ["output"]},
     "cap": "filesystem.read", "note": "input: path; scope-matched grant"},
    {"op": "filesystem.write", "effect": "FILESYSTEM_WRITE", "inputs": 2,
     "out": "i64", "fields": {"required": [], "optional": ["output"]},
     "cap": "filesystem.write", "note": "inputs: [path, content]; limits checked before write"},
    {"op": "data.insert", "effect": "DATA_WRITE", "inputs": "one per non-identity column, declared order",
     "out": "i64 rowid", "fields": {"required": ["entity"]},
     "cap": "data.write", "note": "requires --db"},
    {"op": "data.count", "effect": "DATA_READ", "inputs": 1, "out": "i64",
     "fields": {"required": ["entity", "where"]}, "cap": "data.read",
     "note": "requires --db"},
    {"op": "data.select", "effect": "DATA_READ", "inputs": 1,
     "out": "column type (default when absent)", "fields": {"required": ["entity", "column", "where"]},
     "cap": "data.read", "note": "requires --db"},
    {"op": "data.update", "effect": "DATA_WRITE", "inputs": 2, "out": "i64 rows",
     "fields": {"required": ["entity", "set", "where"]}, "cap": "data.write",
     "note": "inputs: [new value, where value]; requires --db"},
    {"op": "data.delete", "effect": "DATA_WRITE", "inputs": 1, "out": "i64 rows",
     "fields": {"required": ["entity", "where"], "optional": ["when"]}, "cap": "data.delete",
     "note": "separate action: data.read CANNOT delete; requires --db; `when <bool-node>` guards the write (false = verified no-op, returns 0)"},
    {"op": "net.fetch", "effect": "NETWORK", "inputs": 1, "out": "string body",
     "fields": {"required": [], "optional": ["output"]}, "cap": "net.request (hostname)",
     "note": "outbound GET on the full URL given as input; host must be allowlisted by a net.request grant (subdomains covered); host supplies transport; failure E560"},
    {"op": "session.verify", "effect": "IDENTITY", "inputs": 1, "out": "i64 subject_id",
     "fields": {"optional": ["output"]}, "cap": "session verifier (--session-key)",
     "note": "input: token string; forged/malformed E406, expired E407; programs cannot mint tokens"},
    {"op": "data.list", "effect": "DATA_READ", "inputs": 1, "out": "list<column type>",
     "fields": {"required": ["entity", "column", "where"]}, "cap": "data.read",
     "note": "all matching rows' column values ordered by id; needs --db"},
    {"op": "list.length", "effect": "PURE", "inputs": 1, "out": "i64",
     "fields": {"optional": ["output"]}, "cap": None, "note": "list element count"},
    {"op": "list.get", "effect": "PURE", "inputs": 2, "out": "element type",
     "fields": {"optional": ["output"]}, "cap": None,
     "note": "inputs [list, i64 index]; out of range E308"},
    {"op": "list.join", "effect": "PURE", "inputs": 2, "out": "string",
     "fields": {"optional": ["output"]}, "cap": None,
     "note": "inputs [list<string>, separator]"},
]

_ERROR_CODES = {
    "E101": "statement outside any node block",
    "E102": "invalid field (unknown, duplicate, empty, or not allowed for op)",
    "E103": "missing required field",
    "E104": "duplicate node id (global)",
    "E105": "literal invalid for declared type",
    "E106": "unknown type name",
    "E107": "malformed header (node id, main with arguments)",
    "E108": "empty program",
    "E109": "malformed or duplicate func declaration",
    "E201": "unknown operation",
    "E202": "input references unknown or cross-scope node",
    "E203": "type mismatch (expected/received/allowed_repairs)",
    "E204": "dependency cycle within a scope",
    "E205": "declared output type disagrees with inferred type",
    "E206": "no output channel (emit/system.write) in main",
    "E207": "input arity mismatch",
    "E208": "unknown compare mode",
    "E210": "call references unknown function",
    "E211": "call argument count mismatch",
    "E212": "call cycle (recursion)",
    "E214": "operation not allowed in this scope",
    "E215": "function must contain exactly one return",
    "E216": "param indexes must be exactly 0..k-1",
    "E301": "runtime: i64 division by zero",
    "E302": "runtime: i64 overflow",
    "E303": "runtime: f64 not representable as i64 in cast",
    "E304": "runtime: string not parseable as number in cast",
    "E305": "runtime: filesystem IO error",
    "E401": "authority: denied, no capability",
    "E402": "authority: capability expired",
    "E403": "authority: capability size limit exceeded",
    "E406": "authority: session token invalid or signature failed",
    "E407": "authority: session token expired",
    "E408": "authority: delegation bound to a different program hash",
    "E410": "authority: resource budget exceeded (deterministic limit — nodes/steps/literals/lists/call-depth/io/rows)",
    "E560": "network: net.fetch transport failure (unreachable, non-2xx, timeout)",
    "E308": "runtime: list index out of range",
    "E601": "proposal: made against a different base hash (graph moved)",
    "E602": "proposal: signature verification failed",
    "E603": "proposal: conflicting mutation (merge rejected)",
    "E604": "proposal: malformed",
    "E501": "data: unknown entity",
    "E502": "data: unknown column",
    "E503": "data: identity column cannot be updated",
    "E505": "data: SQLite error",
}


def ai_reference(version: str) -> dict:
    """The complete machine-readable language reference for this build."""
    ops = {entry["op"]: entry for entry in _OPS_REFERENCE}
    missing = sorted(set(_OPS) - set(ops))
    extra = sorted(set(ops) - set(_OPS))
    if missing or extra:  # pragma: no cover - test-enforced
        raise AssertionError(
            f"ai reference out of sync with validator: missing={missing} "
            f"extra={extra}")
    from . import PROTOCOL_VERSION
    return {
        "language": "2066",
        "protocol": PROTOCOL_VERSION,
        "version": version,
        "types": ["bool", "i64", "f64", "string", "bytes", "null"],
        "effects": sorted(set(EFFECT_OF.values())),
        "ops": ops,
        "error_codes": _ERROR_CODES,
        "exit_codes": {"0": "ok", "1": "parse/validation (E1xx,E2xx)",
                       "2": "runtime (E3xx)", "3": "usage/IO/trust",
                       "4": "authority denial (E4xx)"},
        "guarantees": [
            "deterministic: same program -> byte-identical output and errors",
            "total: no undefined behavior; every failure is a structured error",
            "terminating: DAG scopes + acyclic call graph",
            "authority-bounded: effects only behind capabilities; default deny",
        ],
    }
