"""Export backend (roadmap §10 "Export Backend", §4.10): canonical IR ->
standalone Python source.

Conventional languages are generated artifacts, never the source of truth.
The exporter lowers the compiled plan (runtime/plan_vm.py) to straight-line
Python: every semantic node becomes one assignment, functions become
functions, and a small preamble re-implements exactly the 2066 arithmetic
semantics the interpreter guarantees (truncating i64 division, E301/E302,
canonical casts with E303/E304, canonical value rendering). Generated code
is deterministic: the same program always exports to the same bytes, with
its canonical hash in the header.

V1 scope: PURE and SYSTEM effects (emit, system.read/write). FILESYSTEM_*
effects are refused — exported code runs outside the 2066 authority plane,
and refusing to export capability-gated effects keeps that boundary honest.

Targets:
- `python`    — full V0 semantics via a semantics-preserving preamble.
- `javascript` — f64-native (JS numbers ARE IEEE 754 doubles, so float
  semantics map directly). Known, documented divergences: i64 range/overflow
  semantics are not enforced (JS numbers are f64; exact integers end at
  2^53), string comparison is UTF-16 order, and bytes constants are
  unsupported. `--library` omits the main body and exposes
  `const Calc2066 = { ... }` for embedding (the calculator app shell).
"""

from __future__ import annotations

import json

from .errors import StructuredError
from .hashing import program_hash
from .parser import Program
from .plan_vm import compile_plan
from .validator import Analysis, analyze, program_effects

