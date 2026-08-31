"""Key-copying defenses (spec/key-copying.md):
- hash-bound approvals (`approve --for-hash`): a copied key can only
  approve/authorize ONE inspected artifact
- revocation list: stolen delegations die early, chain-verified
- split-trust derivation: disk factor + host factor
- sessions: revoked token_ids are denied before expiry
"""

import json
import tempfile
import unittest
from pathlib import Path

from runtime import keydisk
from runtime.capabilities import GrantSet
from runtime.revocation import (Revocations, bind_to_hash, derive_two_factor_seed,
                                grant_id)
from runtime.session import SessionVerifier, mint_session_token
from runtime import generate_identity
from tests.helpers import run_cli

WANTED = {"subject": "agent-A91", "grants": [
    {"action": "filesystem.read", "resource": "examples/incoming"}]}


class TestRevocationChain(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.rev_path = str(Path(self.tmp.name) / "rev.jsonl")
        self.rev = Revocations(self.rev_path)

    def test_revoke_and_query(self):
        self.assertFalse(self.rev.is_revoked("abc"))
        self.rev.revoke("abc", reason="stolen disk")
        self.assertTrue(self.rev.is_revoked("abc"))
        self.assertFalse(self.rev.is_revoked("other"))

    def test_chain_survives_reload_and_detects_tamper(self):
        self.rev.revoke("a")
        self.rev.revoke("b")
        result = Revocations(self.rev_path).verify_chain()
        self.assertTrue(result["ok"])
        self.assertEqual(result["records"], 2)
        lines = Path(self.rev_path).read_text("utf-8").splitlines()
        record = json.loads(lines[0])
        record["revoke"] = "hacked"
        lines[0] = json.dumps(record, sort_keys=True)
        Path(self.rev_path).write_text("\n".join(lines), "utf-8")
        result = Revocations(self.rev_path).verify_chain()
        self.assertFalse(result["ok"])

    def test_reordering_detected(self):
        self.rev.revoke("a")
        self.rev.revoke("b")
        lines = Path(self.rev_path).read_text("utf-8").splitlines()
        lines.reverse()
        Path(self.rev_path).write_text("\n".join(lines), "utf-8")
        self.assertFalse(self.rev.verify_chain()["ok"])


class TestHashBoundApprovals(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "disk").mkdir()
        (self.dir / "caps.json").write_text(json.dumps(WANTED),
                                            encoding="utf-8")
        (self.dir / "hello.ai").write_text(
            'node 001\nop const\ntype string\nvalue "hi"\n\n'
            "node 002\nop emit\ninput 001\n", encoding="utf-8")
        (self.dir / "other.ai").write_text(
            'node 001\nop const\ntype string\nvalue "other"\n\n'
            "node 002\nop emit\ninput 001\n", encoding="utf-8")
        run_cli("key-format", str(self.dir / "disk"), "--id", "human-1",
                "--pin", "1234")

    def test_bound_delegation_runs_only_that_program(self):
        # compute the target program's hash, approve FOR it
        import hashlib
        target = (self.dir / "hello.ai").read_text(encoding="utf-8")
        prog_hash = "sha256:" + hashlib.sha256(
            target.encode("utf-8")).hexdigest()
        rc, _, _ = run_cli("approve", str(self.dir / "caps.json"),
                           "--key", str(self.dir / "disk"), "--pin", "1234",
                           "--for-hash", prog_hash,
                           "--out", str(self.dir / "bound.json"))
        self.assertEqual(rc, 0)
        # the bound program runs
        rc, out, _ = run_cli("run", str(self.dir / "hello.ai"),
                             "--caps", str(self.dir / "bound.json"),
                             "--require-signed")
        self.assertEqual((rc, out), (0, "hi\n"))
        # a DIFFERENT program under the same delegation: E408
        rc, _, err = run_cli("run", str(self.dir / "other.ai"),
                             "--caps", str(self.dir / "bound.json"),
                             "--require-signed")
        self.assertEqual(rc, 4)
        self.assertIn("E408", err)
        self.assertIn("cannot be reused", err)

    def test_binder_is_signature_covered(self):
        rc, _, _ = run_cli("approve", str(self.dir / "caps.json"),
                           "--key", str(self.dir / "disk"), "--pin", "1234",
                           "--for-hash", "sha256:aaa",
                           "--out", str(self.dir / "b.json"))
        envelope = json.loads((self.dir / "b.json").read_text("utf-8"))
        envelope["payload"]["bound_program_hash"] = "sha256:bbb"
        (self.dir / "b.json").write_text(json.dumps(envelope), "utf-8")
        rc, _, err = run_cli("verify-caps", str(self.dir / "b.json"))
        self.assertEqual(rc, 1)  # binding edit breaks the signature


class TestRevokedGrantsAndSessions(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "caps.json").write_text(json.dumps(WANTED),
                                            encoding="utf-8")
        self.rev = Revocations(str(self.dir / "rev.jsonl"))
        (self.dir / "p.ai").write_text(
            'node 001\nop const\ntype string\nvalue "hi"\n\n'
            "node 002\nop emit\ninput 001\n", encoding="utf-8")

    def test_revoked_capability_set_refused(self):
        caps = self.dir / "caps.json"
        envelope = json.loads(caps.read_text("utf-8"))
        self.rev.revoke(grant_id(envelope), reason="stolen disk")
        with self.assertRaises(ValueError) as ctx:
            GrantSet.from_file(str(caps), revocations=self.rev)
        self.assertIn("REVOKED", str(ctx.exception))

    def test_unrelated_grants_unaffected(self):
        envelope = json.loads(caps_text(WANTED))
        self.assertFalse(self.rev.is_revoked(grant_id(envelope)))
        GrantSet.from_file(str(caps_path(self.dir, WANTED)),
                           revocations=self.rev)

    def test_revoked_session_token_denied(self):
        ident, secret = generate_identity("server")
        ver = SessionVerifier(public_key=ident.public_key,
                              revocations=self.rev)
        token = mint_session_token(secret, 5)
        self.assertEqual(ver.verify("001", token), 5)
        payload = token.split(".")[0]
        import base64
        decoded = json.loads(base64.urlsafe_b64decode(
            payload + "=" * (-len(payload) % 4)))
        self.rev.revoke(decoded["token_id"], reason="leaked")
        with self.assertRaises(Exception) as ctx:
            ver.verify("001", token)
        self.assertIn("REVOKED", ctx.exception.detail)


def caps_text(payload):
    return json.dumps(payload)


def caps_path(directory, payload):
    p = Path(directory) / "caps2.json"
    p.write_text(caps_text(payload), encoding="utf-8")
    return p


class TestSplitTrust(unittest.TestCase):
    def test_deterministic_and_factor_sensitive(self):
        a = derive_two_factor_seed("ab" * 32, "host-secret")
        b = derive_two_factor_seed("ab" * 32, "host-secret")
        self.assertEqual(a, b)
        self.assertNotEqual(a, derive_two_factor_seed("cd" * 32,
                                                      "host-secret"))
        self.assertNotEqual(a, derive_two_factor_seed("ab" * 32,
                                                      "other-host"))
        self.assertEqual(len(a), 64)


if __name__ == "__main__":
    unittest.main()
