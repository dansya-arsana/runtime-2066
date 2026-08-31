#!/usr/bin/env python3
"""Repo-run shim for the MCP server.

The real server is runtime/mcp_server.py (pip: `2066-mcp`). This shim
preserves the historical repo behavior: data plane at
examples/notes_app/notes.db, so `python examples/mcp/mcp_server.py` and
`python examples/mcp/test_mcp.py` keep working from a checkout.
"""

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
os.environ.setdefault(
    "2066_NOTES_DB", str(ROOT / "examples" / "notes_app" / "notes.db"))
sys.path.insert(0, str(ROOT))

from runtime.mcp_server import serve  # noqa: E402

if __name__ == "__main__":
    try:
        serve()
    except KeyboardInterrupt:
        pass