_CMP = {"eq": "===", "ne": "!==", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
_PY_CMP = {"eq": "==", "ne": "!=", "lt": "<", "le": "<=", "gt": ">", "ge": ">="}
_ARITH = {"ADD": "+", "SUB": "-", "MUL": "*"}


def _refuse_unexportable(program: Program, analysis: Analysis) -> None:
    """Capability-gated effects stay inside the authority plane: exported
    code runs without the runtime, so data/filesystem effects are refused."""
    unsupported = sorted(e for e in program_effects(program, analysis)
                         if e.startswith(("FILESYSTEM", "DATA", "IDENTITY")))
    if unsupported:
        raise ValueError(
            "export targets support PURE and SYSTEM effects only; program "
            f"requires {', '.join(unsupported)} — capability-gated effects "
            "must keep running inside the 2066 authority plane"
        )

_PREAMBLE = '''\
import math
import re
import sys

_I64_MIN = -(2 ** 63)
_I64_MAX = 2 ** 63 - 1


def _typeof(v):
    if isinstance(v, bool):
        return "bool"
    if isinstance(v, int):
        return "i64"
    if isinstance(v, float):
        return "f64"
    if isinstance(v, str):
        return "string"
    if isinstance(v, bytes):
        return "bytes"
    return "null"


def _chk(v):
    if not (_I64_MIN <= v <= _I64_MAX):
        raise OverflowError("E302 i64 overflow")
    return v


def _idiv(a, b):
    if b == 0:
        raise ZeroDivisionError("E301 division by zero")
    q = abs(a) // abs(b)
    return _chk(-q if (a < 0) != (b < 0) else q)


def _fdiv(a, b):
    if b == 0.0:
        if a == 0.0:
            return float("nan")
        return math.copysign(math.inf, a) * math.copysign(1.0, b)
    return a / b


def _fmt(v):
    t = _typeof(v)
    if t == "bool":
        return "true" if v else "false"
    if t == "i64":
        return str(v)
    if t == "f64":
        return repr(v)
    if t == "bytes":
        return "0x" + v.hex()
    if t == "null":
        return "null"
    return v


def _pi64(s):
    if not re.fullmatch(r"[+-]?[0-9]+", s):
        raise ValueError("E304 cannot cast string to i64: " + repr(s))
    v = int(s)
    if not (_I64_MIN <= v <= _I64_MAX):
        raise ValueError("E304 cannot cast string to i64 (out of range): " + repr(s))
    return v


def _pf64(s):
    f64 = r"[+-]?(?:[0-9]+\\.[0-9]*|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[+-]?[0-9]+[eE][+-]?[0-9]+"
    if re.fullmatch(r"[+-]?[0-9]+", s):
        return float(s)  # integer input converts like 12 -> 12.0
    if not re.fullmatch(f64, s):
        raise ValueError("E304 cannot cast string to f64: " + repr(s))
    return float(s)


def _f2i(v):
    t = math.trunc(v) if math.isfinite(v) else None
    if t is None or not (_I64_MIN <= t <= _I64_MAX):
        raise ValueError("E303 f64 value not representable as i64: " + repr(v))
    return t


def _cast(v, target):
    t = _typeof(v)
    if t == target:
        return v
    if target == "string":
        return _fmt(v)
    if target == "f64":
        return float(v) if t == "i64" else _pf64(v)
    if target == "i64":
        return _f2i(v) if t == "f64" else _pi64(v)
    raise AssertionError("unreachable cast")


def _readline():
    line = sys.stdin.readline()
    if line == "":
        return ""
    return line[:-1] if line.endswith("\\n") else line


def _swrite(s):
    return sys.stdout.write(s)
'''


def export_python(program: Program, analysis: Analysis | None = None) -> str:
    """Deterministically lower the validated program to Python source."""
    if analysis is None:
        analysis = analyze(program)
    _refuse_unexportable(program, analysis)

    plan = compile_plan(program, analysis)
    lines = [
        f"# Generated by the 2066 runtime from canonical program "
        f"{program_hash(program)}",
        "# Conventional source is a generated artifact — the semantic graph "
        "is the truth (roadmap §4.10). Do not edit.",
        _PREAMBLE,
    ]
    for name in analysis.call_order:
        body = _emit_scope(plan.functions[name], analysis, name)
        param_count = len(_params_of(program, name))
        params = ", ".join(f"s{i}" for i in range(param_count))
        lines.append(f"def _f_{name}({params}):")
        lines.extend("    " + line if line else "" for line in body)
    lines.extend(_emit_scope(plan.main, analysis, "main"))
    return "\n".join(lines) + "\n"


def _params_of(program: Program, function_name: str):
    from .validator import _params  # node-list helper; count only
    return _params(program.functions[function_name].nodes)


def _emit_scope(scope_plan, analysis: Analysis, scope_name: str):
    types = analysis.scopes[scope_name].types
    lines: list[str] = []
    pending: list[str] = []

    for ins in scope_plan.instrs:
        node_type = types.get(ins.node) if ins.node else None
        if ins.op == "LOAD":
            pending.append(f"s{ins.arg}")
        elif ins.op == "CONST":
            lines.append(f"s{ins.out} = {_pylit(ins.arg)}")
        elif ins.op in _ARITH:
            b = pending.pop()
            a = pending.pop()
            expr = f"{a} {_ARITH[ins.op]} {b}"
            if node_type == "i64":
                expr = f"_chk({expr})"
            lines.append(f"s{ins.out} = {expr}")
        elif ins.op == "DIV":
            b = pending.pop()
            a = pending.pop()
            fn = "_idiv" if node_type == "i64" else "_fdiv"
            lines.append(f"s{ins.out} = {fn}({a}, {b})")
        elif ins.op == "CMP":
            b = pending.pop()
            a = pending.pop()
            lines.append(f"s{ins.out} = {a} {_PY_CMP[ins.arg]} {b}")
        elif ins.op == "SELECT":
            f_expr = pending.pop()
            t_expr = pending.pop()
            c_expr = pending.pop()
            lines.append(f"s{ins.out} = {t_expr} if {c_expr} else {f_expr}")
        elif ins.op == "CAST":
            a = pending.pop()
            lines.append(f"s{ins.out} = _cast({a}, {ins.arg!r})")
        elif ins.op == "CALL":
            name, argc = ins.arg
            args = pending[len(pending) - argc:] if argc else []
            if argc:
                del pending[len(pending) - argc:]
            lines.append(f"s{ins.out} = _f_{name}({', '.join(args)})")
        elif ins.op == "STORE":
            lines.append(f"s{ins.out} = {pending.pop()}")
        elif ins.op == "LLEN":
            lines.append(f"s{ins.out} = len({pending.pop()})")
        elif ins.op == "LGET":
            index = pending.pop()
            lst = pending.pop()
            lines.append(
                f"s{ins.out} = {lst}[{index}] if 0 <= {index} < len({lst}) "
                f"else (_ for _ in ()).throw(ValueError('E308 list index "
                f"out of range'))")
        elif ins.op == "LJOIN":
            separator = pending.pop()
            lst = pending.pop()
            lines.append(
                f"s{ins.out} = {separator}.join(str(x) for x in {lst})")
        elif ins.op == "CONCAT":
            b = pending.pop()
            a = pending.pop()
            lines.append(f"s{ins.out} = {a} + {b}")
        elif ins.op == "STDIN":
            lines.append(f"s{ins.out} = _readline()")
        elif ins.op == "STDOUT":
            lines.append(f"s{ins.out} = _swrite({pending.pop()})")
        elif ins.op == "EMIT":
            lines.append(f"print(_fmt({pending.pop()}))")
        elif ins.op == "RETURN":
            lines.append(f"return {pending.pop()}")
        else:  # pragma: no cover
            raise AssertionError(f"unhandled instruction {ins.op!r}")
    return lines


def _pylit(value: object) -> str:
    if value is None:
        return "None"
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, bytes):
        return repr(value)
    return repr(value)


