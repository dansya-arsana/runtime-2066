"""2066 Notes — HTTP shell for the full-stack demo.

Business logic lives in the .ai programs and executes inside the 2066
runtime with capability grants and the SQLite data plane. This shell only
translates HTTP <-> stdin/stdout AND holds the one secret the programs
structurally cannot: the session-signing key. That layering is the point —
programs verify sessions (`session.verify`) but cannot mint them.

Persistent runtime: every program is parsed and validated ONCE at startup;
requests execute the cached analysis in-process.

Sessions are revocable: minted token_ids are recorded in
`session_registry.json`; `python examples/notes_app/server.py
--logout-user <id>` revokes all outstanding sessions of that subject.

Run from the repository root:
    python examples/notes_app/server.py
    -> http://localhost:8618
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
APP_DIR = Path(__file__).resolve().parent

from runtime import (StructuredError, analyze, execute, identity,  # noqa: E402
                     parse_source, program_effects, program_hash)
from runtime.capabilities import GrantSet  # noqa: E402
from runtime.data import DataPlane  # noqa: E402
from runtime.revocation import Revocations  # noqa: E402
from runtime.session import (SessionRegistry, SessionVerifier,  # noqa: E402
                             mint_session_token)

import runtime as _runtime_pkg
HELLO_EXAMPLE = (Path(_runtime_pkg.__file__).parent / "programs"
                 / "hello.ai")
from runtime.revocation import Revocations  # noqa: E402

DB = os.environ.get("2066_NOTES_DB", str(APP_DIR / "notes.db"))
CAPS = str(APP_DIR / "caps.json")
SERVER_IDENTITY = _KEY_HOME / "notes_server_identity.json"
SERVER_KEY = _KEY_HOME / "notes_server_identity.key"
REGISTRY_PATH = str(_KEY_HOME / "notes_session_registry.json")
_REVOCATIONS_PATH = str(_KEY_HOME / "notes_session_revocations.jsonl")
STATIC = {"index.html": "text/html; charset=utf-8",
          "app.js": "text/javascript; charset=utf-8",
          "styles.css": "text/css; charset=utf-8",
          "playground.html": "text/html; charset=utf-8"}
PORT = int(os.environ.get("PORT", "8618"))
HOST = os.environ.get("HOST", "127.0.0.1")
SESSION_TTL_MINUTES = 30

_db_lock = threading.Lock()


def _ensure_server_identity():
    """Generate the signing identity on first run (the mint authority)."""
    if SERVER_IDENTITY.exists() and SERVER_KEY.exists():
        return
    ident, secret = identity.generate_identity("notes-server")
    SERVER_IDENTITY.write_text(json.dumps({
        "agent_id": ident.agent_id, "algorithm": ident.algorithm,
        "public_key": ident.public_key, "created": ident.created},
        indent=2) + "\n", encoding="utf-8")
    SERVER_KEY.write_text(json.dumps({
        "agent_id": ident.agent_id, "algorithm": ident.algorithm,
        "secret_key": secret}, indent=2) + "\n", encoding="utf-8")
    print(f"generated session-signing identity: {SERVER_IDENTITY.name} "
          f"(keep {SERVER_KEY.name} secret)")


SESSION_REVOCATIONS = str(_KEY_HOME / "notes_session_revocations.jsonl")
_KEY_HOME.mkdir(parents=True, exist_ok=True)

_ensure_server_identity()
SERVER_IDENT = identity.parse_identity(
    json.loads(SERVER_IDENTITY.read_text(encoding="utf-8")))
_, SERVER_SECRET = identity.load_secret_key(
    json.loads(SERVER_KEY.read_text(encoding="utf-8")))
SESSIONS = SessionVerifier(
    public_key=SERVER_IDENT.public_key,
    revocations=Revocations(str(APP_DIR / "session_revocations.jsonl")))
REGISTRY = SessionRegistry(REGISTRY_PATH)
GRANTS = GrantSet.from_file(CAPS)

# Compile once: parse + validate every engine program at startup.
PROGRAMS = {}
for name in ("register", "login", "add_note", "get_note", "list_notes"):
    program = parse_source((APP_DIR / f"{name}.ai").read_text(encoding="utf-8"))
    PROGRAMS[name] = (program, analyze(program))
    node_count = sum(len(nodes) for nodes in
                     [program.nodes]
                     + [f.nodes for f in program.functions.values()])
    print(f"engine ready: {name}.ai ({node_count} nodes, validated)")


def mint_recorded(subject_id: int) -> str:
    """Trusted-host mint: sign a session AND record its id for revocation."""
    token = mint_session_token(SERVER_SECRET, subject_id,
                               ttl_minutes=SESSION_TTL_MINUTES)
    body_b64 = token.split(".")[0]
    pad = "=" * (-len(body_b64) % 4)
    payload = json.loads(base64.urlsafe_b64decode(body_b64 + pad))
    REGISTRY.register(subject_id, payload["token_id"])
    return token


def run_engine(name: str, params: list[str]) -> tuple[str, int]:
    """Execute a cached program in-process. Returns (output, exit_class).

    The programs do I/O through the semantic stdio ops (system.read /
    system.write), so we swap in string streams under the engine lock —
    thread-safe because execution is serialized.
    """
    program, analysis = PROGRAMS[name]
    db = DataPlane(DB, program.entities, GRANTS, now=None)
    stdin_buffer = io.StringIO("".join(p + "\n" for p in params))
    stdout_buffer = io.StringIO()
    with _db_lock:
        # swap process-global stdin INSIDE the engine lock: parallel
        # requests swapping it outside the lock read each other's
        # parameters under load (observed as E406 malformed-token 5/12).
        old_stdin = sys.stdin
        sys.stdin = stdin_buffer
        try:
            with redirect_stdout(stdout_buffer):
                execute(program, analysis, grants=GRANTS, db=db,
                        sessions=SESSIONS)
            return stdout_buffer.getvalue().strip(), 0
        except Exception as exc:  # StructuredError by contract
            code = getattr(exc, "code", "E???")
            return f"error {code}: {getattr(exc, 'detail', exc)}", 1
        finally:
            sys.stdin = old_stdin
            db.close()


def playground_run(source: str, stdin_text: str) -> dict:
    """Execute a visitor's program with the authority model visible.

    No capability grants exist at this endpoint, so every effectful op is
    structurally denied by the runtime (E4xx) — the denial IS the demo.
    The grammar is a DAG (no loops), so execution terminates on its own;
    a node cap and source cap bound the work per request.
    """
    try:
        program = parse_source(source)
        analysis = analyze(program)
    except StructuredError as exc:
        err = {"code": str(exc.code), "detail": exc.detail}
        if getattr(exc, "allowed_repairs", None):
            err["allowed_repairs"] = exc.allowed_repairs
        return {"ok": False, "stage": "validate", "error": err}
    except Exception as exc:
        return {"ok": False, "stage": "parse",
                "error": {"code": "E1xx", "detail": str(exc)}}
    node_count = len(program.nodes)
    if node_count > 500:
        return {"ok": False, "stage": "validate",
                "error": {"code": "E1xx",
                          "detail": f"too many nodes "
                                    f"({node_count} > 500)"}, }
    payload = {"ok": True,
               "hash": program_hash(program),
               "nodes": node_count,
               "effects": sorted(set(program_effects(program, analysis)))}
    stdin_buffer = io.StringIO(stdin_text[:4000])
    stdout_buffer = io.StringIO()
    with _db_lock:
        old_in, old_out = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = stdin_buffer, stdout_buffer
        try:
            # emit values come back from execute() (the CLI prints them);
            # system.write lands in the captured stdout stream
            result = execute(program, analysis)  # no grants: default-deny
            output = stdout_buffer.getvalue()
            emitted = "\n".join(str(v) for v in result)
            payload["output"] = (output + ("\n" if output and emitted
                                           else "") + emitted)
        except StructuredError as exc:
            output = stdout_buffer.getvalue()
            emitted = ""
            payload["output"] = output
            payload["denied"] = {"code": str(exc.code),
                                 "detail": exc.detail}
        finally:
            sys.stdin, sys.stdout = old_in, old_out
    return payload


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
        path = self.path.split("?")[0]
        if path == "/api/note":
            query = dict(pair.split("=", 1)
                         for pair in self.path.split("?")[1].split("&"))
            result, failed = run_engine("get_note",
                                        [query.get("token", ""),
                                         query["id"]])
            self._json({"result": result, "denied": failed == 1 and
                        result.startswith("error E4")})
        elif path == "/api/notes":
            query = dict(pair.split("=", 1)
                         for pair in self.path.split("?")[1].split("&"))
            result, failed = run_engine("list_notes",
                                        [query.get("token", "")])
            self._json({"result": result,
                        "titles": result.split("\n") if result else [],
                        "denied": failed == 1})
        elif path == "/api/health":
            self._json({"ok": True, "engines": sorted(PROGRAMS)})
        elif path == "/api/playground/example":
            self._json({"source": HELLO_EXAMPLE.read_text(encoding="utf-8")})
        else:
            static_name = ("playground.html" if path == "/playground"
                           else "index.html" if path == "/"
                           else path.lstrip("/"))
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
        try:
            data = self._body()
        except json.JSONDecodeError:
            self._json({"error": "bad json"}, 400)
            return
        if self.path == "/api/playground/run":
            if not isinstance(data, dict):
                self._json({"error": "bad body"}, 400)
                return
            source = data.get("source")
            if not isinstance(source, str) or not source.strip():
                self._json({"error": "missing source"}, 400)
                return
            if len(source) > 32_000:
                self._json({"error": "source too large (max 32000 chars)"},
                           413)
                return
            self._json(playground_run(source, str(data.get("stdin", ""))))
            return
        routes = {
            "/api/register": ("register", ["username", "password"]),
            "/api/login": ("login", ["username", "password"]),
            "/api/note": ("add_note", ["token", "title", "body"]),
        }
        route = routes.get(self.path)
        if route is None:
            self._json({"error": "not found"}, 404)
            return
        program, fields = route
        try:
            params = [str(data[field]) for field in fields]
        except KeyError as exc:
            self._json({"error": f"missing field {exc}"}, 400)
            return
        result, failed = run_engine(program, params)
        payload = {"result": result}

        # the trusted shell mints the session AFTER the engine accepted
        # the credentials — programs can verify but never mint
        if not failed and program in ("register", "login") \
                and result.startswith("ok:"):
            subject = int(result[3:])
            payload["token"] = mint_recorded(subject)
        self._json(payload)

    def log_message(self, fmt, *args):
        pass


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--logout-user", type=int, default=None,
                        metavar="SUBJECT_ID",
                        help="revoke all outstanding sessions of this "
                             "subject, then exit (do not serve)")
    args = parser.parse_args()
    if args.logout_user is not None:
        # real logout: every outstanding token_id lands in the revocation
        # chain, so old tokens are DENIED server-side, not just forgotten
        killed = REGISTRY.revoke_all_for(args.logout_user)
        revocations = Revocations(SESSION_REVOCATIONS)
        for token_id in killed:
            revocations.revoke(token_id, reason="logout")
        print(f"revoked {killed} outstanding session token(s) for "
              f"subject {args.logout_user}")
        sys.exit(0)

    print(f"2066 Notes on http://localhost:{PORT} "
          f"(sessions: {SESSION_TTL_MINUTES} min TTL)")
    ThreadingHTTPServer((HOST, PORT), Handler).serve_forever()
