import unittest

from tests.helpers import expect_error, run_source
from runtime.types import format_value


def cast_program(value_type: str, literal: str, target: str) -> str:
    return (
        f"node 001\nop const\ntype {value_type}\nvalue {literal}\n\n"
        "node 002\nop cast\ninput 001\n"
        f"output {target}\n\n"
        "node 003\nop emit\ninput 002\n"
    )


def div_program(a: str, b: str) -> str:
    return (
        f"node 001\nop const\ntype f64\nvalue {a}\n\n"
        f"node 002\nop const\ntype f64\nvalue {b}\n\n"
        "node 003\nop divide\ninput 001 002\noutput f64\n\n"
        "node 004\nop cast\ninput 003\noutput i64\n\n"
        "node 005\nop emit\ninput 004\n"
    )


class TestCast(unittest.TestCase):
    def test_numeric_and_string_conversions(self):
        cases = [
            ("i64", "100", "f64", 100.0, "100.0"),
            ("f64", "2.9", "i64", 2, "2"),
            ("f64", "-2.9", "i64", -2, "-2"),
            ("string", '"42"', "i64", 42, "42"),
            ("string", '"1.05"', "f64", 1.05, "1.05"),
            ("i64", "42", "string", "42", "42"),
            ("f64", "1.5", "string", "1.5", "1.5"),
            ("bool", "true", "string", "true", "true"),
        ]
        for value_type, literal, target, value, rendered in cases:
            with self.subTest(f"{value_type}->{target}"):
                emits, err = run_source(cast_program(value_type, literal, target))
                self.assertIsNone(err)
                self.assertEqual(emits, [value])
                self.assertEqual(format_value(emits[0]), rendered)

    def test_identity_cast_allowed(self):
        emits, err = run_source(cast_program("i64", "7", "i64"))
        self.assertIsNone(err)
        self.assertEqual(emits, [7])

    def test_f64_not_representable_is_e303(self):
        expect_error(cast_program("f64", "1.0e300", "i64"), "E303")

    def test_nan_and_inf_cast_to_e303(self):
        expect_error(div_program("0.0", "0.0"), "E303")   # 0/0 = nan
        expect_error(div_program("1.0", "0.0"), "E303")   # 1/0 = inf

    def test_unparseable_string_is_e304(self):
        expect_error(cast_program("string", '"abc"', "i64"), "E304")
        expect_error(cast_program("string", '"1.5"', "i64"), "E304")
        expect_error(cast_program("string", '"nope"', "f64"), "E304")

    def test_disallowed_cast_pair_is_e203(self):
        err = expect_error(cast_program("bool", "true", "i64"), "E203")
        self.assertIn("no cast from bool to i64", err.detail)

    def test_cast_demo_usage_in_examples(self):
        # compound_interest.ai casts 100 (i64) -> f64, then multiplies the
        # same explicit chain the graph spells out (no pow shortcut).
        with open("examples/compound_interest.ai", encoding="utf-8") as fh:
            emits, err = run_source(fh.read())
        self.assertIsNone(err)
        base = 100 * 1.05
        b2 = base * base
        b4 = b2 * b2
        b8 = b4 * b4
        expected = b8 * base * base  # nodes 008 and 009
        self.assertEqual(emits, [expected])


if __name__ == "__main__":
    unittest.main()
