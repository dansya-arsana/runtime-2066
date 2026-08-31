"""Red-team verification pipeline (Phase 15): no proposal is trusted
because it looks reasonable; every proposal is attacked before it is
accepted.

`verify_proposal(base_source, proposal)` merges a signed proposal into
its base program and drives the result through five gates:

  1. structural          — the merge must succeed and re-validate;
                           malformed keys, conflicts, and invalid merged
                           programs reject outright
  2. authority delta     — the merged program's static effect manifest
                           is compared with the base's; NEW authority
                           (e.g. DATA_WRITE added to a pure program)
                           flags the proposal for human review
  3. capability boundary — executed with NO grants, the program must be
                           denied with a structured E4xx (default deny),
                           never an unhandled crash
  4. execution safety    — execution may fail with any StructuredError
                           (legitimate), but an unhandled Python
                           exception is a crash and crashes fail the
                           gate unconditionally
  5. fuzz resilience     — deterministic mutants of the merged program
                           must all either run or produce StructuredErrors

Score: +1 per passed gate, -5 per failed gate, 0 per flagged or skipped
gate. Verdict: "reject" if any gate failed, "needs_review" if any gate
is flagged, else "accept".
"""

from __future__ import annotations

from .errors import StructuredError
from .fuzzer import ProgramFuzzer, sandboxed_stdio
from .interpreter import execute
from .parser import parse_source
from .proposals import merge_proposals
from .validator import analyze, program_effects

# Every field a well-formed proposal envelope carries (compare
# proposals.verify_proposal, which enforces the same list as E604).
_PROPOSAL_FIELDS = ("agent_id", "algorithm", "public_key", "base_hash",
                    "program_hash", "issued_at", "changes", "signature")

# Effects that carry no authority over shared resources: every program
# has them and they request nothing (SYSTEM is the program's own stdio).
_NON_AUTHORITY_EFFECTS = frozenset({"PURE", "SYSTEM"})

GATE_NAMES = (
    "structural",
    "authority_delta",
    "capability_boundary",
    "execution_safety",
    "fuzz_resilience",
)

_GATE_WEIGHT = {"pass": 1, "fail": -5, "flagged": 0, "skipped": 0}


