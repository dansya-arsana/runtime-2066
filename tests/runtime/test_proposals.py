"""Semantic mutation protocol (§29–§30, C.4, demo §83).

Beats: independent proposals auto-merge into a valid program; same-unit
conflicts are rejected with attribution; stale-base and forged proposals
are refused fail-closed; identical duplicate changes dedupe."""

import json
import tempfile
import unittest
from pathlib import Path

from runtime import analyze, execute, generate_identity, parse_source
from runtime.proposals import (create_proposal, diff_programs,
                               merge_proposals, verify_proposal)
from tests.helpers import run_cli

BASE = """func square
node 101
op param
index 0
type i64

node 102
op multiply
input 101 101
output i64

node 103
op return
input 102

main

node 001
op const
type i64
value 6

node 002
op call
callee square
input 001
output i64

node 003
op emit
input 002
"""


def variant(extra_func: str) -> str:
    return BASE.replace("main\n", extra_func + "\nmain\n")


NEGATE = """func negate
node 201
op param
index 0
type i64

node 202
op const
type i64
value 0

node 203
op subtract
input 202 201
output i64

node 204
op return
input 203
"""
NEGATE_ALT = NEGATE.replace("value 0", "value 100")
DOUBLE = """func double
node 301
op param
index 0
type i64

node 302
op add
input 301 301
output i64

node 303
op return
input 302
"""


def signed(base_program, proposed_source, agent_id):
    agent, secret = generate_identity(agent_id)
    proposal = create_proposal(
        base_program, parse_source(proposed_source), agent, secret,
        "2026-08-31T00:00:00+00:00")
    return proposal, agent, secret


class TestDiff(unittest.TestCase):
    def test_diff_detects_adds_changes_removals(self):
        base = parse_source(BASE)
        changed = BASE.replace("value 6", "value 7")
        diff = diff_programs(base, parse_source(changed))
        self.assertEqual(list(diff["changed"]), ["main/001"])
        diff = diff_programs(base, parse_source(variant(NEGATE)))
        self.assertIn("func/negate", diff["added"])
        self.assertEqual(diff["removed"], [])
        # removing the emit
        no_emit = BASE[:BASE.index("node 003")]
        diff = diff_programs(base, parse_source(no_emit))
        self.assertEqual(diff["removed"], ["main/003"])


class TestMerge(unittest.TestCase):
    def setUp(self):
        self.base = parse_source(BASE)

    def test_independent_proposals_merge_and_run(self):
        a, _, _ = signed(self.base, variant(NEGATE), "agent-A")
        b, _, _ = signed(self.base, variant(DOUBLE), "agent-B")
        result = merge_proposals(self.base, [a, b])
        self.assertEqual(result["conflicts"], [])
        merged = parse_source(result["merged_text"])
        analyze(merged)
        self.assertEqual(set(merged.functions), {"square", "negate", "double"})
        self.assertEqual(execute(merged), [36])  # unchanged main

    def test_identical_duplicate_changes_dedupe(self):
        a1, _, _ = signed(self.base, variant(NEGATE), "agent-A")
        a2, _, _ = signed(self.base, variant(NEGATE), "agent-B")
        result = merge_proposals(self.base, [a1, a2])
        self.assertEqual(result["conflicts"], [])
        merged = parse_source(result["merged_text"])
        self.assertEqual(set(merged.functions), {"square", "negate"})

    def test_same_unit_different_content_conflicts(self):
        a, _, _ = signed(self.base, variant(NEGATE), "agent-A")
        c, _, _ = signed(self.base, variant(NEGATE_ALT), "agent-C")
        result = merge_proposals(self.base, [a, c])
        self.assertIsNone(result["merged_text"])
        units = {conflict["unit"] for conflict in result["conflicts"]}
        self.assertIn("func/negate/202", units)
        agents = {result["conflicts"][0]["agent_a"],
                  result["conflicts"][0]["agent_b"]}
        self.assertEqual(agents, {"agent-A", "agent-C"})

    def test_merged_program_must_still_validate(self):
        # both agents delete the emit -> merged main has no output channel
        a_src = BASE[:BASE.index("node 003")]
        a, _, _ = signed(self.base, a_src, "agent-A")
        b, _, _ = signed(self.base, BASE.replace("value 6", "value 7"),
                         "agent-B")
        result = merge_proposals(self.base, [a, b])
        # the merge is REJECTED because the result would not validate —
        # reported as a conflict, never a half-merged program
        self.assertIsNone(result["merged_text"])
        self.assertEqual(result["conflicts"][0]["unit"], "<whole program>")
        self.assertIn("does not validate", result["conflicts"][0]["detail"])


