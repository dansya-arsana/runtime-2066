import unittest

from runtime import compile_plan, execute_plan, parse_source
from tests.helpers import binary_program, example, run_source


class TestPlanVM(unittest.TestCase):
    def test_compilation_is_deterministic(self):
        plan_a = compile_plan(parse_source(example("call.ai")))
        plan_b = compile_plan(parse_source(example("call.ai")))
        self.assertEqual(plan_a, plan_b)

    def test_examples_execute_identically(self):
        expected = {
            "hello.ai": ["Hello, World!"],
            "arithmetic.ai": [50],
            "branch.ai": ["greater"],
            "call.ai": [42],
        }
        for name, want in expected.items():
            with self.subTest(example=name):
                program = parse_source(example(name))
                self.assertEqual(execute_plan(program), want)

    def test_shared_subexpression_evaluated_from_single_slot(self):
        # diamond: 002 = 001*001, 003 = 002+002 — computed once, loaded twice
        src = (
            "node 001\nop const\ntype i64\nvalue 6\n\n"
            "node 002\nop multiply\ninput 001 001\noutput i64\n\n"
            "node 003\nop add\ninput 002 002\noutput i64\n\n"
            "node 004\nop emit\ninput 003\n"
        )
        self.assertEqual(execute_plan(parse_source(src)), [72])
        plan = compile_plan(parse_source(src))
        loads = [i for i in plan.main.instrs if i.op == "LOAD"]
        # 002 loads slot(001) twice; 003 loads slot(002) twice; emit loads once
        self.assertEqual(len(loads), 5)
        mul = next(i for i in plan.main.instrs if i.op == "MUL")
        add = next(i for i in plan.main.instrs if i.op == "ADD")
        # both MUL operands load the same slot(001); ADD loads MUL's result twice
        self.assertEqual(loads[0].arg, loads[1].arg)
        self.assertEqual((loads[2].arg, loads[3].arg), (mul.out, mul.out))
        self.assertEqual(loads[4].arg, add.out)  # emit consumes ADD's slot

    def test_runtime_errors_carry_attribution(self):
        err = None
        try:
            execute_plan(parse_source(
                binary_program("divide", "i64", "7", "i64", "0", "i64")))
        except Exception as exc:  # noqa: BLE001 - structured by contract
            err = exc
        self.assertIsNotNone(err)
        self.assertEqual(err.code, "E301")
        self.assertEqual(err.node, "003")
        self.assertEqual(err.operation, "divide")

    def test_matches_tree_adapter_on_randomish_programs(self):
        programs = [
            binary_program(op, "i64", a, "i64", b, "i64")
            for op, a, b in [
                ("add", "20", "4"), ("subtract", "20", "4"),
                ("multiply", "20", "4"), ("divide", "-7", "2"),
            ]
        ] + [example("call.ai"), example("branch.ai")]
        for src in programs:
            with self.subTest(src=src.splitlines()[0] + "..." + src.splitlines()[2]):
                tree_emits, tree_err = run_source(src)
                plan_emits, plan_err = None, None
                try:
                    plan_emits = execute_plan(parse_source(src))
                except Exception as exc:  # noqa: BLE001
                    plan_err = exc
                if tree_err is not None:
                    self.assertIsNotNone(plan_err)
                    self.assertEqual(tree_err.code, plan_err.code)
                else:
                    self.assertIsNone(plan_err)
                    self.assertEqual(tree_emits, plan_emits)


if __name__ == "__main__":
    unittest.main()
