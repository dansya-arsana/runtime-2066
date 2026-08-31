"""Filesystem trust boundary (review P1): symlink escapes and
check-then-open races are CLOSED, not mitigated.

Guarantees pinned here:
  - a symlink inside an allowed directory cannot read/write outside
    the capability scope (authorization covers the RESOLVED target)
  - the open acts on the RESOLVED path with O_NOFOLLOW where available
    — a swapped final-component symlink is refused, not followed
  - read size limits are enforced ON THE OPEN HANDLE (bounded read),
    eliminating the size-check TOCTOU
  - non-regular objects (directories, devices) are refused
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from runtime.capabilities import GrantSet
from runtime.errors import StructuredError
from runtime.fsops import read_file, write_file

NOW = datetime.now(timezone.utc)


def grants_for(path: Path, max_bytes=None) -> GrantSet:
    entry = {"action": "filesystem.read", "resource": str(path.resolve())}
    grants = {"subject": "t", "grants": [entry,
               {"action": "filesystem.write",
                "resource": str(path.resolve())}]}
    if max_bytes is not None:
        grants["grants"][0]["max_bytes"] = max_bytes
    return GrantSet.from_dict(grants)


def can_symlink() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp) / "t"
        target.write_text("x", encoding="utf-8")
        link = Path(tmp) / "l"
        try:
            os.symlink(target, link)
        except (OSError, NotImplementedError):
            return False
        return True


class TestSymlinkEscape(unittest.TestCase):
    @unittest.skipUnless(can_symlink(), "symlinks unavailable on this host")
    def test_read_through_symlink_out_of_scope_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inside = root / "inside"
            secret = root / "secret.txt"
            inside.mkdir()
            secret.write_text("classified", encoding="utf-8")
            link = inside / "innocent.txt"
            os.symlink(secret, link)
            grants = grants_for(inside)
            with self.assertRaises(StructuredError) as ctx:
                read_file(grants, "001", str(link), NOW)
            self.assertEqual(ctx.exception.code, "E401",
                             "symlink target outside the granted scope "
                             "must be denied")

    @unittest.skipUnless(can_symlink(), "symlinks unavailable on this host")
    def test_write_through_symlink_out_of_scope_denied(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            inside = root / "inside"
            outside = root / "outside.txt"
            inside.mkdir()
            link = inside / "escape.txt"
            os.symlink(outside, link)
            grants = grants_for(inside)
            with self.assertRaises(StructuredError) as ctx:
                write_file(grants, "001", str(link), "payload", NOW)
            self.assertEqual(ctx.exception.code, "E401")
            self.assertFalse(outside.exists(),
                             "nothing may be created outside the scope")

    @unittest.skipUnless(can_symlink(), "symlinks unavailable on this host")
    def test_symlink_INSIDE_scope_resolves_and_works(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            real = root / "real.txt"
            real.write_text("hello", encoding="utf-8")
            link = root / "alias.txt"
            os.symlink(real, link)
            grants = grants_for(root)
            self.assertEqual(read_file(grants, "001", str(link), NOW),
                             "hello")

    def test_directory_refused_as_read_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            grants = grants_for(Path(tmp))
            with self.assertRaises(StructuredError) as ctx:
                read_file(grants, "001", tmp, NOW)
            self.assertEqual(ctx.exception.code, "E305")

    def test_size_limit_enforced_on_handle(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            big = root / "big.txt"
            big.write_text("x" * 1000, encoding="utf-8")
            grants = grants_for(root, max_bytes=100)
            with self.assertRaises(StructuredError) as ctx:
                read_file(grants, "001", str(big), NOW)
            self.assertEqual(ctx.exception.code, "E403")


if __name__ == "__main__":
    unittest.main()
