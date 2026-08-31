"""Argument parsing (verbatim from the original cli.py)."""

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

ADAPTERS = ('tree', 'plan')
EXPORT_TARGETS = ('python', 'javascript')

def _parse_args(argv: list[str]):
    """Returns the parsed flags + positional args, or None on bad usage."""
    json_mode = False
    adapter = "tree"
    caps_path = out_path = now_raw = None
    agent_path: str | None = None
    key_paths: list[str] = []   # repeated --key (multisig pass-around)
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
    reputation_path: str | None = None
    agent_id: str | None = None
    target: str | None = None
    library_flag = False
    require_signed = False
    multisig_spec: str | None = None     # "--multisig 2-of-3"
    new_pin_value: str | None = None     # key-rotate
    subject_id: str | None = None        # delegate
    profile = "development"             # development | production
    programs_root: str | None = None   # backup sources
    policies_root: str | None = None
    to_dir: str | None = None          # restore destination
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
                     "--trust", "--force", "--reputation", "--multisig",
                     "--new-pin", "--subject", "--profile",
                     "--programs", "--policies", "--to"):
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
                key_paths.append(value)
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
            elif arg == "--reputation":
                reputation_path = value
            elif arg == "--multisig":
                multisig_spec = value
            elif arg == "--new-pin":
                new_pin_value = value
            elif arg == "--subject":
                subject_id = value
            elif arg == "--programs":
                programs_root = value
            elif arg == "--policies":
                policies_root = value
            elif arg == "--to":
                to_dir = value
            elif arg == "--profile":
                if value not in ("development", "production"):
                    return None
                profile = value
        elif arg.startswith("-"):
            return None
        else:
            positional.append(arg)
        i += 1
    key_path = key_paths[-1] if key_paths else None  # last-wins (legacy)
    # production profile (H4): unsigned grants are ALWAYS rejected —
    # security must not depend on remembering --require-signed
    if profile == "production":
        require_signed = True
    return (json_mode, adapter, caps_path, now_raw, agent_path, key_path,
            out_path, require_signed, agent_id, target, library_flag, db_path,
            session_key_path, evidence_path, base_path, proposals_paths,
            force_flag, ttl_minutes, pin_value, revocations_path,
            for_hash, trust_store_path, reputation_path, positional,
            key_paths, multisig_spec, new_pin_value, subject_id, profile,
            programs_root, policies_root, to_dir)
def _take_value(argv: list[str], i: int) -> bool:
    return i + 1 < len(argv)
