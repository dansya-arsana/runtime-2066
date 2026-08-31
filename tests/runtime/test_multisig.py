"""Multisig approvals (Phase 11 prep): m-of-n signed envelopes."""

import unittest

from runtime import generate_identity
from runtime.multisig import sign_multisig, verify_multisig


class TestMultisig(unittest.TestCase):
    def setUp(self):
        self.a, self.a_secret = generate_identity("agent-A")
        self.b, self.b_secret = generate_identity("agent-B")
        self.c, self.c_secret = generate_identity("agent-C")

    def _sign(self, keys, payload=None):
        payload = payload or {"grants": [{"action": "x"}]}
        return sign_multisig(payload, keys, "2026-08-31T00:00:00+00:00")

    def test_meets_threshold(self):
        envelope = self._sign([(self.a, self.a_secret),
                               (self.b, self.b_secret)])
        result = verify_multisig(envelope, threshold=2)
        self.assertEqual(sorted(result["signers"]),
                         sorted(["agent-A", "agent-B"]))

    def test_below_threshold_refused(self):
        envelope = self._sign([(self.a, self.a_secret)])
        with self.assertRaises(Exception) as ctx:
            verify_multisig(envelope, threshold=2)
        self.assertEqual(ctx.exception.code, "E602")

    def test_forged_signature_does_not_count(self):
        envelope = self._sign([(self.a, self.a_secret),
                               (self.c, self.c_secret)])
        envelope["signatures"][1]["signature"] = "ff" * 64
        with self.assertRaises(Exception) as ctx:
            verify_multisig(envelope, threshold=2)
        self.assertIn("1 valid", str(ctx.exception.detail))

    def test_untrusted_key_ignored_when_pinned(self):
        envelope = self._sign([(self.c, self.c_secret)])
        with self.assertRaises(Exception):
            verify_multisig(envelope, threshold=1,
                            trust_keys={self.a.public_key})

    def test_duplicate_signer_counts_once(self):
        envelope = self._sign([(self.a, self.a_secret),
                               (self.a, self.a_secret)])
        with self.assertRaises(Exception):
            verify_multisig(envelope, threshold=2)

    def test_payload_tampering_breaks_all(self):
        envelope = self._sign([(self.a, self.a_secret),
                               (self.b, self.b_secret)])
        envelope["payload"]["grants"][0]["resource"] = "/"
        with self.assertRaises(Exception):
            verify_multisig(envelope, threshold=2)


if __name__ == "__main__":
    unittest.main()
