"""Agent identity and signed grants (roadmap §26, §28 groundwork).

Trust beats tested here: a signed grant file survives round trips intact,
any tampering (payload, timestamps, issuer) breaks verification fail-closed,
and --require-signed refuses unsigned files outright."""

import json
import tempfile
import unittest
from pathlib import Path

from runtime import (canonical_json, generate_identity, parse_source,
                     sign_capabilities)
from runtime.capabilities import (GrantSet, verify_envelope)
from runtime import identity
from tests.helpers import run_cli

CAPS = {"subject": "agent-A91", "grants": [
    {"action": "filesystem.read", "resource": "examples/incoming"}]}


class TestIdentity(unittest.TestCase):
    def test_canonical_json_is_deterministic_and_key_order_free(self):
        a = canonical_json({"b": 1, "a": {"y": [1, 2], "x": "é"}})
        b = canonical_json({"a": {"x": "é", "y": [1, 2]}, "b": 1})
        self.assertEqual(a, b)
        self.assertEqual(json.loads(a), {"a": {"x": "é", "y": [1, 2]}, "b": 1})

    def test_generate_identity_shape(self):
        ident, secret = generate_identity("agent-X")
        self.assertEqual(ident.agent_id, "agent-X")
        self.assertEqual(ident.algorithm, "ed25519")
        self.assertEqual(len(ident.public_key), 64)   # 32 bytes
        self.assertEqual(len(secret), 64)             # 32-byte seed
        int(ident.public_key, 16)
        int(secret, 16)

    def test_ed25519_is_deterministic(self):
        ident, secret = generate_identity("agent-X")
        data = canonical_json(CAPS)
        self.assertEqual(identity.sign(secret, data),
                         identity.sign(secret, data))

    def test_sign_and_verify_with_tamper_detection(self):
        ident, secret = generate_identity("agent-X")
        data = canonical_json(CAPS)
        sig = identity.sign(secret, data)
        self.assertTrue(identity.verify(ident.public_key, sig, data))
        self.assertFalse(identity.verify(ident.public_key, sig,
                                         data + b"!"))
        flipped = ("0" if sig[0] != "0" else "1") + sig[1:]
        self.assertFalse(identity.verify(ident.public_key, flipped, data))
        _, other_secret = generate_identity("agent-Y")
        self.assertFalse(identity.verify(ident.public_key,
                                         identity.sign(other_secret, data),
                                         data))

    def test_malformed_keys_rejected(self):
        with self.assertRaises(ValueError):
            identity.sign("nothex", b"x")
        with self.assertRaises(ValueError):
            identity.sign("ab" * 31, b"x")  # too short
        # verify() fails closed: malformed keys/sigs are False, not raises
        self.assertFalse(identity.verify("ff" * 31, "ab" * 64, b"x"))
        self.assertFalse(identity.verify("ab" * 32, "zz", b"x"))
        with self.assertRaises(ValueError):
            generate_identity("")

    def test_unsupported_algorithm_rejected(self):
        with self.assertRaises(ValueError):
            identity.parse_identity({"agent_id": "a", "algorithm": "rsa",
                                     "public_key": "ab" * 32})


class TestSignedEnvelopes(unittest.TestCase):
    def setUp(self):
        self.issuer, self.secret = generate_identity("agent-A91")

    def sign(self, payload, issued_at="2026-08-30T00:00:00+00:00"):
        return sign_capabilities(payload, self.issuer, self.secret, issued_at)

    def test_round_trip(self):
        envelope = self.sign(CAPS)
        self.assertEqual(verify_envelope(envelope), CAPS)

    def test_payload_tampering_breaks_verification(self):
        envelope = self.sign(CAPS)
        envelope["payload"]["grants"][0]["resource"] = "examples"  # widen!
        with self.assertRaises(ValueError) as ctx:
            verify_envelope(envelope)
        self.assertIn("FAILED", str(ctx.exception))

    def test_issued_at_tampering_breaks_verification(self):
        envelope = self.sign(CAPS)
        envelope["issued_at"] = "2020-01-01T00:00:00+00:00"
        with self.assertRaises(ValueError):
            verify_envelope(envelope)

    def test_issuer_swap_breaks_verification(self):
        envelope = self.sign(CAPS)
        other, _ = generate_identity("agent-B")
        envelope["issued_by"] = {"agent_id": other.agent_id,
                                 "algorithm": other.algorithm,
                                 "public_key": other.public_key}
        with self.assertRaises(ValueError):
            verify_envelope(envelope)

    def test_missing_issuer_fields_fail_closed(self):
        envelope = self.sign(CAPS)
        envelope["issued_by"] = {"agent_id": "ghost"}
        with self.assertRaises(ValueError):
            verify_envelope(envelope)
        with self.assertRaises(ValueError):
            verify_envelope({"payload": CAPS, "signature": "ab" * 64})

    def test_unsupported_algorithm_fail_closed(self):
        envelope = self.sign(CAPS)
        envelope["issued_by"]["algorithm"] = "rsa"
        with self.assertRaises(ValueError):
            verify_envelope(envelope)

    def test_unsigned_passthrough_without_flag(self):
        self.assertEqual(verify_envelope(CAPS), CAPS)

    def test_unsigned_refused_when_signed_required(self):
        with self.assertRaises(ValueError) as ctx:
            verify_envelope(CAPS, require_signed=True)
        self.assertIn("not signed", str(ctx.exception))


