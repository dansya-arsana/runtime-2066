"""Shared test helpers: in-process execution and CLI subprocess runner."""

import pathlib
import subprocess
import sys

from runtime import StructuredError, analyze, execute, parse_source

ROOT = pathlib.Path(__file__).resolve().parents[1]


def example(name: str) -> str:
    return (ROOT / "examples" / name).read_text(encoding="utf-8")


def run_source(src: str):
    """Parse + validate + execute. Returns (emits, error); exactly one is None."""
    try:
        program = parse_source(src)
        analysis = analyze(program)
    except StructuredError as exc:
        return None, exc
    try:
        return execute(program, analysis), None
    except StructuredError as exc:
        return None, exc


def expect_error(src: str, code: str) -> StructuredError:
    _, err = run_source(src)
    assert err is not None, f"expected {code}, but the program executed"
    assert err.code == code, f"expected {code}, received:\n{err.render()}"
    return err


def binary_program(op: str, t0: str, v0: str, t1: str, v1: str, out_t: str,
                   extra: str = "") -> str:
    """A program computing `op` over two constants and emitting the result."""
    return (
        f"node 001\nop const\ntype {t0}\nvalue {v0}\n\n"
        f"node 002\nop const\ntype {t1}\nvalue {v1}\n\n"
        f"node 003\nop {op}\n{extra}input 001 002\noutput {out_t}\n\n"
        "node 004\nop emit\ninput 003\n"
    )


def run_cli(*args: str, stdin: str | None = None):
    proc = subprocess.run(
        [sys.executable, "-m", "runtime", *args],
        input=stdin, capture_output=True, text=True, cwd=ROOT, timeout=120,
    )
    return proc.returncode, proc.stdout, proc.stderr
