"""Command implementations (moved verbatim from the original cli.py)."""

from __future__ import annotations
import hashlib
import json
import pathlib
import re
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
from runtime.multisig import sign_multisig, stamp_multisig, verify_multisig
from runtime.delegation import (build_delegation, chain_ok, envelope_issuer,
                                walk_chain)
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
from runtime.reputation import ReputationLedger
from runtime.redteam import RedTeamPipeline
ADAPTERS = ('tree', 'plan')

def _parse_args(argv: list[str]):
    """Returns the parsed flags + positional args, or None on bad usage."""
    json_mode = False
    adapter = "tree"
    caps_path = agent_path = key_path = out_path = now_raw = None
    db_path: str | None = None
    evidence_path: str | None = None
    base_path: str | None = None
    proposals_paths: str | None = None
    force_flag = False
    ttl_minutes: int | None = None
    pin_value: str | None = None
    revocations_path: str | None = None
    for_hash: str | None = None
    trust_store_path: str | None = None
    session_key_path: str | None = None
    agent_id: str | None = None
    target: str | None = None
    library_flag = False
    require_signed = False
    positional: list[str] = []
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--json":
            json_mode = True
        elif arg == "--require-signed":
            require_signed = True
        elif arg == "--library":
            library_flag = True
        elif arg == "--force":
            force_flag = True
        elif arg in ("--adapter", "--caps", "--now", "--agent", "--key",
                     "--out", "--id", "--target", "--db",
                     "--session-key", "--evidence", "--base",
                     "--proposals", "--ttl-minutes", "--pin",
                     "--revocations", "--for-hash", "--trust-store",
                     "--trust", "--force"):
            if not _take_value(argv, i):
                return None
            value = argv[i + 1]
            i += 1
            if arg == "--adapter":
                if value not in ADAPTERS:
                    return None
                adapter = value
            elif arg == "--caps":
                caps_path = value
            elif arg == "--now":
                now_raw = value
            elif arg == "--agent":
                agent_path = value
            elif arg == "--key":
                key_path = value
            elif arg == "--out":
                out_path = value
            elif arg == "--id":
                agent_id = value
            elif arg == "--target":
                if value not in EXPORT_TARGETS:
                    return None
                target = value
            elif arg == "--db":
                db_path = value
            elif arg == "--session-key":
                session_key_path = value
            elif arg == "--evidence":
                evidence_path = value
            elif arg == "--base":
                base_path = value
            elif arg == "--proposals":
                proposals_paths = value
            elif arg == "--ttl-minutes":
                try:
                    ttl_minutes = int(value)
                except ValueError:
                    return None
            elif arg == "--pin":
                pin_value = value
            elif arg == "--revocations":
                revocations_path = value
            elif arg == "--for-hash":
                for_hash = value
            elif arg == "--trust-store":
                trust_store_path = value
            elif arg == "--trust":
                trust_store_path = value
        elif arg.startswith("-"):
            return None
        else:
            positional.append(arg)
        i += 1
    return (json_mode, adapter, caps_path, now_raw, agent_path, key_path,
            out_path, require_signed, agent_id, target, library_flag, db_path,
            session_key_path, evidence_path, base_path, proposals_paths,
            force_flag, ttl_minutes, pin_value, revocations_path,
            for_hash, trust_store_path, positional)

def _take_value(argv: list[str], i: int) -> bool:
    return i + 1 < len(argv)

def _repair(source: str, json_mode: bool) -> int:
    outcome = repair_source(source)
    if json_mode:
        payload: dict = {
            "ok": outcome.repaired,
            "rounds": outcome.rounds,
            "applied": outcome.applied,
        }
        if outcome.program_text is not None:
            payload["program"] = outcome.program_text
        if outcome.repaired:
            payload["emits"] = [format_value(v) for v in outcome.emits]
        error = outcome.runtime_error or outcome.validation_error
        if error is not None:
            payload["error"] = error.to_dict()
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    else:
        for step in outcome.applied:
            print(f"repair: {step}", file=sys.stderr)
        if outcome.program_text is not None:
            sys.stdout.write(outcome.program_text)
        error = outcome.runtime_error or outcome.validation_error
        if error is not None:
            print(error.render(), file=sys.stderr)
    if outcome.runtime_error is not None:
        return 2
    return 0 if outcome.repaired else 1

def _hash(source: str, json_mode: bool) -> int:
    try:
        program = parse_source(source)
    except StructuredError as exc:
        print(exc.to_json() if json_mode else exc.render(), file=sys.stderr)
        return 1
    digest = program_hash(program)
    if json_mode:
        print(json.dumps({"ok": True, "hash": digest}, sort_keys=True))
    else:
        print(digest)
    return 0

