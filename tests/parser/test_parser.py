import unittest

from runtime import parse_source
from tests.helpers import example, expect_error


class TestParser(unittest.TestCase):
    def test_hello_structure(self):
        program = parse_source(example("hello.ai"))
        self.assertEqual(list(program.nodes), ["001", "002"])
        self.assertEqual(program.nodes["001"].field("op"), "const")
        self.assertEqual(program.nodes["001"].field("value"), '"Hello, World!"')
        self.assertEqual(program.nodes["002"].field("op"), "emit")
        self.assertEqual([ref for ref, _ in program.nodes["002"].inputs], ["001"])

    def test_arithmetic_structure(self):
        node = parse_source(example("arithmetic.ai")).nodes["003"]
        self.assertEqual(node.field("op"), "multiply")
        self.assertEqual(node.field("output"), "i64")
        self.assertEqual([ref for ref, _ in node.inputs], ["001", "002"])

    def test_comments_ignored_and_hash_inside_string_kept(self):
        src = (
            "# leading comment\n"
            "node 001  # header comment\n"
            "op const\n"
            'value "a # b # \\"c\\""\n'
            "type string\n"
            "\n"
            "node 002\n"
            "op emit\n"
            "input 001\n"
        )
        program = parse_source(src)
        self.assertEqual(program.nodes["001"].field("value"), '"a # b # \\"c\\""')

    def test_statement_outside_block(self):
        expect_error("op const\n", "E101")

    def test_duplicate_node_id(self):
        src = (
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 001\nop const\ntype i64\nvalue 2\n\n"
            "node 002\nop emit\ninput 001\n"
        )
        expect_error(src, "E104")

    def test_unknown_field(self):
        src = (
            "node 001\nop const\ntype i64\nvalue 1\ncolour blue\n\n"
            "node 002\nop emit\ninput 001\n"
        )
        expect_error(src, "E102")

    def test_duplicate_field(self):
        src = (
            "node 001\nop const\ntype i64\ntype i64\nvalue 1\n\n"
            "node 002\nop emit\ninput 001\n"
        )
        expect_error(src, "E102")

    def test_node_id_must_be_digits(self):
        src = (
            "node a1\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop emit\ninput a1\n"
        )
        expect_error(src, "E107")

    def test_node_header_without_id(self):
        expect_error("node\nop const\n", "E107")

    def test_empty_program(self):
        expect_error("# nothing here\n", "E108")


if __name__ == "__main__":
    unittest.main()