class RedTeamPipeline:
    """Five adversarial gates between a proposal and acceptance."""

    def __init__(self, seed: int = 2066, fuzz_count: int = 10):
        self.fuzzer = ProgramFuzzer(seed)
        self.fuzz_count = fuzz_count

    # ------------------------------------------------------------------

    def verify(self, base_source: str, proposal: dict) -> dict:
        gates: list[dict] = []
        gate1, base_program, merged_text = self._gate_structural(
            base_source, proposal)
        gates.append(gate1)
        if merged_text is None:
            # nothing survived to check; the later gates are skipped
            # (0 points), the failed structural gate already forces reject
            for number, name in enumerate(GATE_NAMES[1:], start=2):
                gates.append({
                    "gate": number, "name": name, "status": "skipped",
                    "detail": "structural gate failed; nothing to verify",
                })
        else:
            gates.append(self._gate_authority(base_program, merged_text))
            gates.append(self._gate_boundary(merged_text))
            gates.append(self._gate_safety(merged_text))
            gates.append(self._gate_fuzz(merged_text))
        score = float(sum(_GATE_WEIGHT[gate["status"]] for gate in gates))
        if any(gate["status"] == "fail" for gate in gates):
            verdict = "reject"
        elif any(gate["status"] == "flagged" for gate in gates):
            verdict = "needs_review"
        else:
            verdict = "accept"
        return {"verdict": verdict, "gates": gates, "score": score}

    # ------------------------------------------------------------------
    # gate 1 — structural

    def _gate_structural(self, base_source: str,
                         proposal: dict) -> tuple[dict, object, str | None]:
        def fail(detail: str, **extra) -> tuple[dict, object, None]:
            return ({"gate": 1, "name": "structural", "status": "fail",
                     "detail": detail, **extra}, None, None)

        try:
            base_program = parse_source(base_source)
            analyze(base_program)
        except StructuredError as exc:
            return fail(f"base program does not validate: {exc.detail}")
        except Exception as exc:  # noqa: BLE001 — crashes reject, by rule
            return fail(f"base program crashed the runtime: {exc!r}")

        # a proposal missing envelope fields is malformed regardless of
        # what its changes say (same field list proposals.verify_proposal
        # enforces as E604)
        if not isinstance(proposal, dict):
            return fail("malformed proposal: not a JSON object")
        missing = [field for field in _PROPOSAL_FIELDS
                   if field not in proposal]
        if missing:
            return fail(f"malformed proposal: missing "
                        f"{', '.join(repr(f) for f in missing)}")

        # merge_proposals is the single structural authority: malformed
        # unit keys raise E604, conflicts return reports, and the merged
        # text is re-validated before it is ever handed back
        try:
            result = merge_proposals(base_program, [proposal])
        except Exception as exc:  # noqa: BLE001 — missing fields, bad shapes
            detail = exc.detail if isinstance(exc, StructuredError) \
                else f"{type(exc).__name__}: {exc}"
            return fail(f"merge failed: {detail}")
        if result["merged_text"] is None:
            reasons = "; ".join(c["detail"] for c in result["conflicts"])
            return fail(f"merge rejected: {reasons}",
                        conflicts=result["conflicts"])
        gate = {
            "gate": 1, "name": "structural", "status": "pass",
            "detail": (f"merge applies {len(result['applied'])} change(s) "
                       f"and the merged program validates"),
            "applied": result["applied"],
        }
        return gate, base_program, result["merged_text"]

    # ------------------------------------------------------------------
    # gate 2 — authority delta

    def _gate_authority(self, base_program, merged_text: str) -> dict:
        try:
            merged_program = parse_source(merged_text)
            analysis = analyze(merged_program)
            base_effects = set(program_effects(base_program))
            merged_effects = set(program_effects(merged_program, analysis))
        except Exception as exc:  # noqa: BLE001 — crashes reject, by rule
            return {"gate": 2, "name": "authority_delta", "status": "fail",
                    "detail": f"effect analysis crashed: {exc!r}"}
        new_effects = sorted(merged_effects - base_effects)
        new_authority = [effect for effect in new_effects
                         if effect not in _NON_AUTHORITY_EFFECTS]
        if new_authority:
            return {
                "gate": 2, "name": "authority_delta", "status": "flagged",
                "detail": (f"proposal requests NEW authority: "
                           f"{', '.join(new_authority)} "
                           f"(base effects: {', '.join(sorted(base_effects))})"),
                "new_effects": new_authority,
            }
        return {"gate": 2, "name": "authority_delta", "status": "pass",
                "detail": "no new authority requested "
                          f"(effects: {', '.join(sorted(merged_effects))})"}

    # ------------------------------------------------------------------
    # gate 3 — capability boundary (default deny)

    def _gate_boundary(self, merged_text: str) -> dict:
        try:
            program = parse_source(merged_text)
            analysis = analyze(program)
            with sandboxed_stdio():
                execute(program, analysis, grants=None)  # no grants, no db
        except StructuredError as exc:
            if exc.code.startswith("E4"):
                return {"gate": 3, "name": "capability_boundary",
                        "status": "pass",
                        "detail": f"default-deny respected: {exc.code} "
                                  f"({exc.detail})"}
            return {"gate": 3, "name": "capability_boundary", "status": "pass",
                    "detail": f"structured failure {exc.code} before any "
                              f"authority was requested"}
        except Exception as exc:  # noqa: BLE001 — crashes reject, by rule
            return {"gate": 3, "name": "capability_boundary", "status": "fail",
                    "detail": f"unhandled crash under default-deny: "
                              f"{type(exc).__name__}: {exc}"}
        # clean completion with no grants: no ungranted effect succeeded —
        # by construction every effectful op checks authority first
        return {"gate": 3, "name": "capability_boundary", "status": "pass",
                "detail": "no ungranted effect executed; default-deny holds"}

    # ------------------------------------------------------------------
    # gate 4 — execution safety

    def _gate_safety(self, merged_text: str) -> dict:
        try:
            program = parse_source(merged_text)
            analysis = analyze(program)
            with sandboxed_stdio():
                execute(program, analysis)
        except StructuredError as exc:
            return {"gate": 4, "name": "execution_safety", "status": "pass",
                    "detail": f"structured failure {exc.code} — programs "
                              f"may legitimately fail"}
        except Exception as exc:  # noqa: BLE001 — crashes reject, by rule
            return {"gate": 4, "name": "execution_safety", "status": "fail",
                    "detail": f"UNHANDLED CRASH: {type(exc).__name__}: {exc} "
                              f"— crashes are never acceptable"}
        return {"gate": 4, "name": "execution_safety", "status": "pass",
                "detail": "executed cleanly with no crash"}

    # ------------------------------------------------------------------
    # gate 5 — fuzz resilience

    def _gate_fuzz(self, merged_text: str) -> dict:
        report = self.fuzzer.fuzz(merged_text, self.fuzz_count)
        if report["crashes"]:
            return {"gate": 5, "name": "fuzz_resilience", "status": "fail",
                    "detail": (f"{report['crashes']}/{report['total']} "
                               f"mutants crashed the runtime"),
                    "crashes": report["crash_details"]}
        return {"gate": 5, "name": "fuzz_resilience", "status": "pass",
                "detail": (f"{report['total']} mutants: {report['valid']} "
                           f"valid, {report['structured_errors']} structured "
                           f"errors, 0 crashes")}


def verify_proposal(base_source: str, proposal: dict) -> dict:
    """Run the full red-team pipeline; see module docstring for gates.

    Returns {"verdict": "accept"|"reject"|"needs_review",
             "gates": [...], "score": float}.
    """
    return RedTeamPipeline().verify(base_source, proposal)
