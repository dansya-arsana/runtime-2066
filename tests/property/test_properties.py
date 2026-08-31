"""Property-based tests (hardening plan §34 / H6).

Deterministic: every loop runs on a fixed seed — properties, not
statistics. The four protocol properties pinned here:

  P1  canonicalization is idempotent
  P2  canonical form is hash-stable (formatting is not identity)
  P3  sign(verify) round-trips; any mutation breaks verification
  P4  authority cannot widen itself (subset grants stay subset)
"""

import json
import random
import tempfile
import unittest
from pathlib import Path

from runtime import (PROTOCOL_VERSION, __version__, analyze, identity,
                     parse_source, program_hash, serialize_program)
from runtime.capabilities import (GrantSet, sign_capabilities,
                                  verify_envelope)
from tests.helpers import ROOT

SEED = 2066
CORPUS = json.loads(
    (ROOT / "protocol" / "conformance" / "corpus.json")
    .read_text(encoding="utf-8"))["programs"]


class TestCanonicalizationProperties(unittest.TestCase):
    def test_p1_canonicalization_is_idempotent(self):
        """serialize(parse(serialize(parse(src)))) == serialize(parse(src))
        for every frozen corpus program."""
        for rel in CORPUS:
            with self.subTest(program=rel):
                source = (ROOT / rel).read_text(encoding="utf-8")
                once = serialize_program(parse_source(source))
                twice = serialize_program(parse_source(once))
                self.assertEqual(once, twice)

    def test_p2_hash_is_formatting_independent(self):
        """The canonical text rehashes to the program's identity, and
        whitespace-padded source hashes identically too."""
        rng = random.Random(SEED)
        for rel in list(CORPUS)[:12]:
            with self.subTest(program=rel):
                source = (ROOT / rel).read_text(encoding="utf-8")
                expected = program_hash(parse_source(source))
                canonical = serialize_program(parse_source(source))
                self.assertEqual(
                    program_hash(parse_source(canonical)), expected)
                padded = canonical.replace("\n", "\n\n" if rng.random() < .5
                                           else "\n\n\n")
                self.assertEqual(
                    program_hash(parse_source(padded)), expected,
                    "formatting leaked into identity")


class TestSigningProperties(unittest.TestCase):
    def setUp(self):
        self.ident, self.secret = identity.generate_identity("prop")
        self.payload = {"subject": "sales",
                        "grants": [{"action": "data.read",
                                    "resource": "business"}]}

    def test_p3_sign_verify_round_trip_and_mutation_fails(self):
        envelope = sign_capabilities(self.payload, self.ident,
                                     self.secret, "2026-08-31T00:00:00Z")
        self.assertEqual(verify_envelope(envelope), self.payload)

        rng = random.Random(SEED)
        broken = 0
        for _ in range(50):
            candidate = json.loads(json.dumps(envelope))
            # mutate one hex character of the signature
            sig = list(candidate["signature"])
            pos = rng.randrange(len(sig))
            sig[pos] = "0" if sig[pos] != "0" else "1"
            candidate["signature"] = "".join(sig)
            try:
                verify_envelope(candidate)
            except (ValueError, Exception) as exc:  # noqa: BLE001
                self.assertIsInstance(  # structured refusal, never accept
                    exc, (ValueError, type(None)))
                broken += 1
        self.assertEqual(broken, 50,
                         "every mutated signature must fail verification")


class TestAuthorityProperties(unittest.TestCase):
    def test_p4_grants_cannot_widen_themselves(self):
        """A grant set with only data.read can never authorize a write —
        no combination of granted entries widens authority (§46)."""
        grants = GrantSet.from_dict({"subject": "t", "grants": [
            {"action": "data.read", "resource": "business"},
            {"action": "data.read", "resource": "note"},
        ]})
        from runtime.errors import StructuredError
        for action in ("data.write", "data.delete", "filesystem.read",
                       "net.request"):
            with self.subTest(action=action):
                with self.assertRaises(StructuredError) as ctx:
                    grants.check(action, "business")
                self.assertEqual(ctx.exception.code, "E401")


class TestPackageIdentityProperties(unittest.TestCase):
    def test_unit_hash_equals_direct_hash_for_every_sales_unit(self):
        """Identity is semantic: store resolution and direct file parse
        of the same unit hash identically (H3 invariant, whole package)."""
        from runtime.packages import PackageStore
        store = PackageStore(ROOT / "programs")
        for address in store.addresses():
            with self.subTest(unit=address):
                unit = store.unit(address)
                direct = program_hash(parse_source(
                    unit.path.read_text(encoding="utf-8")))
                self.assertEqual(unit.hash, direct)


class TestVersionSeparation(unittest.TestCase):
    def test_protocol_and_runtime_version_independently(self):
        """§29: the protocol version exists, is semver-shaped, and is
        distinct from the runtime version."""
        self.assertRegex(PROTOCOL_VERSION, r"^\d+\.\d+$")
        self.assertNotEqual(PROTOCOL_VERSION, __version__)


if __name__ == "__main__":
    unittest.main()