class TestSignedGrantFiles(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.issuer, self.secret = generate_identity("agent-A91")
        self._write("agent.json", {"agent_id": self.issuer.agent_id,
                                   "algorithm": self.issuer.algorithm,
                                   "public_key": self.issuer.public_key})
        self._write("agent.key", {"agent_id": self.issuer.agent_id,
                                  "algorithm": "ed25519",
                                  "secret_key": self.secret})
        self._write("caps.json", CAPS)
        self.reader = parse_source(
            'node 001\nop const\ntype string\nvalue "x"\n\n'
            "node 002\nop emit\ninput 001\n")

    def sign(self, payload, issued_at="2026-08-30T00:00:00+00:00"):
        return sign_capabilities(payload, self.issuer, self.secret, issued_at)

    def _write(self, name, payload):
        (self.dir / name).write_text(json.dumps(payload, indent=2),
                                     encoding="utf-8")
        return str(self.dir / name)

    def test_signed_file_loads_and_verifies(self):
        g = GrantSet.from_file(self._write("signed.json", self.sign(CAPS)))
        self.assertEqual(g.subject, "agent-A91")

    def test_unsigned_accepted_by_default_refused_with_flag(self):
        self.assertEqual(GrantSet.from_file(self._write("u.json", CAPS)).subject,
                         "agent-A91")
        with self.assertRaises(ValueError):
            GrantSet.from_file(str(self.dir / "u.json"), require_signed=True)

    def test_tampered_signed_file_refused(self):
        signed = self._write("t.json", self.sign(CAPS))
        path = Path(signed)
        envelope = json.loads(path.read_text(encoding="utf-8"))
        envelope["payload"]["grants"][0]["max_bytes"] = 10**9  # widen limit
        path.write_text(json.dumps(envelope), encoding="utf-8")
        with self.assertRaises(ValueError):
            GrantSet.from_file(signed, require_signed=True)


class TestIdentityCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.caps = self.dir / "caps.json"
        self.caps.write_text(json.dumps(CAPS), encoding="utf-8")

    def test_keygen_creates_usable_identity(self):
        rc, out, err = run_cli("keygen", str(self.dir / "agent.json"),
                               "--id", "agent-A91")
        self.assertEqual(rc, 0)
        self.assertIn("keep private", err)
        ident = json.loads((self.dir / "agent.json").read_text(encoding="utf-8"))
        self.assertEqual(ident["agent_id"], "agent-A91")
        self.assertEqual(len(ident["public_key"]), 64)
        key = json.loads((self.dir / "agent.key").read_text(encoding="utf-8"))
        self.assertEqual(len(key["secret_key"]), 64)

    def test_full_sign_flow_with_tamper_refusal(self):
        rc, _, _ = run_cli("keygen", str(self.dir / "agent.json"),
                           "--id", "agent-A91")
        self.assertEqual(rc, 0)
        signed = self.dir / "signed.json"
        rc, _, err = run_cli("sign-caps", str(self.caps),
                             "--agent", str(self.dir / "agent.json"),
                             "--key", str(self.dir / "agent.key"),
                             "--out", str(signed))
        self.assertEqual((rc, err), (0, "signed grants written to "
                                     + str(signed) + "\n"))
        rc, out, _ = run_cli("verify-caps", str(signed))
        self.assertEqual((rc, out.count("OK")), (0, 1))
        rc, out, _ = run_cli("verify-caps", str(signed), "--json")
        self.assertEqual(json.loads(out)["grants"], 1)

        # a validly signed file authorizes the run even with --require-signed
        (self.dir / "p.ai").write_text(
            'node 001\nop const\ntype string\nvalue "x"\n\n'
            "node 002\nop emit\ninput 001\n", encoding="utf-8")
        rc, out, err = run_cli("run", str(self.dir / "p.ai"),
                               "--caps", str(signed), "--require-signed")
        self.assertEqual((rc, out), (0, "x\n"))

        # tamper: widen the grant scope -> signature breaks -> refusal
        envelope = json.loads(signed.read_text(encoding="utf-8"))
        envelope["payload"]["grants"][0]["resource"] = "/"
        signed.write_text(json.dumps(envelope), encoding="utf-8")
        rc, _, err = run_cli("run", str(self.dir / "p.ai"),
                             "--caps", str(signed), "--require-signed")
        self.assertEqual(rc, 3)
        self.assertIn("signature verification FAILED", err)

    def test_sign_caps_refuses_already_signed_file(self):
        run_cli("keygen", str(self.dir / "agent.json"), "--id", "a")
        signed = self.dir / "signed.json"
        run_cli("sign-caps", str(self.caps),
                "--agent", str(self.dir / "agent.json"),
                "--key", str(self.dir / "agent.key"), "--out", str(signed))
        rc, _, err = run_cli("sign-caps", str(signed),
                             "--agent", str(self.dir / "agent.json"),
                             "--key", str(self.dir / "agent.key"))
        self.assertEqual(rc, 3)
        self.assertIn("already signed", err)

    def test_sign_caps_requires_agent_and_key(self):
        rc, _, err = run_cli("sign-caps", str(self.caps))
        self.assertEqual(rc, 3)
        self.assertIn("--agent", err)


if __name__ == "__main__":
    unittest.main()
