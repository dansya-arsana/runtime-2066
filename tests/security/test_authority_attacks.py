"""Security regression matrix (plan SS34 security list, SS78 gate).

Each attack here is a named, replayable case. The runtime's answer must
be a STRUCTURED refusal — never a crash, never silence, never success:

    path traversal · SQL injection · expired capability · scope
    confusion · replay (expired session) · proposal impersonation ·
    evidence corruption · net egress to ungranted hosts
"""

import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

from runtime import analyze, execute, identity, parse_source
from runtime.capabilities import GrantSet
from runtime.data import DataPlane
from runtime.evidence import EvidenceLog, verify_evidence
from runtime.errors import StructuredError
from runtime.packages import PackageStore
from runtime.proposals import create_proposal, verify_proposal
from runtime.session import SessionVerifier, mint_session_token
from tests.helpers import ROOT

INJECTION_PAYLOADS = [
    "x'; DROP TABLE user;--",
    '"; DELETE FROM note WHERE 1=1;--',
    "' OR '1'='1",
    "'); ATTACH DATABASE '/tmp/evil.db' AS evil;--",
    "union select * from user",
]


class TestSqlInjection(unittest.TestCase):
    def test_payloads_are_inert_data(self):
        """Values travel as bound parameters; identifiers come from the
        grammar. Injected payloads must survive as literal data and
        never alter schema."""
        grants = GrantSet.from_dict({"subject": "t", "grants": [
            {"action": "data.write", "resource": "user"},
            {"action": "data.read", "resource": "user"}]})
        program = parse_source(
            (ROOT / "programs" / "sales" / "auth" / "register.ai")
            .read_text(encoding="utf-8"))
        analysis = analyze(program)
        with tempfile.TemporaryDirectory() as tmp:
            db_path = str(Path(tmp) / "injection.db")
            for payload in INJECTION_PAYLOADS:
                with self.subTest(payload=payload):
                    db = DataPlane(db_path, program.entities, grants, None)
                    stdin, stdout = sys.stdin, sys.stdout
                    sys.stdin = io.StringIO(payload + "\npw\n")
                    sys.stdout = io.StringIO()
                    try:
                        execute(program, analysis, grants=grants, db=db)
                        out = sys.stdout.getvalue().strip()
                    finally:
                        sys.stdin, sys.stdout = stdin, stdout
                        db.close()
                    self.assertTrue(out.startswith("ok:"),
                                    f"payload {payload!r} broke execution")
            # schema intact: exactly N users, table still queryable
            db = DataPlane(db_path, program.entities, grants, None)
            rows = db.connection.execute(
                "SELECT COUNT(*) FROM user").fetchone()[0]
            db.close()
            self.assertEqual(rows, len(INJECTION_PAYLOADS),
                             "injection changed row visibility")


class TestExpiredCapability(unittest.TestCase):
    def test_expired_grant_denies_with_E402(self):
        grants = GrantSet.from_dict({"subject": "t", "grants": [
            {"action": "data.write", "resource": "note",
             "expires": "2020-01-01T00:00:00Z"}]})
        from datetime import datetime, timezone
        with self.assertRaises(StructuredError) as ctx:
            grants.check("data.write", "note",
                         now=datetime(2026, 8, 31, tzinfo=timezone.utc))
        self.assertEqual(ctx.exception.code, "E402")


class TestScopeConfusion(unittest.TestCase):
    def test_read_grant_never_covers_write_or_delete(self):
        grants = GrantSet.from_dict({"subject": "t", "grants": [
            {"action": "data.read", "resource": "business"}]})
        for action in ("data.write", "data.delete"):
            with self.subTest(action=action):
                with self.assertRaises(StructuredError) as ctx:
                    grants.check(action, "business")
                self.assertEqual(ctx.exception.code, "E401")


class TestSessionReplay(unittest.TestCase):
    def test_expired_token_is_rejected_not_replayed(self):
        ident, secret = identity.generate_identity("replay")
        sessions = SessionVerifier(public_key=ident.public_key)
        from datetime import datetime, timedelta, timezone
        expired_token = mint_session_token(
            secret, 7, ttl_minutes=-1)  # already expired
        with self.assertRaises(StructuredError) as ctx:
            sessions.verify("001", expired_token,
                            datetime.now(timezone.utc))
        self.assertEqual(ctx.exception.code, "E407")


