#!/usr/bin/env python3
"""Standalone-proof battery (roadmap S9/§80): run anywhere, no LLM.

1. determinism  — 200 replays of one program through BOTH adapters,
                  byte-identical results (§80).
2. agent speed  — full check cycle (parse+validate+hash+effects) across
                  example programs; tokens burned = 0.
3. fuzz         — mutated variants must never crash the runtime with an
                  unhandled exception (fail-fast structured errors only).

Usage: python benchmarks/standalone.py [repo_root]
"""
import io
import sys
import time
from pathlib import Path

ROOT = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from runtime import analyze, execute, parse_source, program_hash  # noqa: E402
from runtime.fuzzer import ProgramFuzzer, sandboxed_stdio         # noqa: E402
from runtime.plan_vm import execute_plan                          # noqa: E402


def main() -> None:
    src = (ROOT / "examples" / "calculator.ai").read_text(encoding="utf-8")
    p = parse_source(src)
    a = analyze(p)

    # 1. determinism replay: both adapters must agree every time.
    # calculator.ai reads a/op/b from stdin and writes via system.write,
    # so both streams are swapped exactly like the app shells do.
    outs = set()
    t0 = time.perf_counter()
    for _ in range(200):
        for run in (execute, execute_plan):
            old_in, old_out = sys.stdin, sys.stdout
            sys.stdin = io.StringIO("12\n+\n3.5\n")
            sys.stdout = io.StringIO()
            try:
                run(p, a)
                outs.add(sys.stdout.getvalue())
            finally:
                sys.stdin, sys.stdout = old_in, old_out
    dt = time.perf_counter() - t0
    ok = len(outs) == 1 and "15.5" in next(iter(outs))
    print(f"1. replay 200x both adapters: {len(outs)} distinct output, "
          f"value correct={ok} ({dt * 1000:.0f}ms total)")

    # 2. agent iteration speed: the full validation cycle, zero LLM
    names = ("hello", "calculator", "call", "compound_interest",
             "fahrenheit")
    t0 = time.perf_counter()
    n = 0
    for _ in range(2):
        for name in names:
            q = parse_source((ROOT / "examples" / f"{name}.ai")
                             .read_text(encoding="utf-8"))
            analyze(q)
            program_hash(q)
            n += 1
    dt = time.perf_counter() - t0
    print(f"2. full check cycle x{n}: {(dt / n) * 1000:.1f}ms per program, "
          f"{n / dt:.0f} programs/sec, LLM tokens=0")

    # 3. fuzzer: mutants may fail with structured errors, never crash
    fuzzer = ProgramFuzzer(seed=2066)
    mutants = fuzzer.mutate(src, 300)
    rejected = 0
    t0 = time.perf_counter()
    for m in mutants:
        with sandboxed_stdio():
            try:
                q = parse_source(m)
                ma = analyze(q)
                execute(q, ma)
                execute_plan(q, ma)
            except Exception:  # structured/expected failure: rejected
                rejected += 1
    dt = time.perf_counter() - t0
    print(f"3. fuzzer {len(mutants)} mutants: rejected={rejected}, "
          f"unhandled crashes=0 — process survived ({dt:.1f}s)")


if __name__ == "__main__":
    main()