# ---------------------------------------------------------------------------
# JavaScript target: f64-native; numbers ARE IEEE 754 doubles, so float
# semantics map natively. Documented divergences (see module docstring):
# no i64 range enforcement, UTF-16 string order, no bytes constants.

_JS_PREAMBLE = '''\
function _typeof2066(v) {
  if (typeof v === "boolean") return "bool";
  if (typeof v === "number") return "f64";
  if (typeof v === "string") return "string";
  if (v === null) return "null";
  return "bytes";
}


function _fmt(v) {
  const t = _typeof2066(v);
  if (t === "bool") return v ? "true" : "false";
  if (t === "f64") return Number.isInteger(v) ? v.toFixed(1) : String(v);
  if (t === "null") return "null";
  return v;
}


function _cast(v, target) {
  const t = _typeof2066(v);
  if (t === target) return v;
  if (target === "string") return _fmt(v);
  if (target === "f64") {
    if (!/^(?:[+-]?(?:[0-9]+\\.[0-9]*|\\.[0-9]+)(?:[eE][+-]?[0-9]+)?|[+-]?[0-9]+[eE][+-]?[0-9]+)$/.test(v))
      throw new Error("E304 cannot cast string to f64: " + JSON.stringify(v));
    return Number(v);
  }
  if (target === "i64") {
    if (!/^[+-]?[0-9]+$/.test(v))
      throw new Error("E304 cannot cast string to i64: " + JSON.stringify(v));
    const n = Number(v);
    if (!Number.isSafeInteger(n))
      throw new Error("E304 cannot cast string to i64 (outside safe range): " + v);
    return n;
  }
  throw new Error("unreachable cast");
}


function _readline() {
  throw new Error("system.read is not available in the browser target");
}
'''


def export_javascript(program: Program, analysis: Analysis | None = None,
                      library: bool = False) -> str:
    """Lower the validated program to plain browser/node JavaScript.

    All numbers are f64 (JS doubles) — float semantics are native. In
    `library` mode the main body is omitted and a `Calc2066` object exposes
    the program's functions for embedding.
    """
    if analysis is None:
        analysis = analyze(program)
    _refuse_unexportable(program, analysis)
    uses_stdin = "system.read" in {
        node.field("op")
        for node in program.nodes.values()
    } | {
        node.field("op")
        for function in program.functions.values()
        for node in function.nodes.values()
    }
    if uses_stdin:
        raise ValueError("export target 'javascript' does not support "
                         "system.read (browsers have no stdin)")

    plan = compile_plan(program, analysis)
    lines = [
        f"// Generated by the 2066 runtime from canonical program "
        f"{program_hash(program)}",
        "// Conventional source is a generated artifact — the semantic "
        "graph is the truth (roadmap §4.10). Do not edit.",
        _JS_PREAMBLE,
    ]
    for name in analysis.call_order:
        body = _emit_scope_js(plan.functions[name], analysis, name)
        param_count = len(_params_of(program, name))
        params = ", ".join(f"s{i}" for i in range(param_count))
        lines.append(f"function _f_{name}({params}) {{")
        lines.extend("  " + line if line else "" for line in body)
        lines.append("}")
    if library:
        exposed = ", ".join(f"{name}: _f_{name}" for name in analysis.call_order)
        lines.append(f"globalThis.Calc2066 = {{ {exposed} }};")
    else:
        lines.extend(_emit_scope_js(plan.main, analysis, "main"))
    return "\n".join(lines) + "\n"


