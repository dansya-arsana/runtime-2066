import unittest

from tests.helpers import expect_error, run_source

_TWO_PARAM = (
    "func addxy\n"
    "node 101\nop param\nindex 0\ntype i64\n\n"
    "node 102\nop param\nindex 1\ntype i64\n\n"
    "node 103\nop add\ninput 101 102\noutput i64\n\n"
    "node 104\nop return\ninput 103\n\n"
    "main\n\n"
    "node 001\nop const\ntype i64\nvalue 20\n\n"
    "node 002\nop const\ntype i64\nvalue 22\n\n"
    "node 003\nop call\ncallee addxy\ninput 001 002\noutput i64\n\n"
    "node 004\nop emit\ninput 003\n"
)


class TestCall(unittest.TestCase):
    def test_call_demo_example(self):
        emits, err = run_source(open("examples/call.ai", encoding="utf-8").read())
        self.assertIsNone(err)
        self.assertEqual(emits, [42])

    def test_two_params(self):
        emits, err = run_source(_TWO_PARAM)
        self.assertIsNone(err)
        self.assertEqual(emits, [42])

    def test_forward_reference_call_order_is_free(self):
        # main first, function later: call order does not depend on file order
        src = (
            "node 001\nop const\ntype i64\nvalue 5\n\n"
            "node 002\nop call\ncallee triple\ninput 001\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n\n"
            "func triple\n"
            "node 101\nop param\nindex 0\ntype i64\n\n"
            "node 102\nop multiply\ninput 101 101\noutput i64\n\n"
            "node 103\nop add\ninput 102 101\noutput i64\n\n"
            "node 104\nop return\ninput 103\n"
        )
        emits, err = run_source(src)  # triple(5) = 5*5 + 5 = 30
        self.assertIsNone(err)
        self.assertEqual(emits, [30])

    def test_call_in_function_body(self):
        src = (
            "func inner\n"
            "node 101\nop param\nindex 0\ntype i64\n\n"
            "node 102\nop return\ninput 101\n\n"
            "func outer\n"
            "node 201\nop param\nindex 0\ntype i64\n\n"
            "node 202\nop call\ncallee inner\ninput 201\noutput i64\n\n"
            "node 203\nop return\ninput 202\n\n"
            "main\n\n"
            "node 001\nop const\ntype i64\nvalue 7\n\n"
            "node 002\nop call\ncallee outer\ninput 001\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n"
        )
        emits, err = run_source(src)
        self.assertIsNone(err)
        self.assertEqual(emits, [7])

    def test_unknown_callee(self):
        expect_error(
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop call\ncallee ghost\ninput 001\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n",
            "E210",
        )

    def test_call_arity_mismatch(self):
        err = expect_error(
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 003\nop call\ncallee addxy\ninput 001\noutput i64\n\n"
            "node 004\nop emit\ninput 003\n\n" + _TWO_PARAM.split("main", 1)[0],
            "E211",
        )
        self.assertIn("takes 2 argument(s), received 1", err.detail)

    def test_call_type_mismatch_is_e203_with_cast_repair(self):
        src = (
            "func double\n"
            "node 101\nop param\nindex 0\ntype i64\n\n"
            "node 102\nop return\ninput 101\n\n"
            "main\n\n"
            "node 001\nop const\ntype f64\nvalue 1.5\n\n"
            "node 002\nop call\ncallee double\ninput 001\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n"
        )
        err = expect_error(src, "E203")
        self.assertEqual(err.expected, {"input[0]": "i64"})
        self.assertEqual(err.received, {"input[0]": "f64"})
        self.assertIn("cast node 001 -> i64", err.allowed_repairs)

    def test_recursion_is_rejected(self):
        src = (
            "func a\nnode 101\nop call\ncallee b\noutput i64\n\n"
            "node 102\nop return\ninput 101\n\n"
            "func b\nnode 201\nop call\ncallee a\noutput i64\n\n"
            "node 202\nop return\ninput 201\n\n"
            "main\n\n"
            "node 002\nop call\ncallee a\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n"
        )
        err = expect_error(src, "E212")
        self.assertEqual(err.detail, "call cycle: a -> b -> a")

    def test_return_outside_function(self):
        expect_error(
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop return\ninput 001\n\n"
            "node 003\nop emit\ninput 001\n",
            "E214",
        )

    def test_param_in_main(self):
        expect_error(
            "node 000\nop param\nindex 0\ntype i64\n\n"
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop emit\ninput 001\n",
            "E214",
        )

    def test_emit_inside_function(self):
        expect_error(
            "func f\n"
            "node 101\nop param\nindex 0\ntype i64\n\n"
            "node 102\nop emit\ninput 101\n\n"
            "node 103\nop return\ninput 101\n\n"
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop call\ncallee f\ninput 001\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n",
            "E214",
        )

    def test_function_without_return(self):
        expect_error(
            "func f\n"
            "node 101\nop param\nindex 0\ntype i64\n\n"
            "main\n\n"
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop call\ncallee f\ninput 001\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n",
            "E215",
        )

    def test_noncontiguous_param_indexes(self):
        expect_error(
            "func f\n"
            "node 101\nop param\nindex 0\ntype i64\n\n"
            "node 102\nop param\nindex 5\ntype i64\n\n"
            "node 103\nop return\ninput 101\n\n"
            "main\n\n"
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop call\ncallee f\ninput 001 001\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n",
            "E216",
        )

    def test_cross_scope_reference(self):
        src = (
            "func f\n"
            "node 101\nop param\nindex 0\ntype i64\n\n"
            "node 102\nop add\ninput 101 999\noutput i64\n\n"
            "node 103\nop return\ninput 102\n\n"
            "main\n\n"
            "node 999\nop const\ntype i64\nvalue 1\n\n"
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop call\ncallee f\ninput 001\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n"
        )
        err = expect_error(src, "E202")
        self.assertIn("another scope", err.detail)


if __name__ == "__main__":
    unittest.main()
