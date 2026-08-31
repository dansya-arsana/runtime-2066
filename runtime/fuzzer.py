"""Program fuzzer: adversarial inputs must produce structured errors,
never unhandled crashes (roadmap determinism-by-sampling gap).

The validator is a fixed set of passes; the interpreter is a fixed
walker. Neither is "probably safe" — the claim is that ANY input text,
however mangled, either parses+validates+executes or raises a
StructuredError with a stable E-code. The fuzzer tests that claim by
sampling: mutate a valid program, run the full pipeline, and count
crashes (any exception that is NOT a StructuredError). The correct
runtime scores crashes == 0 for every sample.

Determinism: a fixed seed (default 2066) drives a private
random.Random instance per run, so the same source always yields the
same mutants — a failing fuzz run is reproducible exactly.
"""

from __future__ import annotations
import io
import random
import re
import sys
from contextlib import contextmanager

from .errors import StructuredError
from .interpreter import execute
from .parser import parse_source
from .validator import analyze

DEFAULT_SEED = 2066

# type swaps that keep the text shape but change semantics / types
_TYPE_SWAPS = {
    "i64": "f64",
    "f64": "i64",
    "string": "bool",
    "bool": "string",
}

# op renames that keep the grammar but break arity/type contracts
_OP_SWAPS = {
    "add": "subtract",
    "subtract": "multiply",
    "multiply": "divide",
    "divide": "add",
    "const": "copy",
    "copy": "const",
    "compare": "branch",
    "branch": "compare",
    "cast": "copy",
    "concat": "add",
    "emit": "cast",
}

_GARBAGE_LINES = (
    "flurb 12",
    "garbage",
    "op totally_bogus",
    "value \"unterminated",
    "input 00X",
    "entity bad {",
    "}",
    "format-version 99",
    "type bogus",
    "node 999999",
    "value",
    "input",
)

_NUMBER_RE = re.compile(r"[0-9]")


@contextmanager
def sandboxed_stdio():
    """Keep fuzzed execution hermetic: no real stdin reads (which would
    block on `system.read`), no stray stdout writes (`system.write`)."""
    real_in, real_out = sys.stdin, sys.stdout
    sys.stdin = io.StringIO("")
    sys.stdout = io.StringIO()
    try:
        yield
    finally:
        sys.stdin, sys.stdout = real_in, real_out