def _keygen(identity_path: str, json_mode: bool, agent_id: str | None,
            trust_store_path: str | None = None) -> int:
    """Generate <identity.json> + <stem>.key (secret — never commit)."""
    identity_obj, secret_hex = identity.generate_identity(
        agent_id or pathlib.Path(identity_path).stem)
    identity_payload = {
        "agent_id": identity_obj.agent_id,
        "algorithm": identity_obj.algorithm,
        "public_key": identity_obj.public_key,
        "created": identity_obj.created,
    }
    secret_payload = {
        "agent_id": identity_obj.agent_id,
        "algorithm": identity_obj.algorithm,
        "secret_key": secret_hex,
    }
    key_path = str(pathlib.Path(identity_path).with_suffix(".key"))
    try:
        pathlib.Path(identity_path).write_text(
            json.dumps(identity_payload, indent=2) + "\n", encoding="utf-8")
        pathlib.Path(key_path).write_text(
            json.dumps(secret_payload, indent=2) + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot write identity files: {exc}", file=sys.stderr)
        return 3
    if json_mode:
        print(json.dumps({"ok": True, "identity": identity_payload,
                          "secret_key_file": key_path}, sort_keys=True))
        if trust_store_path:
            store = pathlib.Path(trust_store_path)
            payload = (json.loads(store.read_text(encoding="utf-8"))
                       if store.exists() else {"version": 1, "issuers": []})
            payload.setdefault("issuers", []).append({
                "agent_id": identity_payload["agent_id"],
                "public_key": identity_payload["public_key"]})
            store.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
    else:
        if trust_store_path:
            store = pathlib.Path(trust_store_path)
            payload = (json.loads(store.read_text(encoding="utf-8"))
                       if store.exists() else {"version": 1, "issuers": []})
            payload.setdefault("issuers", []).append({
                "agent_id": identity_payload["agent_id"],
                "public_key": identity_payload["public_key"]})
            store.write_text(json.dumps(payload, indent=2) + "\n",
                             encoding="utf-8")
        print(f"identity:  {identity_path}")
        print(f"agent_id:  {identity_obj.agent_id}")
        print(f"algorithm: {identity_obj.algorithm}")
        print(f"public_key: {identity_obj.public_key}")
        print(f"secret key: {key_path} — keep private, never commit",
              file=sys.stderr)
        if trust_store_path:
            print(f"pinned in trust store: {trust_store_path}",
                  file=sys.stderr)
    return 0

def _sign_caps(caps_path: str, agent_path: str | None, key_path: str | None,
               out_path: str | None) -> int:
    if not agent_path or not key_path:
        print("error: sign-caps requires --agent <identity.json> "
              "and --key <secret.json>", file=sys.stderr)
        return 3
    try:
        issuer = identity.parse_identity(
            json.loads(pathlib.Path(agent_path).read_text(encoding="utf-8")))
        _, secret_hex = identity.load_secret_key(
            json.loads(pathlib.Path(key_path).read_text(encoding="utf-8")))
        payload = json.loads(pathlib.Path(caps_path).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"error: cannot read signing inputs: {exc}", file=sys.stderr)
        return 3
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    if not isinstance(payload, dict) or "signature" in payload:
        print("error: sign-caps signs a plain grants object; "
              "this file is already signed", file=sys.stderr)
        return 3
    from datetime import datetime, timezone
    issued_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    envelope = sign_capabilities(payload, issuer, secret_hex, issued_at)
    text = json.dumps(envelope, indent=2) + "\n"
    try:
        if out_path:
            pathlib.Path(out_path).write_text(text, encoding="utf-8")
            print(f"signed grants written to {out_path}", file=sys.stderr)
        else:
            sys.stdout.write(text)
    except OSError as exc:
        print(f"error: cannot write signed grants: {exc}", file=sys.stderr)
        return 3
    return 0

def _verify_caps(path: str, json_mode: bool) -> int:
    try:
        envelope = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        payload = verify_envelope(envelope)
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 3
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    who = envelope_issuer(envelope)
    if isinstance(who, list):
        who = ", ".join(str(name) for name in who)
    if json_mode:
        print(json.dumps({
            "ok": True,
            "agent_id": who,
            "subject": payload.get("subject", "anonymous"),
            "grants": len(payload.get("grants", [])),
        }, sort_keys=True))
    else:
        print("OK")
        print(f"issued_by: {who}")
        print(f"subject:   {payload.get('subject', 'anonymous')}")
        print(f"grants:    {len(payload.get('grants', []))}")
    return 0

def _export(path: str, target: str | None, out_path: str | None,
            library: bool = False) -> int:
    """§10 export backend: lower the validated program to conventional source."""
    from runtime.export import export_javascript, export_python

    if target is None:
        print("error: export requires --target (supported: "
              f"{', '.join(EXPORT_TARGETS)})", file=sys.stderr)
        return 3
    try:
        source = pathlib.Path(path).read_text(encoding="utf-8")
        program = parse_source(source)
        analysis = analyze(program)
        if target == "javascript":
            generated = export_javascript(program, analysis, library=library)
        else:
            generated = export_python(program, analysis)
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 3
    except StructuredError as exc:
        print(exc.render(), file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    try:
        if out_path:
            pathlib.Path(out_path).write_text(generated, encoding="utf-8")
            print(f"exported {path} -> {out_path} (target: {target})",
                  file=sys.stderr)
        else:
            sys.stdout.write(generated)
    except OSError as exc:
        print(f"error: cannot write export: {exc}", file=sys.stderr)
        return 3
    return 0

def _migrate(path: str, db_path: str | None, json_mode: bool) -> int:
    """§25: diff the program's entities against the database schema.

    Safe steps (create table, add column) are reported; breaking steps
    (drop column, type change) are reported with data-loss detail and
    NEVER applied — destructive migration is a human decision, not an
    agent's (roadmap §25: AI may propose; the runtime verifies).
    """
    if db_path is None:
        print("error: migrate requires --db <file>", file=sys.stderr)
        return 3
    try:
        source = pathlib.Path(path).read_text(encoding="utf-8")
        program = parse_source(source)
        analysis = analyze(program)
        # auto_create=False: drift must be measured against the database's
        # PRE-existing state, not a state the constructor just made
        db = DataPlane(db_path, program.entities, grants=None, now=None,
                       auto_create=False)
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 3
    except StructuredError as exc:
        print(exc.render(), file=sys.stderr)
        return 1
    except sqlite3.Error as exc:
        print(f"error: cannot open database {db_path}: {exc}", file=sys.stderr)
        return 3

    steps = db.schema_drift()
    breaking = [s for s in steps if s["breaking"]]
    safe = [s for s in steps if not s["breaking"]]
    if breaking:
        # never touch the database when any step is destructive
        db.close()
        _print_migration(json_mode, [], breaking)
        print("refusing: destructive changes require human review "
              "(backup/export/edit the database by hand)", file=sys.stderr)
        return 1
    db.apply_safe_steps(safe)
    db.close()
    _print_migration(json_mode, safe, [])
    return 0

def _evidence(path: str, json_mode: bool) -> int:
    """Verify an evidence log's hash chain (tamper-evident audit)."""
    try:
        result = verify_evidence(path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read evidence file {path}: {exc}",
              file=sys.stderr)
        return 3
    if json_mode:
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    else:
        if result.get("ok"):
            print(f"OK — {result.get('records', 0)} record(s) intact"
                  + (f", last {result['last']}" if result.get("last") else ""))
        else:
            print(f"TAMPERED — {result}")
    return 0 if result.get("ok") else 1

def _propose(path: str, base_path: str | None, agent_path: str | None,
             key_path: str | None, out_path: str | None) -> int:
    """§28/C.4: sign a node-level proposal of `path` against --base."""
    if not (base_path and agent_path and key_path):
        print("error: propose requires --base <base.ai> --agent <id.json> "
              "--key <secret.key> [--out proposal.json]", file=sys.stderr)
        return 3
    try:
        base, _ = _load_program(base_path, "base")
        proposed, _ = _load_program(path, "proposed")
        agent = identity.parse_identity(
            json.loads(pathlib.Path(agent_path).read_text(encoding="utf-8")))
        _, secret_hex = identity.load_secret_key(
            json.loads(pathlib.Path(key_path).read_text(encoding="utf-8")))
    except OSError as exc:
        print(f"error: cannot read inputs: {exc}", file=sys.stderr)
        return 3
    except (ValueError, json.JSONDecodeError, StructuredError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    from datetime import datetime, timezone
    proposal = create_proposal(
        base, proposed, agent, secret_hex,
        datetime.now(timezone.utc).isoformat(timespec="seconds"))
    text = json.dumps(proposal, indent=1, sort_keys=True) + "\n"
    try:
        if out_path:
            pathlib.Path(out_path).write_text(text, encoding="utf-8")
            print(f"proposal written to {out_path} (agent {agent.agent_id}, "
                  f"base {proposal['base_hash'][:19]})", file=sys.stderr)
        else:
            sys.stdout.write(text)
    except OSError as exc:
        print(f"error: cannot write proposal: {exc}", file=sys.stderr)
        return 3
    return 0

def _load_program(path: str, what: str):
    source = pathlib.Path(path).read_text(encoding="utf-8")
    program = parse_source(source)
    return program, analyze(program)

def _verify_proposal(path: str, base_path: str | None,
                     json_mode: bool) -> int:
    if base_path is None:
        print("error: verify-proposal requires --base <base.ai>",
              file=sys.stderr)
        return 3
    try:
        proposal = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        base, _ = _load_program(base_path, "base")
        verify_proposal(proposal, base)
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 3
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    except StructuredError as exc:
        print(exc.to_json() if json_mode else exc.render(), file=sys.stderr)
        return 1
    n = (len(proposal["changes"]["added"])
         + len(proposal["changes"]["changed"])
         + len(proposal["changes"]["removed"]))
    if json_mode:
        print(json.dumps({"ok": True, "agent_id": proposal["agent_id"],
                          "changes": n}, sort_keys=True))
    else:
        print("OK")
        print(f"author:   {proposal['agent_id']}")
        print(f"base:     {proposal['base_hash']}")
        print(f"changes:  {n} unit(s)")
    return 0

def _merge(path: str, proposals_paths: str | None, out_path: str | None,
           json_mode: bool) -> int:
    """§29-§30: deterministically merge signed proposals into the base."""
    if not proposals_paths:
        print("error: merge requires --proposals a.json,b.json "
              "[--out merged.ai]", file=sys.stderr)
        return 3
    try:
        base, _ = _load_program(path, "base")
        proposals = []
        for entry in proposals_paths.split(","):
            proposal = json.loads(
                pathlib.Path(entry.strip()).read_text(encoding="utf-8"))
            verify_proposal(proposal, base)  # fail-closed before merging
            proposals.append(proposal)
        result = merge_proposals(base, proposals)
    except OSError as exc:
        print(f"error: cannot read inputs: {exc}", file=sys.stderr)
        return 3
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except StructuredError as exc:
        print(exc.to_json() if json_mode else exc.render(), file=sys.stderr)
        return 1

    if result["conflicts"]:
        if json_mode:
            print(json.dumps({"ok": False, "conflicts": result["conflicts"]},
                             ensure_ascii=False, sort_keys=True, indent=1))
        else:
            print("MERGE REJECTED - conflicting mutations:")
            for conflict in result["conflicts"]:
                print(f"  unit {conflict['unit']}: {conflict['detail']}")
        return 1
    if out_path and result["merged_text"] is not None:
        pathlib.Path(out_path).write_text(result["merged_text"],
                                          encoding="utf-8")
    if json_mode:
        print(json.dumps({"ok": True, "applied": result["applied"]},
                         ensure_ascii=False, sort_keys=True, indent=1))
    else:
        for step in result["applied"]:
            print(f"applied: [{step['kind']}] {step['unit']} "
                  f"by {step['agent_id']}")
        if out_path:
            print(f"merged program written to {out_path}", file=sys.stderr)
        elif result["merged_text"] is not None:
            sys.stdout.write(result["merged_text"])
    return 0

def _key_inspect(path: str, json_mode: bool) -> int:
    try:
        info = keydisk.inspect_key(path)
    except (keydisk.KeyError_, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    if json_mode:
        print(json.dumps(info, sort_keys=True))
    else:
        ident = info["identity"]
        print(f"2066 key: {ident['agent_id']} ({ident['algorithm']})")
        print(f"public_key: {ident['public_key']}")
        print(f"wrong-PIN attempts: {info['wrong_pin_attempts']} "
              f"({info['remaining']} remaining before self-destruct)")
    return 0

def _key_format(path: str, agent_id: str | None, force: bool,
                pin_value: str | None = None) -> int:
    """Initialize any disk/directory as a 2066 human key (KEY v1)."""
    pin = pin_value or keydisk.prompt_pin(confirm=True)
    try:
        result = keydisk.format_key(path, agent_id or "human-key", pin,
                                    force=force)
    except keydisk.KeyError_ as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(f"key formatted: {result['path']} ({result['agent_id']})")
    print("keep this disk physically private — it is a bearer object",
          file=sys.stderr)
    return 0

_MULTISIG_SPEC = re.compile(r"^(\d+)-of-(\d+)$")


def _parse_multisig(spec: str):
    """'2-of-3' -> (2, 3); None when malformed or inconsistent."""
    match = _MULTISIG_SPEC.match(spec.strip())
    if not match:
        return None
    threshold, total = int(match.group(1)), int(match.group(2))
    if threshold < 1 or total < threshold:
        return None
    return threshold, total


def _load_approval_payload(caps_path: str, ttl_minutes: int | None,
                           for_hash: str | None):
    """Read and prepare the plain grants object an approval signs.

    Returns (payload, None) or (None, exit_code) after printing the
    error. Applies the TTL and hash binding the same way for single and
    multisig approvals.
    """
    try:
        payload = json.loads(pathlib.Path(caps_path).read_text("utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return None, 3
    if not isinstance(payload, dict) or "signature" in payload \
            or "signatures" in payload:
        print("error: approve signs a plain grants object; file already "
              "signed", file=sys.stderr)
        return None, 3
    if ttl_minutes is not None:
        expires = (datetime.now(timezone.utc)
                   + timedelta(minutes=ttl_minutes)).isoformat(
                       timespec="seconds")
        for grant in payload.get("grants", []):
            grant["expires"] = grant.get("expires") or expires
    if for_hash:
        payload = bind_to_hash(payload, for_hash)
    return payload, None


def _approve(caps_path: str, key_path: str | None, out_path: str | None,
             ttl_minutes: int | None, pin_value: str | None = None,
             for_hash: str | None = None, multisig_spec: str | None = None,
             key_paths: list[str] | None = None) -> int:
    """§33: human approves a grant file with the key disk — sign it as a
    delegation from the human identity, optionally expiring soon.

    With --multisig m-of-n, several key disks sign the same payload in
    turn (pass-around signing); the envelope carries a `signatures`
    list and only verifies when at least m distinct signatures do.
    """
    if multisig_spec:
        return _approve_multisig(caps_path, multisig_spec,
                                 key_paths or ([key_path] if key_path else []),
                                 out_path, ttl_minutes, pin_value, for_hash)
    if not key_path:
        print("error: approve requires --key <disk with .2066key>",
              file=sys.stderr)
        return 3
    pin = pin_value or keydisk.prompt_pin(confirm=False)
    try:
        ident, secret_hex = keydisk.unlock(key_path, pin)
    except (keydisk.KeyError_, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    payload, rc = _load_approval_payload(caps_path, ttl_minutes, for_hash)
    if payload is None:
        return rc
    envelope = sign_capabilities(payload, ident, secret_hex,
                                 datetime.now(timezone.utc).isoformat(
                                     timespec="seconds"))
    text = json.dumps(envelope, indent=2) + "\n"
    try:
        if out_path:
            pathlib.Path(out_path).write_text(text, encoding="utf-8")
            print(f"approved by {ident.agent_id} -> {out_path}"
                  + (f" (expires in {ttl_minutes} min)"
                     if ttl_minutes else ""), file=sys.stderr)
        else:
            sys.stdout.write(text)
    except OSError as exc:
        print(f"error: cannot write: {exc}", file=sys.stderr)
        return 3
    return 0


def _approve_multisig(caps_path: str, multisig_spec: str,
                      key_paths: list[str], out_path: str | None,
                      ttl_minutes: int | None, pin_value: str | None,
                      for_hash: str | None) -> int:
    """m-of-n approval: unlock each key disk, sign the payload with all
    of them, stamp the threshold into the SIGNED payload."""
    parsed = _parse_multisig(multisig_spec)
    if parsed is None:
        print(f"error: --multisig expects <m>-of-<n> like 2-of-3 "
              f"(received {multisig_spec!r})", file=sys.stderr)
        return 3
    threshold, total = parsed
    if len(key_paths) < threshold:
        print(f"error: multisig {threshold}-of-{total} needs at least "
              f"{threshold} --key disks to reach the threshold; "
              f"{len(key_paths)} given", file=sys.stderr)
        return 3
    pin = pin_value or keydisk.prompt_pin(confirm=False)
    signers: list[tuple] = []
    try:
        for disk in key_paths:
            ident, secret_hex = keydisk.unlock(disk, pin)
            signers.append((ident, secret_hex))
    except (keydisk.KeyError_, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    payload, rc = _load_approval_payload(caps_path, ttl_minutes, for_hash)
    if payload is None:
        return rc
    stamp_multisig(payload, threshold, total)
    envelope = sign_multisig(payload, signers,
                             datetime.now(timezone.utc).isoformat(
                                 timespec="seconds"))
    try:
        verify_multisig(envelope, threshold)  # self-check before writing
    except Exception as exc:
        print(f"error: the signatures collected do not meet {threshold}-"
              f"of-{total} (are the key disks distinct?) — {exc}",
              file=sys.stderr)
        return 3
    text = json.dumps(envelope, indent=2) + "\n"
    try:
        if out_path:
            pathlib.Path(out_path).write_text(text, encoding="utf-8")
            print(f"approved by {len(envelope['signatures'])} signer(s), "
                  f"{threshold}-of-{total} -> {out_path}"
                  + (f" (expires in {ttl_minutes} min)"
                     if ttl_minutes else ""), file=sys.stderr)
        else:
            sys.stdout.write(text)
    except OSError as exc:
        print(f"error: cannot write: {exc}", file=sys.stderr)
        return 3
    return 0

def _delegate(path: str, agent_path: str | None, key_path: str | None,
              subject_id: str | None, ttl_minutes: int | None,
              out_path: str | None) -> int:
    """Stage C: an agent sub-delegates (narrowed) authority it holds.

    The parent file is verified fail-closed first; the child is signed
    with the AGENT's key and records `payload.delegated_by` referencing
    the parent's grant id (see runtime/delegation.py for the rules).
    """
    if not (agent_path and key_path and subject_id):
        print("error: delegate requires --agent <identity.json> "
              "--key <secret.key> --subject <sub_agent_id>",
              file=sys.stderr)
        return 3
    try:
        agent = identity.parse_identity(
            json.loads(pathlib.Path(agent_path).read_text(encoding="utf-8")))
        secret_agent_id, agent_secret = identity.load_secret_key(
            json.loads(pathlib.Path(key_path).read_text(encoding="utf-8")))
        parent = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except OSError as exc:
        print(f"error: cannot read delegate inputs: {exc}", file=sys.stderr)
        return 3
    except (ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    if secret_agent_id != agent.agent_id:
        print(f"error: --key belongs to {secret_agent_id!r} but --agent "
              f"is {agent.agent_id!r}", file=sys.stderr)
        return 3
    try:
        envelope = build_delegation(parent, path, agent, agent_secret,
                                    subject_id, ttl_minutes=ttl_minutes)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    text = json.dumps(envelope, indent=2) + "\n"
    try:
        if out_path:
            pathlib.Path(out_path).write_text(text, encoding="utf-8")
            print(f"delegated by {agent.agent_id} -> {subject_id} "
                  f"({len(envelope['payload']['grants'])} grant(s))"
                  + (f", capped at {ttl_minutes} min"
                     if ttl_minutes else ""), file=sys.stderr)
        else:
            sys.stdout.write(text)
    except OSError as exc:
        print(f"error: cannot write: {exc}", file=sys.stderr)
        return 3
    return 0


def _chain(path: str, json_mode: bool,
           revocations_path: str | None = None) -> int:
    """Stage C: walk a delegation chain up to its human root and report
    every link — signer, subject, grants, and link health."""
    revocations = Revocations(revocations_path) if revocations_path else None
    try:
        levels = walk_chain(path, revocations=revocations)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read delegation chain: {exc}", file=sys.stderr)
        return 3
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    ok = chain_ok(levels)
    if json_mode:
        print(json.dumps({"ok": ok, "levels": levels}, ensure_ascii=False,
                         sort_keys=True, indent=1))
    else:
        print(f"chain: {len(levels)} level(s)")
        for number, level in enumerate(levels, start=1):
            issuer = level["issuer"]
            who = ", ".join(issuer) if isinstance(issuer, list) else issuer
            print(f"level {number}  signer: {who}  "
                  f"subject: {level['subject']}")
            for grant in level["grants"]:
                line = f"  {grant['action']} @ {grant['resource']}"
                if grant.get("expires"):
                    line += f"  (expires {grant['expires']})"
                print(line)
            ref = level.get("delegated_by")
            if ref:
                print(f"  delegated_by: {ref.get('issuer')} "
                      f"(grant {str(ref.get('grant_id'))[:12]}…)")
            problems = []
            if level["expired"]:
                problems.append(f"EXPIRED at {', '.join(level['expired_at'])}")
            if level["revoked"]:
                problems.append("REVOKED")
            if level["issuer_mismatch"]:
                problems.append("BROKEN LINK: signed by an agent that is "
                                "not the subject of the level above")
            if level["parent_mismatch"]:
                problems.append("BROKEN LINK: the parent file does not "
                                "match the delegated_by reference")
            if level["parent_missing"]:
                problems.append("UNRESOLVED: the referenced parent file "
                                "is missing")
            print(f"  status: {'; '.join(problems) if problems else 'ok'}")
        print("OK — chain intact" if ok else "BROKEN — see statuses above")
    return 0 if ok else 1


def _key_rotate(path: str, pin_value: str | None,
                new_pin_value: str | None) -> int:
    """Stage C: rotate a key disk — new keypair, new PIN, history kept."""
    old_pin = pin_value or keydisk.prompt_pin(confirm=False)
    new_pin = new_pin_value or keydisk.prompt_pin(confirm=True)
    try:
        result = keydisk.rotate_key(path, old_pin, new_pin)
    except (keydisk.KeyError_, OSError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    print(f"rotated: {result['old_agent_id']} -> {result['new_agent_id']}")
    print(f"old key recorded in {result['rotation_log']}", file=sys.stderr)
    return 0


def _revoke(target: str, revocations_path: str | None, json_mode: bool,
            reason: str = "") -> int:
    """Revoke a signed delegation file or a session token id."""
    if not revocations_path:
        print("error: revoke requires --revocations <list.jsonl>",
              file=sys.stderr)
        return 3
    revocations = Revocations(revocations_path)
    ids: list[str] = []
    target_path = pathlib.Path(target)
    if target_path.exists():
        try:
            envelope = json.loads(target_path.read_text(encoding="utf-8"))
            ids.append(grant_id(envelope))
            for entry in envelope.get("payload", {}).get("grants", []):
                ids.append(hashlib.sha256(json.dumps(
                    entry, sort_keys=True, separators=(",", ":"),
                    ensure_ascii=False).encode("utf-8")).hexdigest())
        except (ValueError, json.JSONDecodeError) as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 3
    else:
        # treat as a raw session token: decode payload, revoke token_id
        try:
            body_b64, _ = target.split(".")
            import base64
            padding = "=" * (-len(body_b64) % 4)
            payload = json.loads(base64.urlsafe_b64decode(
                body_b64 + padding))
            ids.append(payload.get("token_id", ""))
        except (ValueError, json.JSONDecodeError):
            ids.append(target)  # revoke as a literal id
    ids = [one for one in ids if one]
    for one in ids:
        revocations.revoke(one, reason)
    if json_mode:
        print(json.dumps({"ok": True, "revoked": ids}, sort_keys=True))
    else:
        for one in ids:
            print(f"revoked: {one}")
    return 0

def _runtime_digest(json_mode: bool) -> int:
    """S9: self-hash — digest of the runtime package the caller is using.

    Publish this digest; anyone can recompute it against the runtime they
    actually run (frozen exe or source tree) to detect a swapped or
    backdoored verifier.
    """
    import hashlib
    from runtime import __version__
    package_dir = pathlib.Path(__file__).resolve().parent
    parts = []
    for file in sorted(package_dir.glob("*.py")):
        parts.append(file.name.encode("utf-8")
                     + b""
                     + hashlib.sha256(file.read_bytes()).digest())
    digest = hashlib.sha256(b"".join(parts)).hexdigest()
    payload = {"runtime_version": __version__,
               "digest": f"sha256:{digest}",
               "mode": "frozen" if getattr(sys, "frozen", False)
                       else "source"}
    if json_mode:
        print(json.dumps({"ok": True, **payload}, sort_keys=True))
    else:
        print(f"2066 runtime {payload['runtime_version']} "
              f"({payload['mode']})")
        print(f"digest: {payload['digest']}")
    return 0

def _check(path: str, json_mode: bool) -> int:
    """Agent fast-path: validate + effects + canonical hash in one call."""
    try:
        source = pathlib.Path(path).read_text(encoding="utf-8")
        program = parse_source(source)
        analysis = analyze(program)
        effects = program_effects(program, analysis)
        digest = program_hash(program)
    except StructuredError as exc:
        if json_mode:
            print(json.dumps({"ok": False, "error": exc.to_dict()},
                             ensure_ascii=False, sort_keys=True))
        else:
            print(exc.render(), file=sys.stderr)
        return exit_code_for(exc.code)
    except OSError as exc:
        print(f"error: cannot read {path}: {exc}", file=sys.stderr)
        return 3
    if json_mode:
        print(json.dumps({"ok": True, "effects": effects,
                          "hash": digest}, ensure_ascii=False,
                         sort_keys=True))
    else:
        print(f"hash:    {digest}")
        for effect in effects:
            print(f"effect:  {effect}")
    return 0


def _print_migration(json_mode, safe, breaking):
    if json_mode:
        print(json.dumps({
            "ok": not breaking,
            "applied_safe": [s["detail"] for s in safe],
            "breaking": breaking,
        }, ensure_ascii=False, sort_keys=True, indent=1))
    else:
        for step in safe:
            print(f"applied: [{step['kind']}] {step['entity']}: {step['detail']}")
        for step in breaking:
            print(f"BREAKING: [{step['kind']}] {step['entity']}: {step['detail']}")
        if not safe and not breaking:
            print("schema is in sync — no changes needed")


def _reputation(path: str, agent_id: str | None, json_mode: bool) -> int:
    """Phase 14: show an agent's evidence-based score from the ledger.

    Without --agent, lists every agent in the ledger. The score is
    computed only from chained events; a broken chain is reported and
    exits non-zero (the score is not trustworthy).
    """
    try:
        ledger = ReputationLedger(path)
        chain = ledger.verify_chain()
    except (OSError, json.JSONDecodeError) as exc:
        print(f"error: cannot read reputation ledger {path}: {exc}",
              file=sys.stderr)
        return 3
    if not chain.get("ok"):
        print(f"TAMPERED — {chain}", file=sys.stderr)
    if agent_id is None:
        rows = {name: ledger.reputation(name) for name in ledger.agents()}
        if json_mode:
            print(json.dumps({"ok": True, "chain_ok": chain.get("ok"),
                              "agents": rows}, ensure_ascii=False,
                             sort_keys=True, indent=1))
        else:
            for name in sorted(rows):
                print(f"{name}\t{rows[name]['score']}\t"
                      f"{rows[name]['events']} event(s)")
        return 0 if chain.get("ok") else 1
    rep = ledger.reputation(agent_id)
    if json_mode:
        print(json.dumps({"ok": True, "agent_id": agent_id,
                          "score": rep["score"],
                          "breakdown": rep["breakdown"],
                          "events": rep["events"],
                          "chain_ok": chain.get("ok")},
                         ensure_ascii=False, sort_keys=True, indent=1))
    else:
        print(f"agent:  {agent_id}")
        print(f"score:  {rep['score']}")
        print(f"events: {rep['events']}")
        for event_type, count in sorted(rep["breakdown"].items()):
            print(f"  {event_type}: {count}")
        if chain.get("ok"):
            print(f"chain:  intact ({chain.get('records', 0)} record(s))")
        else:
            print(f"chain:  TAMPERED — {chain}")
    return 0 if chain.get("ok") else 1


_VERDICT_EVENT = {
    "accept": ("proposal_accepted", "red-team verdict: accept"),
    "needs_review": ("proposal_conflict", "red-team verdict: needs_review"),
    "reject": ("proposal_rejected", "red-team verdict: reject"),
}


def _redteam(path: str, base_path: str | None,
             reputation_path: str | None, json_mode: bool) -> int:
    """Phase 15: run a proposal through the five adversarial gates.

    Exit codes: 0 accept, 1 needs_review, 2 reject, 3 usage/IO. With
    --reputation the outcome is recorded into the ledger as evidence.
    """
    if base_path is None:
        print("error: redteam requires --base <base.ai>", file=sys.stderr)
        return 3
    try:
        proposal = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        base_source = pathlib.Path(base_path).read_text(encoding="utf-8")
    except OSError as exc:
        print(f"error: cannot read inputs: {exc}", file=sys.stderr)
        return 3
    except json.JSONDecodeError as exc:
        print(f"error: proposal is not valid JSON: {exc}", file=sys.stderr)
        return 3
    if not isinstance(proposal, dict):
        print("error: proposal must be a JSON object", file=sys.stderr)
        return 3

    result = RedTeamPipeline().verify(base_source, proposal)

    recorded: list[dict] = []
    if reputation_path is not None:
        agent = proposal.get("agent_id") or "unknown"
        ledger = ReputationLedger(reputation_path)
        event_type, note = _VERDICT_EVENT[result["verdict"]]
        ledger.record(agent, event_type,
                      detail=f"{note} (proposal {pathlib.Path(path).name})")
        recorded.append({"agent_id": agent, "event_type": event_type})
        # crash evidence: the specific failure modes deserve their own
        # entries so the score reflects WHAT went wrong, not just that
        # something did
        for gate in result["gates"]:
            if gate["status"] != "fail":
                continue
            if gate["name"] in ("capability_boundary", "execution_safety"):
                ledger.record(agent, "verification_failed",
                              detail=f"gate {gate['gate']} "
                                     f"({gate['name']}): {gate['detail']}")
                recorded.append({"agent_id": agent,
                                 "event_type": "verification_failed"})
            elif gate["name"] == "fuzz_resilience":
                ledger.record(agent, "fuzz_crash",
                              detail=f"gate 5 (fuzz_resilience): "
                                     f"{gate['detail']}")
                recorded.append({"agent_id": agent,
                                 "event_type": "fuzz_crash"})

    if json_mode:
        payload = {"verdict": result["verdict"], "score": result["score"],
                   "gates": result["gates"]}
        if recorded:
            payload["recorded"] = recorded
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True,
                         indent=1))
    else:
        print(f"verdict: {result['verdict']}")
        print(f"score:   {result['score']}")
        for gate in result["gates"]:
            print(f"gate {gate['gate']} {gate['name']:<20} "
                  f"{gate['status']:<8} {gate['detail']}")
        if recorded:
            for entry in recorded:
                print(f"recorded: {entry['event_type']} for "
                      f"{entry['agent_id']}", file=sys.stderr)
    return {"accept": 0, "needs_review": 1, "reject": 2}[result["verdict"]]


def _load_program(path, what):
    source = pathlib.Path(path).read_text(encoding="utf-8")
    program = parse_source(source)
    return program, analyze(program)


def _list_packages(package_filter: str | None, json_mode: bool) -> int:
    """2066 list [package] — semantic packages, modules, units (H3)."""
    from runtime.packages import PackageStore, default_store_root
    store = PackageStore(default_store_root())
    packages = store.packages()
    if not packages:
        print("no semantic packages "
              "(create programs/<name>/package.ai to add one)")
        return 0
    if package_filter is not None and package_filter not in packages:
        print(f"error: unknown package {package_filter!r} "
              f"(have: {', '.join(sorted(packages))})", file=sys.stderr)
        return 3
    selected = {package_filter: packages[package_filter]} if package_filter \
        else packages
    if json_mode:
        print(json.dumps({"packages": {
            name: {"version": p.version, "modules": p.modules}
            for name, p in selected.items()}}, indent=1))
        return 0
    for name, package in selected.items():
        units = sum(len(u) for u in package.modules.values())
        print(f"{name} {package.version}  "
              f"({len(package.modules)} modules, {units} units)")
        for module, unit_names in package.modules.items():
            print(f"  {module:<14} {' '.join(unit_names)}")
    return 0


def _inspect_unit(address: str, json_mode: bool) -> int:
    """2066 inspect <package::module::unit> — the semantic context card
    (hardening plan §16): everything an agent needs without browsing."""
    from runtime.packages import PackageStore, default_store_root
    store = PackageStore(default_store_root())
    try:
        unit = store.unit(address)
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    deps = unit.dependencies()
    effects = unit.effects
    pure_only = effects == ["PURE"]
    if json_mode:
        print(json.dumps({
            "unit": unit.address,
            "hash": unit.hash,
            "node_count": unit.node_count,
            "inputs": {"stdin_lines": unit.input_count},
            "outputs": {"emit": unit.emit_count,
                        "stdout": unit.writes_stdout},
            "effects": effects,
            "capabilities": unit.capabilities(),
            "dependencies": deps,
            "callers": [],
            "path": str(unit.path),
        }, indent=1))
        return 0
    output = ("stdout: 1 system.write" if unit.writes_stdout else "none")
    if unit.emit_count:
        output += f", {unit.emit_count} emit value(s)"
    authority = unit.capabilities() or ["none (pure computation)"]
    print(f"UNIT         {unit.address}")
    print(f"HASH         {unit.hash}")
    print(f"NODES        {unit.node_count}")
    print(f"INPUT        {unit.input_count} stdin line(s) (system.read order)")
    print(f"OUTPUT       {output}")
    print(f"EFFECTS      {' '.join(effects)}"
          + ("  (no authority required)" if pure_only else ""))
    print("CAPABILITIES " + " · ".join(authority))
    entity_note = ", ".join(deps["entities"]) or "none"
    host_note = ", ".join(deps["hosts"]) or "none"
    session_note = "yes" if deps["session"] else "no"
    print(f"DEPENDENCIES entities: {entity_note} · session verifier: "
          f"{session_note} · egress hosts: {host_note}")
    print("CALLERS      none — units are self-contained graphs "
          "(protocol 0.2)")
    print(f"PATH         {unit.path}")
    return 0
