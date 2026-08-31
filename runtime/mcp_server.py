"""2066 MCP Server — verified .ai programs exposed as MCP tools over stdio.

Installable form of examples/mcp/mcp_server.py: ships inside the
`runtime-2066` package with the tool programs bundled under
runtime/programs/. The `2066-mcp` console script starts it; an MCP client
(Claude Desktop, Claude Code, any JSON-RPC 2.0 stdio client) only needs:

    {"mcpServers": {"2066": {"command": "2066-mcp"}}}

Every tool is a 2066 semantic program: parsed and validated ONCE at
startup, executed in-process per call. The shell holds the two things the
programs structurally cannot mint: capability grants (programs/caps.json)
and the SQLite data plane. The session-mint key lives in ~/.2066/mcp/,
outside the package — copying site-packages must not hand out mint
authority.

Session model: register/login verify credentials inside the program, then
the SHELL mints a signed, expiring, revocable session token. notes_add/
get/list verify the token via `session.verify` inside the program; forged
tokens fail closed with the runtime's structured error.

Default locations (override with env):
    2066_NOTES_DB  — SQLite data plane (default ~/.2066/mcp/notes.db)
    2066_MCP_HOME  — identity, session registry, revocations

Transport: MCP stdio — JSON-RPC 2.0, one message per line, responses
flushed immediately. Stdlib only.
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
from pathlib import Path

from . import StructuredError, analyze, execute, identity, parse_source
from .capabilities import GrantSet
from .data import DataPlane
from .revocation import Revocations
from .session import (SessionRegistry, SessionVerifier,
                      mint_session_token)

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "2066-mcp", "version": "1.3.0"}

PROGRAMS_DIR = Path(__file__).resolve().parent / "programs"

_MCP_HOME = Path(os.environ.get("2066_MCP_HOME",
                                str(Path.home() / ".2066" / "mcp")))
_MCP_HOME.mkdir(parents=True, exist_ok=True)
NOTES_DB = os.environ.get(
    "2066_NOTES_DB", str(_MCP_HOME / "notes.db"))
Path(NOTES_DB).parent.mkdir(parents=True, exist_ok=True)
GRANTS = GrantSet.from_file(str(PROGRAMS_DIR / "caps.json"))

IDENTITY_PATH = _MCP_HOME / "mcp_identity.json"
KEY_PATH = _MCP_HOME / "mcp_identity.key"
REGISTRY_PATH = _MCP_HOME / "mcp_session_registry.json"
REVOCATIONS_PATH = _MCP_HOME / "mcp_session_revocations.jsonl"
SESSION_TTL_MINUTES = 30


def _ensure_identity() -> tuple:
    """Generate the MCP server's signing identity on first run."""
    if IDENTITY_PATH.exists() and KEY_PATH.exists():
        ident = identity.parse_identity(
            json.loads(IDENTITY_PATH.read_text(encoding="utf-8")))
        _, secret = identity.load_secret_key(
            json.loads(KEY_PATH.read_text(encoding="utf-8")))
        return ident, secret
    ident, secret = identity.generate_identity("2066-mcp")
    IDENTITY_PATH.write_text(json.dumps({
        "agent_id": ident.agent_id, "algorithm": ident.algorithm,
        "public_key": ident.public_key, "created": ident.created},
        indent=2) + "\n", encoding="utf-8")
    KEY_PATH.write_text(json.dumps({
        "agent_id": ident.agent_id, "algorithm": ident.algorithm,
        "secret_key": secret}, indent=2) + "\n", encoding="utf-8")
    return ident, secret


_IDENT, _SECRET = _ensure_identity()
SESSIONS = SessionVerifier(
    public_key=_IDENT.public_key,
    revocations=Revocations(str(REVOCATIONS_PATH)))
REGISTRY = SessionRegistry(str(REGISTRY_PATH))

