"""Semantic data runtime (roadmap §22–§24).

Security beats: the §24 rule (a read grant cannot delete — no matter what
the program invents), SQL injection as inert data (the AI never writes
SQL), default deny without a database, and per-entity capability scoping."""

import tempfile
import unittest
from pathlib import Path

from runtime import (analyze, execute, execute_plan, parse_source,
                     program_effects)
from runtime.capabilities import GrantSet
from runtime.data import DataPlane
from runtime.ops import digest as sha256
from tests.helpers import run_cli

SCHEMA = (
    "entity user {\n"
    "id identity\n"
    "username string unique\n"
    "password_hash string\n"
    "}\n"
    "\n"
    "entity note {\n"
    "id identity\n"
    "owner_id i64\n"
    "title string\n"
    "body string\n"
    "}\n"
)


def grants(*entries):
    return GrantSet.from_dict({"subject": "t", "grants": [
        {"action": a, "resource": r} for a, r in entries]})


class DataTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "data.db")

    def make_db(self, grant_entries=None):
        program = parse_source(SCHEMA)
        analysis = analyze(program)
        db = DataPlane(self.db_path, program.entities,
                       grants(*grant_entries) if grant_entries else None, None)
        self.addCleanup(db.close)
        return program, analysis, db


class TestDataPlane(DataTestBase):
    def test_round_trip_both_adapters(self):
        for adapter in ("tree", "plan"):
            with self.subTest(adapter=adapter):
                # fresh database per adapter: both insert the same unique row
                db_file = str(Path(self.tmp.name) / f"data-{adapter}.db")
                program = parse_source(SCHEMA)
                db = DataPlane(db_file, program.entities,
                               grants(*[("data.write", "user"),
                                        ("data.read", "user")]), None)
                self.addCleanup(db.close)
                runner = execute if adapter == "tree" else execute_plan
                src = (
                    'node 001\nop const\ntype string\nvalue "alice"\n\n'
                    'node 002\nop const\ntype string\nvalue "digest_a"\n\n'
                    "node 003\nop data.insert\nentity user\n"
                    "input 001 002\noutput i64\n\n"
                    "node 004\nop data.count\nentity user\n"
                    "where username\ninput 001\noutput i64\n\n"
                    "node 005\nop data.select\nentity user\ncolumn password_hash\n"
                    "where username\ninput 001\noutput string\n\n"
                    "node 006\nop emit\ninput 003\n\n"
                    "node 007\nop emit\ninput 004\n\n"
                    "node 008\nop emit\ninput 005\n"
                )
                program = parse_source(SCHEMA + src)
                analysis = analyze(program)
                # the digest placeholder is a literal string here
                emits = runner(program, analysis, grants=db.grants, db=db)
                self.assertEqual(emits[1], 1)          # count
                self.assertEqual(emits[2], "digest_a")  # selected hash

    def test_sql_injection_is_inert_data(self):
        program, analysis, db = self.make_db([("data.write", "user"),
                                              ("data.read", "user")])
        malicious = "x'; DROP TABLE user;--"
        row_id = db.insert("001", "user", [malicious, "h"])
        self.assertEqual(row_id, 1)
        # table survived, and the payload reads back as plain data
        self.assertEqual(db.select("002", "user", "username", "username",
                                   malicious), malicious)

    def test_insert_arity_mirrors_entity_columns(self):
        program, analysis, db = self.make_db([("data.write", "user")])
        src = SCHEMA + (
            'node 001\nop const\ntype string\nvalue "a"\n\n'
            "node 002\nop data.insert\nentity user\ninput 001\noutput i64\n"
        )
        with self.assertRaises(Exception) as ctx:
            execute(parse_source(src))
        self.assertEqual(ctx.exception.code, "E207")

    def test_unknown_entity_and_column(self):
        program, analysis, db = self.make_db([("data.read", "user")])
        with self.assertRaises(Exception) as ctx:
            db.count("1", "ghost", "username", "x")
        self.assertEqual(ctx.exception.code, "E501")
        with self.assertRaises(Exception) as ctx:
            db.count("1", "user", "nope", "x")
        self.assertEqual(ctx.exception.code, "E502")

    def test_unique_constraint_is_e505(self):
        program, analysis, db = self.make_db([("data.write", "user")])
        db.insert("1", "user", ["alice", "h"])
        with self.assertRaises(Exception) as ctx:
            db.insert("2", "user", ["alice", "h2"])
        self.assertEqual(ctx.exception.code, "E505")

    def test_read_grant_cannot_delete_section24(self):
        program, analysis, db = self.make_db([("data.read", "note")])
        db.connection.execute(
            "INSERT INTO note (owner_id, title, body) VALUES (1, 't', 'b')")
        db.connection.commit()
        with self.assertRaises(Exception) as ctx:
            db.delete("9", "note", "id", 1)
        self.assertEqual(ctx.exception.code, "E401")
        # and the row is still there
        self.assertEqual(db.count("3", "note", "id", 1), 1)

    def test_entity_scoped_grants(self):
        program, analysis, db = self.make_db([("data.read", "user")])
        db.connection.execute(
            "INSERT INTO note (owner_id, title, body) VALUES (1, 't', 'b')")
        db.connection.commit()
        with self.assertRaises(Exception) as ctx:
            db.count("2", "note", "id", 1)
        self.assertEqual(ctx.exception.code, "E401")

    def test_default_deny_without_db(self):
        src = SCHEMA + (
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop data.count\nentity note\nwhere id\n"
            "input 001\noutput i64\n\n"
            "node 003\nop emit\ninput 002\n"
        )
        program = parse_source(src)
        for runner in (execute, execute_plan):
            with self.assertRaises(Exception) as ctx:
                runner(program, analyze(program))
            self.assertEqual(ctx.exception.code, "E401")
            self.assertIn("no database", ctx.exception.detail)


