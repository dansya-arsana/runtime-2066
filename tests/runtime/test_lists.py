"""List values (M8): data.list + list.length/get/join across adapters,
capabilities, type rules, export parity, and the notes-app program."""

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from runtime import (analyze, execute, execute_plan, export_javascript,
                     export_python, parse_source, program_effects)
from runtime.capabilities import GrantSet
from runtime.data import DataPlane
from tests.helpers import ROOT, run_cli

SCHEMA = ("entity note {\nid identity\nowner_id i64\ntitle string\n}\n")
GRANTS = [("data.write", "note"), ("data.read", "note")]

LIST_PROGRAM = SCHEMA + """
node 001
op const
type i64
value 7

node 002
op const
type string
value "alpha"

node 003
op data.insert
entity note
input 001 002
output i64

node 004
op const
type string
value "beta"

node 005
op data.insert
entity note
input 001 004
output i64

node 006
op data.list
entity note
column title
where owner_id
input 001
output list<string>

node 007
op list.length
input 006
output i64

node 008
op emit
input 007

node 009
op const
type string
value " | "

node 010
op list.join
input 006 009
output string

node 011
op emit
input 010

node 012
op const
type i64
value 1

node 013
op list.get
input 006 012
output string

node 014
op emit
input 013
"""


def grants(entries):
    return GrantSet.from_dict({"subject": "t", "grants": [
        {"action": a, "resource": r} for a, r in entries]})


