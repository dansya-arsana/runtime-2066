"""Differential storage test (plan SS14 adapter independence, SS34):

the same programs, the same grants, run against SQLite AND the
in-memory store must produce identical outputs and identical denial
behavior. Replacing the storage adapter is thereby a tested property.
"""

import io
import os
import sys
import tempfile
import unittest

from runtime import analyze, execute, identity, parse_source
from runtime.capabilities import GrantSet
from runtime.data import DataPlane
from runtime.memory_store import MemoryPlane
from runtime.session import SessionVerifier, mint_session_token
from tests.helpers import ROOT

GRANTS = GrantSet.from_file(
    str(ROOT / "policies" / "deployment" / "sales-caps.json"))
ENGINE_PATH = {
    "register": "auth/register", "login": "auth/login",
    "biz_add": "business/add", "biz_list": "business/list",
    "biz_ids": "business/ids", "opp_add": "opportunity/add",
    "opp_stage": "opportunity/stage", "funnel": "analytics/funnel",
}


def run_flow(store_factory) -> list:
    ident, secret = identity.generate_identity("diff")
    sessions = SessionVerifier(public_key=ident.public_key)

    programs = {}
    for engine, path in ENGINE_PATH.items():
        program = parse_source(
            (ROOT / "programs" / "sales" / f"{path}.ai")
            .read_text(encoding="utf-8"))
        programs[engine] = (program, analyze(program))
    # one persistent store per flow, aware of every engine's entities
    # (mirrors the SQLite file persisting across DataPlane instances)
    merged = {}
    for program, _ in programs.values():
        merged.update(program.entities)
    store = store_factory(merged)

    outputs = []

    def run(engine, args):
        program, analysis = programs[engine]
        stdin, stdout = sys.stdin, sys.stdout
        sys.stdin = io.StringIO("".join(a + "\n" for a in args))
        sys.stdout = io.StringIO()
        try:
            execute(program, analysis, grants=GRANTS, db=store,
                    sessions=sessions)
            outputs.append(sys.stdout.getvalue().strip())
        except Exception as exc:
            outputs.append(f"ERR {getattr(exc, 'code', type(exc).__name__)}")
        finally:
            sys.stdin, sys.stdout = stdin, stdout

    run("register", ["diff_user", "pw-123456"])
    run("login", ["diff_user", "WRONG"])               # denied path
    token = mint_session_token(secret, 1, ttl_minutes=30)
    run("biz_add", [token, "Kopi A", "cafe", "Bandung", "0812", "a.id", "2"])
    run("biz_add", [token, "Kopi A", "cafe", "Bandung", "", "", "1"])  # dup
    run("biz_add", [token, "Bengkel B", "shop", "Jakarta", "", "", "1"])
    run("biz_list", [token])
    run("biz_ids", [token])
    run("opp_add", [token, "1", "POS", "paper", "5000", "demo"])
    run("opp_add", [token, "99", "X", "x", "1", "y"])  # not your business
    run("opp_stage", [token, "1", "new", "qualified"])
    run("opp_stage", [token, "1", "new", "proposal"])  # stage mismatch
    run("funnel", [token])
    store.close()
    return outputs


class TestStoreEquivalence(unittest.TestCase):
    def test_sqlite_and_memory_stores_are_interchangeable(self):
        tmpdir = tempfile.mkdtemp()
        sqlite_path = os.path.join(tmpdir, "sales.db")
        sqlite_results = run_flow(
            lambda entities: DataPlane(sqlite_path, entities, GRANTS, None))
        memory_results = run_flow(
            lambda entities: MemoryPlane(entities, GRANTS, None))
        self.assertEqual(
            sqlite_results, memory_results,
            "storage adapters diverged — adapter independence violated")
        joined = "\n".join(sqlite_results)
        self.assertIn("ok:1", joined)
        self.assertIn("E409", joined)


if __name__ == "__main__":
    unittest.main()
