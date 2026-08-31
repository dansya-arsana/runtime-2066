"""Sales app end-to-end: the sales-machine vertical slice on 2066.

Engine-level (no HTTP): register -> login -> discover/score businesses ->
opportunities -> stage state machine -> follow-ups -> funnel. Pins the
`when`-guarded behavior at the application level: every denied mutation
must leave the pipeline untouched.
"""

import io
import os
import sys
import tempfile
import unittest

from runtime import analyze, execute, identity, parse_source
from runtime.capabilities import GrantSet
from runtime.data import DataPlane
from runtime.session import SessionVerifier, mint_session_token

APP = "examples/sales_app"
GRANTS = GrantSet.from_file(f"{APP}/caps.json")


class SalesAppTest(unittest.TestCase):
    def setUp(self):
        self.db_path = os.path.join(tempfile.mkdtemp(), "sales.db")
        ident, self.secret = identity.generate_identity("sales-test")
        self.sessions = SessionVerifier(public_key=ident.public_key)
        self._run("register", ["owner", "pw-123456"])
        self.token = mint_session_token(self.secret, 1, ttl_minutes=30)

    def _run(self, engine, args):
        program = parse_source(
            open(f"{APP}/{engine}.ai", encoding="utf-8").read())
        analysis = analyze(program)
        db = DataPlane(self.db_path, program.entities, GRANTS, None)
        old_in, old_out = sys.stdin, sys.stdout
        sys.stdin = io.StringIO("".join(a + "\n" for a in args))
        sys.stdout = io.StringIO()
        try:
            with_self = execute(program, analysis, grants=GRANTS, db=db,
                                sessions=self.sessions)
            out = sys.stdout.getvalue().strip()
        except Exception as exc:
            out = f"error {getattr(exc, 'code', 'E???')}: " \
                  f"{getattr(exc, 'detail', exc)}"
        finally:
            sys.stdin, sys.stdout = old_in, old_out
            db.close()
        return out

    def ids_of(self, engine):
        program = parse_source(
            open(f"{APP}/{engine}.ai", encoding="utf-8").read())
        db = DataPlane(self.db_path, program.entities, GRANTS, None)
        old_in = sys.stdin
        sys.stdin = io.StringIO(self.token + "\n")
        try:
            return execute(program, analyze(program), grants=GRANTS, db=db,
                           sessions=self.sessions)
        finally:
            sys.stdin = old_in
            db.close()

    def test_full_pipeline(self):
        # deterministic in-graph scoring: tier*30 + website*20 + phone*10
        self._run("biz_add", [self.token, "Kopi A", "cafe", "Bandung",
                             "0812", "kopia.id", "2"])
        self._run("biz_add", [self.token, "Bengkel B", "workshop", "Jakarta",
                             "", "", "1"])
        ids, scores = self.ids_of("biz_ids")
        self.assertEqual(scores, [90, 30])

        # opportunities, guarded: only own business, value >= 0
        self._run("opp_add", [self.token, "1", "POS", "paper", "5000",
                             "demo"])
        self._run("opp_add", [self.token, "1", "Bad", "x", "-1", "y"])
        self._run("opp_add", [self.token, "99", "X", "x", "1", "y"])
        _, values = self.ids_of("opp_ids")
        self.assertEqual(values, [5000], "denied adds must not insert")

        # the stage machine, in-graph
        self.assertEqual(self._run("opp_stage", [self.token, "1", "new",
                                                "qualified"]), "ok:1")
        self.assertTrue(self._run("opp_stage", [self.token, "1", "new",
                                               "proposal"])
                        .startswith("error E409"))
        self.assertEqual(self._run("opp_stage", [self.token, "1", "qualified",
                                                "won"]), "ok:1")
        self.assertTrue(self._run("opp_stage", [self.token, "1", "won",
                                               "qualified"])
                        .startswith("error E400"))

        # follow-ups close once, funnel counts the truth
        self._run("fu_add", [self.token, "1", "send proposal", "2026-09-05"])
        self.assertEqual(self._run("fu_done", [self.token, "1"]), "ok:1")
        funnel = dict(zip(("businesses", "new", "qualified", "proposal",
                           "won", "lost", "activities", "followups_open"),
                          self._run("funnel", [self.token]).split("\n")))
        self.assertEqual(funnel["businesses"], "2")
        self.assertEqual(funnel["won"], "1")
        self.assertEqual(funnel["followups_open"], "0")


if __name__ == "__main__":
    unittest.main()
