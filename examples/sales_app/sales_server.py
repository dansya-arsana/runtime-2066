#!/usr/bin/env python3
"""2066 Sales — the sales-machine vertical slice, rebuilt on the runtime.

Mirrors the real sales-api domain (businesses -> scored opportunities ->
activities/follow-ups -> funnel) but every state change is a .ai program:
deterministic scoring instead of a model, an in-graph stage state machine,
and `when`-guarded writes so a denied mutation is a NO-OP, not a hidden
side effect. The shell holds only what programs structurally cannot: the
session-signing key, the HTTP plumbing, and the SQLite file.

Run from the repository root:
    python examples/sales_app/sales_server.py   -> http://localhost:8628
"""

import base64
import io
import json
import os
import sys
import threading
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent.parent
sys.path.insert(0, str(ROOT))

# the session-signing KEY lives outside the app tree: an intruder who
# copies the app directory must not inherit the mint authority
_KEY_HOME = Path(os.environ.get("2066_KEY_HOME", str(Path.home() / ".2066")))
_KEY_HOME.mkdir(parents=True, exist_ok=True)

from runtime import (analyze, execute, identity, parse_source)  # noqa: E402
from runtime.capabilities import GrantSet  # noqa: E402
from runtime.data import DataPlane  # noqa: E402
from runtime.revocation import Revocations  # noqa: E402
from runtime.session import (SessionRegistry, SessionVerifier,  # noqa: E402
                             mint_session_token)

DB = os.environ.get("2066_SALES_DB", str(APP_DIR / "sales.db"))
CAPS = str(APP_DIR / "caps.json")
SERVER_IDENTITY = _KEY_HOME / "sales_server_identity.json"
SERVER_KEY = _KEY_HOME / "sales_server_identity.key"
REGISTRY_PATH = str(_KEY_HOME / "sales_session_registry.json")
REVOCATIONS_PATH = str(_KEY_HOME / "sales_session_revocations.jsonl")
STATIC = {"index.html": "text/html; charset=utf-8",
          "app.js": "text/javascript; charset=utf-8",
          "styles.css": "text/css; charset=utf-8"}
PORT = int(os.environ.get("PORT", "8628"))
HOST = os.environ.get("HOST", "127.0.0.1")
SESSION_TTL_MINUTES = 30

_db_lock = threading.Lock()


def _ensure_server_identity():
    """Generate the signing identity on first run (the mint authority)."""
    if SERVER_IDENTITY.exists() and SERVER_KEY.exists():
        return
    ident, secret = identity.generate_identity("sales-server")
    SERVER_IDENTITY.write_text(json.dumps({
        "agent_id": ident.agent_id, "algorithm": ident.algorithm,
        "public_key": ident.public_key, "created": ident.created},
        indent=2) + "\n", encoding="utf-8")
    SERVER_KEY.write_text(json.dumps({
        "agent_id": ident.agent_id, "algorithm": ident.algorithm,
        "secret_key": secret}, indent=2) + "\n", encoding="utf-8")
    print(f"generated session-signing identity: {SERVER_IDENTITY.name} "
          f"(keep {SERVER_KEY.name} secret)")


_ensure_server_identity()
SERVER_IDENT = identity.parse_identity(
    json.loads(SERVER_IDENTITY.read_text(encoding="utf-8")))
_, SERVER_SECRET = identity.load_secret_key(
    json.loads(SERVER_KEY.read_text(encoding="utf-8")))
SESSIONS = SessionVerifier(
    public_key=SERVER_IDENT.public_key,
    revocations=Revocations(REVOCATIONS_PATH))
REGISTRY = SessionRegistry(REGISTRY_PATH)
GRANTS = GrantSet.from_file(CAPS)

