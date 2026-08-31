import unittest
from datetime import datetime, timedelta, timezone

from runtime.capabilities import (GrantSet, normalize_path, parse_timestamp)
from runtime.errors import StructuredError

NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=timezone.utc)
FUTURE = "2036-01-01T00:00:00Z"
PAST = "2020-01-01T00:00:00Z"

ROOT = normalize_path(".")


def grants(*specs):
    entries = []
    for spec in specs:
        action, resource = spec[0], spec[1]
        entry = {"action": action, "resource": resource}
        if len(spec) > 2 and spec[2] is not None:
            entry["expires"] = spec[2]
        if len(spec) > 3 and spec[3] is not None:
            entry["max_bytes"] = spec[3]
        entries.append(entry)
    return GrantSet.from_dict({"subject": "test", "grants": entries})


class TestPathNormalization(unittest.TestCase):
    def test_absolute_forward_slashes(self):
        p = normalize_path("some/relative/../path\\file.txt")
        self.assertTrue(p.startswith(ROOT))
        self.assertNotIn("\\", p)
        self.assertNotIn("..", p)

    def test_timestamp_parsing(self):
        self.assertEqual(parse_timestamp(FUTURE).tzinfo is not None, True)
        # +02:00 offset is normalized to the same UTC instant (22:00Z Dec 31)
        self.assertEqual(parse_timestamp("2026-01-01T00:00:00+02:00"),
                         datetime(2025, 12, 31, 22, 0, 0, tzinfo=timezone.utc))
        self.assertEqual(parse_timestamp("2026-01-01 00:00:00").tzinfo,
                         timezone.utc)  # naive -> UTC


class TestScopeMatching(unittest.TestCase):
    def setUp(self):
        self.g = grants(("filesystem.read", "examples/incoming"))
        self.scope = normalize_path("examples/incoming")

    def test_exact_directory_allowed(self):
        self.g.check("filesystem.read", self.scope, NOW)

    def test_subfile_allowed(self):
        self.g.check("filesystem.read", self.scope + "/note.txt", NOW)

    def test_subdirectory_allowed(self):
        self.g.check("filesystem.read", self.scope + "/sub/dir/f.txt", NOW)

    def test_sibling_prefix_denied(self):
        # /incoming must not cover /incoming-evil
        with self.assertRaises(StructuredError) as ctx:
            self.g.check("filesystem.read", self.scope + "-evil/f.txt", NOW)
        self.assertEqual(ctx.exception.code, "E401")

    def test_parent_denied(self):
        with self.assertRaises(StructuredError) as ctx:
            self.g.check("filesystem.read", normalize_path("examples"), NOW)
        self.assertEqual(ctx.exception.code, "E401")

    def test_action_must_match(self):
        with self.assertRaises(StructuredError) as ctx:
            self.g.check("filesystem.write", self.scope + "/f.txt", NOW)
        self.assertEqual(ctx.exception.code, "E401")


class TestExpiryAndLimits(unittest.TestCase):
    def test_unexpired_allowed(self):
        g = grants(("filesystem.read", ".", FUTURE))
        g.check("filesystem.read", normalize_path("."), NOW)

    def test_expired_denied_e402(self):
        g = grants(("filesystem.read", ".", PAST))
        with self.assertRaises(StructuredError) as ctx:
            g.check("filesystem.read", normalize_path("."), NOW)
        self.assertEqual(ctx.exception.code, "E402")

    def test_boundary_expiry_is_allowed(self):
        g = grants(("filesystem.read", ".", "2026-08-30T12:00:00Z"))
        g.check("filesystem.read", normalize_path("."), NOW)  # now == expires

    def test_max_bytes_denied_e403(self):
        g = grants(("filesystem.write", ".", None, 10))
        with self.assertRaises(StructuredError) as ctx:
            g.check("filesystem.write", normalize_path("./f.txt"), NOW, nbytes=11)
        self.assertEqual(ctx.exception.code, "E403")
        g.check("filesystem.write", normalize_path("./f.txt"), NOW, nbytes=10)

    def test_no_limit_accepts_anything(self):
        g = grants(("filesystem.write", "."))
        g.check("filesystem.write", normalize_path("./f.txt"), NOW, nbytes=10**9)


class TestGrantFileParsing(unittest.TestCase):
    def test_from_dict_minimal(self):
        g = GrantSet.from_dict({"grants": [
            {"action": "filesystem.read", "resource": "examples/incoming"}]})
        self.assertEqual(g.subject, "anonymous")
        self.assertEqual(g.capabilities[0].max_bytes, None)

    def test_unknown_action_rejected(self):
        with self.assertRaises(ValueError):
            GrantSet.from_dict({"grants": [
                {"action": "filesystem.delete", "resource": "."}]})

    def test_missing_resource_rejected(self):
        with self.assertRaises(ValueError):
            GrantSet.from_dict({"grants": [{"action": "filesystem.read"}]})

    def test_demo_caps_file_loads(self):
        g = GrantSet.from_file("examples/caps_demo.json")
        self.assertEqual(g.subject, "agent-A91")
        self.assertEqual(len(g.capabilities), 1)
        self.assertEqual(g.capabilities[0].id, "incoming-read")


if __name__ == "__main__":
    unittest.main()
