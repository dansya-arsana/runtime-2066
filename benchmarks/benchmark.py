"""2066 benchmark — honest numbers, wins and losses.

Three questions, three measurements:

1. RUNTIME:  how fast does the same computation run through the 2066
   pipeline (tree adapter, plan adapter, exported Python, exported JS)
   vs hand-written native Python and native JavaScript?
2. AUTHORING: how many characters (≈ tokens/4) does the same calculator
   engine cost in 2066 vs hand-written Python and JavaScript?
3. VERIFICATION: after changing the engine, what does it cost to get from
   "changed" to "all artifacts regenerated and every test green"?

Run:  python benchmarks/benchmark.py
"""

import contextlib
import io
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from runtime import (analyze, execute, execute_plan, export_javascript,  # noqa: E402
                     export_python, parse_source)

N_OPS = 10_000
REPEATS = 5


def chain_source(n: int) -> str:
    parts = ["node 000\nop const\ntype i64\nvalue 1\n\n",
             "node 001\nop const\ntype i64\nvalue 0\n\n"]
    prev = "001"
    for i in range(2, n + 1):
        node_id = f"{i:05d}"
        parts.append(f"node {node_id}\nop add\ninput {prev} 000\noutput i64\n\n")
        prev = node_id
    parts.append(f"node {n + 1:06d}\nop emit\ninput {prev}\n")
    return "".join(parts)


def best_of(fn, repeats=REPEATS):
    times = []
    result = None
    for _ in range(repeats):
        start = time.perf_counter()
        result = fn()
        times.append(time.perf_counter() - start)
    return min(times), result


def internal_node_time(js_body: str, expect: int) -> float:
    """Native JS timing measured INSIDE node (excludes process startup)."""
    script = (
        "const t0 = process.hrtime.bigint();\n"
        f"const r = {js_body};\n"
        "const t1 = process.hrtime.bigint();\n"
        "if (Number(r) !== " + str(expect) + ") throw new Error('wrong result ' + r);\n"
        "console.log(Number(t1 - t0) / 1e6);\n"
    )
    script_file = ROOT / "benchmarks" / "_bench_timing.js"
    script_file.write_text(script, encoding="utf-8")
    best = float("inf")
    try:
        for _ in range(REPEATS):
            proc = subprocess.run(["node", str(script_file)],
                                  capture_output=True, text=True,
                                  timeout=60, cwd=ROOT)
            if proc.returncode != 0:
                raise AssertionError(proc.stderr)
            best = min(best, float(proc.stdout.strip()))
    finally:
        script_file.unlink(missing_ok=True)
    return best / 1000.0


def internal_python_time(stmt: str, expect: int) -> float:
    compiled = compile(stmt, "<native>", "exec")  # compile once, like the export
    best = float("inf")
    for _ in range(REPEATS):
        start = time.perf_counter()
        namespace = {}
        exec(compiled, namespace)  # noqa: S102
        best = min(best, time.perf_counter() - start)
        if namespace.get("r") != expect:
            raise AssertionError("wrong result")
    return best


