"""Evidence protocol (Appendix C.5): hash-chained, tamper-evident audit."""

import json
import tempfile
import unittest
from pathlib import Path

from runtime.data import DataPlane
from runtime.evidence import EvidenceLog, verify_evidence
from runtime import parse_source
from tests.helpers import run_cli

SCHEMA = ("entity note {\nid identity\nowner_id i64\ntitle string\n"
          "body string\n}\n")
INSERT = (SCHEMA + "\n"
          "node 001\nop const\ntype i64\nvalue 1\n\n"
          'node 002\nop const\ntype string\nvalue "t"\n\n'
          'node 003\nop const\ntype string\nvalue "b"\n\n'
          "node 004\nop data.insert\nentity note\n"
          "input 001 002 003\noutput i64\n\n"
          "node 005\nop emit\ninput 004\n")


class TestEvidenceChain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.log_path = str(self.dir / "audit.jsonl")

    def _write(self, grants_entries=None):
        from runtime.capabilities import GrantSet
        grants = (GrantSet.from_dict({"subject": "audit-test", "grants": [
            {"action": a, "resource": r} for a, r in grants_entries]})
            if grants_entries else None)
        db = DataPlane(str(self.dir / "n.db"),
                       parse_source(SCHEMA).entities, grants, None,
                       evidence=EvidenceLog(
                           self.log_path, program="sha256:test",
                           subject="audit-test"))
        self.addCleanup(db.close)
        return db

    def test_writes_are_recorded_and_chained(self):
        db = self._write([("data.write", "note"), ("data.read", "note"),
                          ("data.delete", "note")])
        db.insert("1", "note", [1, "t", "b"])
        db.insert("2", "note", [2, "t2", "b2"])
        db.delete("3", "note", "id", 1)
        records = [json.loads(line) for line in
                   Path(self.log_path).read_text("utf-8").splitlines()]
        self.assertEqual([r["seq"] for r in records], [1, 2, 3])
        self.assertEqual([r["action"] for r in records],
                         ["data.insert", "data.insert", "data.delete"])
        self.assertEqual(records[0]["prev_hash"], "0" * 64)
        for prev, cur in zip(records, records[1:]):
            self.assertEqual(cur["prev_hash"], prev["hash"])
        self.assertTrue(verify_evidence(self.log_path)["ok"])

    def test_reads_are_not_recorded(self):
        db = self._write([("data.write", "note"), ("data.read", "note")])
        db.insert("1", "note", [1, "t", "b"])
        db.count("2", "note", "id", 1)
        db.select("3", "note", "title", "id", 1)
        lines = Path(self.log_path).read_text("utf-8").splitlines()
        self.assertEqual(len(lines), 1)  # only the insert

    def test_edited_record_breaks_chain(self):
        db = self._write([("data.write", "note")])
        db.insert("1", "note", [1, "t", "b"])
        db.insert("2", "note", [2, "t", "b"])
        lines = Path(self.log_path).read_text("utf-8").splitlines()
        record = json.loads(lines[0])
        record["detail"] = "rowid=999 (intruder)"
        lines[0] = json.dumps(record, sort_keys=True)
        Path(self.log_path).write_text("\n".join(lines) + "\n", "utf-8")
        result = verify_evidence(self.log_path)
        self.assertFalse(result["ok"])
        self.assertEqual(result["broken_at"], 1)

    def test_deleted_record_breaks_chain(self):
        db = self._write([("data.write", "note")])
        for i in range(3):
            db.insert(str(i), "note", [i, "t", "b"])
        lines = Path(self.log_path).read_text("utf-8").splitlines()
        del lines[1]  # make record 2 silently disappear
        Path(self.log_path).write_text("\n".join(lines) + "\n", "utf-8")
        result = verify_evidence(self.log_path)
        self.assertFalse(result["ok"])
        self.assertIn("link mismatch", result["reason"])

    def test_reordered_records_break_chain(self):
        db = self._write([("data.write", "note")])
        for i in range(3):
            db.insert(str(i), "note", [i, "t", "b"])
        lines = Path(self.log_path).read_text("utf-8").splitlines()
        lines.reverse()
        Path(self.log_path).write_text("\n".join(lines) + "\n", "utf-8")
        self.assertFalse(verify_evidence(self.log_path)["ok"])

    def test_missing_file_and_empty_log(self):
        self.assertFalse(verify_evidence(str(self.dir / "nope.jsonl"))["ok"])
        empty = self.dir / "empty.jsonl"
        empty.write_text("", encoding="utf-8")
        self.assertTrue(verify_evidence(str(empty))["ok"])


class TestEvidenceCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "caps.json").write_text(json.dumps({
            "subject": "cli-audit",
            "grants": [
                {"action": "data.write", "resource": "note"},
                {"action": "data.read", "resource": "note"}]}),
            encoding="utf-8")
        (self.dir / "add.ai").write_text(INSERT, encoding="utf-8")

    def test_run_records_evidence_and_verifies(self):
        log = str(self.dir / "audit.jsonl")
        db = str(self.dir / "n.db")
        rc, out, _ = run_cli("run", str(self.dir / "add.ai"), "--db", db,
                             "--caps", str(self.dir / "caps.json"),
                             "--evidence", log)
        self.assertEqual((rc, out), (0, "1\n"))
        rc, out, _ = run_cli("evidence", log)
        self.assertEqual(rc, 0)
        self.assertIn("1 record(s) intact", out)
        # the record identifies the program by canonical hash
        record = json.loads(Path(log).read_text("utf-8").splitlines()[0])
        self.assertTrue(record["program"].startswith("sha256:"))
        self.assertEqual(record["subject"], "cli-audit")

    def test_verify_reports_tampering_with_exit_1(self):
        log = self.dir / "audit.jsonl"
        rc, _, _ = run_cli("run", str(self.dir / "add.ai"),
                           "--db", str(self.dir / "n.db"),
                           "--caps", str(self.dir / "caps.json"),
                           "--evidence", str(log))
        self.assertEqual(rc, 0)
        lines = log.read_text("utf-8").splitlines()
        record = json.loads(lines[0])
        record["resource"] = "user"  # cover tracks: claim it touched users
        lines[0] = json.dumps(record, sort_keys=True)
        log.write_text("\n".join(lines) + "\n", "utf-8")
        rc, out, _ = run_cli("evidence", str(log))
        self.assertEqual(rc, 1)
        self.assertIn("TAMPERED", out)
        rc, out, _ = run_cli("evidence", str(log), "--json")
        self.assertEqual(rc, 1)
        self.assertFalse(json.loads(out)["ok"])

    def test_no_evidence_flag_means_no_log(self):
        rc, _, _ = run_cli("run", str(self.dir / "add.ai"),
                           "--db", str(self.dir / "fresh.db"),
                           "--caps", str(self.dir / "caps.json"))
        self.assertEqual(rc, 0)
        self.assertFalse(list(self.dir.glob("*.jsonl")))


if __name__ == "__main__":
    unittest.main()
