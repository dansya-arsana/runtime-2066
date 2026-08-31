"""Semantic packages (hardening plan H3): package::module::unit.

Key property: packaging never changes identity — a unit's canonical
hash equals the hash of the same program text anywhere else, and
addresses can never traverse paths.
"""

import tempfile
import unittest
from pathlib import Path

from runtime import parse_source, program_hash
from runtime.packages import PackageStore, Unit, load_manifest

HELLO = 'node 001\nop const\ntype string\nvalue "hi"\n\nnode 002\nop emit\ninput 001\n'

NOTE_WRITE = """entity note {
id identity
owner_id i64
title string
}

main

node 001
op system.read

node 002
op cast
input 001
output i64

node 003
op const
type string
value "t"

node 004
op data.insert
entity note
input 002 003
output i64

node 005
op emit
input 004
"""


def build_store() -> tuple[PackageStore, Path]:
    tmp = tempfile.mkdtemp()
    root = Path(tmp) / "programs"
    pkg = root / "demo"
    (pkg / "core").mkdir(parents=True)
    (pkg / "core" / "hello.ai").write_text(HELLO, encoding="utf-8")
    (pkg / "core" / "note_add.ai").write_text(NOTE_WRITE, encoding="utf-8")
    (pkg / "package.ai").write_text(
        "# demo package\npackage demo\nversion 1.2.3\n\nmodule core\n",
        encoding="utf-8")
    return PackageStore(root), root


class TestManifest(unittest.TestCase):
    def test_manifest_parses_and_is_strict(self):
        _, root = build_store()
        package = load_manifest(root / "demo" / "package.ai")
        self.assertEqual(package.name, "demo")
        self.assertEqual(package.version, "1.2.3")
        self.assertEqual(package.modules, {"core": ["hello", "note_add"]})

    def test_unknown_field_fails_closed(self):
        _, root = build_store()
        bad = root / "demo2"
        (bad / "core").mkdir(parents=True)
        (bad / "core" / "x.ai").write_text(HELLO, encoding="utf-8")
        (bad / "package.ai").write_text(
            "package demo2\nmodule core\nfactory yes\n", encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_manifest(bad / "package.ai")
        self.assertIn("bad line", str(ctx.exception))

    def test_undeclared_module_directory_fails_closed(self):
        _, root = build_store()
        (root / "demo" / "hidden").mkdir()
        (root / "demo" / "hidden" / "x.ai").write_text(HELLO, encoding="utf-8")
        with self.assertRaises(ValueError) as ctx:
            load_manifest(root / "demo" / "package.ai")
        self.assertIn("not declared", str(ctx.exception))


class TestUnits(unittest.TestCase):
    def setUp(self):
        self.store, _ = build_store()

    def test_hash_is_path_independent_identity(self):
        unit = self.store.unit("demo::core::hello")
        direct = program_hash(parse_source(HELLO))
        self.assertEqual(unit.hash, direct)

    def test_address_never_traverses_paths(self):
        for bad in ("demo::core::..", "demo::../core::hello",
                    "demo::core::../../etc/passwd",
                    "demo::core::hello.ai.exe", "demo::..::hello"):
            with self.subTest(address=bad):
                with self.assertRaises(ValueError):
                    self.store.unit(bad)

    def test_unknown_parts_name_what_exists(self):
        with self.assertRaises(ValueError) as ctx:
            self.store.unit("demo::nope::hello")
        self.assertIn("declared: core", str(ctx.exception))
        with self.assertRaises(ValueError) as ctx:
            self.store.unit("demo::core::nope")
        self.assertIn("have: hello, note_add", str(ctx.exception))

    def test_capability_and_effect_derivation(self):
        unit = self.store.unit("demo::core::note_add")
        self.assertIn("data.write:note", unit.capabilities())
        self.assertIn("DATA_WRITE", unit.effects)
        self.assertEqual(unit.input_count, 1)   # stdin: owner_id
        self.assertEqual(unit.emit_count, 1)
        self.assertEqual(unit.node_count, 5)
        self.assertEqual(unit.entities, ["note"])
        self.assertEqual(unit.dependencies()["entities"], ["note"])

    def test_unit_card_fields(self):
        unit = self.store.unit("demo::core::hello")
        self.assertEqual(unit.node_count, 2)
        self.assertIn("SYSTEM", unit.effects)


if __name__ == "__main__":
    unittest.main()


class TestCli(unittest.TestCase):
    """2066 list / 2066 inspect against the real sales package, and the
    production profile gate (H4): unsigned grants always rejected."""

    def test_list_and_inspect_cli(self):
        from tests.helpers import run_cli
        code, out, _ = run_cli("list")
        self.assertEqual(code, 0)
        self.assertIn("sales 0.1.0", out)
        self.assertIn("business", out)

        code, out, _ = run_cli("inspect", "sales::business::add")
        self.assertEqual(code, 0)
        self.assertIn("UNIT         sales::business::add", out)
        self.assertIn(
            "sha256:81aabb2384e62a901e568bd22ab3cb34167eb98d42b4be752d257202b1b16d08",
            out)  # frozen corpus hash (H0 snapshot)
        self.assertIn("data.write:business", out)
        self.assertIn("DATA_WRITE", out)

        code, _, err = run_cli("inspect", "sales::nope::add")
        self.assertEqual(code, 3)
        self.assertIn("no module", err)

        code, out, _ = run_cli("inspect", "sales::business::add", "--json")
        self.assertEqual(code, 0)
        import json
        card = json.loads(out)
        self.assertEqual(card["unit"], "sales::business::add")
        self.assertIn("data.write:business", card["capabilities"])

    def test_production_profile_rejects_unsigned_grants(self):
        """--profile production makes unsigned grants unploadable, even
        without remembering --require-signed (H4)."""
        import json
        import tempfile
        import os
        from tests.helpers import run_cli
        tmp = tempfile.mkdtemp()
        prog = os.path.join(tmp, "p.ai")
        caps = os.path.join(tmp, "caps.json")
        with open(prog, "w", encoding="utf-8") as fh:
            fh.write('entity note {\nid identity\nowner_id i64\n'
                     'title string\n}\n\n'
                     'node 001\nop const\ntype i64\nvalue 1\n\n'
                     'node 002\nop const\ntype string\nvalue "t"\n\n'
                     'node 003\nop data.insert\nentity note\n'
                     'input 001 002\noutput i64\n\n'
                     'node 004\nop emit\ninput 003\n')
        with open(caps, "w", encoding="utf-8") as fh:
            json.dump({"subject": "t", "grants": [
                {"action": "data.write", "resource": "note"}]}, fh)
        db = os.path.join(tmp, "t.db")

        # development (default): the unsigned grant loads and works
        code, out, _ = run_cli("run", prog, "--db", db, "--caps", caps)
        self.assertEqual(code, 0, out)

        # production: same file refused at load — fail closed
        code, _, err = run_cli("run", prog, "--db", db + "2", "--caps",
                               caps, "--profile", "production")
        self.assertEqual(code, 3)
        self.assertIn("signed", err.lower())

        # and a bogus profile value is a usage error
        code, _, _ = run_cli("run", prog, "--profile", "lax")
        self.assertEqual(code, 3)
