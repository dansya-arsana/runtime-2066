"""Demo: drive the 2066 MCP server running ON THE VPS from this PC.

Speaks JSON-RPC 2.0 over ssh -> docker -> stdio, exactly like an MCP
client would. Proves the agent-on-PC / runtime-on-server split with zero
LLM involvement.
"""
import json
import subprocess

SSH = ('ssh main "cd ~/apps/runtime-2066 && docker run --rm -i '
       '-v $PWD:/src -w /src -e 2066_MCP_HOME=/tmp/mcp '
       '-e 2066_NOTES_DB=/tmp/mcp/mcp.db python:3.12-slim bash -c '
       '\'pip install -q cryptography && python examples/mcp/mcp_server.py\'"')
proc = subprocess.Popen(SSH, shell=True, stdin=subprocess.PIPE,
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                        text=True, bufsize=1)


def call(method, params, i):
    req = json.dumps({"jsonrpc": "2.0", "method": method, "id": i,
                      "params": params})
    proc.stdin.write(req + "\n")
    proc.stdin.flush()
    return json.loads(proc.stdout.readline())


def tool(name, args, i):
    return call("tools/call", {"name": name, "arguments": args}, i)


def text(r):
    return r["result"]["content"][0]["text"]


r = call("initialize", {"protocolVersion": "2024-11-05"}, 1)
print("1. handshake  ->", r["result"]["serverInfo"], "(server on VPS)")
tools = call("tools/list", {}, 2)["result"]["tools"]
print("2. tools/list ->", len(tools), "tools:",
      ", ".join(t["name"] for t in tools))
print("3. register   ->", text(tool("2066_notes_register",
      {"username": "agent_z", "password": "Remote-2066!"}, 3))[:30], "...")
tok = text(tool("2066_notes_login",
      {"username": "agent_z", "password": "Remote-2066!"}, 4))
print("4. login      ->", tok[:30], "...")
print("5. add note   ->", text(tool("2066_notes_add",
      {"token": tok[6:], "title": "from my PC",
       "body": "via ssh to VPS MCP"}, 5)))
print("6. list       ->", text(tool("2066_notes_list",
      {"token": tok[6:]}, 6)))
bad = tool("2066_notes_list", {"token": "forged-by-attacker"}, 7)
print("7. forged     ->", text(bad), "(isError:",
      bad["result"].get("isError"), ")")
proc.stdin.close()
proc.wait()
print("\nREMOTE MCP SESSION COMPLETE — agent on PC, runtime on VPS")