class ProgramFuzzer:
    """Deterministic mutation fuzzer over canonical .ai program text."""

    def __init__(self, seed: int = DEFAULT_SEED):
        self.seed = seed

    # ------------------------------------------------------------------
    # mutation strategies (each takes lines, returns lines or None)

    def mutate(self, source: str, count: int) -> list[str]:
        """Generate `count` mutated variants of a valid program.

        Each variant applies 1-3 random mutations drawn from the
        strategy pool: type swaps, value corruption, op renames, line
        removal, field duplication, garbage insertion.
        """
        rng = random.Random(self.seed)  # fixed seed -> reproducible
        mutants: list[str] = []
        for _ in range(count):
            lines = source.splitlines()
            for _ in range(rng.randint(1, 3)):
                lines = self._apply_one(rng, lines) or lines
            mutants.append("\n".join(lines) + "\n")
        return mutants

    def _apply_one(self, rng: random.Random,
                   lines: list[str]) -> list[str] | None:
        strategies = (
            self._mutate_swap_type,
            self._mutate_corrupt_value,
            self._mutate_swap_op,
            self._mutate_remove_line,
            self._mutate_duplicate_field,
            self._mutate_insert_garbage,
        )
        order = list(strategies)
        rng.shuffle(order)
        for strategy in order:
            mutated = strategy(rng, lines)
            if mutated is not None:
                return mutated
        return None

    # ------------------------------------------------------------------

    @staticmethod
    def _mutate_swap_type(rng: random.Random,
                          lines: list[str]) -> list[str] | None:
        """Swap a type token: i64->f64, string->bool, ..."""
        candidates = [i for i, line in enumerate(lines)
                      if re.search(r"\b(i64|f64|string|bool)\b", line)]
        if not candidates:
            return None
        index = rng.choice(candidates)

        def swap(match: re.Match) -> str:
            return _TYPE_SWAPS.get(match.group(0), match.group(0))

        lines[index] = re.sub(r"\b(i64|f64|string|bool)\b", swap,
                              lines[index], count=1)
        return lines

    @staticmethod
    def _mutate_corrupt_value(rng: random.Random,
                              lines: list[str]) -> list[str] | None:
        """Corrupt a `value` field: flip a digit or truncate a string."""
        candidates = [i for i, line in enumerate(lines)
                      if line.startswith("value ")]
        if not candidates:
            return None
        index = rng.choice(candidates)
        raw = lines[index][len("value "):]
        digits = [m.start() for m in _NUMBER_RE.finditer(raw)]
        if raw.startswith('"') and len(raw) >= 3:
            # truncate the quoted literal one character early
            lines[index] = "value " + raw[:-2] + '"'
            return lines
        if digits:
            pos = rng.choice(digits)
            flipped = "0" if raw[pos] != "0" else "1"
            lines[index] = ("value " + raw[:pos] + flipped
                            + raw[pos + 1:])
            return lines
        # numeric literal with no digits left to flip: grow it
        lines[index] = "value " + raw + rng.choice("0123456789")
        return lines

    @staticmethod
    def _mutate_swap_op(rng: random.Random,
                        lines: list[str]) -> list[str] | None:
        """Rename an op: add->subtract, const->copy, ..."""
        candidates = []
        for i, line in enumerate(lines):
            if line.startswith("op "):
                op = line[len("op "):].strip()
                if op in _OP_SWAPS:
                    candidates.append((i, op))
        if not candidates:
            return None
        index, op = rng.choice(candidates)
        lines[index] = "op " + _OP_SWAPS[op]
        return lines

    @staticmethod
    def _mutate_remove_line(rng: random.Random,
                            lines: list[str]) -> list[str] | None:
        """Break syntax: drop one non-empty line."""
        candidates = [i for i, line in enumerate(lines) if line.strip()]
        if not candidates:
            return None
        del lines[rng.choice(candidates)]
        return lines if lines else None

    @staticmethod
    def _mutate_duplicate_field(rng: random.Random,
                                lines: list[str]) -> list[str] | None:
        """Duplicate a field line inside a node block (duplicate-field
        grammar violation -> structured E102)."""
        candidates = [i for i, line in enumerate(lines)
                      if line.strip() and not line.startswith(("node ", "func ",
                                                               "entity ", "main"))]
        if not candidates:
            return None
        index = rng.choice(candidates)
        return lines[:index + 1] + [lines[index]] + lines[index + 1:]

    @staticmethod
    def _mutate_insert_garbage(rng: random.Random,
                               lines: list[str]) -> list[str] | None:
        """Insert a hostile line from the garbage pool."""
        if not lines:
            return None
        garbage = rng.choice(_GARBAGE_LINES)
        position = rng.randrange(len(lines) + 1)
        return lines[:position] + [garbage] + lines[position:]

    # ------------------------------------------------------------------
    # pipeline

    @staticmethod
    def _run_one(source: str) -> tuple[str, Exception | None]:
        """Classify one mutant: "valid", "structured", or "crash"."""
        with sandboxed_stdio():
            try:
                program = parse_source(source)
                analysis = analyze(program)
                execute(program, analysis)
                return "valid", None
            except StructuredError:
                return "structured", None
            except Exception as exc:  # noqa: BLE001 — the metric itself
                return "crash", exc

    def fuzz(self, source: str, count: int = 100) -> dict:
        """Mutate + run; crashes are the metric that must be zero."""
        report = {"total": count, "valid": 0, "structured_errors": 0,
                  "crashes": 0, "crash_details": []}
        for index, mutant in enumerate(self.mutate(source, count)):
            outcome, exc = self._run_one(mutant)
            if outcome == "valid":
                report["valid"] += 1
            elif outcome == "structured":
                report["structured_errors"] += 1
            else:
                report["crashes"] += 1
                report["crash_details"].append({
                    "mutant": index,
                    "exception": type(exc).__name__,
                    "detail": str(exc),
                    "source": mutant,
                })
        return report
