"""Session capabilities (roadmap §4.6, §18) and the session.verify op."""

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from runtime import analyze, execute, execute_plan, generate_identity, parse_source
from runtime.session import SessionVerifier, mint_session_token
from runtime import identity
from tests.helpers import run_cli

VERIFY_PROGRAM = (
    'node 001\nop const\ntype string\nvalue TOKEN_PLACEHOLDER\n\n'
    "node 002\nop session.verify\ninput 001\noutput i64\n\n"
    "node 003\nop emit\ninput 002\n"
)


class TestSessionTokens(unittest.TestCase):
    def setUp(self):
        self.ident, self.secret = generate_identity("server")
        self.verifier = SessionVerifier(public_key=self.ident.public_key)

    def test_round_trip(self):
        token = mint_session_token(self.secret, 42)
        self.assertEqual(self.verifier.verify("001", token), 42)

    def test_forged_token_denied(self):
        _, attacker_secret = generate_identity("attacker")
        with self.assertRaises(Exception) as ctx:
            self.verifier.verify("001", mint_session_token(attacker_secret, 42))
        self.assertEqual(ctx.exception.code, "E406")
        self.assertIn("signature FAILED", ctx.exception.detail)

    def test_expired_token_denied(self):
        stale = mint_session_token(
            self.secret, 42,
            now=datetime.now(timezone.utc) - timedelta(hours=2))
        with self.assertRaises(Exception) as ctx:
            self.verifier.verify("001", stale)
        self.assertEqual(ctx.exception.code, "E407")

    def test_future_expiry_still_valid(self):
        fresh = mint_session_token(
            self.secret, 42,
            now=datetime.now(timezone.utc) - timedelta(minutes=1),
            ttl_minutes=30)
        self.assertEqual(self.verifier.verify("001", fresh), 42)

    def test_tampered_payload_denied(self):
        token = mint_session_token(self.secret, 42)
        body_b64, sig = token.split(".")
        decoded = json.loads(
            __import__("base64").urlsafe_b64decode(body_b64 + "=="))
        decoded["subject_id"] = 1  # try to become the admin
        import base64
        re_encoded = base64.urlsafe_b64encode(
            json.dumps(decoded, sort_keys=True, separators=(",", ":"))
            .encode()).decode().rstrip("=")
        with self.assertRaises(Exception) as ctx:
            self.verifier.verify("001", f"{re_encoded}.{sig}")
        self.assertEqual(ctx.exception.code, "E406")

    def test_garbage_denied(self):
        for bad in ("garbage", "a.b.c", "", "...."):
            with self.subTest(token=bad):
                with self.assertRaises(Exception) as ctx:
                    self.verifier.verify("001", bad)
                self.assertEqual(ctx.exception.code, "E406")

    def test_programs_cannot_mint(self):
        # the instruction set has no mint operation — structural guarantee
        from runtime.validator import _OPS
        self.assertNotIn("session.mint", _OPS)
        self.assertNotIn("session.create", _OPS)


class TestSessionVerifyOp(unittest.TestCase):
    def setUp(self):
        self.ident, self.secret = generate_identity("server")
        self.verifier = SessionVerifier(public_key=self.ident.public_key)
        self.token = mint_session_token(self.secret, 7)

    def _program(self):
        return parse_source(
            VERIFY_PROGRAM.replace("TOKEN_PLACEHOLDER",
                                   json.dumps(self.token)))

    def test_op_executes_in_both_adapters(self):
        for runner in (execute, execute_plan):
            with self.subTest(adapter=runner.__name__):
                program = self._program()
                self.assertEqual(
                    runner(program, analyze(program), sessions=self.verifier),
                    [7])

    def test_default_deny_without_verifier(self):
        program = self._program()
        for runner in (execute, execute_plan):
            with self.subTest(adapter=runner.__name__):
                with self.assertRaises(Exception) as ctx:
                    runner(program, analyze(program))
                self.assertEqual(ctx.exception.code, "E401")
                self.assertIn("no session verifier", ctx.exception.detail)

    def test_forged_token_in_program_denied(self):
        _, attacker = generate_identity("attacker")
        program = parse_source(VERIFY_PROGRAM.replace(
            "TOKEN_PLACEHOLDER", json.dumps(
                mint_session_token(attacker, 1))))
        with self.assertRaises(Exception) as ctx:
            execute(program, analyze(program), sessions=self.verifier)
        self.assertEqual(ctx.exception.code, "E406")

    def test_op_requires_string_input(self):
        program = parse_source(
            "node 001\nop const\ntype i64\nvalue 5\n\n"
            "node 002\nop session.verify\ninput 001\noutput i64\n")
        with self.assertRaises(Exception) as ctx:
            analyze(program)
        self.assertEqual(ctx.exception.code, "E203")

    def test_effects_manifest_includes_identity(self):
        program = self._program()
        from runtime import program_effects
        self.assertIn("IDENTITY", program_effects(program))

    def test_cli_session_key_flag(self):
        with tempfile.TemporaryDirectory() as tmp:
            ident_path = Path(tmp) / "server.json"
            key_path = Path(tmp) / "server.key"
            program_path = Path(tmp) / "p.ai"
            ident_path.write_text(json.dumps({
                "agent_id": "server", "algorithm": "ed25519",
                "public_key": self.ident.public_key}), encoding="utf-8")
            key_path.write_text(json.dumps({
                "agent_id": "server", "algorithm": "ed25519",
                "secret_key": self.secret}), encoding="utf-8")
            program_path.write_text(VERIFY_PROGRAM.replace(
                "TOKEN_PLACEHOLDER", json.dumps(self.token)),
                encoding="utf-8")
            rc, out, err = run_cli("run", str(program_path),
                                   "--session-key", str(ident_path))
            self.assertEqual((rc, out, err), (0, "7\n", ""))
            # without the flag: default deny
            rc, _, err = run_cli("run", str(program_path))
            self.assertEqual(rc, 4)
            self.assertIn("no session verifier", err)
            # bad key file: usage error
            rc, _, err = run_cli("run", str(program_path),
                                 "--session-key", str(program_path))
            self.assertEqual(rc, 3)

    def test_export_refuses_identity_effects(self):
        from runtime import export_python
        program = self._program()
        with self.assertRaises(ValueError) as ctx:
            export_python(program, analyze(program))
        self.assertIn("IDENTITY", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