class TestProposalImpersonation(unittest.TestCase):
    def test_signature_by_other_identity_fails_pin(self):
        author, secret = identity.generate_identity("author")
        other, _ = identity.generate_identity("attacker")
        base = parse_source(
            (ROOT / "examples" / "hello.ai").read_text(encoding="utf-8"))
        proposed = parse_source(
            (ROOT / "examples" / "call.ai").read_text(encoding="utf-8"))
        proposal = create_proposal(base, proposed, author, secret,
                                   "2026-08-31T00:00:00Z")
        # signature itself verifies (author really signed it)...
        verify_proposal(proposal, base)
        # ...but the CONTENT lies about who made it: rewriting agent_id
        # breaks the signature — tamper detection, not identity guessing
        forged = json.loads(json.dumps(proposal))
        forged["agent_id"] = "attacker"
        with self.assertRaises((StructuredError, ValueError)):
            verify_proposal(forged, base)


class TestPathTraversal(unittest.TestCase):
    def test_semantic_addresses_never_reach_the_filesystem(self):
        store = PackageStore(ROOT / "programs")
        for attack in ("sales::..::add", "sales::business::../../etc/passwd",
                       "sales::business/..::add",
                       "sales::business::add.ai.exe",
                       "sales::C:\\windows::add"):
            with self.subTest(attack=attack):
                with self.assertRaises(ValueError):
                    store.unit(attack)

    def test_filesystem_scope_escaping_write_is_denied(self):
        from runtime.fsops import write_file
        from datetime import datetime, timezone
        with tempfile.TemporaryDirectory() as tmp:
            inside = Path(tmp) / "inside"
            inside.mkdir()
            grants = GrantSet.from_dict({"subject": "t", "grants": [
                {"action": "filesystem.write",
                 "resource": str(inside.resolve())}]})
            escape = str((inside / ".." / "escaped.txt").resolve())
            with self.assertRaises(StructuredError) as ctx:
                write_file(grants, "001", escape, "payload",
                           datetime.now(timezone.utc))
            self.assertIn(ctx.exception.code, ("E401", "E403"))
            self.assertFalse((Path(tmp) / "escaped.txt").exists())


class TestNetEgressBoundary(unittest.TestCase):
    def test_ungranted_host_denied_before_transport(self):
        """Even with a transport attached, only allowlisted hosts are
        reachable — the exfiltration attempt fails closed with zero
        calls made."""
        program = parse_source(
            (ROOT / "programs" / "sales" / "integration" / "api_health.ai")
            .read_text(encoding="utf-8"))
        analysis = analyze(program)
        # grant egress to a DIFFERENT host than the program's const URL
        grants = GrantSet.from_dict({"subject": "t", "grants": [
            {"action": "net.request", "resource": "harmless.example"}]})
        calls = []

        def transport(url):
            calls.append(url)
            return "exfiltrated"

        stdin, stdout = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = io.StringIO(""), io.StringIO()
        try:
            with self.assertRaises(StructuredError) as ctx:
                execute(program, analysis, grants=grants, net=transport)
        finally:
            sys.stdin, sys.stdout = stdin, stdout
        self.assertEqual(ctx.exception.code, "E401")
        self.assertEqual(calls, [], "denied request must never leave")


class TestEvidenceCorruption(unittest.TestCase):
    def test_corrupted_chain_reports_not_ok(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = str(Path(tmp) / "ev.jsonl")
            log = EvidenceLog(path)
            for n in range(4):
                log.append("data.write", "business", f"row={n}")
            lines = Path(path).read_text(encoding="utf-8").splitlines()
            record = json.loads(lines[2])
            record["detail"] = "REWRITTEN BY ATTACKER"
            lines[2] = json.dumps(record)
            Path(path).write_text("\n".join(lines), encoding="utf-8")
            self.assertFalse(verify_evidence(path)["ok"])


if __name__ == "__main__":
    unittest.main()