# Tool name -> bundled program, stdin parameter order (in order), whether
# execution needs the capability-granted data plane, the JSON-Schema for
# the agent, and a description naming the authority used.
TOOL_SPECS = {
    "2066_calculate": {
        "program": PROGRAMS_DIR / "calculator.ai",
        "params": ["a", "op", "b"],
        "needs_db": False,
        "description": (
            "Deterministic arithmetic on two numbers (add, subtract, "
            "multiply, divide) in f64, with a guarded divide: b = 0 "
            "yields the program's 'error: division by zero' value, never "
            "a crash. Pure computation — no capability grants, no "
            "database."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "a": {"type": "number", "description": "left operand"},
                "op": {"type": "string", "enum": ["+", "-", "*", "/"],
                       "description": "operator"},
                "b": {"type": "number", "description": "right operand"},
            },
            "required": ["a", "op", "b"],
        },
    },
    "2066_notes_register": {
        "program": PROGRAMS_DIR / "register.ai",
        "params": ["username", "password"],
        "needs_db": True,
        "description": (
            "Register a notes-app user (salted sha256 password digest). "
            "Returns a minted session token, or 'username taken'. "
            "Authority: capability grants + data plane (data.read/"
            "data.write on user)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["username", "password"],
        },
    },
    "2066_notes_login": {
        "program": PROGRAMS_DIR / "login.ai",
        "params": ["username", "password"],
        "needs_db": True,
        "description": (
            "Verify notes-app credentials against the stored digest. "
            "Returns a minted session token, or 'invalid credentials'. "
            "Authority: capability grants + data plane (data.read on "
            "user)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "username": {"type": "string"},
                "password": {"type": "string"},
            },
            "required": ["username", "password"],
        },
    },
    "2066_notes_add": {
        "program": PROGRAMS_DIR / "add_note.ai",
        "params": ["token", "title", "body"],
        "needs_db": True,
        "description": (
            "Add a note ('ok:<id>') bound to the session subject; the "
            "token is verified inside the program via session.verify. "
            "Authority: capability grants + data plane (data.write on "
            "note)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {"type": "string",
                          "description": "session token"},
                "title": {"type": "string"},
                "body": {"type": "string"},
            },
            "required": ["token", "title", "body"],
        },
    },
    "2066_notes_get": {
        "program": PROGRAMS_DIR / "get_note.ai",
        "params": ["token", "note_id"],
        "needs_db": True,
        "description": (
            "Read one note as 'title :: body' ('not your note' / 'no such "
            "note' otherwise); the token is verified inside the program "
            "via session.verify. Authority: capability grants + data "
            "plane (data.read on note)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {"type": "string",
                          "description": "session token"},
                "note_id": {"type": "integer"},
            },
            "required": ["token", "note_id"],
        },
    },
    "2066_notes_list": {
        "program": PROGRAMS_DIR / "list_notes.ai",
        "params": ["token"],
        "needs_db": True,
        "description": (
            "List the session subject's note titles (newline-joined, "
            "empty when none); the token is verified inside the program "
            "via session.verify. Authority: capability grants + data "
            "plane (data.read on note)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "token": {"type": "string",
                          "description": "session token"},
            },
            "required": ["token"],
        },
    },
}