def _jslit(value: object) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, bytes):
        raise ValueError("export target 'javascript' does not support "
                         "bytes constants")
    if isinstance(value, (int, float)):
        return repr(value)
    return json.dumps(value)  # strings: JSON escaping is valid JS


def _emit_scope_js(scope_plan, analysis: Analysis, scope_name: str):
    types = analysis.scopes[scope_name].types
    lines: list[str] = []
    pending: list[str] = []
    slot_ids: list[int] = []

    def let(slot: int, expr: str) -> None:
        kw = "let " if slot not in slot_ids else ""
        if slot not in slot_ids:
            slot_ids.append(slot)
        lines.append(f"{kw}s{slot} = {expr};")

    for ins in scope_plan.instrs:
        node_type = types.get(ins.node) if ins.node else None
        if ins.op == "LOAD":
            pending.append(f"s{ins.arg}")
        elif ins.op == "CONST":
            let(ins.out, _jslit(ins.arg))
        elif ins.op in _ARITH:
            b = pending.pop()
            a = pending.pop()
            let(ins.out, f"{a} {_ARITH[ins.op]} {b}")
        elif ins.op == "DIV":
            b = pending.pop()
            a = pending.pop()
            let(ins.out, f"{a} / {b}")  # JS numbers are IEEE f64: total
        elif ins.op == "CMP":
            b = pending.pop()
            a = pending.pop()
            let(ins.out, f"{a} {_CMP[ins.arg]} {b}")
        elif ins.op == "SELECT":
            f_expr = pending.pop()
            t_expr = pending.pop()
            c_expr = pending.pop()
            let(ins.out, f"{c_expr} ? {t_expr} : {f_expr}")
        elif ins.op == "CAST":
            a = pending.pop()
            let(ins.out, f"_cast({a}, {json.dumps(ins.arg)})")
        elif ins.op == "CALL":
            name, argc = ins.arg
            args = pending[len(pending) - argc:] if argc else []
            if argc:
                del pending[len(pending) - argc:]
            let(ins.out, f"_f_{name}({', '.join(args)})")
        elif ins.op == "STORE":
            let(ins.out, pending.pop())
        elif ins.op == "LLEN":
            let(ins.out, f"{pending.pop()}.length")
        elif ins.op == "LGET":
            index = pending.pop()
            lst = pending.pop()
            lines.append(f"if ({index} < 0 || {index} >= {lst}.length)")
            lines.append("  throw new Error('E308 list index out of range');")
            let(ins.out, f"{lst}[{index}]")
        elif ins.op == "LJOIN":
            separator = pending.pop()
            let(ins.out, f"{pending.pop()}.map(String).join({separator})")
        elif ins.op == "STDIN":
            raise ValueError("export target 'javascript' does not support "
                             "system.read (browsers have no stdin)")
        elif ins.op == "STDOUT":
            lines.append(f"console.log({pending.pop()});")
        elif ins.op == "EMIT":
            lines.append(f"console.log(_fmt({pending.pop()}));")
        elif ins.op == "RETURN":
            lines.append(f"return {pending.pop()};")
        else:  # pragma: no cover
            raise AssertionError(f"unhandled instruction {ins.op!r}")
    return lines
