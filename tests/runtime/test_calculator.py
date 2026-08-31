"""Calculator app + styled page generation + export parity (the stress-test
deliverables): a real interactive program, browser-ready output, and the
same program running as standalone Python outside the runtime."""

import json
import subprocess
import sys
import unittest
from pathlib import Path

from runtime import execute, execute_plan, parse_source, analyze, export_python
from tests.helpers import ROOT, example, run_cli

INPUTS = [
    ("12\n+\n3.5\n", "a = op = b = result = 15.5\n"),
    ("6\n*\n7\n", "a = op = b = result = 42.0\n"),
    ("7\n-\n9\n", "a = op = b = result = -2.0\n"),
    ("10\n/\n0\n", "a = op = b = error: division by zero\n"),
    ("7\n%\n2\n", "a = op = b = error: invalid operator\n"),
]

CALC = "examples/calculator.ai"


class TestCalculator(unittest.TestCase):
    def test_interactive_cases(self):
        for stdin_text, expected in INPUTS:
            with self.subTest(stdin=stdin_text.replace("\n", " ")):
                rc, out, err = run_cli("run", CALC, stdin=stdin_text)
                self.assertEqual((rc, out, err), (0, expected, ""))

    def test_plan_adapter_identical(self):
        for stdin_text, expected in INPUTS:
            with self.subTest(stdin=stdin_text.replace("\n", " ")):
                rc, out, err = run_cli("run", CALC, "--adapter", "plan",
                                       stdin=stdin_text)
                self.assertEqual((rc, out, err), (0, expected, ""))

    def test_structured_error_on_garbage_number(self):
        rc, out, err = run_cli("run", CALC, stdin="abc\n+\n1\n")
        self.assertEqual(rc, 2)
        self.assertTrue(err.startswith("ERROR E304"), err)
        self.assertIn("node: 010", err)  # the cast node, for repair loops


class TestStyledPage(unittest.TestCase):
    def test_generates_html_with_css_via_capability_write(self):
        html_path = ROOT / "examples" / "out" / "calculator.html"
        rc, out, err = run_cli("run", "examples/calculator_page.ai",
                               "--caps", "examples/caps_write.json")
        self.assertEqual((rc, err), (0, ""))
        written = int(out.strip())
        html = html_path.read_text(encoding="utf-8")
        self.assertEqual(written, len(html.encode("utf-8")))
        self.assertIn("<style>", html)
        self.assertIn(".result{", html)          # real CSS rules
        self.assertIn("42.0", html)               # computed 12 × 3.5
        self.assertIn("</html>", html)

    def test_page_write_denied_without_caps(self):
        rc, _, err = run_cli("run", "examples/calculator_page.ai")
        self.assertEqual(rc, 4)
        self.assertTrue(err.startswith("ERROR E401"), err)


class TestExportParity(unittest.TestCase):
    """§10 export backend: the same .ai runs as standalone Python."""

    def test_exported_calculator_matches_runtime(self):
        generated_path = ROOT / "calc_parity.py"
        rc, _, err = run_cli("export", CALC, "--target", "python",
                             "--out", "calc_parity.py")
        self.assertEqual((rc, err), (0, f"exported {CALC} -> calc_parity.py "
                                        "(target: python)\n"))
        try:
            for stdin_text, expected in INPUTS:
                runtime_out = subprocess.run(
                    [sys.executable, "-m", "runtime", "run", CALC],
                    input=stdin_text, capture_output=True, text=True,
                    cwd=ROOT, timeout=60)
                exported_out = subprocess.run(
                    [sys.executable, generated_path.name],
                    input=stdin_text, capture_output=True, text=True,
                    cwd=ROOT, timeout=60)
                self.assertEqual(runtime_out.stdout, expected)
                self.assertEqual(exported_out.returncode, 0)
                self.assertEqual(exported_out.stdout, runtime_out.stdout)
        finally:
            generated_path.unlink(missing_ok=True)

    def test_export_preserves_i64_semantics(self):
        src = (
            "node 001\nop const\ntype i64\nvalue -7\n\n"
            "node 002\nop const\ntype i64\nvalue 2\n\n"
            "node 003\nop divide\ninput 001 002\noutput i64\n\n"
            "node 004\nop emit\ninput 003\n"
        )
        generated = export_python(parse_source(src))
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            exec(compile(generated, "<exported>", "exec"), {})
        self.assertEqual(buffer.getvalue(), "-3\n")  # truncates toward zero

    def test_export_overflow_raises_like_runtime(self):
        src = (
            "node 001\nop const\ntype i64\nvalue 9223372036854775807\n\n"
            "node 002\nop const\ntype i64\nvalue 1\n\n"
            "node 003\nop add\ninput 001 002\noutput i64\n\n"
            "node 004\nop emit\ninput 003\n"
        )
        generated = export_python(parse_source(src))
        with self.assertRaises(OverflowError) as ctx:
            exec(compile(generated, "<exported>", "exec"), {})
        self.assertIn("E302", str(ctx.exception))

    def test_export_refuses_capability_gated_effects(self):
        program = parse_source(example("file_read.ai"))
        with self.assertRaises(ValueError) as ctx:
            export_python(program, analyze(program))
        self.assertIn("FILESYSTEM_READ", str(ctx.exception))

    def test_export_is_deterministic_and_hashed(self):
        source = open(ROOT / CALC, encoding="utf-8").read()
        a = export_python(parse_source(source))
        b = export_python(parse_source(source))
        self.assertEqual(a, b)
        self.assertIn("# Generated by the 2066 runtime from canonical "
                      "program sha256:", a)


if __name__ == "__main__":
    unittest.main()
