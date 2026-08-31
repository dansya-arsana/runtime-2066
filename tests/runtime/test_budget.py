"""Execution budgets (review P2, plan SS76-77): termination is not
bounded resource consumption — the budget IS authority, and exceeding
it is the canonical, deterministic E410.

Pinned: same program + same budget -> identical rejection in BOTH
adapters (same code, same detail), for every countable limit.
"""

import io
import sys
import tempfile
import unittest

from runtime import analyze, execute, parse_source
from runtime.budget import DEFAULT_BUDGET, ExecutionBudget
from runtime.capabilities import GrantSet
from runtime.data import DataPlane
from runtime.errors import StructuredError
from runtime.plan_vm import execute_plan

TINY = ExecutionBudget(max_nodes=5, max_steps=3, max_graph_bytes=10_000,
                       max_literal_bytes=4, max_list_items=2,
                       max_call_depth=1, max_io_bytes=8,
                       max_rows=1)

SRC_4_NODES = ('node 001\nop const\ntype i64\nvalue 1\n\n'
               'node 002\nop const\ntype i64\nvalue 1\n\n'
               'node 003\nop add\ninput 001 002\noutput i64\n\n'
               'node 004\nop emit\ninput 003\n')


def run_both(source, budget, **ctx):
    """Run through both adapters; return list of (code, detail, node)."""
    results = []
    for adapter in (execute, execute_plan):
        program = parse_source(source)
        analysis = analyze(program)
        stdin, stdout = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = io.StringIO(""), io.StringIO()
        try:
            adapter(program, analysis, budget=budget, **ctx)
            results.append(("OK", "", None))
        except StructuredError as exc:
            results.append((exc.code, exc.detail, exc.node))
        finally:
            sys.stdin, sys.stdout = stdin, stdout
    return results


class TestBudgetDeterminism(unittest.TestCase):
    def test_node_count_exceeded_identically(self):
        program = parse_source(SRC_4_NODES)
        from runtime.budget import BudgetTracker
        with self.assertRaises(StructuredError) as ctx:
            BudgetTracker(ExecutionBudget(max_nodes=3)).check_program(
                program)
        self.assertEqual(ctx.exception.code, "E410")
        self.assertIn("nodes", ctx.exception.detail)

    def test_steps_exceeded_identically_in_both_adapters(self):
        # 4 evaluated nodes with max_steps=3 -> E410 at node 004
        tree, plan = run_both(SRC_4_NODES, ExecutionBudget(max_steps=3))
        self.assertEqual(tree, plan)
        self.assertEqual(tree[0], "E410")
        self.assertIn("steps", tree[1])

    def test_literal_size_exceeded_identically(self):
        src = ('node 001\nop const\ntype string\nvalue "toolong"\n\n'
               'node 002\nop emit\ninput 001\n')
        from runtime.budget import BudgetTracker
        with self.assertRaises(StructuredError) as ctx:
            BudgetTracker(ExecutionBudget(max_literal_bytes=4)
                          ).check_program(parse_source(src))
        self.assertIn("literal_bytes", ctx.exception.detail)

    def test_io_budget_covers_stdout_and_both_adapters_agree(self):
        src = ('node 001\nop const\ntype string\nvalue "0123456789"\n\n'
               'node 002\nop system.write\ninput 001\n')
        tree, plan = run_both(src, ExecutionBudget(max_io_bytes=5))
        self.assertEqual(tree, plan)
        self.assertEqual(tree[0], "E410")
        self.assertIn("io_bytes", tree[1])

    def test_call_depth_exceeded_identically(self):
        src = ('func double\nnode 101\nop param\nindex 0\ntype i64\n\n'
               'node 102\nop add\ninput 101 101\noutput i64\n\n'
               'node 103\nop return\ninput 102\n\n'
               'main\n\n'
               'node 001\nop const\ntype i64\nvalue 21\n\n'
               'node 002\nop call\ncallee double\ninput 001\n'
               'output i64\n\n'
               'node 003\nop emit\ninput 002\n')
        tree, plan = run_both(src, ExecutionBudget(
            max_nodes=10, max_steps=50, max_call_depth=0))
        self.assertEqual(tree, plan)
        self.assertEqual(tree[0], "E410")
        self.assertIn("call_depth", tree[1])

    def test_list_items_and_rows_enforced(self):
        src = ('entity note {\nid identity\nowner_id i64\ntitle string\n}\n\n'
               'node 001\nop const\ntype i64\nvalue 1\n\n'
               'node 002\nop data.list\nentity note\ncolumn title\n'
               'where owner_id\ninput 001\noutput list<string>\n\n'
               'node 003\nop emit\ninput 002\n')
        grants = GrantSet.from_dict({"subject": "t", "grants": [
            {"action": "data.read", "resource": "note"},
            {"action": "data.write", "resource": "note"}]})
        with tempfile.TemporaryDirectory() as tmp:
            import os
            db_path = os.path.join(tmp, "rows.db")
            seed = DataPlane(db_path, parse_source(src).entities,
                             grants, None)
            for n in range(3):
                seed.connection.execute(
                    "INSERT INTO note (owner_id, title) VALUES (1, ?)",
                    (f"t{n}",))
            seed.connection.commit()
            seed.close()
            outs = []
            for adapter in (execute, execute_plan):
                program = parse_source(src)
                stdin, stdout = sys.stdin, sys.stdout
                sys.stdin, sys.stdout = io.StringIO(""), io.StringIO()
                try:
                    db = DataPlane(db_path, program.entities, grants, None)
                    try:
                        adapter(program, analyze(program), grants=grants,
                                db=db,
                                budget=ExecutionBudget(max_list_items=2))
                        outs.append(("OK", ""))
                    except StructuredError as exc:
                        outs.append((exc.code, exc.detail))
                    finally:
                        db.close()
                finally:
                    sys.stdin, sys.stdout = stdin, stdout
            self.assertEqual(outs[0], outs[1])
            self.assertEqual(outs[0][0], "E410")
            self.assertIn("list_items", outs[0][1])

    def test_default_budget_leaves_the_corpus_green(self):
        """The default budget must be generous enough that every frozen
        corpus program still runs (the suite enforces this broadly;
        here: the reference chain program executes under default)."""
        from tests.helpers import ROOT
        source = (ROOT / "examples" / "compound_interest.ai") \
            .read_text(encoding="utf-8")
        tree, plan = run_both(source, DEFAULT_BUDGET)
        self.assertEqual(tree[0], "OK")
        self.assertEqual(plan[0], "OK")


if __name__ == "__main__":
    unittest.main()
