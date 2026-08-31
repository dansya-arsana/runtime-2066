"""Fuzz targets (hardening plan SS34 / H6 / SS78 security gate).

Deterministic mutation fuzzing over the trust-critical loaders. The
invariant under fuzz is not "no exception" — it is classification:

    malformed input may ONLY raise the allowed structured failure types
    or be cleanly refused — never an unrelated crash, and NEVER a
    silent acceptance of mutated trust material.

Targets (plan SS34 fuzz list): grant loader, signature envelope,
proposal verifier, evidence chain, package manifests.
"""

import json
import random
import tempfile
import unittest
from pathlib import Path

from runtime import identity, parse_source
from runtime.capabilities import GrantSet, sign_capabilities, verify_envelope
from runtime.evidence import EvidenceLog, verify_evidence
from runtime.errors import StructuredError
from runtime.packages import load_manifest
from runtime.proposals import create_proposal, verify_proposal

SEED = 2066
ALLOWED = (ValueError, json.JSONDecodeError, StructuredError, OSError,
           KeyError, TypeError)

BASE = Path(__file__).resolve().parents[2]
HELLO = (BASE / "examples" / "hello.ai").read_text(encoding="utf-8")
CALL = (BASE / "examples" / "call.ai").read_text(encoding="utf-8")


def mutations(rng: random.Random, text: str, count: int) -> list:
    """Deterministic text mutations: char flips, splices, truncations,
    duplications, adversarial injections."""
    out = []
    for _ in range(count):
        chars = list(text)
        if not chars:
            break
        strategy = rng.randrange(5)
        if strategy == 0:                       # flip a char
            pos = rng.randrange(len(chars))
            chars[pos] = rng.choice("abz{}[]\\.:,0123456789")
        elif strategy == 1:                     # truncate
            chars = chars[:rng.randrange(len(chars))]
        elif strategy == 2:                     # duplicate a slice
            a = rng.randrange(len(chars))
            b = min(len(chars), a + rng.randrange(1, 40))
            chars[a:a] = chars[a:b]
        elif strategy == 3:                     # delete a slice
            a = rng.randrange(len(chars))
            b = min(len(chars), a + rng.randrange(1, 40))
            del chars[a:b]
        else:                                   # inject adversarial text
            pos = rng.randrange(len(chars))
            chars[pos:pos] = rng.choice(
                ["adversary\", \"", "}}}", "{{{",
                 "\"admin\": true", "null,", "0x"])
        out.append("".join(chars))
    return out


class TestGrantLoaderFuzz(unittest.TestCase):
    def setUp(self):
        self.path = Path(tempfile.mkdtemp()) / "caps.json"
        self.valid = {"subject": "t", "grants": [
            {"action": "data.read", "resource": "business"},
            {"action": "data.write", "resource": "business",
             "expires": "2027-01-01T00:00:00Z"}]}

    def test_mutated_grant_files_only_fail_structuredly(self):
        rng = random.Random(SEED)
        text = json.dumps(self.valid, indent=1)
        accepted_clean = 0
        for i, mutant in enumerate(mutations(rng, text, 300)):
            self.path.write_text(mutant, encoding="utf-8")
            try:
                GrantSet.from_file(str(self.path))
                accepted_clean += 1
            except ALLOWED:
                pass                          # classified refusal: fine
            except Exception as exc:          # noqa: BLE001
                self.fail(f"mutant {i}: unhandled "
                          f"{type(exc).__name__}: {exc}")
        # sanity: at least some mutants remain valid-but-ugly JSON
        self.assertGreater(accepted_clean, 0)


