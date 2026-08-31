"""Stage D: reputation ledger, red-team pipeline, program fuzzer.

Beats: reputation is computed only from chained evidence (tampering is
detectable); proposals face five adversarial gates before acceptance —
valid ones pass, authority grabs route to review, crashes reject; the
fuzzer closes the determinism-by-sampling gap (crashes must be 0).
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from runtime import generate_identity, parse_source
from runtime.fuzzer import ProgramFuzzer
from runtime.proposals import create_proposal
from runtime.redteam import RedTeamPipeline, verify_proposal
from runtime.reputation import EVENT_TYPES, SCORES, ReputationLedger
from tests.helpers import run_cli

# ---------------------------------------------------------------- fixtures

BASE = '''node 001
op const
type string
value "notes.txt"

node 002
op filesystem.read
input 001
output string

node 003
op emit
input 002
'''

PURE_BASE = '''node 001
op const
type i64
value 40

node 002
op const
type i64
value 2

node 003
op add
input 001 002
output i64

node 004
op emit
input 003
'''

RICH = '''func bump
node 101
op param
index 0
type i64

node 102
op const
type i64
value 1

node 103
op add
input 101 102
output i64

node 104
op return
input 103

main

node 001
op const
type i64
value 41

node 002
op call
callee bump
input 001
output i64

node 003
op const
type i64
value 100

node 004
op compare
mode lt
input 002 003
output bool

node 005
op const
type string
value "small"

node 006
op const
type string
value "large"

node 007
op branch
input 004 005 006
output string

node 008
op emit
input 007
'''


def make_proposal(base_source: str, proposed_source: str,
                  agent_id: str) -> dict:
    agent, secret = generate_identity(agent_id)
    return create_proposal(parse_source(base_source),
                           parse_source(proposed_source), agent, secret,
                           "2026-08-30T00:00:00+00:00")


# ---------------------------------------------------------------- reputation

class TestReputation(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = str(Path(self.tmp.name) / "ledger.jsonl")

    def tearDown(self):
        self.tmp.cleanup()

    def test_record_and_score(self):
        ledger = ReputationLedger(self.path)
        ledger.record("agent-a", "proposal_accepted", "merge 1")
        ledger.record("agent-a", "proposal_accepted", "merge 2")
        ledger.record("agent-a", "proposal_rejected", "merge 3")
        rep = ledger.reputation("agent-a")
        self.assertEqual(rep["score"], 1.0)  # +1 +1 -1
        self.assertEqual(rep["events"], 3)
        self.assertEqual(rep["breakdown"],
                         {"proposal_accepted": 2, "proposal_rejected": 1})

    def test_score_weights_all_events(self):
        ledger = ReputationLedger(self.path)
        for event in EVENT_TYPES:
            ledger.record("agent-x", event, "probe")
        self.assertEqual(ledger.reputation("agent-x")["score"],
                         float(sum(SCORES.values())))

    def test_crash_costs_more_than_finding_pays(self):
        ledger = ReputationLedger(self.path)
        ledger.record("agent-b", "fuzz_crash", "mutant 17 crashed")
        ledger.record("agent-b", "security_finding", "found E301 leak")
        self.assertEqual(ledger.reputation("agent-b")["score"], -5.0)

    def test_agents_are_isolated_and_sorted(self):
        ledger = ReputationLedger(self.path)
        ledger.record("zeta", "proposal_accepted", "m")
        ledger.record("alpha", "verification_passed", "v")
        ledger.record("alpha", "proposal_conflict", "c")
        self.assertEqual(ledger.agents(), ["alpha", "zeta"])
        self.assertEqual(ledger.reputation("alpha")["score"], 1 - 2)
        self.assertEqual(ledger.reputation("zeta")["score"], 1.0)
        self.assertEqual(ledger.reputation("nobody")["events"], 0)
        self.assertEqual(ledger.reputation("nobody")["score"], 0.0)

    def test_unknown_event_type_refused(self):
        ledger = ReputationLedger(self.path)
        with self.assertRaises(ValueError):
            ledger.record("agent-a", "self_reported_trust", "trust me")
        self.assertEqual(ledger.agents(), [])  # nothing appended

    def test_verify_chain_ok(self):
        ledger = ReputationLedger(self.path)
        for i in range(5):
            ledger.record("agent-a", "proposal_accepted", f"m{i}")
        result = ReputationLedger(self.path).verify_chain()
        self.assertTrue(result["ok"])
        self.assertEqual(result["records"], 5)

    def test_verify_chain_empty_ledger(self):
        result = ReputationLedger(self.path).verify_chain()
        self.assertTrue(result["ok"])
        self.assertEqual(result["records"], 0)

    def test_tampered_record_detected(self):
        ledger = ReputationLedger(self.path)
        ledger.record("agent-a", "proposal_accepted", "m1")
        ledger.record("agent-a", "proposal_accepted", "m2")
        # rewrite history: change the first record's detail without rehashing
        lines = Path(self.path).read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["detail"] = "actually everything was fine"
        lines[0] = json.dumps(record, sort_keys=True, ensure_ascii=False)
        Path(self.path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = ReputationLedger(self.path).verify_chain()
        self.assertFalse(result["ok"])
        self.assertEqual(result["broken_at"], 1)
        self.assertEqual(result["reason"],
                         "record content does not match its hash")

    def test_deleted_record_detected(self):
        ledger = ReputationLedger(self.path)
        for i in range(4):
            ledger.record("agent-a", "verification_passed", f"v{i}")
        lines = [line for line in
                 Path(self.path).read_text(encoding="utf-8").splitlines()
                 if line]
        del lines[2]  # critical evidence cannot silently disappear
        Path(self.path).write_text("\n".join(lines) + "\n", encoding="utf-8")
        result = ReputationLedger(self.path).verify_chain()
        self.assertFalse(result["ok"])
        self.assertEqual(result["broken_at"], 3)
        self.assertEqual(result["reason"], "chain link mismatch")

    def test_ledger_extends_across_instances(self):
        ReputationLedger(self.path).record("agent-a", "proposal_accepted", "1")
        second = ReputationLedger(self.path)  # fresh handle, same file
        second.record("agent-a", "proposal_accepted", "2")
        records = [json.loads(line) for line in
                   Path(self.path).read_text(encoding="utf-8").splitlines()
                   if line]
        self.assertEqual([r["seq"] for r in records], [1, 2])
        self.assertEqual(records[1]["prev_hash"], records[0]["hash"])
        self.assertEqual(ReputationLedger(self.path).agents(), ["agent-a"])


# ---------------------------------------------------------------- red team

class TestRedTeam(unittest.TestCase):
    def test_valid_proposal_accepts(self):
        proposal = make_proposal(BASE, BASE.replace('"notes.txt"',
                                                    '"journal.txt"'),
                                 "agent-good")
        result = verify_proposal(BASE, proposal)
        self.assertEqual(result["verdict"], "accept")
        self.assertEqual(result["score"], 5.0)
        self.assertEqual([g["status"] for g in result["gates"]],
                         ["pass"] * 5)
        boundary = result["gates"][2]
        self.assertIn("default-deny respected: E401", boundary["detail"])

    def test_capability_escalation_needs_review(self):
        escalating = '''node 001
op const
type i64
value 40

node 002
op const
type i64
value 2

node 003
op add
input 001 002
output i64

node 005
op const
type string
value "secret.txt"

node 006
op filesystem.read
input 005
output string

node 004
op emit
input 006
'''
        proposal = make_proposal(PURE_BASE, escalating, "agent-hungry")
        result = verify_proposal(PURE_BASE, proposal)
        self.assertEqual(result["verdict"], "needs_review")
        authority = result["gates"][1]
        self.assertEqual(authority["status"], "flagged")
        self.assertEqual(authority["new_effects"], ["FILESYSTEM_READ"])
        self.assertIn("FILESYSTEM_READ", authority["detail"])
        # flagged gates score 0, everything else passed
        self.assertEqual(result["score"], 4.0)

    def test_crashing_program_rejects(self):
        proposal = make_proposal(BASE, BASE.replace('"notes.txt"',
                                                    '"journal.txt"'),
                                 "agent-crash")
        # a merged program cannot legitimately crash the runtime; a crash
        # means a runtime bug — simulate one and demand the pipeline
        # classify it as reject, never as an unhandled traceback
        with mock.patch("runtime.redteam.execute",
                        side_effect=ValueError("boom: runtime bug")):
            result = RedTeamPipeline().verify(BASE, proposal)
        self.assertEqual(result["verdict"], "reject")
        statuses = {g["name"]: g["status"] for g in result["gates"]}
        self.assertEqual(statuses["capability_boundary"], "fail")
        self.assertEqual(statuses["execution_safety"], "fail")
        self.assertIn("UNHANDLED CRASH",
                      result["gates"][3]["detail"])
        # pass(+1) flagged-none pass(-5) fail(-5) pass(+1) => -7
        self.assertEqual(result["score"], -7.0)

    def test_malformed_proposal_rejects(self):
        for malformed in (
            {"agent_id": "ghost"},  # missing everything else
            {"agent_id": "ghost", "changes": {}},  # no base hash etc.
            {"agent_id": "ghost", "changes": {"added": {"main/@@@": "x"}}},
        ):
            with self.subTest(proposal=malformed):
                result = verify_proposal(BASE, malformed)
                self.assertEqual(result["verdict"], "reject")
                self.assertEqual(result["gates"][0]["status"], "fail")
                self.assertTrue(all(
                    g["status"] in ("fail", "skipped")
                    for g in result["gates"]))
                self.assertLessEqual(result["score"], -5.0)

    def test_invalid_merged_program_rejects(self):
        proposal = make_proposal(BASE, BASE.replace('"notes.txt"',
                                                    '"journal.txt"'),
                                 "agent-bad")
        # well-formed keys, but content that breaks validation once merged
        proposal["changes"]["changed"]["main/001"]["to"] = (
            "op const\ntype string\nvalue not_a_quoted_string")
        result = verify_proposal(BASE, proposal)
        self.assertEqual(result["verdict"], "reject")
        self.assertEqual(result["gates"][0]["status"], "fail")
        self.assertIn("merge rejected", result["gates"][0]["detail"])

    def test_verdicts_are_deterministic(self):
        proposal = make_proposal(BASE, BASE.replace('"notes.txt"',
                                                    '"journal.txt"'), "a7")
        first = verify_proposal(BASE, proposal)
        second = verify_proposal(BASE, proposal)
        self.assertEqual(first, second)


# ---------------------------------------------------------------- fuzzer

class TestFuzzer(unittest.TestCase):
    def test_mutate_shape_and_determinism(self):
        fuzzer = ProgramFuzzer(seed=2066)
        mutants = fuzzer.mutate(RICH, 100)
        self.assertEqual(len(mutants), 100)
        self.assertTrue(all(isinstance(m, str) for m in mutants))
        # fixed seed => identical mutants on a fresh instance
        self.assertEqual(mutants, ProgramFuzzer(seed=2066).mutate(RICH, 100))
        self.assertNotEqual(mutants, ProgramFuzzer(seed=1).mutate(RICH, 100))
        # mutation must actually mutate (some lines differ somewhere)
        self.assertTrue(any(m != RICH for m in mutants))

    def test_fuzz_one_hundred_mutants_zero_crashes(self):
        report = ProgramFuzzer(seed=2066).fuzz(RICH, 100)
        self.assertEqual(report["total"], 100)
        self.assertEqual(report["crashes"], 0,
                         f"fuzz crashes: {report['crash_details'][:2]}")
        self.assertEqual(report["valid"] + report["structured_errors"], 100)
        # the sampler must exercise both sides: programs that still run
        # and programs the validator refuses
        self.assertGreater(report["structured_errors"], 0)
        self.assertGreater(report["valid"], 0)

    def test_fuzz_report_is_deterministic(self):
        first = ProgramFuzzer(seed=2066).fuzz(RICH, 50)
        second = ProgramFuzzer(seed=2066).fuzz(RICH, 50)
        self.assertEqual(first, second)

    def test_fuzz_effectful_program_zero_crashes(self):
        report = ProgramFuzzer(seed=2066).fuzz(BASE, 100)
        self.assertEqual(report["crashes"], 0)
        self.assertEqual(report["total"], 100)


# ---------------------------------------------------------------- CLI

class TestStageDCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self.tmp.name)
        self.ledger_path = self.dir / "ledger.jsonl"
        ledger = ReputationLedger(str(self.ledger_path))
        ledger.record("agent-cli", "proposal_accepted", "merge a")
        ledger.record("agent-cli", "verification_failed", "gate 4 crashed")
        ledger.record("agent-cli", "security_finding", "found bug E301")
        self.base_path = self.dir / "base.ai"
        self.base_path.write_text(BASE, encoding="utf-8")
        self.proposal_path = self.dir / "proposal.json"
        proposal = make_proposal(BASE, BASE.replace('"notes.txt"',
                                                    '"journal.txt"'),
                                 "agent-cli")
        self.proposal_path.write_text(json.dumps(proposal), encoding="utf-8")

    def tearDown(self):
        self.tmp.cleanup()

    def test_reputation_shows_score_and_breakdown(self):
        rc, out, err = run_cli("reputation", str(self.ledger_path),
                               "--agent", "agent-cli")
        self.assertEqual((rc, err), (0, ""))
        self.assertIn("agent-cli", out)
        self.assertIn("4.0", out)  # +1 accepted -2 failed +5 finding
        self.assertIn("security_finding: 1", out)
        self.assertIn("chain:  intact", out)

    def test_reputation_json_mode(self):
        rc, out, _ = run_cli("reputation", str(self.ledger_path),
                             "--agent", "agent-cli", "--json")
        self.assertEqual(rc, 0)
        payload = json.loads(out)
        self.assertEqual(payload["score"], 4.0)
        self.assertEqual(payload["events"], 3)
        self.assertTrue(payload["chain_ok"])

    def test_reputation_tampered_ledger_exits_nonzero(self):
        lines = self.ledger_path.read_text(encoding="utf-8").splitlines()
        record = json.loads(lines[0])
        record["detail"] = "rewritten history"
        lines[0] = json.dumps(record, sort_keys=True)
        self.ledger_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        rc, _, err = run_cli("reputation", str(self.ledger_path),
                             "--agent", "agent-cli")
        self.assertEqual(rc, 1)
        self.assertIn("TAMPERED", err)

    def test_redteam_accept_and_record(self):
        rc, out, err = run_cli("redteam", str(self.proposal_path),
                               "--base", str(self.base_path),
                               "--reputation", str(self.ledger_path))
        self.assertEqual(rc, 0)
        self.assertIn("verdict: accept", out)
        self.assertIn("gate 1 structural", out)
        self.assertIn("gate 5 fuzz_resilience", out)
        # the run was recorded as evidence, and the score reflects it
        rc2, out2, _ = run_cli("reputation", str(self.ledger_path),
                               "--agent", "agent-cli", "--json")
        self.assertEqual(rc2, 0)
        payload = json.loads(out2)
        self.assertEqual(payload["events"], 4)
        self.assertEqual(payload["score"], 5.0)  # 4.0 + 1 (accepted)
        self.assertEqual(payload["breakdown"]["proposal_accepted"], 2)

    def test_redteam_rejects_malformed(self):
        bad = self.dir / "bad.json"
        bad.write_text('{"agent_id": "ghost"}', encoding="utf-8")
        rc, out, _ = run_cli("redteam", str(bad),
                             "--base", str(self.base_path))
        self.assertEqual(rc, 2)
        self.assertIn("verdict: reject", out)

    def test_redteam_requires_base(self):
        rc, _, err = run_cli("redteam", str(self.proposal_path))
        self.assertEqual(rc, 3)
        self.assertIn("--base", err)


if __name__ == "__main__":
    unittest.main()
