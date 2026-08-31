"""CLI: `2066 run|validate|repair|hash|effects|export|keygen|sign-caps|verify-caps`.

Commands:
  run         execute the program (adapters: --adapter tree|plan, default tree)
  validate    validate only
  repair      apply the mechanical cast-repair loop, print the canonical result
  hash        print the deterministic canonical-form identity (§15)
  effects     print the static effect manifest (what authority execution needs)
  export      lower the program to a standalone conventional source file
              (§10 export backend: export <file> --target python [--out out.py])
  keygen      generate an agent identity: keygen <identity.json> (writes <stem>.key)
  sign-caps   sign a grants file: sign-caps <caps.json> --agent id.json --key id.key
  verify-caps verify a signed grants file: verify-caps <signed.json>

Authority flags (§17, §26): --caps <grants.json> attaches the runtime-held
capability set; signed envelopes are always verified fail-closed, and
--require-signed refuses unsigned grant files. --now <iso-8601> freezes the
capability clock for deterministic tests. Denials exit with code 4.

stdout carries program output only (for `repair`/`sign-caps`/`export`:
the generated artifact); structured errors and diagnostics go to stderr.
Exit codes: 0 ok, 1 parse/validation, 2 runtime error, 3 usage/IO/trust, 4 denied."""

from __future__ import annotations
import hashlib
import json
import pathlib
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from runtime import identity
from runtime import __version__
from runtime.capabilities import GrantSet, parse_timestamp, sign_capabilities, verify_envelope
from runtime.data import DataPlane
from runtime.pinning import TrustStore
from runtime.evidence import EvidenceLog, verify_evidence
from runtime.revocation import (bind_to_hash, grant_id, Revocations)
from runtime.proposals import (create_proposal, merge_proposals,
                             verify_proposal)
from runtime import keydisk
from runtime.session import SessionVerifier
from runtime.errors import StructuredError, exit_code_for
from runtime.hashing import program_hash
from runtime.interpreter import execute
from runtime.plan_vm import execute_plan
from runtime.repair import repair_source
from runtime.types import format_value
from runtime.parser import parse_source
from runtime.validator import analyze, program_effects
from runtime.cli.args import ADAPTERS, _parse_args  # noqa: F401
def _reference(json_mode: bool) -> int:
    from runtime.airef import ai_reference
    from runtime import __version__
    payload = ai_reference(__version__)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=1))
    return 0


from runtime.cli.commands import (  # noqa: F401
    _approve, _chain, _check, _delegate, _evidence, _export, _hash,
    _key_format, _key_inspect, _key_rotate, _keygen, _merge, _migrate,
    _propose, _redteam, _repair, _reputation, _revoke, _runtime_digest,
    _sign_caps, _verify_caps, _verify_proposal)
from runtime.cli.usage import USAGE

