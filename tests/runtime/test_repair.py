import unittest

from runtime import repair_source
from tests.helpers import run_cli, run_source

BROKEN = open("examples/compound_interest_error.ai", encoding="utf-8").read()
CLEAN = open("examples/compound_interest.ai", encoding="utf-8").read()

MIXED_ADD = (
    "node 001\nop const\ntype i64\nvalue 1\n\n"
    "node 002\nop const\ntype f64\nvalue 2.5\n\n"
    "node 003\nop add\ninput 001 002\noutput f64\n\n"
    "node 004\nop emit\ninput 003\n"
)

UNREPAIRABLE = (
    "node 001\nop const\ntype i64\nvalue 1\n\n"
    "node 002\nop const\ntype i64\nvalue 2\n\n"
    "node 003\nop const\ntype i64\nvalue 3\n\n"
    "node 004\nop branch\ninput 001 002 003\noutput i64\n\n"
    "node 005\nop emit\ninput 004\n"
)


class TestRepairLoop(unittest.TestCase):
    def test_demo81_repair_matches_clean_execution(self):
        outcome = repair_source(BROKEN)
        self.assertTrue(outcome.repaired)
        self.assertEqual(outcome.rounds, 1)
        self.assertEqual(outcome.runtime_error, None)
        self.assertEqual(outcome.emits, run_source(CLEAN)[0])
        self.assertIn("cast node 002 -> f64 as node 011", outcome.applied[0])
        # the repaired text is itself valid canonical 2066
        self.assertEqual(run_source(outcome.program_text)[0], outcome.emits)

    def test_single_round_convergence(self):
        # repair[0] casts node 001 -> f64; after that the add is f64/f64
        outcome = repair_source(MIXED_ADD)
        self.assertTrue(outcome.repaired)
        self.assertEqual(outcome.rounds, 1)
        self.assertEqual(outcome.emits, [3.5])

    def test_unrepairable_stop_replace_only(self):
        outcome = repair_source(UNREPAIRABLE)
        self.assertFalse(outcome.repaired)
        self.assertEqual(outcome.validation_error.code, "E203")
        self.assertIn("no cast from i64 to bool", outcome.validation_error.detail)

    def test_parse_error_is_not_repairable(self):
        outcome = repair_source("hello\n")
        self.assertFalse(outcome.repaired)
        self.assertEqual(outcome.validation_error.code, "E101")
        self.assertEqual(outcome.program_text, None)

    def test_non_type_errors_are_not_repairable(self):
        outcome = repair_source("node 001\nop const\ntype i64\nvalue 1\n")
        self.assertFalse(outcome.repaired)
        self.assertEqual(outcome.validation_error.code, "E206")

    def test_cli_repair_text_mode(self):
        rc, out, err = run_cli("repair", "examples/compound_interest_error.ai")
        self.assertEqual(rc, 0)
        self.assertIn("cast node 002 -> f64", err)
        self.assertTrue(out.startswith("node 001"))
        self.assertEqual(run_source(out)[0], run_source(CLEAN)[0])

    def test_cli_repair_json_mode(self):
        rc, out, _ = run_cli("repair", "examples/compound_interest_error.ai", "--json")
        self.assertEqual(rc, 0)
        self.assertIn('"ok": true', out)
        self.assertIn('"emits": ["1.6288946267774412e+20"]', out)


if __name__ == "__main__":
    unittest.main()
