import unittest
from pathlib import Path

from tests.helpers import run_source

FIXTURES = Path(__file__).resolve().parent


class TestInvalidPrograms(unittest.TestCase):
    def test_every_fixture_fails_with_its_declared_error_code(self):
        fixtures = sorted(FIXTURES.glob("*.ai"))
        self.assertGreaterEqual(len(fixtures), 10)
        for path in fixtures:
            with self.subTest(program=path.name):
                expected = path.with_suffix(".expected").read_text(encoding="utf-8").strip()
                _, err = run_source(path.read_text(encoding="utf-8"))
                self.assertIsNotNone(err, f"{path.name} unexpectedly executed")
                self.assertEqual(err.code, expected)
                self.assertEqual(err.render(), err.render())  # stable rendering

    def test_type_mismatch_error_shape(self):
        src = (FIXTURES / "add_type_mismatch.ai").read_text(encoding="utf-8")
        _, err = run_source(src)
        self.assertEqual(err.node, "003")
        self.assertEqual(err.operation, "add")
        self.assertEqual(err.expected, {"input[0]": "i64", "input[1]": "i64"})
        self.assertEqual(err.received, {"input[0]": "i64", "input[1]": "string"})
        self.assertEqual(
            err.allowed_repairs, ["cast node 002 -> i64", "replace node 002"])
        text = err.render()
        for fragment in (
            "ERROR E203", "node: 003", "operation: add", "expected:",
            "input[1]: string", "allowed_repairs:", "- cast node 002 -> i64",
        ):
            self.assertIn(fragment, text)

    def test_cycle_error_names_the_cycle(self):
        src = (FIXTURES / "cycle.ai").read_text(encoding="utf-8")
        _, err = run_source(src)
        self.assertEqual(err.code, "E204")
        self.assertEqual(err.detail, "dependency cycle: 001 -> 002 -> 003 -> 001")


if __name__ == "__main__":
    unittest.main()
