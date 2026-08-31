"""2066 KEY v1: any disk as a human authority key (§31–§33 prep, §84 beats
in software form) + delegation approval flow."""

import json
import tempfile
import unittest
from pathlib import Path

from runtime import keydisk
from tests.helpers import run_cli

WANTED = {"subject": "agent-A91", "grants": [
    {"action": "filesystem.read", "resource": "examples/incoming"}]}


class TestKeyDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.disk = Path(self.tmp.name) / "flashdisk"
        self.disk.mkdir()

    def test_format_inspect_round_trip(self):
        result = keydisk.format_key(self.disk, "human-1", "1234")
        self.assertTrue(result["agent_id"].startswith("human-1"))
        self.assertTrue(keydisk.is_key(self.disk))
        info = keydisk.inspect_key(self.disk)
        self.assertEqual(info["identity"]["algorithm"], "ed25519")
        self.assertEqual(info["wrong_pin_attempts"], 0)
        # the secret at rest is not the raw seed: encrypted blob
        blob = (self.disk / ".2066key" / "secret.enc").read_bytes()
        self.assertNotIn(b"2066", blob[:32])

    def test_unlock_with_correct_pin(self):
        keydisk.format_key(self.disk, "human-1", "1234")
        ident, seed = keydisk.unlock(self.disk, "1234")
        self.assertEqual(ident.algorithm, "ed25519")
        self.assertEqual(len(seed), 64)
        # counter resets after success
        self.assertEqual(keydisk.inspect_key(self.disk)[
            "wrong_pin_attempts"], 0)

    def test_wrong_pin_counts_and_recovers(self):
        keydisk.format_key(self.disk, "human-1", "1234")
        for expected_attempts in (1, 2):
            with self.assertRaises(keydisk.KeyError_) as ctx:
                keydisk.unlock(self.disk, "0000")
            self.assertIn(f"{expected_attempts}/8", str(ctx.exception))
        ident, _ = keydisk.unlock(self.disk, "1234")
        self.assertEqual(ident.agent_id.split("-")[0], "human")

    def test_self_destruct_after_max_attempts(self):
        keydisk.format_key(self.disk, "human-1", "1234")
        for _ in range(keydisk.MAX_ATTEMPTS):
            try:
                keydisk.unlock(self.disk, "0000")
            except keydisk.KeyError_:
                pass
        self.assertFalse((self.disk / ".2066key" / "secret.enc").exists())
        with self.assertRaises(keydisk.KeyError_) as ctx:
            keydisk.unlock(self.disk, "1234")  # even the right PIN now
        self.assertIn("destroyed", str(ctx.exception))

    def test_cannot_read_secret_with_wrong_pin_even_offline(self):
        keydisk.format_key(self.disk, "human-1", "1234")
        blob = (self.disk / ".2066key" / "secret.enc").read_bytes()
        # copying the blob elsewhere and brute-forcing still needs the PIN
        # (AES-GCM authenticated): wrong PIN can never yield a seed
        for wrong in ("", "123", "12345"):
            with self.assertRaises(keydisk.KeyError_):
                keydisk.unlock(self.disk, wrong)

    def test_dangerous_targets_refused(self):
        with self.assertRaises(keydisk.KeyError_):
            keydisk.check_safe_target(Path("C:/"))
        with self.assertRaises(keydisk.KeyError_):
            keydisk.check_safe_target(Path.home())
        with self.assertRaises(keydisk.KeyError_):
            keydisk.check_safe_target(Path(self.tmp.name) / "missing")

    def test_reformat_replaces_key(self):
        keydisk.format_key(self.disk, "human-1", "1234")
        first = keydisk.inspect_key(self.disk)["identity"]["public_key"]
        keydisk.format_key(self.disk, "human-1", "5678")
        second = keydisk.inspect_key(self.disk)["identity"]["public_key"]
        self.assertNotEqual(first, second)
        ident, _ = keydisk.unlock(self.disk, "5678")
        self.assertEqual(ident.public_key, second)


