"""Appendix F.3 proof: the same canonical program produces equivalent
results (and equivalent structured errors) through both execution adapters,
across the whole example corpus plus adversarial runtime-error programs."""

import unittest

from runtime import analyze, execute, execute_plan, parse_source
from tests.helpers import binary_program, example, run_cli
from runtime.types import format_value

CORPUS = [example(name) for name in
          ("hello.ai", "arithmetic.ai", "branch.ai", "call.ai",
           "compound_interest.ai")] + [
    # runtime errors must be identical across adapters too
    binary_program("divide", "i64", "7", "i64", "0", "i64"),        # E301
    binary_program("add", "i64", str(2**63 - 1), "i64", "1", "i64"),  # E302
    binary_program("multiply", "i64", "3037000500", "i64", "3037000500", "i64"),
    binary_program("divide", "f64", "0.0", "f64", "0.0", "f64"),    # nan
    binary_program("divide", "f64", "-1.0", "f64", "0.0", "f64"),   # -inf
    # cast errors
    ("node 001\nop const\ntype f64\nvalue 1.0e300\n\n"
     "node 002\nop cast\ninput 001\noutput i64\n\n"
     "node 003\nop emit\ninput 002\n"),                              # E303
    ("node 001\nop const\ntype string\nvalue \"abc\"\n\n"
     "node 002\nop cast\ninput 001\noutput i64\n\n"
     "node 003\nop emit\ninput 002\n"),                              # E304
    # call + branch + compare depth
    ("func classify\n"
     "node 101\nop param\nindex 0\ntype i64\n\n"
     "node 102\nop compare\nmode gt\ninput 101 101\noutput bool\n\n"
     "node 103\nop const\ntype string\nvalue \"sq-or-zero\"\n\n"
     "node 104\nop branch\ninput 102 103 103\noutput string\n\n"
     "node 105\nop return\ninput 104\n\n"
     "main\n\n"
     "node 001\nop const\ntype i64\nvalue 9\n\n"
     "node 002\nop call\ncallee classify\ninput 001\noutput string\n\n"
     "node 003\nop emit\ninput 002\n"),
]


def _run(adapter: str, source: str):
    program = parse_source(source)
    analysis = analyze(program)
    runner = execute if adapter == "tree" else execute_plan
    try:
        return runner(program, analysis), None
    except Exception as exc:  # noqa: BLE001 - StructuredError by contract
        return None, exc


class TestAdapterEquivalence(unittest.TestCase):
    def test_corpus_produces_identical_results_and_errors(self):
        for index, source in enumerate(CORPUS):
            with self.subTest(case=index):
                tree_emits, tree_err = _run("tree", source)
                plan_emits, plan_err = _run("plan", source)
                if tree_err is not None or plan_err is not None:
                    self.assertIsNotNone(tree_err)
                    self.assertIsNotNone(plan_err)
                    self.assertEqual(tree_err.code, plan_err.code)
                    self.assertEqual(tree_err.node, plan_err.node)
                    self.assertEqual(tree_err.operation, plan_err.operation)
                    self.assertEqual(tree_err.render(), plan_err.render())
                else:
                    self.assertIsNone(plan_err)
                    # render through format_value: NaN and inf must compare
                    # by canonical rendering, not float identity
                    self.assertEqual([format_value(v) for v in tree_emits],
                                     [format_value(v) for v in plan_emits])

    def test_cli_plan_adapter_end_to_end(self):
        for name, want in [("hello.ai", "Hello, World!\n"),
                           ("arithmetic.ai", "50\n"),
                           ("compound_interest.ai", "1.6288946267774412e+20\n")]:
            with self.subTest(example=name):
                rc, out, err = run_cli("run", f"examples/{name}", "--adapter", "plan")
                self.assertEqual((rc, out, err), (0, want, ""))

    def test_cli_rejects_unknown_adapter(self):
        self.assertEqual(run_cli("run", "examples/hello.ai", "--adapter", "wasi")[0], 3)
        self.assertEqual(run_cli("run", "examples/hello.ai", "--adapter")[0], 3)


if __name__ == "__main__":
    unittest.main()