def main() -> None:
    print(f"2066 benchmark — {N_OPS} chained operations, "
          f"best of {REPEATS}\n" + "=" * 62)

    # ---------------- 1. runtime ----------------
    source = chain_source(N_OPS)
    program = parse_source(source)
    analysis = analyze(program)

    t, _ = best_of(lambda: parse_source(source))
    print(f"\n[RUNTIME — same computation, different engines]")
    print(f"  2066 parse+validate ......... {t * 1000:8.2f} ms")

    t, _ = best_of(lambda: execute(program, analysis))
    print(f"  2066 tree adapter ........... {t * 1000:8.2f} ms")

    t, _ = best_of(lambda: execute_plan(program, analysis))
    print(f"  2066 plan adapter ........... {t * 1000:8.2f} ms")

    t, py_source = best_of(lambda: export_python(program, analysis))
    print(f"  2066 -> Python export ....... {t * 1000:8.2f} ms (one-time)")

    compiled = compile(py_source, "<exported>", "exec")

    def exported_py():
        with contextlib.redirect_stdout(io.StringIO()):
            exec(compiled, {})  # noqa: S102
    t, _ = best_of(exported_py)
    print(f"  exported Python, executed ... {t * 1000:8.2f} ms")

    t, js_source = best_of(lambda: export_javascript(program, analysis))
    print(f"  2066 -> JavaScript export ... {t * 1000:8.2f} ms (one-time)")

    # time the exported JS hot code inside node: cut before the emit, wrap
    # in an IIFE that returns the final value slot instead of printing
    final_slot = f"s{N_OPS:05d}"  # the last add node's slot
    hot_js = js_source.split("console.log", 1)[0]
    wrapped = f"(function(){{{hot_js}return _fmt({final_slot});}})()"
    t = internal_node_time(wrapped, expect=N_OPS - 1)
    print(f"  exported JS, executed ....... {t * 1000:8.2f} ms")

    additions = N_OPS - 1  # the chain performs exactly this many adds
    native_py = "r = 0\n" + "r = r + 1\n" * additions
    t = internal_python_time(native_py, expect=additions)
    print(f"  native Python loop .......... {t * 1000:8.2f} ms")

    native_js = ("(function(){ let r = 0; " + "r = r + 1; " * additions
                 + "return r; })()")
    t = internal_node_time(native_js, expect=additions)
    print(f"  native JavaScript loop ...... {t * 1000:8.2f} ms")

    # ---------------- 2. authoring ----------------
    print(f"\n[AUTHORING — the calculator engine, 3 languages]")
    rows = []
    engine_ai = (ROOT / "examples/calculator_app/engine.ai").read_text("utf-8")
    rows.append(("engine.ai (2066)", engine_ai))

    native_engine_py = (
        "def calculate(a, b, op):\n"
        "    if op == '+': return str(a + b)\n"
        "    if op == '-': return str(a - b)\n"
        "    if op == '*': return str(a * b)\n"
        "    if op == '/':\n"
        "        if b == 0: return 'Cannot divide by zero'\n"
        "        return str(a / b)\n"
        "    return 'Unsupported operator'\n"
    )
    rows.append(("calculate() (Python)", native_engine_py))

    native_engine_js = (
        "function calculate(a, b, op) {\n"
        "  if (op === '+') return String(a + b);\n"
        "  if (op === '-') return String(a - b);\n"
        "  if (op === '*') return String(a * b);\n"
        "  if (op === '/') return b === 0 ? 'Cannot divide by zero'\n"
        "                                : String(a / b);\n"
        "  return 'Unsupported operator';\n"
        "}\n"
    )
    rows.append(("calculate() (JavaScript)", native_engine_js))

    for name, text in rows:
        chars, lines = len(text), text.count("\n")
        print(f"  {name:26s} {chars:6d} chars ~{chars // 4:5d} tokens  {lines:3d} lines")

    # ---------------- 3. verification ----------------
    print(f"\n[VERIFICATION — engine.ai change -> all artifacts regenerated + tested]")
    start = time.perf_counter()
    program = parse_source(engine_ai)
    analysis = analyze(program)
    export_python(program, analysis)
    export_javascript(program, analysis, library=True)
    rebuild = time.perf_counter() - start
    print(f"  regenerate both backends .... {rebuild * 1000:8.2f} ms")
    proc = subprocess.run(
        [sys.executable, "-m", "unittest", "discover"],
        capture_output=True, text=True, timeout=300, cwd=ROOT)
    suite_line = next(line for line in proc.stderr.splitlines()
                      if line.startswith("Ran "))
    ok = "OK" in proc.stderr.splitlines()[-1]
    print(f"  full deterministic suite .... {suite_line.strip()} (OK={ok})")
    print(f"\n  (hand-written engines get none of this automatically: no"
          f"\n  validator, no repair protocol, no canonical hash, no second"
          f"\n  backend for free — every guarantee must be built by hand)")


if __name__ == "__main__":
    main()