class TestApprovalFlow(unittest.TestCase):
    """§84 beats in software form: deny -> approve from key -> allow ->
    expiry deny."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.disk = Path(self.tmp.name) / "flashdisk"
        self.disk.mkdir()
        self.wanted = Path(self.tmp.name) / "wanted.json"
        self.wanted.write_text(json.dumps(WANTED), encoding="utf-8")
        self.signed = Path(self.tmp.name) / "signed.json"

    def test_beats_end_to_end(self):
        # format the "old flashdisk"
        rc, out, err = run_cli("key-format", str(self.disk),
                               "--id", "human-1", "--pin", "1234")
        self.assertEqual((rc, err.splitlines()[-1]),
                         (0, "keep this disk physically private — it is a "
                             "bearer object"))
        self.assertIn("key formatted", out)

        # beat 1: no approval -> denied
        rc, _, err = run_cli("run", "examples/file_read.ai")
        self.assertEqual(rc, 4)
        self.assertIn("E401", err)

        # beat 2: human approves from the key, 5-minute TTL
        rc, _, err = run_cli("approve", str(self.wanted),
                             "--key", str(self.disk), "--pin", "1234",
                             "--ttl-minutes", "5", "--out", str(self.signed))
        self.assertEqual(rc, 0)
        self.assertIn("approved by human-1", err)
        self.assertIn("expires in 5 min", err)

        # the delegation carries the human as issuer + expiry
        envelope = json.loads(self.signed.read_text("utf-8"))
        self.assertEqual(envelope["issued_by"]["agent_id"], "human-1")
        self.assertTrue(envelope["payload"]["grants"][0]["expires"])

        # beat 3: allowed under the approved grant
        rc, out, _ = run_cli("run", "examples/file_read.ai",
                             "--caps", str(self.signed), "--require-signed")
        self.assertEqual((rc, out),
                         (0, "The runtime decides — not the model.\n\n"))

        # beat 4: past expiry -> denied E402
        rc, _, err = run_cli("run", "examples/file_read.ai",
                             "--caps", str(self.signed), "--require-signed",
                             "--now", "2030-01-01T00:00:00Z")
        self.assertEqual(rc, 4)
        self.assertIn("E402", err)

    def test_tampered_approval_is_refused(self):
        run_cli("key-format", str(self.disk), "--id", "human-1",
                "--pin", "1234")
        run_cli("approve", str(self.wanted), "--key", str(self.disk),
                "--pin", "1234", "--out", str(self.signed))
        envelope = json.loads(self.signed.read_text("utf-8"))
        envelope["payload"]["grants"][0]["resource"] = "examples"  # widen
        self.signed.write_text(json.dumps(envelope), encoding="utf-8")
        rc, _, err = run_cli("run", "examples/file_read.ai",
                             "--caps", str(self.signed), "--require-signed")
        self.assertEqual(rc, 3)
        self.assertIn("signature verification FAILED", err)

    def test_approve_requires_key_and_plain_grants(self):
        self.assertEqual(run_cli("approve", str(self.wanted))[0], 3)
        run_cli("key-format", str(self.disk), "--id", "human-1",
                "--pin", "1234")
        run_cli("approve", str(self.wanted), "--key", str(self.disk),
                "--pin", "1234", "--out", str(self.signed))
        # already signed -> refused
        rc, _, err = run_cli("approve", str(self.signed),
                             "--key", str(self.disk), "--pin", "1234")
        self.assertEqual((rc, err.split("error:")[-1].strip()[:12]),
                         (3, "approve sign"))

    def test_wrong_pin_via_cli_counts(self):
        run_cli("key-format", str(self.disk), "--id", "human-1",
                "--pin", "1234")
        rc, _, err = run_cli("approve", str(self.wanted),
                             "--key", str(self.disk), "--pin", "9999")
        self.assertEqual(rc, 3)
        self.assertIn("1/8", err)
        rc, out, _ = run_cli("key-inspect", str(self.disk))
        self.assertIn("attempts: 1", out)


if __name__ == "__main__":
    unittest.main()
