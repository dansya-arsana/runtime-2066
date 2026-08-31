#!/usr/bin/env python3
"""End-to-end test for the 2066 MCP stdio server (examples/mcp/mcp_server.py).

Spawns the server as a subprocess, speaks MCP (JSON-RPC 2.0, one message
per line) over its stdin/stdout, and checks:

    1. initialize   -> protocolVersion "2024-11-05" + serverInfo 2066-mcp
    2. notifications/initialized -> no response
    3. tools/list   -> exactly the 6 expected tools
    4. 2066_calculate 12 + 3.5  -> "15.5" in output
    5. 2066_calculate 10 / 0    -> the guarded "division by zero" error
    6. protocol edges: structured errors set isError, ping, unknown tool
       (-32602), unknown method (-32601)

Run from anywhere:
    python examples/mcp/test_mcp.py
"""

import json
import os
import queue
import subprocess
import sys
import tempfile
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
SERVER = ROOT / "examples" / "mcp" / "mcp_server.py"
TIMEOUT = 30.0

PASSED = 0


def check(condition: bool, label: str, detail: str = "") -> None:
    global PASSED
    if not condition:
        print(f"FAIL: {label}")
        if detail:
            print(f"      {detail}")
        sys.exit(1)
    PASSED += 1
    print(f"ok: {label}")


