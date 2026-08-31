"""Stress test: a generated 2,000-node graph across the whole pipeline.

Parser -> validator -> tree adapter -> plan adapter -> export -> executed as
standalone Python. Same answer everywhere, and fast enough to be a usable
development loop."""

import subprocess
import sys
import time
import unittest

from runtime import analyze, execute, execute_plan, export_python, parse_source
from tests.helpers import ROOT, run_cli


def chain_program(length: int) -> str:
    """node 000 = +1; nodes 001..N each add 1 to the previous total."""
    lines = [
        "node 000\nop const\ntype i64\nvalue 1\n\n",
        "node 001\nop const\ntype i64\nvalue 0\n\n",
    ]
    prev = "001"
    for i in range(2, length):
        node_id = f"{i:04d}"
        lines.append(f"node {node_id}\nop add\ninput {prev} 000\noutput i64\n\n")
        prev = node_id
    lines.append(f"node {int(prev) + 1:04d}\nop emit\ninput {prev}\n")
    return "".join(lines)


class TestStress(unittest.TestCase):
    LENGTH = 2000

    def test_full_pipeline_on_generated_graph(self):
        src = chain_program(self.LENGTH)
        node_count = src.count("op ")
        self.assertGreaterEqual(node_count, self.LENGTH)

        start = time.perf_counter()
        program = parse_source(src)
        analysis = analyze(program)
        parse_validate = time.perf_counter() - start

        start = time.perf_counter()
        tree = execute(program, analysis)
        tree_time = time.perf_counter() - start

        start = time.perf_counter()
        plan = execute_plan(program, analysis)
        plan_time = time.perf_counter() - start

        expected = [self.LENGTH - 2]  # N-2 additions of 1 starting from 0
        self.assertEqual(tree, expected)
        self.assertEqual(plan, expected)

        # export -> standalone python -> same answer
        start = time.perf_counter()
        generated = export_python(program, analysis)
        export_time = time.perf_counter() - start
        out_file = ROOT / "stress_export.py"
        out_file.write_text(generated, encoding="utf-8")
        try:
            proc = subprocess.run(
                [sys.executable, out_file.name],
                capture_output=True, text=True, cwd=ROOT, timeout=120,
            )
        finally:
            out_file.unlink(missing_ok=True)
        self.assertEqual((proc.returncode, proc.stdout),
                         (0, f"{self.LENGTH - 2}\n"))

        # generous bounds: this must stay a fast development loop
        self.assertLess(parse_validate, 10.0)
        self.assertLess(tree_time, 10.0)
        self.assertLess(plan_time, 10.0)
        self.assertLess(export_time, 10.0)
        print(f"\nstress: {node_count} nodes | parse+validate "
              f"{parse_validate:.3f}s | tree {tree_time:.3f}s | "
              f"plan {plan_time:.3f}s | export {export_time:.3f}s")

    def test_cli_on_generated_graph(self):
        src_path = ROOT / "stress_chain.ai"
        src_path.write_text(chain_program(500), encoding="utf-8")
        try:
            rc, out, err = run_cli("run", "stress_chain.ai")
            self.assertEqual((rc, out, err), (0, "498\n", ""))
            rc, out, _ = run_cli("run", "stress_chain.ai", "--adapter", "plan")
            self.assertEqual((rc, out), (0, "498\n"))
            rc, _, _ = run_cli("hash", "stress_chain.ai")
            self.assertEqual(rc, 0)
        finally:
            src_path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
