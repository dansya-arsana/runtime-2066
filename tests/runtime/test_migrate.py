"""Schema migration (roadmap §25): the runtime diffs program entities
against the database, applies additive changes, and refuses destructive
ones — AI may propose migrations; the runtime verifies them."""

import tempfile
import unittest
from pathlib import Path

from runtime import parse_source
from runtime.data import DataPlane
from tests.helpers import run_cli

USER_V1 = ("entity user {\nid identity\nusername string\n}\n"
           'node 001\nop const\ntype string\nvalue "x"\n\n'
           "node 002\nop emit\ninput 001\n")
USER_V2 = ("entity user {\nid identity\nusername string\nemail string\n}\n"
           'node 001\nop const\ntype string\nvalue "x"\n\n'
           "node 002\nop emit\ninput 001\n")
USER_V3 = ("entity user {\nid identity\nusername string\nemail i64\n}\n"
           'node 001\nop const\ntype string\nvalue "x"\n\n'
           "node 002\nop emit\ninput 001\n")
USER_SHRINK = ("entity user {\nid identity\nusername string\n}\n"
               'node 001\nop const\ntype string\nvalue "x"\n\n'
               "node 002\nop emit\ninput 001\n")


class TestMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.db_path = str(Path(self.tmp.name) / "m.db")
        # seed the v1 schema with a row
        db = DataPlane(self.db_path, parse_source(USER_V1).entities, None, None)
        db.connection.execute(
            "INSERT INTO user (username) VALUES ('alice')")
        db.connection.commit()
        db.close()

    def _drift(self, source):
        db = DataPlane(self.db_path, parse_source(source).entities, None, None,
                       auto_create=False)
        steps = db.schema_drift()
        db.close()
        return steps

    def _apply(self, source):
        db = DataPlane(self.db_path, parse_source(source).entities, None, None,
                       auto_create=False)
        db.apply_safe_steps(db.schema_drift())
        db.close()

    def _row_count(self, sql):
        db = DataPlane(self.db_path, parse_source(USER_V1).entities, None,
                       None, auto_create=False)
        try:
            return db.connection.execute(sql).fetchone()[0]
        finally:
            db.close()

    def test_additive_change_is_safe(self):
        steps = self._drift(USER_V2)
        self.assertEqual(len(steps), 1)
        self.assertFalse(steps[0]["breaking"])
        self.assertEqual(steps[0]["kind"], "add_column")
        self.assertIn("ALTER TABLE user ADD COLUMN email TEXT",
                      steps[0]["sql"])

    def test_type_change_is_breaking(self):
        self._apply(USER_V2)  # email TEXT now exists
        steps = self._drift(USER_V3)  # email declared i64
        breaking = [s for s in steps if s["breaking"]]
        self.assertEqual(len(breaking), 1)
        self.assertEqual(breaking[0]["kind"], "type_change")
        self.assertIn("lose data", breaking[0]["detail"])

    def test_column_removal_is_breaking(self):
        self._apply(USER_V2)  # email column now exists
        steps = self._drift(USER_SHRINK)
        breaking = [s for s in steps if s["breaking"]]
        self.assertEqual(len(breaking), 1)
        self.assertEqual(breaking[0]["kind"], "drop_column")
        self.assertIn("destroy its data", breaking[0]["detail"])

    def test_apply_safe_steps_adds_column_preserving_rows(self):
        self._apply(USER_V2)
        # alice survived the migration
        self.assertEqual(
            self._row_count("SELECT COUNT(*) FROM user WHERE username='alice'"),
            1)

    def test_in_sync_reports_nothing(self):
        self._apply(USER_V1)
        self.assertEqual(self._drift(USER_V1), [])

    def test_new_entity_is_create_step(self):
        source = USER_V2 + (
            "\nentity tag {\nid identity\nlabel string\n}\n")
        steps = self._drift(source)
        creates = [s for s in steps if s["kind"] == "create"]
        self.assertEqual(len(creates), 1)
        self.assertEqual(creates[0]["entity"], "tag")
        self.assertFalse(creates[0]["breaking"])


class TestMigrateCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.db = self.dir / "m.db"
        (self.dir / "v1.ai").write_text(USER_V1, encoding="utf-8")
        (self.dir / "v2.ai").write_text(USER_V2, encoding="utf-8")
        (self.dir / "v3.ai").write_text(USER_V3, encoding="utf-8")

    def test_requires_db(self):
        rc, _, err = run_cli("migrate", str(self.dir / "v1.ai"))
        self.assertEqual((rc, err.split(":")[0]), (3, "error"))

    def test_sync_then_add_then_break(self):
        # first run creates the table (safe, applied)
        rc, out, _ = run_cli("migrate", str(self.dir / "v1.ai"),
                             "--db", str(self.db))
        self.assertEqual(rc, 0)
        self.assertIn("applied: [create] user", out)
        # same schema again: in sync
        rc, out, _ = run_cli("migrate", str(self.dir / "v1.ai"),
                             "--db", str(self.db))
        self.assertEqual((rc, out), (0, "schema is in sync — no changes needed\n"))
        # additive: reported as applied, exit 0
        rc, out, _ = run_cli("migrate", str(self.dir / "v2.ai"),
                             "--db", str(self.db))
        self.assertEqual(rc, 0)
        self.assertIn("add_column", out)
        self.assertIn("applied", out)
        # destructive: refused, exit 1
        rc, out, err = run_cli("migrate", str(self.dir / "v3.ai"),
                               "--db", str(self.db))
        self.assertEqual(rc, 1)
        self.assertIn("BREAKING", out)
        self.assertIn("refusing", err)
        # json mode
        import json
        rc, out, _ = run_cli("migrate", str(self.dir / "v3.ai"),
                             "--db", str(self.db), "--json")
        self.assertEqual(rc, 1)
        payload = json.loads(out)
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["breaking"][0]["kind"], "type_change")


if __name__ == "__main__":
    unittest.main()
