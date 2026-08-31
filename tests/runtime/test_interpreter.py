import unittest

from runtime.types import format_value
from tests.helpers import binary_program, example, expect_error, run_source

I64_MAX = 2**63 - 1
I64_MIN = -(2**63)


class TestInterpreter(unittest.TestCase):
    # --- milestone programs -------------------------------------------------

    def test_hello_world(self):
        emits, err = run_source(example("hello.ai"))
        self.assertIsNone(err)
        self.assertEqual(emits, ["Hello, World!"])

    def test_arithmetic_poc_is_50(self):
        emits, err = run_source(example("arithmetic.ai"))
        self.assertIsNone(err)
        self.assertEqual(emits, [50])

    def test_branch_example(self):
        emits, _ = run_source(example("branch.ai"))
        self.assertEqual(emits, ["greater"])

    # --- i64 arithmetic -----------------------------------------------------

    def test_i64_binary_ops(self):
        cases = {
            "add": 24, "subtract": 16, "multiply": 80, "divide": 5,
        }
        for op, expected in cases.items():
            with self.subTest(op=op):
                emits, err = run_source(binary_program(op, "i64", "20", "i64", "4", "i64"))
                self.assertIsNone(err)
                self.assertEqual(emits, [expected])

    def test_i64_division_truncates_toward_zero(self):
        for a, b, expected in [(-7, 2, -3), (7, -2, -3), (-7, -2, 3), (7, 2, 3)]:
            with self.subTest(a=a, b=b):
                emits, err = run_source(
                    binary_program("divide", "i64", str(a), "i64", str(b), "i64"))
                self.assertIsNone(err)
                self.assertEqual(emits, [expected])

    def test_i64_division_by_zero_is_e301(self):
        err = expect_error(binary_program("divide", "i64", "7", "i64", "0", "i64"), "E301")
        self.assertEqual(err.node, "003")
        self.assertEqual(err.operation, "divide")

    def test_i64_overflow_is_e302(self):
        expect_error(
            binary_program("add", "i64", str(I64_MAX), "i64", "1", "i64"), "E302")
        expect_error(
            binary_program("multiply", "i64", "3037000500", "i64", "3037000500", "i64"),
            "E302")
        expect_error(
            binary_program("divide", "i64", str(I64_MIN), "i64", "-1", "i64"), "E302")

    # --- f64 arithmetic -----------------------------------------------------

    def test_f64_arithmetic(self):
        emits, err = run_source(
            binary_program("add", "f64", "1.5", "f64", "2.25", "f64"))
        self.assertIsNone(err)
        self.assertEqual(emits, [3.75])
        self.assertEqual(format_value(emits[0]), "3.75")

    def test_f64_division_by_zero_is_ieee_total(self):
        cases = [("1.0", "inf"), ("-1.0", "-inf"), ("0.0", "nan")]
        for v, expected in cases:
            with self.subTest(value=v):
                emits, err = run_source(
                    binary_program("divide", "f64", v, "f64", "0.0", "f64"))
                self.assertIsNone(err)
                self.assertEqual(format_value(emits[0]), expected)

    def test_mixed_i64_f64_is_e203_with_repairs(self):
        err = expect_error(
            binary_program("add", "i64", "1", "f64", "2.5", "f64"), "E203")
        self.assertEqual(err.received, {"input[0]": "i64", "input[1]": "f64"})
        self.assertEqual(
            err.allowed_repairs, ["cast node 001 -> f64", "cast node 002 -> i64"])

    def test_type_mismatch_matches_spec_example_shape(self):
        err = expect_error(
            binary_program("add", "i64", "10", "string", '"5"', "i64"), "E203")
        self.assertEqual(err.node, "003")
        self.assertEqual(err.operation, "add")
        self.assertEqual(err.expected, {"input[0]": "i64", "input[1]": "i64"})
        self.assertEqual(err.received, {"input[0]": "i64", "input[1]": "string"})
        self.assertEqual(
            err.allowed_repairs, ["cast node 002 -> i64", "replace node 002"])

    # --- compare / branch / copy / literals ----------------------------------

    def test_compare_modes(self):
        def compare(mode, t0, v0, t1, v1):
            return binary_program("compare", t0, v0, t1, v1, "bool",
                                  extra=f"mode {mode}\n")

        for mode, t0, v0, t1, v1, expected in [
            ("eq", "string", '"abc"', "string", '"abc"', True),
            ("ne", "string", '"abc"', "string", '"abd"', True),
            ("lt", "string", '"a"', "string", '"b"', True),
            ("gt", "i64", "10", "i64", "4", True),
            ("le", "f64", "1.5", "f64", "1.5", True),
            ("ge", "i64", "3", "i64", "4", False),
        ]:
            with self.subTest(mode=mode):
                emits, err = run_source(compare(mode, t0, v0, t1, v1))
                self.assertIsNone(err)
                self.assertEqual(emits, [expected])

    def test_branch_selects_false_arm(self):
        src = (
            "node 001\nop const\ntype bool\nvalue false\n\n"
            "node 002\nop const\ntype i64\nvalue 1\n\n"
            "node 003\nop const\ntype i64\nvalue 2\n\n"
            "node 004\nop branch\ninput 001 002 003\noutput i64\n\n"
            "node 005\nop emit\ninput 004\n"
        )
        emits, err = run_source(src)
        self.assertIsNone(err)
        self.assertEqual(emits, [2])

    def test_copy_passthrough(self):
        src = (
            'node 001\nop const\ntype string\nvalue "kept"\n\n'
            "node 002\nop copy\ninput 001\n\n"
            "node 003\nop emit\ninput 002\n"
        )
        emits, err = run_source(src)
        self.assertIsNone(err)
        self.assertEqual(emits, ["kept"])

    def test_literal_kinds_render_canonically(self):
        cases = [
            ("bool", "true", "true"),
            ("bool", "false", "false"),
            ("i64", "-7", "-7"),
            ("f64", "1.05", "1.05"),
            ("null", "null", "null"),
            ("bytes", "0xDEadBEef", "0xdeadbeef"),
            ("string", '"line\\nbreak"', "line\nbreak"),
        ]
        for type_name, literal, expected in cases:
            with self.subTest(type=type_name):
                src = (
                    f"node 001\nop const\ntype {type_name}\nvalue {literal}\n\n"
                    "node 002\nop emit\ninput 001\n"
                )
                emits, err = run_source(src)
                self.assertIsNone(err)
                self.assertEqual(format_value(emits[0]), expected)

    def test_bytes_equality(self):
        emits, err = run_source(
            binary_program("compare", "bytes", "0xAA", "bytes", "0xaa", "bool",
                           extra="mode eq\n"))
        self.assertIsNone(err)
        self.assertEqual(emits, [True])

    def test_emit_order_is_node_id_order_not_declaration_order(self):
        src = (
            'node 020\nop const\ntype string\nvalue "b"\n\n'
            'node 007\nop const\ntype string\nvalue "a"\n\n'
            "node 021\nop emit\ninput 020\n\n"
            "node 008\nop emit\ninput 007\n"
        )
        emits, err = run_source(src)
        self.assertIsNone(err)
        self.assertEqual(emits, ["a", "b"])


if __name__ == "__main__":
    unittest.main()
