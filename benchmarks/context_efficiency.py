#!/usr/bin/env python3
"""Context-efficiency benchmark (hardening plan SS70).

TASK: "modify the business list behavior of the sales application."

Measures how much context an agent must consume to act safely:

  conventional repo: read every file you must touch/grok (server
  wiring + the three business programs + grants + the app README)
  2066 semantic mode: `2066 context sales::business::list` card + the
  one unit's source

Honest framing: this is a byte/inspection proxy for token cost, not a
model measurement — §68's model-independence study is the follow-up.
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def file_bytes(*paths: Path) -> int:
    return sum(p.stat().st_size for p in paths if p.exists())


def conventional_context() -> int:
    return file_bytes(
        ROOT / "apps" / "sales" / "sales_server.py",
        ROOT / "programs" / "sales" / "business" / "list.ai",
        ROOT / "programs" / "sales" / "business" / "ids.ai",
        ROOT / "programs" / "sales" / "business" / "add.ai",
        ROOT / "policies" / "deployment" / "sales-caps.json",
        ROOT / "apps" / "sales" / "README.md",
        ROOT / "programs" / "sales" / "package.ai",
    )


def semantic_context() -> tuple[int, int]:
    card = subprocess.run(
        [sys.executable, "-m", "runtime", "context",
         "sales::business::list"],
        capture_output=True, text=True, cwd=str(ROOT), timeout=60)
    card_bytes = len(card.stdout.encode("utf-8"))
    unit_bytes = (ROOT / "programs" / "sales" / "business"
                  / "list.ai").stat().st_size
    return card_bytes, unit_bytes


def main() -> None:
    conv = conventional_context()
    card, unit = semantic_context()
    total_2066 = card + unit
    print(f"task: modify sales business list behavior")
    print(f"  conventional files+context : {conv:>7,} bytes")
    print(f"  2066 context card          : {card:>7,} bytes")
    print(f"  2066 unit source           : {unit:>7,} bytes")
    print(f"  2066 total                 : {total_2066:>7,} bytes")
    print(f"  reduction                  : "
          f"{(1 - total_2066 / conv) * 100:.1f}% "
          f"({conv / total_2066:.1f}x less context)")


if __name__ == "__main__":
    main()
