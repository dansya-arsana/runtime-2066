import unittest

from runtime import parse_source, serialize_program
from tests.helpers import example, run_source


class TestSerializer(unittest.TestCase):
    def test_round_trip_executes_identically(self):
        for name in ("hello.ai", "arithmetic.ai", "branch.ai", "call.ai"):
            with self.subTest(example=name):
                source = example(name)
                first = parse_source(source)
                text = serialize_program(first)
                second = parse_source(text)
                self.assertEqual(serialize_program(second), text)  # stable
                self.assertEqual(run_source(source)[0], run_source(text)[0])

    def test_field_order_is_canonical(self):
        scrambled = (
            "node 001\noutput i64\ninput 002 003\nop add\n\n"
            "node 003\nvalue 5\ntype i64\nop const\n\n"
            "node 002\nop const\ntype i64\nvalue 2\n\n"
            "node 004\nop emit\ninput 001\n"
        )
        text = serialize_program(parse_source(scrambled))
        self.assertIn("node 001\nop add\ninput 002 003\noutput i64", text)
        emits, err = run_source(text)
        self.assertIsNone(err)
        self.assertEqual(emits, [7])

    def test_literals_are_recanonicalized(self):
        src = (
            'node 001\nop const\ntype i64\nvalue +5\n\n'
            'node 002\nop const\ntype f64\nvalue 1.50\n\n'
            'node 003\nop const\ntype bytes\nvalue 0xDE\n\n'
            'node 004\nop const\ntype string\nvalue "a\\"b\\n"\n\n'
            "node 005\nop emit\ninput 001\n"
        )
        text = serialize_program(parse_source(src))
        self.assertIn("value 5", text)
        self.assertIn("value 1.5", text)
        self.assertIn("value 0xde", text)
        self.assertIn('value "a\\"b\\n"', text)

    def test_functions_serialize_after_main(self):
        text = serialize_program(parse_source(example("call.ai")))
        self.assertLess(text.index("node 001"), text.index("func double"))
        self.assertIn("func double\nnode 101\nop param\nindex 0\ntype i64", text)


if __name__ == "__main__":
    unittest.main()