class MCPError(Exception):
    """Protocol-level error carrying its JSON-RPC code."""

    def __init__(self, code: int, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _rpc_error(rpc_id, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rpc_id,
            "error": {"code": code, "message": message}}


class MCPServer:
    """Persistent engine set: each tool's program is compiled (parse +
    validate) once; tool calls execute the cached analysis in-process."""

    def __init__(self):
        self.engines: dict[str, tuple] = {}
        for name, spec in TOOL_SPECS.items():
            program = parse_source(
                spec["program"].read_text(encoding="utf-8"))
            self.engines[name] = (program, analyze(program))

    # ---- JSON-RPC dispatch ------------------------------------------------

    def handle(self, message: dict) -> dict | None:
        """Handle one decoded message; None -> send nothing (notification)."""
        method = message.get("method", "")
        if message.get("id") is None or method.startswith("notifications/"):
            return None  # JSON-RPC notification: never answered
        params = message.get("params")
        if not isinstance(params, dict):
            params = {}
        try:
            result = self.dispatch(method, params)
            return {"jsonrpc": "2.0", "id": message["id"], "result": result}
        except MCPError as exc:
            return _rpc_error(message["id"], exc.code, exc.message)
        except Exception as exc:  # a bug must not kill the transport
            return _rpc_error(message["id"], -32603,
                              f"internal error: "
                              f"{exc.__class__.__name__}: {exc}")

    def dispatch(self, method: str, params: dict) -> dict:
        if method == "initialize":
            requested = params.get("protocolVersion")
            version = (requested if requested == PROTOCOL_VERSION
                       else PROTOCOL_VERSION)
            return {"protocolVersion": version,
                    "capabilities": {"tools": {}},
                    "serverInfo": SERVER_INFO}
        if method == "ping":
            return {}
        if method == "tools/list":
            return {"tools": [
                {"name": name,
                 "description": spec["description"],
                 "inputSchema": spec["inputSchema"]}
                for name, spec in TOOL_SPECS.items()]}
        if method == "tools/call":
            return self._tools_call(params)
        raise MCPError(-32601, f"method not found: {method}")

    # ---- tool execution ---------------------------------------------------

    def _tools_call(self, params: dict) -> dict:
        name = params.get("name")
        if name not in TOOL_SPECS:
            raise MCPError(-32602, f"unknown tool: {name!r}")
        arguments = params.get("arguments")
        if not isinstance(arguments, dict):
            raise MCPError(-32602, "arguments must be an object")
        values = []
        for param in TOOL_SPECS[name]["params"]:
            if param not in arguments:
                raise MCPError(-32602, f"missing argument: {param}")
            values.append(str(arguments[param]))
        try:
            text = self._run_program(name, values)
        except Exception as exc:  # engine crash -> tool error, not protocol
            text = (f"error E999: engine crash: "
                    f"{exc.__class__.__name__}: {exc}")
        if name in ("2066_notes_register", "2066_notes_login") \
                and text.startswith("ok:"):
            # engine verified the credential -> the SHELL mints the session
            # token (programs verify sessions but can never mint them).
            text = "token:" + self._mint(int(text.split(":", 1)[1]))
        result = {"content": [{"type": "text", "text": text}]}
        if text.startswith("error E"):  # structured 2066 error
            result["isError"] = True
        return result

    def _mint(self, subject_id: int) -> str:
        token = mint_session_token(_SECRET, subject_id,
                                   ttl_minutes=SESSION_TTL_MINUTES)
        payload = json.loads(base64.urlsafe_b64decode(
            token.split(".")[0] + "=" * (-len(token.split(".")[0]) % 4)))
        REGISTRY.register(subject_id, payload["token_id"])
        return token

    def _run_program(self, name: str, values: list[str]) -> str:
        """Execute a cached program with `values` fed to semantic stdin.

        The programs do I/O through the semantic stdio ops
        (system.read / system.write), so we swap in string streams for the
        duration of execution. Authority: db-backed tools run with the
        capability grants + the notes data plane; the calculator runs pure
        (no grants, no db — it has no effectful ops to deny).
        """
        spec = TOOL_SPECS[name]
        program, analysis = self.engines[name]
        db = None
        if spec["needs_db"]:
            db = DataPlane(NOTES_DB, program.entities, GRANTS, None)
        stdin_buffer = io.StringIO("".join(v + "\n" for v in values))
        stdout_buffer = io.StringIO()
        old_stdin, old_stdout = sys.stdin, sys.stdout
        sys.stdin, sys.stdout = stdin_buffer, stdout_buffer
        try:
            if db is None:
                execute(program, analysis)
            else:
                execute(program, analysis, grants=GRANTS, db=db,
                        sessions=SESSIONS)
        except StructuredError as exc:
            return f"error {exc.code}: {exc.detail}"
        finally:
            sys.stdin, sys.stdout = old_stdin, old_stdout
            if db is not None:
                db.close()
        return stdout_buffer.getvalue().strip()


def serve(stdin=None, stdout=None) -> None:
    """MCP stdio loop: one JSON-RPC message per line, responses flushed."""
    stdin = sys.stdin if stdin is None else stdin
    stdout = sys.stdout if stdout is None else stdout
    server = MCPServer()
    while True:
        line = stdin.readline()
        if not line:  # EOF: the client hung up
            break
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError as exc:
            response = _rpc_error(None, -32700, f"parse error: {exc}")
        else:
            if isinstance(message, dict):
                response = server.handle(message)
            else:
                response = _rpc_error(None, -32600,
                                      "invalid request: expected an object")
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


def main() -> None:
    try:
        serve()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