USAGE = f"""usage:
  python -m runtime run <program.ai> [--adapter {'|'.join(ADAPTERS)}]
                       [--caps grants.json] [--require-signed]
                       [--now iso-8601] [--json]
  python -m runtime validate <program.ai> [--json]
  python -m runtime repair <program.ai> [--json]
  python -m runtime hash <program.ai> [--json]
  python -m runtime effects <program.ai> [--json]
  python -m runtime check <program.ai> [--json]   # validate+effects+hash, one call
  python -m runtime keygen <identity.json> [--id agent-A91] [--json]
  python -m runtime reference            # machine-readable docs for AI agents
  python -m runtime evidence <log.jsonl> # verify the audit hash chain
  python -m runtime propose <new.ai> --base <base.ai> --agent <id.json> --key <secret.key>
  python -m runtime merge <base.ai> --proposals a.json,b.json [--out merged.ai]
  python -m runtime verify-proposal <p.json> --base <base.ai>
  python -m runtime revoke <signed.json|token> --revocations rev.jsonl [--reason r]
  python -m runtime digest                 # self-hash of this runtime (S9)
  python -m runtime run <p.ai> --caps c.json --trust-store issuers.json --require-signed
  python -m runtime keygen agent.json --trust-store issuers.json   # pin new issuer
  python -m runtime key-format <disk> [--id human-1] [--force]   # any flashdisk becomes a key
  python -m runtime key-inspect <disk>
  python -m runtime approve <caps.json> --key <disk> [--ttl-minutes 5] [--out signed.json]
  python -m runtime approve <caps.json> --multisig 2-of-3 --key d1 --key d2 --key d3
                       [--pin <pin>] [--ttl-minutes 5] [--out signed.json]
  python -m runtime key-rotate <disk> --pin <old-pin> --new-pin <new-pin>
  python -m runtime delegate <parent.json> --agent <id.json> --key <secret.key>
                       --subject <sub_agent_id> [--ttl-minutes 30] [--out delegated.json]
  python -m runtime chain <delegated.json> [--revocations rev.jsonl] [--json]
  python -m runtime sign-caps <caps.json> --agent <identity.json> --key <secret.json>
                              [--out signed.json]
  python -m runtime verify-caps <signed.json> [--json]
  python -m runtime reputation <ledger.jsonl> [--agent <agent_id>] [--json]
  python -m runtime redteam <proposal.json> --base <base.ai>
                       [--reputation <ledger.jsonl>] [--json]
  (or: bin/2066 run <program.ai>)"""

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parsed = _parse_args(argv)
    if parsed is None:
        print(USAGE, file=sys.stderr)
        return 3
    (json_mode, adapter, caps_path, now_raw, agent_path, key_path, out_path,
     require_signed, agent_id, target, library_flag, db_path,
     session_key_path, evidence_path, base_path, proposals_paths,
     force_flag, ttl_minutes, pin_value, revocations_path,
     for_hash, trust_store_path, reputation_path, args,
     key_paths, multisig_spec, new_pin_value, subject_id) = parsed
    ONE_ARG = ("keygen", "reference", "digest", "selftest")
    PATH_ONLY = ("evidence",)  # command + one path, no second argument
    TWO_ARG = ("run", "validate", "repair", "hash", "effects", "migrate",
               "propose", "sign-caps", "verify-caps", "approve", "keygen",
               "key-format", "key-inspect", "merge", "verify-proposal",
               "evidence", "export", "check", "reputation", "redteam",
               "delegate", "chain", "key-rotate", "revoke")
    if len(args) == 1 and args[0] in ONE_ARG:
        command, path = args[0], None
    elif len(args) == 2 and args[0] in TWO_ARG:
        command, path = args
    elif len(args) == 1 and args[0] in PATH_ONLY:
        command, path = args[0], None
    else:
        print(USAGE, file=sys.stderr)
        return 3

    if command == "keygen":
        return _keygen(path, json_mode, agent_id, trust_store_path)
    if command == "sign-caps":
        return _sign_caps(path, agent_path, key_path, out_path)
    if command == "verify-caps":
        return _verify_caps(path, json_mode)
    if command == "reference":
        return _reference(json_mode)
    if command == "export":
        return _export(path, target, out_path, library=library_flag)
    if command == "migrate":
        return _migrate(path, db_path, json_mode)
    if command == "evidence":
        return _evidence(path, json_mode)
    if command == "check":
        return _check(path, json_mode)
    if command == "selftest":
        return _selftest(json_mode)
    if command == "propose":
        return _propose(path, base_path, agent_path, key_path, out_path)
    if command == "verify-proposal":
        return _verify_proposal(path, base_path, json_mode)
    if command == "merge":
        return _merge(path, proposals_paths, out_path, json_mode)
    if command == "key-format":
        return _key_format(path, agent_id, force_flag, pin_value)
    if command == "key-inspect":
        return _key_inspect(path, json_mode)
    if command == "approve":
        return _approve(path, key_path, out_path, ttl_minutes, pin_value,
                        for_hash, multisig_spec, key_paths)
    if command == "delegate":
        return _delegate(path, agent_path, key_path, subject_id,
                         ttl_minutes, out_path)
    if command == "chain":
        return _chain(path, json_mode, revocations_path)
    if command == "key-rotate":
        return _key_rotate(path, pin_value, new_pin_value)
    if command == "revoke":
        return _revoke(path, revocations_path, json_mode)
    if command == "reputation":
        # --agent doubles as the agent id here (elsewhere it is an
        # identity file path; the reputation ledger needs only the id)
        return _reputation(path, agent_path, json_mode)
    if command == "redteam":
        return _redteam(path, base_path, reputation_path, json_mode)
    if command == "digest":
        return _runtime_digest(json_mode)

    try:
        source = pathlib.Path(path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 3

    revocations = Revocations(revocations_path) \
        if revocations_path is not None else None
    grants: GrantSet | None = None
    now = None
    if caps_path is not None:
        trust = (TrustStore.from_file(trust_store_path)
                 if trust_store_path else None)
        try:
            caps_program = parse_source(source)
            caps_hash = program_hash(caps_program)
            grants = GrantSet.from_file(
                caps_path, require_signed=require_signed,
                revocations=revocations, program_hash=caps_hash,
                trust_store=trust)
        except StructuredError as exc:
            print(exc.to_json() if json_mode else exc.render(),
                  file=sys.stderr)
            return exit_code_for(exc.code)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"error: cannot load capability file {caps_path}: {exc}",
                  file=sys.stderr)
            return 3
    if now_raw is not None:
        try:
            now = parse_timestamp(now_raw)
        except ValueError as exc:
            print(f"error: bad --now timestamp: {exc}", file=sys.stderr)
            return 3

    sessions: SessionVerifier | None = None
    if session_key_path is not None:
        try:
            sessions = SessionVerifier.from_identity_file(session_key_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"error: cannot load session key {session_key_path}: {exc}",
                  file=sys.stderr)
            return 3

    db: DataPlane | None = None
    if db_path is not None:
        try:
            program = parse_source(source)
            analysis = analyze(program)
            evidence = (EvidenceLog(evidence_path,
                                     program=program_hash(program),
                                     subject=grants.subject if grants
                                     else "anonymous")
                        if evidence_path else None)
            db = DataPlane(db_path, program.entities, grants, now,
                           evidence=evidence)
        except StructuredError as exc:
            print(exc.render(), file=sys.stderr)
            return 1
        except sqlite3.Error as exc:
            print(f"error: cannot open database {db_path}: {exc}",
                  file=sys.stderr)
            return 3

    if command == "repair":
        return _repair(source, json_mode)
    if command == "hash":
        return _hash(source, json_mode)

    try:
        program = parse_source(source)
        analysis = analyze(program)
        if command == "validate":
            if json_mode:
                print(json.dumps({"ok": True}, sort_keys=True))
            else:
                print("OK")
            return 0
        if command == "effects":
            effects = program_effects(program, analysis)
            if json_mode:
                print(json.dumps({"ok": True, "effects": effects}, sort_keys=True))
            else:
                for effect in effects:
                    print(effect)
            return 0
        if adapter == "plan":
            emits = execute_plan(program, analysis, grants=grants, now=now,
                                 db=db, sessions=sessions)
        else:
            emits = execute(program, analysis, grants=grants, now=now,
                            db=db, sessions=sessions)
        if json_mode:
            print(json.dumps(
                {"ok": True, "emits": [format_value(v) for v in emits]},
                ensure_ascii=False, sort_keys=True,
            ))
        else:
            for value in emits:
                print(format_value(value))
        return 0
    except StructuredError as exc:
        print(exc.to_json() if json_mode else exc.render(), file=sys.stderr)
        return exit_code_for(exc.code)
