"""Stage C (Human Trust Layer), software-completable pieces:

- multisig approvals from m key disks (approve --multisig 2-of-3)
- delegation chains: human -> agent -> sub-agent, every link signed
- key rotation: new keypair + new PIN, history in rotation.log
"""

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime import generate_identity, keydisk
from runtime.capabilities import verify_envelope
from runtime.delegation import (build_delegation, chain_ok, walk_chain)
from runtime.pinning import TrustStore
from runtime.revocation import grant_id
from tests.helpers import run_cli

WANTED = {"subject": "agent-A91", "grants": [
    {"action": "filesystem.read", "resource": "examples/incoming"}]}


class StageCHarness(unittest.TestCase):
    """Shared fixtures: temp dirs, key disks, identities."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)

    def disk(self, name: str, human_id: str, pin: str = "1234") -> Path:
        path = self.root / name
        path.mkdir(parents=True, exist_ok=True)
        keydisk.format_key(path, human_id, pin)
        return path

    def write(self, name: str, payload) -> Path:
        path = self.root / name
        path.write_text(payload if isinstance(payload, str)
                        else json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def trust_store(self, name: str, entries: list[dict]) -> Path:
        return self.write(name, {"version": 1, "issuers": entries})

    def keygen(self, agent_id: str) -> tuple[Path, Path]:
        identity_path = self.root / f"{agent_id}.json"
        rc, _, _ = run_cli("keygen", str(identity_path), "--id", agent_id)
        self.assertEqual(rc, 0)
        secret_path = self.root / f"{agent_id}.key"
        return identity_path, secret_path


class TestMultisigApprove(StageCHarness):
    def setUp(self):
        super().setUp()
        self.disks = [self.disk(f"disk{i}", f"human-{i}") for i in (1, 2, 3)]
        self.caps = self.write("caps.json", WANTED)
        self.signed = self.root / "signed.json"

    def test_two_of_three_with_three_keys(self):
        rc, out, err = run_cli(
            "approve", str(self.caps), "--multisig", "2-of-3",
            "--key", str(self.disks[0]), "--key", str(self.disks[1]),
            "--key", str(self.disks[2]), "--pin", "1234",
            "--out", str(self.signed))
        self.assertEqual(rc, 0)
        self.assertIn("3 signer(s), 2-of-3", err)
        envelope = json.loads(self.signed.read_text("utf-8"))
        self.assertNotIn("signature", envelope)  # list form, not scalar
        self.assertEqual(len(envelope["signatures"]), 3)
        signers = {s["agent_id"] for s in envelope["signatures"]}
        self.assertEqual(signers, {"human-1", "human-2", "human-3"})
        # threshold is stamped into the SIGNED payload
        self.assertEqual(envelope["payload"]["multisig"],
                         {"threshold": 2, "total": 3})

    def test_two_of_three_with_two_keys_present(self):
        rc, _, err = run_cli(
            "approve", str(self.caps), "--multisig", "2-of-3",
            "--key", str(self.disks[0]), "--key", str(self.disks[1]),
            "--pin", "1234", "--out", str(self.signed))
        self.assertEqual(rc, 0)
        envelope = json.loads(self.signed.read_text("utf-8"))
        self.assertEqual(len(envelope["signatures"]), 2)

    def test_two_of_three_with_one_key_fails(self):
        rc, _, err = run_cli(
            "approve", str(self.caps), "--multisig", "2-of-3",
            "--key", str(self.disks[0]), "--pin", "1234",
            "--out", str(self.signed))
        self.assertEqual(rc, 3)
        self.assertIn("at least 2 --key disks", err)
        self.assertFalse(self.signed.exists())

    def test_bad_spec_is_usage_error(self):
        for bad in ("2of3", "2-of-x", "3-of-2", "-of-3"):
            rc, _, _ = run_cli("approve", str(self.caps), "--multisig", bad,
                               "--key", str(self.disks[0]), "--pin", "1234")
            self.assertEqual(rc, 3, bad)

    def test_threshold_cannot_be_lowered_after_signing(self):
        run_cli("approve", str(self.caps), "--multisig", "2-of-3",
                "--key", str(self.disks[0]), "--key", str(self.disks[1]),
                "--pin", "1234", "--out", str(self.signed))
        envelope = json.loads(self.signed.read_text("utf-8"))
        # attacker drops one signature AND lowers the threshold to 1:
        # both edits break the remaining signature's coverage
        envelope["signatures"] = envelope["signatures"][:1]
        envelope["payload"]["multisig"]["threshold"] = 1
        with self.assertRaises(ValueError):
            verify_envelope(envelope)


class TestMultisigVerification(StageCHarness):
    def setUp(self):
        super().setUp()
        self.disks = [self.disk(f"disk{i}", f"human-{i}") for i in (1, 2, 3)]
        self.caps = self.write("caps.json", WANTED)
        self.signed = self.root / "signed.json"
        entries = []
        for i in (1, 2, 3):
            ident = json.loads((self.disks[i - 1] / ".2066key" /
                                "identity.json").read_text("utf-8"))
            entries.append({"agent_id": ident["agent_id"],
                            "public_key": ident["public_key"]})
        self.entries = entries
        rc, _, _ = run_cli(
            "approve", str(self.caps), "--multisig", "2-of-3",
            "--key", str(self.disks[0]), "--key", str(self.disks[1]),
            "--pin", "1234", "--out", str(self.signed))
        self.assertEqual(rc, 0)

    def test_verify_envelope_accepts_and_returns_payload(self):
        envelope = json.loads(self.signed.read_text("utf-8"))
        payload = verify_envelope(envelope)
        self.assertEqual(payload["subject"], "agent-A91")

    def test_runs_under_trust_store(self):
        store = self.trust_store("store.json", self.entries)
        rc, out, _ = run_cli("run", "examples/file_read.ai",
                             "--caps", str(self.signed),
                             "--require-signed", "--trust-store", str(store))
        self.assertEqual((rc, out), (0, "The runtime decides — not the "
                                       "model.\n\n"))

    def test_unpinned_signer_refuses_whole_file(self):
        # only human-1 pinned: human-2's signature is untrusted
        store = self.trust_store("store.json", self.entries[:1])
        rc, _, err = run_cli("run", "examples/file_read.ai",
                             "--caps", str(self.signed),
                             "--require-signed", "--trust-store", str(store))
        self.assertEqual(rc, 3)
        self.assertIn("NOT in the trust store", err)

    def test_tampered_multisig_payload_refused(self):
        envelope = json.loads(self.signed.read_text("utf-8"))
        envelope["payload"]["grants"][0]["resource"] = "examples"  # widen
        self.write("tampered.json", envelope)
        store = self.trust_store("store.json", self.entries)
        rc, _, err = run_cli("run", "examples/file_read.ai",
                             "--caps", str(self.root / "tampered.json"),
                             "--require-signed", "--trust-store", str(store))
        self.assertEqual(rc, 3)
        self.assertIn("FAILED", err)

    def test_check_issuer_pinned_multisig_direct(self):
        envelope = json.loads(self.signed.read_text("utf-8"))
        from runtime.pinning import check_issuer_pinned
        pinned_all = TrustStore(self.entries)
        check_issuer_pinned(envelope, pinned_all, True)  # no exception
        pinned_one = TrustStore(self.entries[:1])
        with self.assertRaises(ValueError):
            check_issuer_pinned(envelope, pinned_one, True)


class TestDelegation(StageCHarness):
    def setUp(self):
        super().setUp()
        self.human_disk = self.disk("flashdisk", "human-1")
        self.caps = self.write("caps.json", WANTED)
        self.parent = self.root / "parent.json"
        rc, _, _ = run_cli("approve", str(self.caps),
                           "--key", str(self.human_disk), "--pin", "1234",
                           "--ttl-minutes", "60", "--out", str(self.parent))
        self.assertEqual(rc, 0)
        self.agent_id, self.agent_key = self.keygen("agent-A91")
        self.delegated = self.root / "delegated.json"

    def _delegate(self, parent=None, subject="sub-agent", out=None,
                  agent_id=None, agent_key=None, ttl=None):
        return run_cli("delegate", str(parent or self.parent),
                       "--agent", str(agent_id or self.agent_id),
                       "--key", str(agent_key or self.agent_key),
                       "--subject", subject,
                       *(["--ttl-minutes", str(ttl)] if ttl else []),
                       "--out", str(out or self.delegated))

    def test_human_agent_subagent_chain(self):
        rc, _, err = self._delegate(ttl=30)
        self.assertEqual(rc, 0)
        self.assertIn("delegated by agent-A91 -> sub-agent", err)
        child = json.loads(self.delegated.read_text("utf-8"))
        parent = json.loads(self.parent.read_text("utf-8"))
        # signed by the AGENT, not the human
        self.assertEqual(child["issued_by"]["agent_id"], "agent-A91")
        self.assertEqual(child["payload"]["subject"], "sub-agent")
        # narrowed TTL: child expires sooner than its parent
        child_exp = child["payload"]["grants"][0]["expires"]
        parent_exp = parent["payload"]["grants"][0]["expires"]
        self.assertLess(child_exp, parent_exp)
        # the link back to the parent's grant id, inside the SIGNED payload
        self.assertEqual(child["payload"]["delegated_by"]["grant_id"],
                         grant_id(parent))
        self.assertEqual(child["payload"]["delegated_by"]["issuer"], "human-1")

        # level 3: sub-agent delegates further
        sub_id, sub_key = self.keygen("sub-agent")
        level3 = self.root / "level3.json"
        rc, _, _ = self._delegate(parent=self.delegated, subject="worker-7",
                                  out=level3, agent_id=sub_id,
                                  agent_key=sub_key)
        self.assertEqual(rc, 0)
        leaf = json.loads(level3.read_text("utf-8"))
        self.assertEqual(leaf["issued_by"]["agent_id"], "sub-agent")
        self.assertEqual(leaf["payload"]["subject"], "worker-7")

        # the leaf actually authorizes execution (agent pinned as issuer)
        agent_identity = json.loads(self.agent_id.read_text("utf-8"))
        store = self.trust_store("agent-store.json", [
            {"agent_id": "agent-A91",
             "public_key": agent_identity["public_key"]}])
        rc, out, _ = run_cli("run", "examples/file_read.ai",
                             "--caps", str(self.delegated),
                             "--require-signed",
                             "--trust-store", str(store))
        self.assertEqual((rc, out), (0, "The runtime decides — not the "
                                       "model.\n\n"))

    def test_agent_cannot_delegate_authority_of_another(self):
        intruder_id, intruder_key = self.keygen("intruder")
        rc, _, err = self._delegate(agent_id=intruder_id,
                                    agent_key=intruder_key)
        self.assertEqual(rc, 1)
        self.assertIn("cannot delegate", err)
        self.assertIn("for subject 'agent-A91'", err)

    def test_expired_parent_cannot_delegate(self):
        human, secret = generate_identity("human-old")
        stale = self.write("expired-parent.json", {
            "subject": "agent-A91",
            "grants": [{"action": "filesystem.read",
                        "resource": "examples/incoming",
                        "expires": "2020-01-01T00:00:00Z"}],
        })
        # sign it properly — expiry, not the signature, must be the refusal
        from runtime.capabilities import sign_capabilities
        envelope = sign_capabilities(
            json.loads(stale.read_text("utf-8")), human, secret,
            "2019-12-31T00:00:00+00:00")
        stale = self.write("expired-parent.json", envelope)
        rc, _, err = self._delegate(parent=stale)
        self.assertEqual(rc, 1)
        self.assertIn("expired", err)
        self.assertFalse(self.delegated.exists())

    def test_subagent_cannot_widen_scope(self):
        parent = json.loads(self.parent.read_text("utf-8"))
        agent, agent_secret = generate_identity("agent-A91")
        with self.assertRaises(ValueError) as ctx:
            build_delegation(
                parent, self.parent, agent, agent_secret, "sub-agent",
                narrows=[{"action": "filesystem.read", "resource": "examples"}])
        self.assertIn("widening refused", str(ctx.exception))

    def test_narrows_within_scope_allowed(self):
        parent = json.loads(self.parent.read_text("utf-8"))
        agent, agent_secret = generate_identity("agent-A91")
        envelope = build_delegation(
            parent, self.parent, agent, agent_secret, "sub-agent",
            narrows=[{"action": "filesystem.read",
                      "resource": "examples/incoming/reports"}])
        grant = envelope["payload"]["grants"][0]
        self.assertEqual(grant["resource"], "examples/incoming/reports")

    def test_forged_parent_signature_refused(self):
        parent = json.loads(self.parent.read_text("utf-8"))
        parent["payload"]["grants"][0]["resource"] = "examples"  # widen
        forged = self.write("forged.json", parent)
        rc, _, err = self._delegate(parent=forged)
        self.assertEqual(rc, 1)
        self.assertIn("verification FAILED", err)

    def test_missing_flags_is_usage_error(self):
        rc, _, err = run_cli("delegate", str(self.parent),
                             "--agent", str(self.agent_id))
        self.assertEqual(rc, 3)
        self.assertIn("requires", err)


class TestChainCommand(StageCHarness):
    def setUp(self):
        super().setUp()
        self.human_disk = self.disk("flashdisk", "human-1")
        self.caps = self.write("caps.json", WANTED)
        self.parent = self.root / "parent.json"
        rc, _, _ = run_cli("approve", str(self.caps),
                           "--key", str(self.human_disk), "--pin", "1234",
                           "--ttl-minutes", "60", "--out", str(self.parent))
        self.assertEqual(rc, 0)
        self.agent_id, self.agent_key = self.keygen("agent-A91")
        self.delegated = self.root / "delegated.json"
        rc, _, _ = run_cli("delegate", str(self.parent),
                           "--agent", str(self.agent_id),
                           "--key", str(self.agent_key),
                           "--subject", "sub-agent",
                           "--out", str(self.delegated))
        self.assertEqual(rc, 0)
        self.sub_id, self.sub_key = self.keygen("sub-agent")
        self.level3 = self.root / "level3.json"
        rc, _, _ = run_cli("delegate", str(self.delegated),
                           "--agent", str(self.sub_id),
                           "--key", str(self.sub_key),
                           "--subject", "worker-7",
                           "--out", str(self.level3))
        self.assertEqual(rc, 0)

    def test_prints_full_three_level_chain(self):
        rc, out, _ = run_cli("chain", str(self.level3))
        self.assertEqual(rc, 0)
        self.assertIn("chain: 3 level(s)", out)
        self.assertIn("signer: sub-agent", out)
        self.assertIn("signer: agent-A91", out)
        self.assertIn("signer: human-1", out)
        self.assertIn("subject: worker-7", out)
        self.assertIn("filesystem.read", out)
        self.assertIn("OK — chain intact", out)

    def test_chain_json_mode(self):
        rc, out, _ = run_cli("chain", str(self.level3), "--json")
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertTrue(payload["ok"])
        self.assertEqual(len(payload["levels"]), 3)
        self.assertEqual(payload["levels"][-1]["issuer"], "human-1")

    def test_walk_chain_library_sees_all_levels(self):
        levels = walk_chain(self.level3)
        self.assertEqual([level["subject"] for level in levels],
                         ["worker-7", "sub-agent", "agent-A91"])
        self.assertTrue(chain_ok(levels))

    def test_detects_expired_link(self):
        # build an already-expired leaf via a frozen clock in the library
        parent = json.loads(self.parent.read_text("utf-8"))
        agent, agent_secret = generate_identity("agent-A91")
        stale = build_delegation(
            parent, self.parent, agent, agent_secret, "sub-agent",
            ttl_minutes=30, now=datetime(2020, 1, 1, tzinfo=timezone.utc))
        expired_file = self.write("expired.json", stale)
        rc, out, _ = run_cli("chain", str(expired_file))
        self.assertEqual(rc, 1)
        self.assertIn("EXPIRED", out)
        self.assertIn("BROKEN", out)

    def test_detects_revoked_link(self):
        revocations = self.root / "rev.jsonl"
        rc, _, _ = run_cli("revoke", str(self.parent),
                           "--revocations", str(revocations))
        self.assertEqual(rc, 0)
        rc, out, _ = run_cli("chain", str(self.level3),
                             "--revocations", str(revocations))
        self.assertEqual(rc, 1)
        self.assertIn("REVOKED", out)

    def test_tampered_link_breaks_chain(self):
        leaf = json.loads(self.level3.read_text("utf-8"))
        leaf["payload"]["grants"][0]["resource"] = "examples"
        tampered = self.write("tampered.json", leaf)
        rc, _, err = run_cli("chain", str(tampered))
        self.assertEqual(rc, 1)
        self.assertIn("verification FAILED", err)

    def test_missing_file_is_usage_error(self):
        rc, _, _ = run_cli("chain", str(self.root / "nope.json"))
        self.assertEqual(rc, 3)


class TestKeyRotation(StageCHarness):
    def setUp(self):
        super().setUp()
        self.disk_path = self.disk("flashdisk", "human-1", pin="1234")

    def test_rotation_replaces_pin_and_key(self):
        old = keydisk.inspect_key(self.disk_path)["identity"]
        rc, out, _ = run_cli("key-rotate", str(self.disk_path),
                             "--pin", "1234", "--new-pin", "5678")
        self.assertEqual(rc, 0)
        # "rotated: <old_id> -> <new_id>"
        self.assertRegex(out, r"^rotated: \S+ -> \S+")
        old_id, _, new_id = out.strip().removeprefix("rotated: ").partition(" -> ")
        self.assertEqual(old_id, "human-1")
        self.assertNotEqual(old_id, new_id)
        self.assertTrue(new_id.startswith("human-1"))

        # old PIN no longer unlocks
        with self.assertRaises(keydisk.KeyError_):
            keydisk.unlock(self.disk_path, "1234")
        # new PIN unlocks the NEW key
        ident, _ = keydisk.unlock(self.disk_path, "5678")
        self.assertNotEqual(ident.public_key, old["public_key"])
        self.assertEqual(ident.agent_id, new_id)

        # rotation history on the disk records the OLD public key
        log = self.disk_path / ".2066key" / "rotation.log"
        self.assertTrue(log.exists())
        records = [json.loads(line) for line
                   in log.read_text("utf-8").splitlines() if line.strip()]
        self.assertEqual(records[0]["from_public_key"], old["public_key"])
        self.assertEqual(records[0]["from_agent_id"], "human-1")

    def test_rotation_via_cli_message(self):
        rc, out, _ = run_cli("key-rotate", str(self.disk_path),
                             "--pin", "1234", "--new-pin", "5678")
        self.assertEqual(rc, 0)
        old_info = keydisk.inspect_key(self.disk_path)["identity"]
        self.assertIn(f"rotated: human-1 -> {old_info['agent_id']}", out)

    def test_wrong_old_pin_refused(self):
        before = keydisk.inspect_key(self.disk_path)["identity"]
        rc, _, err = run_cli("key-rotate", str(self.disk_path),
                             "--pin", "9999", "--new-pin", "5678")
        self.assertEqual(rc, 3)
        self.assertIn("wrong PIN", err)
        # nothing changed: the original PIN still works
        ident, _ = keydisk.unlock(self.disk_path, "1234")
        self.assertEqual(ident.public_key, before["public_key"])

    def test_second_rotation_appends_history(self):
        run_cli("key-rotate", str(self.disk_path), "--pin", "1234",
                "--new-pin", "5678")
        rc, out, _ = run_cli("key-rotate", str(self.disk_path),
                             "--pin", "5678", "--new-pin", "9012")
        self.assertEqual(rc, 0)
        log = self.disk_path / ".2066key" / "rotation.log"
        records = [json.loads(line) for line
                   in log.read_text("utf-8").splitlines() if line.strip()]
        self.assertEqual(len(records), 2)
        self.assertEqual(records[1]["from_agent_id"], records[0]["to_agent_id"])
        ident, _ = keydisk.unlock(self.disk_path, "9012")
        self.assertEqual(ident.agent_id, records[1]["to_agent_id"])

    def test_old_approvals_still_verify_after_rotation(self):
        caps = self.write("caps.json", WANTED)
        signed = self.root / "signed.json"
        run_cli("approve", str(caps), "--key", str(self.disk_path),
                "--pin", "1234", "--out", str(signed))
        run_cli("key-rotate", str(self.disk_path), "--pin", "1234",
                "--new-pin", "5678")
        envelope = json.loads(signed.read_text("utf-8"))
        payload = verify_envelope(envelope)  # history keeps verifying
        self.assertEqual(payload["subject"], "agent-A91")


if __name__ == "__main__":
    unittest.main()
