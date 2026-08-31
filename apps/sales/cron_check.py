#!/usr/bin/env python3
"""Cronjob body: run the verified health engine against the real
sales-api and persist the verdict for the dashboard.

Installed on the host as a real cron entry (see INFRA.md):
    */5 * * * * docker run --rm -v 2066-sales-data:/state/data \
        -v 2066-sales-keys:/state/keys -e 2066_KEY_HOME=/state/keys \
        -e 2066_SALES_DB=/state/data/sales.db 2066-sales:v1 \
        python examples/sales_app/cron_check.py

The DECISION (UP/DOWN) is made by api_health.ai; this script only
timestamps and stores what the program concluded.
"""

import io
import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

APP_DIR = Path(__file__).resolve().parent
ROOT = APP_DIR.parent.parent
sys.path.insert(0, str(ROOT))

from runtime import analyze, execute, parse_source  # noqa: E402
from runtime.capabilities import GrantSet  # noqa: E402

GRANTS = GrantSet.from_file(
    str(ROOT / "policies" / "deployment" / "sales-caps.json"))
STATE_PATH = Path(os.environ.get(
    "2066_SALES_DB", str(APP_DIR / "sales.db"))).parent / "integration_status.json"


def http_transport(url: str) -> str:
    # netpolicy reference enforcement (spec/netpolicy.md)
    from runtime.netpolicy import default_transport, guarded_transport
    return guarded_transport(default_transport(timeout=8))(url)


def main() -> None:
    program = parse_source(
        (ROOT / "programs" / "sales" / "integration" / "api_health.ai")
        .read_text(encoding="utf-8"))
    analysis = analyze(program)
    old_in, old_out = sys.stdin, sys.stdout
    sys.stdin, sys.stdout = io.StringIO(""), io.StringIO()
    try:
        execute(program, analysis, grants=GRANTS, net=http_transport)
        verdict = sys.stdout.getvalue().strip()
    except Exception as exc:
        verdict = f"sales-api: ERROR ({getattr(exc, 'code', 'E???')})"
    finally:
        sys.stdin, sys.stdout = old_in, old_out

    state = {
        "verdict": verdict,
        "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "program": "api_health.ai",
    }
    STATE_PATH.write_text(json.dumps(state, indent=1), encoding="utf-8")
    print(json.dumps(state))


if __name__ == "__main__":
    main()
