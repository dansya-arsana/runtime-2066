"""Primitive types and canonical literals (spec/types.md).

V0 primitive types (roadmap §11): bool, i64, f64, string, bytes, null.
Nothing else. Every literal has exactly one canonical form and one
canonical printed rendering — no undefined behavior (roadmap §4.9).
"""

from __future__ import annotations

import re

I64_MIN = -(2**63)
I64_MAX = 2**63 - 1

TYPE_NAMES = ("bool", "i64", "f64", "string", "bytes", "null")

_I64_RE = re.compile(r"[+-]?[0-9]+")
_F64_RE = re.compile(
    r"[+-]?(?:[0-9]+\.[0-9]*|\.[0-9]+)(?:[eE][+-]?[0-9]+)?"
    r"|[+-]?[0-9]+[eE][+-]?[0-9]+"
)
_BYTES_RE = re.compile(r"0x(?:[0-9a-fA-F]{2})*")

_STRING_ESCAPES = {'"': '"', "\\": "\\", "n": "\n", "t": "\t"}


class InvalidLiteral(Exception):
    """Raised internally; the validator converts this into error E105."""

    def __init__(self, detail: str):
        super().__init__(detail)
        self.detail = detail


def type_of(value: object) -> str:
    """Runtime value -> 2066 type name. bool is checked before int."""
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "i64"
    if isinstance(value, float):
        return "f64"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bytes):
        return "bytes"
    if isinstance(value, list):
        if not value:
            return "list<null>"
        inner = {type_of(element) for element in value}
        return f"list<{'|'.join(sorted(inner))}>" if len(inner) > 1             else f"list<{next(iter(inner))}>"
    if value is None:
        return "null"
    raise TypeError(f"value has no 2066 type: {value!r}")


def parse_literal(type_name: str, raw: str) -> object:
    """Parse a canonical literal for the declared type. Raises InvalidLiteral."""
    if type_name == "i64":
        return _parse_i64(raw)
    if type_name == "f64":
        return _parse_f64(raw)
    if type_name == "string":
        return _parse_string(raw)
    if type_name == "bool":
        if raw == "true":
            return True
        if raw == "false":
            return False
        raise InvalidLiteral(f"bool literal must be 'true' or 'false', received {raw!r}")
    if type_name == "null":
        if raw == "null":
            return None
        raise InvalidLiteral(f"null literal must be 'null', received {raw!r}")
    if type_name == "bytes":
        if not _BYTES_RE.fullmatch(raw):
            raise InvalidLiteral(
                f"bytes literal must be '0x' followed by hex byte pairs, received {raw!r}"
            )
        return bytes.fromhex(raw[2:])
    raise InvalidLiteral(f"unknown type {type_name!r}")


def _parse_i64(raw: str) -> int:
    if not _I64_RE.fullmatch(raw):
        raise InvalidLiteral(f"i64 literal must be a decimal integer, received {raw!r}")
    value = int(raw)
    if not (I64_MIN <= value <= I64_MAX):
        raise InvalidLiteral(
            f"i64 literal {value} outside range [{I64_MIN}, {I64_MAX}]"
        )
    return value


def _parse_f64(raw: str) -> float:
    if not _F64_RE.fullmatch(raw):
        raise InvalidLiteral(
            "f64 literal must contain '.' or an exponent "
            f"(non-finite literals are not expressible), received {raw!r}"
        )
    try:
        return float(raw)
    except ValueError as exc:  # pragma: no cover - regex excludes overflow to inf
        raise InvalidLiteral(f"invalid f64 literal {raw!r}: {exc}") from exc


def _parse_string(raw: str) -> str:
    if len(raw) < 2 or not (raw.startswith('"') and raw.endswith('"')):
        raise InvalidLiteral(f"string literal must be double-quoted, received {raw!r}")
    body = raw[1:-1]
    out: list[str] = []
    i = 0
    while i < len(body):
        ch = body[i]
        if ch == '"':
            raise InvalidLiteral("unescaped '\"' inside string literal")
        if ch == "\\":
            if i + 1 >= len(body):
                raise InvalidLiteral("dangling escape at end of string literal")
            esc = body[i + 1]
            if esc not in _STRING_ESCAPES:
                raise InvalidLiteral(f"unknown escape '\\{esc}' in string literal")
            out.append(_STRING_ESCAPES[esc])
            i += 2
        else:
            out.append(ch)
            i += 1
    return "".join(out)


def format_value(value: object) -> str:
    """Canonical printed rendering of a value (spec/graph.md, emit output)."""
    if isinstance(value, list):
        return "\n".join(format_value(element) for element in value)
    kind = type_of(value)
    if kind == "bool":
        return "true" if value else "false"
    if kind == "i64":
        return str(value)
    if kind == "f64":
        return repr(value)  # shortest round-trip decimal; inf/-inf/nan for non-finite
    if kind == "string":
        return value
    if kind == "bytes":
        return "0x" + value.hex()
    return "null"


def quote_string(value: str) -> str:
    """Canonical double-quoted string literal (inverse of _parse_string)."""
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'