class Client:
    """Subprocess handle with a background reader (Windows-safe timeouts)."""

    def __init__(self, env_extra: dict | None = None, db: Path | None = None):
        env = os.environ.copy()
        if env_extra:
            env.update(env_extra)
        if db is not None:
            env["2066_NOTES_DB"] = str(db)
        self.proc = subprocess.Popen(
            [sys.executable, str(SERVER)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, encoding="utf-8",
            bufsize=1, cwd=str(ROOT), env=env)
        self.lines: queue.Queue = queue.Queue()
        self.reader = threading.Thread(target=self._pump, daemon=True)
        self.reader.start()

    def _pump(self) -> None:
        for line in self.proc.stdout:
            self.lines.put(line.rstrip("\n"))
        self.lines.put(None)  # EOF sentinel

    def send(self, message: dict) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(json.dumps(message) + "\n")
        self.proc.stdin.flush()

    def send_raw(self, raw: str) -> None:
        assert self.proc.stdin is not None
        self.proc.stdin.write(raw + "\n")
        self.proc.stdin.flush()

    def recv(self, timeout: float = TIMEOUT) -> dict:
        line = self.lines.get(timeout=timeout)
        if line is None:
            stderr = self.proc.stderr.read() if self.proc.stderr else ""
            raise AssertionError("server closed stdout unexpectedly\n"
                                 f"stderr:\n{stderr}")
        return json.loads(line)

    def request(self, method: str, params=None, rpc_id=None) -> dict:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        if rpc_id is not None:
            message["id"] = rpc_id
        self.send(message)
        return self.recv()

    def notify(self, method: str, params=None) -> None:
        message = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            message["params"] = params
        self.send(message)

    def call_tool(self, name: str, arguments: dict, rpc_id) -> dict:
        return self.request("tools/call",
                            {"name": name, "arguments": arguments}, rpc_id)

    def text_of(self, response: dict) -> str:
        return response["result"]["content"][0]["text"]

    def close(self) -> None:
        try:
            if self.proc.stdin:
                self.proc.stdin.close()
        except OSError:
            pass
        try:
            self.proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.proc.kill()
            self.proc.wait(timeout=10)


def main() -> None:
    client = Client()
    try:
        # 1. initialize ------------------------------------------------------
        response = client.request(
            "initialize",
            {"protocolVersion": "2024-11-05",
             "capabilities": {},
             "clientInfo": {"name": "mcp-test", "version": "0.0.0"}},
            rpc_id=1)
        check(response.get("jsonrpc") == "2.0" and response.get("id") == 1,
              "initialize response is JSON-RPC 2.0 with matching id")
        result = response.get("result", {})
        check(result.get("protocolVersion") == "2024-11-05",
              "protocolVersion is 2024-11-05",
              f"got {result.get('protocolVersion')!r}")
        check(result.get("serverInfo") == {"name": "2066-mcp",
                                           "version": "1.3.0"},
              "serverInfo is 2066-mcp 1.3.0",
              f"got {result.get('serverInfo')!r}")
        check("tools" in result.get("capabilities", {}),
              "capabilities advertises tools")

        # 2. notifications/initialized (no response) -------------------------
        client.notify("notifications/initialized")
        probe = client.request("ping", rpc_id=2)
        check(probe.get("id") == 2 and probe.get("result") == {},
              "notifications/initialized produced no response "
              "(next response is the ping probe)")

        # 3. tools/list ------------------------------------------------------
        response = client.request("tools/list", {}, rpc_id=3)
        tools = response.get("result", {}).get("tools", [])
        expected = {"2066_calculate", "2066_notes_register",
                    "2066_notes_login", "2066_notes_add",
                    "2066_notes_get", "2066_notes_list"}
        check(len(tools) == 6 and {t["name"] for t in tools} == expected,
              f"tools/list returns the 6 expected tools (got {len(tools)})")
        schemas = {t["name"]: t.get("inputSchema", {}) for t in tools}
        check(schemas["2066_calculate"].get("required")
              == ["a", "op", "b"],
              "2066_calculate schema requires a, op, b")

        # 4. calculate 12 + 3.5 -----------------------------------------------
        response = client.call_tool("2066_calculate",
                                    {"a": 12, "op": "+", "b": 3.5}, 4)
        text = client.text_of(response)
        check("15.5" in text and not response["result"].get("isError", False),
              "calculate 12 + 3.5 output contains 15.5",
              f"got {text!r}")

        # 5. calculate 10 / 0 (guarded division) ------------------------------
        response = client.call_tool("2066_calculate",
                                    {"a": 10, "op": "/", "b": 0}, 5)
        text = client.text_of(response)
        check("division by zero" in text,
              "calculate 10 / 0 output contains the guarded "
              "'division by zero' error",
              f"got {text!r}")

        # 6. protocol edges ----------------------------------------------------
        response = client.call_tool("2066_calculate",
                                    {"a": "abc", "op": "+", "b": 1}, 6)
        text = client.text_of(response)
        check(response["result"].get("isError") is True
              and text.startswith("error E"),
              "structured 2066 error (bad cast) sets isError",
              f"got {text!r}")

        response = client.call_tool("2066_nonsense", {}, 7)
        check(response.get("error", {}).get("code") == -32602,
              "unknown tool returns JSON-RPC error -32602",
              f"got {response.get('error')!r}")

        response = client.request("bogus/method", rpc_id=8)
        check(response.get("error", {}).get("code") == -32601,
              "unknown method returns JSON-RPC error -32601",
              f"got {response.get('error')!r}")

        # 7. raw-protocol edges: the transport must survive garbage --------
        client.send_raw("{not json at all")
        response = client.recv()
        check(response.get("error", {}).get("code") == -32700
              and response.get("id") is None,
              "malformed JSON line returns -32700 with null id",
              f"got {response!r}")

        client.send_raw("[1, 2, 3]")
        response = client.recv()
        check(response.get("error", {}).get("code") == -32600,
              "valid JSON that is not an object returns -32600",
              f"got {response!r}")

        # id-less objects are JSON-RPC notifications: answered NEVER by
        # design. An object carrying an id but no method must still get an
        # error answer, proving the transport treats garbage robustly.
        client.send_raw('{"jsonrpc": "2.0", "id": 42}')
        response = client.recv()
        check(response.get("id") == 42
              and response.get("error", {}).get("code") == -32601,
              "id-bearing garbage still answered with a routed error",
              f"got {response!r}")

        response = client.call_tool("2066_calculate", {"a": 1, "op": "+"}, 9)
        check(response.get("error", {}).get("code") == -32602
              and "missing argument" in response["error"]["message"],
              "missing tool argument returns -32602 naming the parameter",
              f"got {response.get('error')!r}")

        response = client.request("ping", rpc_id=10)
        check(response.get("id") == 10,
              "server survived garbage input and answers normally")
    finally:
        client.close()
        check(client.proc.returncode is not None,
              "server shuts down cleanly on stdin EOF "
              f"(exit {client.proc.returncode})")

    # 8. full auth flow against an ISOLATED temp db -------------------------
    with tempfile.TemporaryDirectory() as tmp:
        db = Path(tmp) / "flow.db"
        client = Client(db=db)
        try:
            response = client.request(
                "initialize", {"protocolVersion": "2024-11-05"}, rpc_id=1)
            check(response.get("result", {}).get("protocolVersion")
                  == "2024-11-05",
                  "isolated-db instance initializes")
            response = client.call_tool("2066_notes_register",
                                        {"username": "mcp_user",
                                         "password": "pw-123456"}, 2)
            check(client.text_of(response).startswith("token:"),
                  "register via MCP returns a minted session token",
                  f"got {client.text_of(response)!r}")
            response = client.call_tool("2066_notes_register",
                                        {"username": "mcp_user",
                                         "password": "other"}, 3)
            check("taken" in client.text_of(response),
                  "duplicate register reports 'username taken'")
            # "invalid credentials" is a normal program value (not a
            # structured error E*), so isError stays unset by contract.
            response = client.call_tool("2066_notes_login",
                                        {"username": "mcp_user",
                                         "password": "WRONG"}, 4)
            check("invalid credentials" in client.text_of(response),
                  "wrong password returns 'invalid credentials'")
            response = client.call_tool("2066_notes_login",
                                        {"username": "mcp_user",
                                         "password": "pw-123456"}, 5)
            token = client.text_of(response)
            check(token.startswith("token:"),
                  "login returns a minted session token",
                  f"got {token!r}")
            session_token = token.split("token:", 1)[1]
            response = client.call_tool("2066_notes_add",
                                        {"token": session_token,
                                         "title": "from mcp",
                                         "body": "written via tools/call"}, 6)
            check("ok:" in client.text_of(response),
                  "add note via MCP with session token")
            response = client.call_tool("2066_notes_list",
                                        {"token": session_token}, 7)
            check("from mcp" in client.text_of(response),
                  "list shows the MCP-written note",
                  f"got {client.text_of(response)!r}")
            response = client.call_tool("2066_notes_get",
                                        {"token": session_token,
                                         "note_id": 1}, 8)
            check("from mcp ::" in client.text_of(response),
                  "get returns 'title :: body'")
            response = client.call_tool("2066_notes_list",
                                        {"token": "forged-token"}, 9)
            check(response["result"].get("isError") is True,
                  "forged session token fails closed as isError")
        finally:
            client.close()

    print(f"\nALL {PASSED} CHECKS PASSED")


if __name__ == "__main__":
    main()
