import unittest

from runtime import parse_source
from tests.helpers import expect_error


class TestFunctionParsing(unittest.TestCase):
    def test_scopes_are_separate(self):
        program = parse_source(
            "func double\n"
            "node 101\nop param\nindex 0\ntype i64\n\n"
            "node 102\nop return\ninput 101\n\n"
            "main\n\n"
            "node 001\nop const\ntype i64\nvalue 21\n\n"
            "node 002\nop emit\ninput 001\n"
        )
        self.assertEqual(list(program.nodes), ["001", "002"])
        self.assertEqual(list(program.functions), ["double"])
        self.assertEqual(list(program.functions["double"].nodes), ["101", "102"])

    def test_main_is_default_scope(self):
        program = parse_source(
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop emit\ninput 001\n"
        )
        self.assertEqual(list(program.nodes), ["001", "002"])
        self.assertEqual(program.functions, {})

    def test_duplicate_function(self):
        expect_error(
            "func f\nnode 101\nop return\ninput 101\n\n"
            "func f\nnode 102\nop return\ninput 102\n\n"
            "node 001\nop emit\ninput 001\n",
            "E109",
        )

    def test_bad_function_name(self):
        expect_error(
            "func 9lives\nnode 101\nop return\ninput 101\n\n"
            "node 001\nop emit\ninput 001\n",
            "E109",
        )

    def test_main_header_takes_no_arguments(self):
        expect_error("main extra\nnode 001\nop emit\ninput 001\n", "E107")

    def test_node_ids_globally_unique_across_scopes(self):
        expect_error(
            "func f\nnode 001\nop return\ninput 001\n\n"
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop emit\ninput 001\n",
            "E104",
        )


if __name__ == "__main__":
    unittest.main()
