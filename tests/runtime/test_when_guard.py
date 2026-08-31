"""`when`-guarded effects (roadmap: conditionals select values; guarded
effects gate writes).

`branch` is eager — both arms' values are computed — so a denied write
MUST be gated by `when`, not hidden in an untaken arm. These tests pin
the guarantee in both adapters: a false guard leaves zero rows touched
and returns 0.
"""

import io
import os
import sys
import tempfile
import unittest

from runtime import analyze, parse_source, execute
from runtime.capabilities import GrantSet
from runtime.data import DataPlane
from runtime.plan_vm import execute_plan

GRANTS = GrantSet.from_dict({"subject": "t", "grants": [
    {"action": "data.read", "resource": "item"},
    {"action": "data.write", "resource": "item"},
]})

SRC = """entity item {
id identity
owner_id i64
label string
}

func try_insert
node 101
op param
index 0
type i64

node 102
op param
index 1
type bool

node 103
op const
type string
value "row"

node 104
op data.insert
entity item
when 102
input 101 103
output i64

node 105
op return
input 104

main

node 001
op const
type i64
value 7

node 002
op const
type bool
value true

node 003
op const
type bool
value false

node 010
op call
callee try_insert
input 001 002
output i64

node 011
op call
callee try_insert
input 001 003
output i64

node 020
op emit
input 010

node 021
op emit
input 011
"""


class TestWhenGuard(unittest.TestCase):
    def test_false_guard_inserts_nothing_both_adapters(self):
        for adapter in ("tree", "plan"):
            with self.subTest(adapter=adapter):
                db_path = os.path.join(tempfile.mkdtemp(), "guard.db")
                program = parse_source(SRC)
                analysis = analyze(program)
                db = DataPlane(db_path, program.entities, GRANTS, None)
                old_in, old_out = sys.stdin, sys.stdout
                sys.stdin, sys.stdout = io.StringIO(""), io.StringIO()
                try:
                    if adapter == "tree":
                        result = execute(program, analysis, grants=GRANTS,
                                         db=db)
                    else:
                        result = execute_plan(program, analysis,
                                              grants=GRANTS, db=db)
                    rows = db.count("t", "item", "owner_id", 7)
                finally:
                    sys.stdin, sys.stdout = old_in, old_out
                    db.close()
                # allowed call inserted id 1; denied call returned 0
                self.assertEqual(result[0], 1)
                self.assertEqual(result[1], 0)
                self.assertEqual(rows, 1, "denied write must not execute")

    def test_guard_type_is_enforced(self):
        bad = SRC.replace("node 102\nop param\nindex 1\ntype bool",
                          "node 102\nop param\nindex 1\ntype i64")
        with self.assertRaises(Exception) as ctx:
            analyze(parse_source(bad))
        self.assertIn("when guard must be bool",
                              getattr(ctx.exception, "detail", ""))


if __name__ == "__main__":
    unittest.main()