class TestLists(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _run(self, source, entries=GRANTS, adapter="tree"):
        program = parse_source(source)
        analysis = analyze(program)
        db_file = Path(self.tmp.name) / f"{adapter}-{id(source)}.db"
        db = DataPlane(str(db_file), program.entities, grants(entries), None)
        try:
            runner = execute if adapter == "tree" else execute_plan
            return runner(program, analysis, grants=db.grants, db=db)
        finally:
            db.close()

    def test_list_semantics_both_adapters(self):
        for adapter in ("tree", "plan"):
            with self.subTest(adapter=adapter):
                self.assertEqual(self._run(LIST_PROGRAM, adapter=adapter),
                                 [2, "alpha | beta", "beta"])

    def test_empty_list_renders_empty(self):
        # length+join only (list.get on an empty list is E308 by design);
        # rows insert for owner 7 but the list queries owner 99 -> empty
        src = LIST_PROGRAM[:LIST_PROGRAM.index("node 012")]
        src = src.replace(
            "where owner_id\ninput 001\noutput list<string>",
            "where owner_id\ninput 099\noutput list<string>")
        src += "\nnode 099\nop const\ntype i64\nvalue 99\n"
        for adapter in ("tree", "plan"):
            with self.subTest(adapter=adapter):
                self.assertEqual(self._run(src, adapter=adapter),
                                 [0, ""])

    def test_index_out_of_range_is_e308(self):
        src = LIST_PROGRAM.replace(
            "node 012\nop const\ntype i64\nvalue 1",
            "node 012\nop const\ntype i64\nvalue 5")
        with self.assertRaises(Exception) as ctx:
            self._run(src)
        self.assertEqual(ctx.exception.code, "E308")
        self.assertIn("out of range", ctx.exception.detail)

    def test_read_grant_suffices_for_listing(self):
        # write nothing: seed via SQL, list with a read-only grant
        program = parse_source(SCHEMA + """
node 001
op const
type i64
value 7

node 002
op data.list
entity note
column title
where owner_id
input 001
output list<string>

node 003
op emit
input 002
""")
        analysis = analyze(program)
        db_file = Path(self.tmp.name) / "ro.db"
        db = DataPlane(str(db_file), program.entities,
                       grants([("data.read", "note")]), None)
        db.connection.executescript(
            "CREATE TABLE IF NOT EXISTS note (id INTEGER PRIMARY KEY "
            "AUTOINCREMENT, owner_id INTEGER, title TEXT);"
            "INSERT INTO note (owner_id, title) VALUES (7,'x'),(7,'y')")
        db.connection.commit()
        self.addCleanup(db.close)
        self.assertEqual(execute(program, analysis, grants=db.grants, db=db),
                         [["x", "y"]])

    def test_default_deny_without_db(self):
        program = parse_source(SCHEMA + """
node 001
op const
type i64
value 1

node 002
op data.list
entity note
column title
where owner_id
input 001
output list<string>

node 003
op emit
input 002
""")
        for runner in (execute, execute_plan):
            with self.assertRaises(Exception) as ctx:
                runner(program, analyze(program))
            self.assertEqual(ctx.exception.code, "E401")

    def test_injection_in_where_value_is_inert(self):
        malicious = "x' OR 1=1; DROP TABLE note;--"
        src = SCHEMA + (
            json_dumps(malicious) and
            'node 001\nop const\ntype i64\nvalue 7\n\n'
            'node 002\nop const\ntype string\nvalue "real"\n\n'
            "node 003\nop data.insert\nentity note\n"
            "input 001 002\noutput i64\n\n"
            "node 004\nop data.list\nentity note\ncolumn title\n"
            "where title\ninput 005\noutput list<string>\n\n"
            "node 005\nop const\ntype string\nvalue "
            + json_dumps(malicious) + "\n\n"
            "node 006\nop list.length\ninput 004\noutput i64\n\n"
            "node 007\nop emit\ninput 006\n"
        )
        emits = self._run(src)
        # the insert succeeded; the malicious where-value matched nothing
        # and never executed as SQL — the table still has its row
        self.assertEqual(emits, [0])

    def test_type_rules(self):
        bad_join = SCHEMA + """
node 001
op const
type i64
value 7

node 002
op data.list
entity note
column owner_id
where owner_id
input 001
output list<i64>

node 003
op const
type string
value ","

node 004
op list.join
input 002 003
output string

node 005
op emit
input 004
"""
        with self.assertRaises(Exception) as ctx:
            analyze(parse_source(bad_join))
        self.assertEqual(ctx.exception.code, "E203")
        self.assertIn("list<string>", str(ctx.exception.expected))

        bad_index = SCHEMA + """
node 001
op const
type i64
value 7

node 002
op data.list
entity note
column title
where owner_id
input 001
output list<string>

node 003
op const
type string
value "0"

node 004
op list.get
input 002 003
output string

node 005
op emit
input 004
"""
        with self.assertRaises(Exception) as ctx:
            analyze(parse_source(bad_index))
        self.assertEqual(ctx.exception.code, "E203")

    def test_effects_manifest(self):
        self.assertIn("DATA_READ",
                      program_effects(parse_source(LIST_PROGRAM)))

    def test_export_refuses_data_list(self):
        # data.list is capability-gated: both exporters refuse it
        src = SCHEMA + (
            "node 001\nop const\ntype i64\nvalue 7\n\n"
            "node 002\nop data.list\nentity note\ncolumn title\n"
            "where owner_id\ninput 001\noutput list<string>\n\n"
            "node 003\nop list.length\ninput 002\noutput i64\n\n"
            "node 004\nop emit\ninput 003\n")
        for exporter in (export_python, export_javascript):
            with self.subTest(exporter=exporter.__name__):
                with self.assertRaises(ValueError) as ctx:
                    exporter(parse_source(src))
                self.assertIn("DATA_READ", str(ctx.exception))
        # and the full list program is refused for the same reason
        with self.assertRaises(ValueError):
            export_python(parse_source(LIST_PROGRAM))

    def test_notes_app_list_program_validates(self):
        source = (ROOT / "examples/notes_app/list_notes.ai").read_text(
            encoding="utf-8")
        analyze(parse_source(source))

    def test_cli_list_run(self):
        db = str(Path(self.tmp.name) / "cli.db")
        program_path = Path(self.tmp.name) / "p.ai"
        program_path.write_text(LIST_PROGRAM, encoding="utf-8")
        # --db without --caps: grants absent, data ops default-deny (exit 4)
        rc, _, err = run_cli("run", str(program_path), "--db", db)
        self.assertEqual(rc, 4)
        self.assertIn("E401", err)
        caps = Path(self.tmp.name) / "caps.json"
        caps.write_text(__import__("json").dumps({
            "subject": "t", "grants": [
                {"action": a, "resource": r} for a, r in GRANTS]}),
            encoding="utf-8")
        rc, out, err = run_cli("run", str(program_path), "--db", db,
                               "--caps", str(caps))
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(out, "2\nalpha | beta\nbeta\n")


def json_dumps(value):
    import json
    return json.dumps(value)


if __name__ == "__main__":
    unittest.main()
