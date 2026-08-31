"""Shared operation semantics — the single source both adapters execute.

The tree-walking interpreter and the compiled-plan VM must be semantically
identical by construction, so both dispatch through this module (master
roadmap Appendix F.3). Arithmetic is total: i64 overflow (E302), i64
division by zero (E301), IEEE 754 f64; casts fail with E303/E304.
"""

from __future__ import annotations

import math

import hashlib

from .errors import StructuredError
from .types import I64_MAX, I64_MIN, InvalidLiteral, format_value, parse_literal, type_of


def const_value(type_name: str, raw: str) -> object:
    return parse_literal(type_name, raw)


def digest(algorithm: str, data: str) -> str:
    if algorithm != "sha256":
        raise AssertionError(f"unhandled digest {algorithm!r}")
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def list_length(value: list) -> int:
    return len(value)


def list_get(node_id: str, value: list, index: object) -> object:
    i = int(index)
    if not (0 <= i < len(value)):
        raise _error(node_id, "list.get", "E308",
                     f"list index {i} out of range "
                     f"(length {len(value)})")
    return value[i]


def list_join(value: list, separator: str) -> str:
    return separator.join(str(element) for element in value)


def concat(a: str, b: str) -> str:
    return a + b


def select(condition: object, if_true: object, if_false: object) -> object:
    return if_true if condition else if_false


def arith(node_id: str, op: str, a: object, b: object) -> object:
    if isinstance(a, int) and isinstance(b, int):
        return i64_arith(node_id, op, a, b)
    return f64_arith(op, float(a), float(b))


def compare(mode: str, a: object, b: object) -> bool:
    if mode == "eq":
        return a == b
    if mode == "ne":
        return a != b
    if mode == "lt":
        return a < b  # type: ignore[operator]
    if mode == "le":
        return a <= b  # type: ignore[operator]
    if mode == "gt":
        return a > b  # type: ignore[operator]
    return a >= b  # type: ignore[operator]


def cast_value(node_id: str, value: object, target: str) -> object:
    source = type_of(value)
    if source == target:
        return value
    if target == "string":
        return format_value(value)
    if target == "i64":
        if source == "f64":
            return _f64_to_i64(node_id, value)
        try:
            return parse_literal("i64", value)
        except InvalidLiteral as exc:
            raise _error(node_id, "cast", "E304",
                         f"cannot cast string to i64: {exc.detail}") from exc
    if target == "f64":
        if source == "i64":
            return float(value)
        # accept canonical f64 OR i64 forms: user-facing input like "12"
        # must convert like 12.0 (program literals stay stricter than casts)
        try:
            return parse_literal("f64", value)
        except InvalidLiteral:
            try:
                return float(parse_literal("i64", value))
            except InvalidLiteral as exc:
                raise _error(node_id, "cast", "E304",
                             f"cannot cast string to f64: {exc.detail}") from exc
    raise AssertionError(f"unreachable cast {source}->{target}")  # pragma: no cover


def i64_arith(node_id: str, op: str, a: int, b: int) -> int:
    if op == "add":
        result = a + b
    elif op == "subtract":
        result = a - b
    elif op == "multiply":
        result = a * b
    else:  # divide — truncate toward zero (C-style), like most hardware
        if b == 0:
            raise _error(node_id, op, "E301", "division by zero")
        result = abs(a) // abs(b)
        if (a < 0) != (b < 0):
            result = -result
    if not (I64_MIN <= result <= I64_MAX):
        raise _error(
            node_id, op, "E302",
            f"i64 overflow: result {result} outside [{I64_MIN}, {I64_MAX}]",
        )
    return result


def f64_arith(op: str, a: float, b: float) -> float:
    if op == "add":
        return a + b
    if op == "subtract":
        return a - b
    if op == "multiply":
        return a * b
    if b == 0.0:
        # IEEE 754 division semantics; Python would raise, 2066 must be total.
        if a == 0.0:
            return float("nan")
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def _f64_to_i64(node_id: str, value: float) -> int:
    truncated = math.trunc(value) if math.isfinite(value) else None
    if truncated is None or not (I64_MIN <= truncated <= I64_MAX):
        raise _error(
            node_id, "cast", "E303",
            f"f64 value not representable as i64: {format_value(value)}",
        )
    return truncated


def _error(node_id: str, op: str, code: str, detail: str) -> StructuredError:
    return StructuredError(code=code, node=node_id, operation=op, detail=detail)
