"""Backup/restore (plan SS60): hash-verified state portability.

Gates: round-trip fidelity, tamper detection (restore copies NOTHING on
any mismatch), and secret exclusion (*.key never lands in a bundle by
default — and its presence in a bundle is itself a verification failure).
"""

import json
import tempfile
import unittest
from pathlib import Path

from runtime.backup import (collect_sources, create_backup, restore_backup,
                            verify_backup)


def _fixture() -> tuple[Path, Path]:
    tmp = Path(tempfile.mkdtemp())
    programs = tmp / "programs" / "demo"
    (programs / "core").mkdir(parents=True)
    (programs / "core" / "hello.ai").write_text(
        'node 001\nop const\ntype string\nvalue "hi"\n\n'
        'node 002\nop emit\ninput 001\n', encoding="utf-8")
    (programs / "package.ai").write_text("package demo\nmodule core\n",
                                         encoding="utf-8")
    db = tmp / "sales.db"
    db.write_bytes(b"sqlite-bytes-0123456789")
    return tmp, programs, db


class TestBackupRestore(unittest.TestCase):
    def setUp(self):
        self.tmp, self.programs, self.db = _fixture()
        self.sources = collect_sources(db=self.db, programs=self.programs)
        self.bundle = self.tmp / "backup-out"

    def test_round_trip_is_byte_identical(self):
        create_backup(self.bundle, self.sources)
        self.assertTrue(verify_backup(self.bundle)["ok"])
        result = restore_backup(self.bundle, self.tmp / "restored")
        self.assertTrue(result["ok"])
        restored_db = self.tmp / "restored" / "data" / "sales.db"
        restored_ai = (self.tmp / "restored" / "programs"
                       / "core" / "hello.ai")
        self.assertEqual(restored_db.read_bytes(), self.db.read_bytes())
        self.assertEqual(restored_ai.read_text(encoding="utf-8"),
                         (self.programs / "core" / "hello.ai")
                         .read_text(encoding="utf-8"))

    def test_tamper_copies_nothing(self):
        create_backup(self.bundle, self.sources)
        victim = self.bundle / "data" / "sales.db"
        victim.write_bytes(b"tampered")
        verification = verify_backup(self.bundle)
        self.assertFalse(verification["ok"])
        self.assertTrue(any("hash mismatch" in p
                            for p in verification["problems"]))
        result = restore_backup(self.bundle, self.tmp / "restored")
        self.assertFalse(result["ok"])
        self.assertFalse((self.tmp / "restored").exists(),
                         "restore must copy NOTHING on any mismatch")

    def test_secrets_are_excluded_and_flagged(self):
        key = self.programs / "agent.key"
        key.write_text('{"secret_key": "x"}', encoding="utf-8")
        sources = collect_sources(programs=self.programs)
        manifest = create_backup(self.bundle, sources)
        self.assertIn("programs/agent.key", manifest["excluded"])
        self.assertFalse((self.bundle / "programs" / "agent.key")
                         .exists())
        # and a smuggled secret inside a bundle fails verification
        (self.bundle / "programs" / "agent.key").write_text(
            '{"secret_key": "evil"}', encoding="utf-8")
        verification = verify_backup(self.bundle)
        self.assertFalse(verification["ok"])
        self.assertTrue(any("secret material" in p
                            for p in verification["problems"]))


if __name__ == "__main__":
    unittest.main()