# compile once: parse + validate every engine at startup
PROGRAMS = {}
for name in ("register", "login", "biz_add", "biz_list", "biz_ids",
             "opp_add", "opp_list", "opp_ids", "opp_stage",
             "act_add", "act_list", "fu_add", "fu_list", "fu_ids", "fu_done",
             "funnel"):
    program = parse_source((APP_DIR / f"{name}.ai").read_text(
        encoding="utf-8"))
    PROGRAMS[name] = (program, analyze(program))


def _mint(subject_id: int) -> str:
    token = mint_session_token(SERVER_SECRET, subject_id,
                               ttl_minutes=SESSION_TTL_MINUTES)
    payload = json.loads(base64.urlsafe_b64decode(
        token.split(".")[0] + "=" * (-len(token.split(".")[0]) % 4)))
    REGISTRY.register(subject_id, payload["token_id"])
    return token


def run_engine(name: str, params: list[str]) -> tuple[str, int]:
    """Execute a cached program; returns (stdout, exit_class)."""
    return _execute(name, params)[0], 0


def _execute(name: str, params: list[str]) -> tuple[str, list]:
    """Run a cached program with params on semantic stdin. Returns
    (stdout, emit_values). Effects are guarded inside the programs."""
    program, analysis = PROGRAMS[name]
    db = DataPlane(DB, program.entities, GRANTS, now=None)
    stdin_buffer = io.StringIO("".join(p + "\n" for p in params))
    stdout_buffer = io.StringIO()
    with _db_lock:
        # swap process-global streams INSIDE the engine lock: parallel
        # requests swapping them outside the lock read each other's
        # parameters under load (the notes-app race, here prevented)
        old_stdin, old_stdout = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = stdin_buffer, stdout_buffer
        try:
            with redirect_stdout(stdout_buffer):
                emits = execute(program, analysis, grants=GRANTS, db=db,
                                sessions=SESSIONS)
            return stdout_buffer.getvalue().strip(), emits
        except Exception as exc:  # StructuredError by contract
            code = getattr(exc, "code", "E???")
            return f"error {code}: {getattr(exc, 'detail', exc)}", []
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout
            db.close()


def _rows(token: str) -> dict:
    """Zip the parallel columns: string columns come as joined CSV lines,
    i64 columns as typed emit lists (biz_ids / opp_ids)."""
    out = {}

    def _emits(name):
        emits = _execute(name, [token])[1]
        return emits if len(emits) == 2 else ([], [])

    text, _ = _execute("biz_list", [token])
    ids, scores = _emits("biz_ids")
    names, cities, categories, stages = _csv_lines(text, 4)
    out["businesses"] = [
        {"id": i, "name": n, "city": c, "category": k,
         "score": s, "stage": st}
        for i, n, c, k, s, st in zip(ids, names, cities, categories,
                                     scores, stages)]
    text, _ = _execute("opp_list", [token])
    ids, values = _emits("opp_ids")
    titles, stages, actions = _csv_lines(text, 3)
    out["opportunities"] = [
        {"id": i, "title": t, "stage": st, "value": v, "next_action": a}
        for i, t, st, v, a in zip(ids, titles, stages, values, actions)]
    text, _ = _execute("act_list", [token])
    types, notes = _csv_lines(text, 2)
    out["activities"] = [
        {"type": t, "notes": n} for t, n in zip(types, notes)]
    text, _ = _execute("fu_list", [token])
    actions, dues, statuses = _csv_lines(text, 3)
    fu_ids = _execute("fu_ids", [token])[1]
    out["followups"] = [
        {"id": i, "action": a, "due": d, "status": s}
        for i, a, d, s in zip(fu_ids[0] if fu_ids else [],
                              actions, dues, statuses)]
    funnel, _ = _execute("funnel", [token])
    out["funnel"] = dict(zip(
        ("businesses", "new", "qualified", "proposal", "won", "lost",
         "activities", "followups_open"),
        (funnel.split("\n") + ["0"] * 8)[:8]))
    return out


