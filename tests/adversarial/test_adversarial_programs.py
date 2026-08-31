"""Adversarial agent tests (plan SS34): programs that TRY to misbehave.

The models that author programs are untrusted proposers. These fixtures
encode hostile intent as .ai source — exactly what a compromised or
prompt-injected agent would emit — and pin the runtime's answer:

    escalate authority · escape resource scope · forge identity ·
    bypass guards · write via an untaken branch

Every case must end in a structured refusal or a verified no-op —
deterministically, forever.
"""

import io
import sys
import tempfile
import unittest
from pathlib import Path

from runtime import analyze, execute, identity, parse_source
from runtime.capabilities import GrantSet
from runtime.data import DataPlane
from runtime.errors import StructuredError
from runtime.session import SessionVerifier, mint_session_token

GRANTS_NOTE_RW = GrantSet.from_dict({"subject": "t", "grants": [
    {"action": "data.read", "resource": "note"},
    {"action": "data.write", "resource": "note"}]})
GRANTS_NOTE_RO = GrantSet.from_dict({"subject": "t", "grants": [
    {"action": "data.read", "resource": "note"}]})

ENTITY = """entity note {
id identity
owner_id i64
title string
}
"""

# attack 1: insert with NO data plane attached at all
A_INSERT_NO_DB = ENTITY + """
main

node 001
op const
type i64
value 1

node 002
op const
type string
value "hostile"

node 003
op data.insert
entity note
input 001 002
output i64

node 004
op emit
input 003
"""

# attack 2: delete with only a READ grant (read must never delete)
A_DELETE_READONLY = ENTITY + """
main

node 001
op const
type i64
value 1

node 002
op data.delete
entity note
where owner_id
input 001
output i64

node 003
op emit
input 002
"""

# attack 3: attempt an identity-column rewrite (rowid forgery)
A_FORGE_IDENTITY = ENTITY + """
main

node 001
op const
type i64
value 99

node 002
op const
type i64
value 1

node 003
op data.update
entity note
set id
where owner_id
input 001 002
output i64

node 004
op emit
input 003
"""

# attack 4: hide a write in an untaken branch arm WITHOUT a when guard —
# the write still executes (eager semantics); the defense is the guard,
# and this documents WHY (pinned when the guard landed)
A_UNGUARDED_WRITE = ENTITY + """
main

node 001
op const
type i64
value 1

node 002
op const
type string
value "smuggled"

node 003
op data.insert
entity note
input 001 002
output i64

node 004
op const
type string
value "denied-looking output"

node 005
op const
type string
value "looked fine"

node 006
op const
type bool
value false

node 007
op branch
input 006 005 004
output string

node 008
op emit
input 003
"""


class TestAdversarialPrograms(unittest.TestCase):
    def _run(self, source, grants, db_path=None, sessions=None):
        program = parse_source(source)
        analysis = analyze(program)
        db = DataPlane(db_path, program.entities, grants, None) \
            if db_path else None
        stdin, stdout = sys.stdin, sys.stdout
        sys.stdin = io.StringIO("")
        sys.stdout = io.StringIO()
        try:
            emits = execute(program, analysis, grants=grants, db=db,
                            sessions=sessions)
            return emits, db
        except Exception:
            if db is not None:
                db.close()  # windows: release the file before raising
            raise
        finally:
            sys.stdin, sys.stdout = stdin, stdout

    def test_insert_without_data_plane_denied(self):
        with self.assertRaises(StructuredError) as ctx:
            self._run(A_INSERT_NO_DB, GRANTS_NOTE_RW)
        self.assertEqual(ctx.exception.code, "E401")

    def test_read_only_grant_cannot_delete(self):
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "adv.db")
            seed, seed_db = self._run(A_UNGUARDED_WRITE.replace(
                '"smuggled"', '"seed"'), GRANTS_NOTE_RW, db_path)
            seed_db.close()
            with self.assertRaises(StructuredError) as ctx:
                self._run(A_DELETE_READONLY, GRANTS_NOTE_RO, db_path)
            self.assertEqual(ctx.exception.code, "E401")
            # and the row survived
            db = DataPlane(db_path, parse_source(
                A_DELETE_READONLY).entities, GRANTS_NOTE_RO, None)
            rows = db.connection.execute(
                "SELECT COUNT(*) FROM note").fetchone()[0]
            db.close()
            self.assertEqual(rows, 1)

    def test_identity_column_update_refused_by_validator(self):
        with self.assertRaises(StructuredError) as ctx:
            analyze(parse_source(A_FORGE_IDENTITY))
        self.assertEqual(ctx.exception.code, "E503")

    def test_forged_session_token_fails_closed(self):
        program = parse_source(
            (Path(__file__).resolve().parents[2] / "programs" / "sales" /
             "business" / "list.ai").read_text(encoding="utf-8"))
        analysis = analyze(program)
        ident, secret = identity.generate_identity("real-authority")
        sessions = SessionVerifier(public_key=ident.public_key)
        for token in ("forged-token", "ok:1", "", "a.b"):
            with self.subTest(token=token[:20] or "<empty>"):
                stdin, stdout = sys.stdin, sys.stdout
                sys.stdin = io.StringIO(token + "\n")
                sys.stdout = io.StringIO()
                try:
                    with self.assertRaises(StructuredError) as ctx:
                        execute(program, analysis,
                                grants=GrantSet.from_file(str(
                                    Path(__file__).resolve().parents[2] /
                                    "policies" / "deployment" /
                                    "sales-caps.json")),
                                db=DataPlane(":memory:",
                                             program.entities,
                                             GrantSet.empty(), None),
                                sessions=sessions)
                finally:
                    sys.stdin, sys.stdout = stdin, stdout
                self.assertEqual(ctx.exception.code, "E406")

    def test_when_guard_false_leaves_zero_rows(self):
        """The modern defense: same smuggle attempt WITH a guard — the
        write is a verified no-op (returns 0, no row)."""
        guarded = A_UNGUARDED_WRITE.replace(
            "op data.insert\nentity note\ninput 001 002",
            "op data.insert\nentity note\nwhen 006\ninput 001 002")
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "guarded.db")
            emits, db = self._run(guarded, GRANTS_NOTE_RW, db_path)
            db.close()
            self.assertEqual(emits, [0], "guarded denied write returns 0")
            db = DataPlane(db_path, parse_source(
                guarded).entities, GRANTS_NOTE_RW, None)
            rows = db.connection.execute(
                "SELECT COUNT(*) FROM note").fetchone()[0]
            db.close()
            self.assertEqual(rows, 0, "no row may exist")


if __name__ == "__main__":
    unittest.main()