class TestSignedEnvelopeFuzz(unittest.TestCase):
    def setUp(self):
        self.ident, self.secret = identity.generate_identity("fuzz")
        self.envelope = sign_capabilities(
            {"subject": "t", "grants": [
                {"action": "data.read", "resource": "note"}]},
            self.ident, self.secret, "2026-08-31T00:00:00Z")
        # control: the pristine envelope verifies
        self.assertEqual(
            verify_envelope(self.envelope)["subject"], "t")

    def test_mutated_envelopes_never_silently_verify(self):
        """Under require_signed (production profile), a mutated envelope
        either fails verification or returns exactly the signed payload
        — never attacker-chosen content."""
        rng = random.Random(SEED)
        text = json.dumps(self.envelope)
        for i, mutant in enumerate(mutations(rng, text, 300)):
            try:
                payload = verify_envelope(json.loads(mutant),
                                          require_signed=True)
            except ALLOWED:
                continue
            except Exception as exc:          # noqa: BLE001
                self.fail(f"mutant {i}: unhandled {type(exc).__name__}")
            self.assertEqual(payload["subject"], "t",
                             f"mutant {i}: mutated envelope verified "
                             "to different content")

    def test_signature_stripping_is_the_transition_hole(self):
        """FUZZ FINDING (H6), pinned: destroying the signature turns a
        signed envelope into an UNSIGNED one — accepted by the
        development default (documented transition, plan SS44), refused
        by the production profile. This is exactly why H4 exists."""
        stripped = {k: v for k, v in self.envelope.items()
                    if k != "signature"}
        # dev default: accepted (unsigned envelopes carry their payload
        # nested — the transition shape from GrantSet.from_dict)
        result = verify_envelope(stripped)
        subject = (result.get("payload", result)).get("subject")
        self.assertEqual(subject, "t")
        with self.assertRaises(ValueError):
            verify_envelope(stripped, require_signed=True)  # prod: no


class TestProposalFuzz(unittest.TestCase):
    def setUp(self):
        self.ident, self.secret = identity.generate_identity("fuzz")
        base = parse_source(HELLO)
        proposed = parse_source(CALL)
        self.proposal = create_proposal(
            base, proposed, self.ident, self.secret,
            "2026-08-31T00:00:00Z")
        self.base = base

    def test_mutated_proposals_fail_verification_or_verify(self):
        rng = random.Random(SEED)
        text = json.dumps(self.proposal)
        for i, mutant in enumerate(mutations(rng, text, 200)):
            try:
                verify_proposal(json.loads(mutant), self.base)
            except ALLOWED:
                continue
            except Exception as exc:          # noqa: BLE001
                self.fail(f"mutant {i}: unhandled {type(exc).__name__}")


class TestEvidenceChainFuzz(unittest.TestCase):
    def setUp(self):
        directory = Path(tempfile.mkdtemp())
        self.path = str(directory / "evidence.jsonl")
        log = EvidenceLog(self.path)
        for n in range(8):
            log.append("data.write", "business", f"row={n}")

    def test_mutated_chains_are_detected_or_classified(self):
        self.assertTrue(verify_evidence(self.path)["ok"])
        rng = random.Random(SEED)
        text = Path(self.path).read_text(encoding="utf-8")
        tampered = 0
        for n, mutant in enumerate(mutations(rng, text, 60)):
            Path(self.path).write_text(mutant, encoding="utf-8")
            try:
                result = verify_evidence(self.path)
                self.assertIn("ok", result)
                if not result["ok"]:
                    tampered += 1
            except ALLOWED:
                tampered += 1
            except Exception as exc:          # noqa: BLE001
                self.fail(f"mutant {n}: unhandled {type(exc).__name__}")
        self.assertGreater(tampered, 0, "tampering must be detectable")

    def test_single_byte_flip_in_event_breaks_chain(self):
        lines = Path(self.path).read_text(encoding="utf-8").splitlines()
        chars = list(lines[3])
        chars[10] = "X" if chars[10] != "X" else "Y"
        lines[3] = "".join(chars)
        Path(self.path).write_text("\n".join(lines), encoding="utf-8")
        self.assertFalse(verify_evidence(self.path).get("ok", False),
                         "flipped byte inside a chained event must "
                         "invalidate the chain")


class TestManifestFuzz(unittest.TestCase):
    def test_mutated_manifests_fail_structuredly(self):
        rng = random.Random(SEED)
        valid = "package fuzzed\nversion 1.0.0\n\nmodule core\n"
        root = Path(tempfile.mkdtemp()) / "fuzzed" / "core"
        root.mkdir(parents=True)
        (root / "x.ai").write_text(HELLO, encoding="utf-8")
        manifest = root.parent / "package.ai"
        for i, mutant in enumerate(mutations(rng, valid, 120)):
            manifest.write_text(mutant, encoding="utf-8")
            try:
                load_manifest(manifest)
            except ALLOWED:
                pass
            except Exception as exc:          # noqa: BLE001
                self.fail(f"mutant {i}: unhandled {type(exc).__name__}")


if __name__ == "__main__":
    unittest.main()