def _csv_lines(text: str, n: int) -> list[list[str]]:
    """Split n joined CSV lines into equal-length column lists."""
    lines = (text.split("\n") + [""] * n)[:n]
    return [line.split(",") if line else [] for line in lines]


def _csv(line: str) -> list[str]:
    return line.split(",") if line else []


class Handler(BaseHTTPRequestHandler):
    def _json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self):
        path, _, query = self.path.partition("?")
        q = dict(pair.split("=", 1) for pair in query.split("&") if "=" in pair)
        if path == "/api/health":
            self._json({"ok": True, "engines": sorted(PROGRAMS)})
        elif path == "/api/board":
            self._json(_rows(q.get("token", "")))
        else:
            static_name = "index.html" if path == "/" else path.lstrip("/")
            if static_name in STATIC:
                body = (APP_DIR / static_name).read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", STATIC[static_name])
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)
            else:
                self._json({"error": "not found"}, 404)

    def do_POST(self):
        body = self._body()
        routes = {
            "/api/register": ("register", ["username", "password"], True),
            "/api/login": ("login", ["username", "password"], True),
            "/api/businesses": ("biz_add",
                                ["token", "name", "category", "city",
                                 "phone", "website", "tier"], False),
            "/api/opportunities": ("opp_add",
                                   ["token", "business_id", "title", "need",
                                    "value", "next_action"], False),
            "/api/opportunity-stage": ("opp_stage",
                                       ["token", "id", "from_stage",
                                        "to_stage"], False),
            "/api/activities": ("act_add",
                                ["token", "business_id", "type", "notes"],
                                False),
            "/api/followups": ("fu_add",
                               ["token", "business_id", "action",
                                "due_date"], False),
            "/api/followup-done": ("fu_done", ["token", "id"], False),
        }
        if self.path not in routes:
            self._json({"error": "not found"}, 404)
            return
        name, fields, mints = routes[self.path]
        try:
            params = [str(body[f]) for f in fields]
        except KeyError as exc:
            self._json({"error": f"missing field {exc}"})
            return
        result, _ = _execute(name, params)
        if mints and result.startswith("ok:"):
            # the engine verified the credential; the shell mints the
            # session and returns it as the auth token
            subject_id = int(result.split(":", 1)[1])
            self._json({"token": _mint(subject_id)})
            return
        self._json({"result": result})

    def _discover(self, q: dict) -> dict:
        """OSM discovery: candidates are fed through the VERIFIED
        biz_add engine — rejected candidates leave zero rows."""
        sys.path.insert(0, str(ROOT / "examples" / "sales_app"))
        import discover_osm
        token = q.get("token", "")
        added = rejected = 0
        try:
            candidates = discover_osm.discover(
                q.get("city", ""), q.get("category", ""),
                int(q.get("limit", "8")))
        except Exception as exc:
            return {"error": f"discovery failed: {exc}"}
        for c in candidates:
            result, _ = _execute("biz_add",
                                 [token, c["name"], q.get("category", ""),
                                  c["city"], c["phone"], c["website"],
                                  "2" if c["website"] else "1"])
            if result.startswith("ok:"):
                added += 1
            else:
                rejected += 1
        return {"candidates": len(candidates), "added": added,
                "rejected": rejected}

    def log_message(self, fmt, *args):  # keep the console calm
        pass


def main() -> None:
    argv = sys.argv[1:]
    if argv and argv[0] == "--logout-user":
        ids = REGISTRY.revoke_all_for(int(argv[1]))
        killed = 0
        if ids:
            rev = Revocations(REVOCATIONS_PATH)
            rev.revoke(ids)
            killed = len(ids)
        print(f"revoked {killed} outstanding session token(s) for "
              f"subject {argv[1]}")
        sys.exit(0)

    print(f"2066 Sales on http://localhost:{PORT} "
          f"(sessions: {SESSION_TTL_MINUTES} min TTL)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