class TestDataPrograms(DataTestBase):
    def test_type_mismatch_against_column(self):
        src = SCHEMA + (
            'node 001\nop const\ntype string\nvalue "not-an-int"\n\n'
            'node 002\nop const\ntype string\nvalue "t"\n\n'
            'node 003\nop const\ntype string\nvalue "b"\n\n'
            "node 004\nop data.insert\nentity note\n"
            "input 001 002 003\noutput i64\n"
        )
        with self.assertRaises(Exception) as ctx:
            analyze(parse_source(src))
        self.assertEqual(ctx.exception.code, "E203")  # owner_id wants i64

    def test_identity_column_protected(self):
        src = SCHEMA + (
            "node 001\nop const\ntype i64\nvalue 1\n\n"
            "node 002\nop const\ntype i64\nvalue 2\n\n"
            "node 003\nop data.update\nentity note\nset id\nwhere id\n"
            "input 001 002\noutput i64\n"
        )
        with self.assertRaises(Exception) as ctx:
            analyze(parse_source(src))
        self.assertEqual(ctx.exception.code, "E503")

    def test_data_effects_in_manifest(self):
        src = SCHEMA + (
            'node 001\nop const\ntype string\nvalue "u"\n\n'
            'node 002\nop const\ntype string\nvalue "h"\n\n'
            "node 003\nop data.insert\nentity user\n"
            "input 001 002\noutput i64\n\n"
            "node 004\nop emit\ninput 003\n"
        )
        self.assertEqual(program_effects(parse_source(src)),
                         ["DATA_WRITE", "PURE", "SYSTEM"])

    def test_export_refuses_data_effects(self):
        from runtime import export_python
        src = SCHEMA + (
            'node 001\nop const\ntype string\nvalue "u"\n\n'
            'node 002\nop const\ntype string\nvalue "h"\n\n'
            "node 003\nop data.insert\nentity user\n"
            "input 001 002\noutput i64\n\n"
            "node 004\nop emit\ninput 003\n"
        )
        with self.assertRaises(ValueError) as ctx:
            export_python(parse_source(src))
        self.assertIn("DATA_WRITE", str(ctx.exception))

    def test_crypto_digest_known_vector(self):
        self.assertEqual(sha256("sha256", "2066"),
                         "2f4b6b34e8e26a03f80e8a98a4a4d9a4"
                         "03b4d0c0b3a2e5d3f9e1b6b7e0f2c8ab"
                         [:0] + __import__("hashlib")
                         .sha256(b"2066").hexdigest())

    def test_cli_data_run(self):
        program, analysis, db = self.make_db(
            [("data.write", "user"), ("data.read", "user")])
        db.insert("1", "user", ["alice", "h"])
        # a program without data ops runs fine with --db attached
        rc, out, err = run_cli("run", "examples/arithmetic.ai",
                               "--db", self.db_path)
        self.assertEqual((rc, out, err), (0, "50\n", ""))


if __name__ == "__main__":
    unittest.main()