class TestProposalVerification(unittest.TestCase):
    def setUp(self):
        self.base = parse_source(BASE)
        self.proposal, self.agent, self.secret = signed(
            self.base, variant(NEGATE), "agent-A")

    def test_valid_proposal_verifies(self):
        verify_proposal(self.proposal, self.base)

    def test_forged_content_fails_signature(self):
        tampered = json.loads(json.dumps(self.proposal))
        tampered["changes"]["added"]["main/999"] = (
            "node 999\nop const\ntype i64\nvalue 1")
        with self.assertRaises(Exception) as ctx:
            verify_proposal(tampered, self.base)
        self.assertEqual(ctx.exception.code, "E602")

    def test_stale_base_fails(self):
        moved = parse_source(BASE.replace("value 6", "value 7"))
        with self.assertRaises(Exception) as ctx:
            verify_proposal(self.proposal, moved)
        self.assertEqual(ctx.exception.code, "E601")
        self.assertIn("the graph moved", ctx.exception.detail)

    def test_wrong_author_key_fails(self):
        other, other_secret = generate_identity("impostor")
        impostor = create_proposal(
            self.base, parse_source(variant(NEGATE)), other, other_secret,
            "2026-08-31T00:00:00+00:00")
        impostor["agent_id"] = self.agent.agent_id  # claim to be agent-A
        with self.assertRaises(Exception) as ctx:
            verify_proposal(impostor, self.base)
        self.assertEqual(ctx.exception.code, "E602")

    def test_malformed_proposal(self):
        with self.assertRaises(Exception) as ctx:
            verify_proposal({"agent_id": "x"}, self.base)
        self.assertEqual(ctx.exception.code, "E604")


class TestProposalCLI(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "base.ai").write_text(BASE, encoding="utf-8")
        (self.dir / "a.ai").write_text(variant(NEGATE), encoding="utf-8")
        (self.dir / "b.ai").write_text(variant(DOUBLE), encoding="utf-8")
        (self.dir / "c.ai").write_text(variant(NEGATE_ALT), encoding="utf-8")
        run_cli("keygen", str(self.dir / "a.json"), "--id", "agent-A")
        run_cli("keygen", str(self.dir / "b.json"), "--id", "agent-B")
        run_cli("keygen", str(self.dir / "c.json"), "--id", "agent-C")

    def _propose(self, src, ident, out):
        return run_cli("propose", str(self.dir / src), "--base",
                       str(self.dir / "base.ai"), "--agent",
                       str(self.dir / f"{ident}.json"), "--key",
                       str(self.dir / f"{ident}.key"), "--out",
                       str(self.dir / out))

    def test_full_merge_flow(self):
        self.assertEqual(self._propose("a.ai", "a", "a.json")[0], 0)
        self.assertEqual(self._propose("b.ai", "b", "b.json")[0], 0)
        rc, out, err = run_cli(
            "merge", str(self.dir / "base.ai"), "--proposals",
            f"{self.dir / 'a.json'},{self.dir / 'b.json'}", "--out",
            str(self.dir / "merged.ai"))
        self.assertEqual(rc, 0)
        self.assertIn("applied: [add] func/negate", out)
        self.assertIn("by agent-A", out)
        self.assertIn("by agent-B", out)
        merged = (self.dir / "merged.ai").read_text(encoding="utf-8")
        program = parse_source(merged)
        analyze(program)
        self.assertEqual(set(program.functions),
                         {"square", "negate", "double"})

    def test_conflict_rejected_with_attribution(self):
        self._propose("a.ai", "a", "a.json")
        self._propose("c.ai", "c", "c.json")
        rc, out, _ = run_cli(
            "merge", str(self.dir / "base.ai"), "--proposals",
            f"{self.dir / 'a.json'},{self.dir / 'c.json'}")
        self.assertEqual(rc, 1)
        self.assertIn("MERGE REJECTED", out)
        self.assertIn("func/negate/202", out)
        self.assertIn("agent-A", out)
        self.assertIn("agent-C", out)

    def test_verify_and_stale_base_via_cli(self):
        self._propose("a.ai", "a", "a.json")
        rc, out, _ = run_cli("verify-proposal", str(self.dir / "a.json"),
                             "--base", str(self.dir / "base.ai"))
        self.assertEqual((rc, out.splitlines()[0]), (0, "OK"))
        # move the base: same proposal must now fail E601
        (self.dir / "base.ai").write_text(
            BASE.replace("value 6", "value 9"), encoding="utf-8")
        rc, _, err = run_cli("verify-proposal", str(self.dir / "a.json"),
                             "--base", str(self.dir / "base.ai"))
        self.assertEqual(rc, 1)
        self.assertIn("E601", err)

    def test_missing_flags_is_usage_error(self):
        self.assertEqual(run_cli("propose", str(self.dir / "a.ai"))[0], 3)
        self.assertEqual(run_cli("merge", str(self.dir / "base.ai"))[0], 3)
        self.assertEqual(run_cli("verify-proposal",
                                 str(self.dir / "a.json"))[0], 3)


if __name__ == "__main__":
    unittest.main()
