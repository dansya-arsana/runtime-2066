"""Effects and capability enforcement, end to end, in both adapters.

Covers the §82 demo beats: scoped access allowed, out-of-scope denied,
default deny without a capability system, and identical enforcement from
the tree interpreter and the plan VM."""

import json
import tempfile
import unittest
from pathlib import Path

from runtime import (analyze, execute, execute_plan, parse_source,
                     program_effects)
from runtime.capabilities import GrantSet
from tests.helpers import example, run_cli


def reader_program(path: str) -> str:
    return (
        f'node 001\nop const\ntype string\nvalue "{path}"\n\n'
        "node 002\nop filesystem.read\ninput 001\noutput string\n\n"
        "node 003\nop emit\ninput 002\n"
    )


def writer_program(path: str, content: str) -> str:
    return (
        f'node 001\nop const\ntype string\nvalue "{path}"\n\n'
        f'node 002\nop const\ntype string\nvalue "{content}"\n\n'
        "node 003\nop filesystem.write\ninput 001 002\noutput i64\n\n"
        "node 004\nop emit\ninput 003\n"
    )


class TestFilesystemEffects(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        self.dir_str = str(self.dir).replace("\\", "/")
        (self.dir / "note.txt").write_text("runtime decides", encoding="utf-8")
        self.grants = GrantSet.from_dict({"subject": "test", "grants": [
            {"action": "filesystem.read", "resource": self.dir_str},
            {"action": "filesystem.write", "resource": self.dir_str},
        ]})

    def _run(self, adapter, source):
        program = parse_source(source)
        analysis = analyze(program)
        runner = execute if adapter == "tree" else execute_plan
        kwargs = {"grants": self.grants}
        try:
            return runner(program, analysis, **kwargs), None
        except Exception as exc:  # noqa: BLE001 - StructuredError by contract
            return None, exc

    def test_scoped_read_allowed_in_both_adapters(self):
        src = reader_program(self.dir_str + "/note.txt")
        for adapter in ("tree", "plan"):
            with self.subTest(adapter=adapter):
                emits, err = self._run(adapter, src)
                self.assertIsNone(err)
                self.assertEqual(emits, ["runtime decides"])

    def test_scoped_write_allowed_and_counted(self):
        target = self.dir_str + "/out.txt"
        emits, err = self._run("plan", writer_program(target, "hello"))
        self.assertIsNone(err)
        self.assertEqual(emits, [5])
        self.assertEqual((self.dir / "out.txt").read_text(encoding="utf-8"),
                         "hello")

    def test_out_of_scope_denied_identically(self):
        src = reader_program(str(self.dir.parent).replace("\\", "/")
                             + "/outside.txt")
        errors = []
        for adapter in ("tree", "plan"):
            _, err = self._run(adapter, src)
            errors.append(err)
        for err in errors:
            self.assertEqual(err.code, "E401")
            self.assertEqual(err.node, "002")
            self.assertEqual(err.operation, "filesystem.read")
        self.assertEqual(errors[0].render(), errors[1].render())

    def test_default_deny_without_capability_system(self):
        program = parse_source(reader_program(self.dir_str + "/note.txt"))
        analysis = analyze(program)
        for runner in (execute, execute_plan):
            with self.subTest(adapter=runner.__module__):
                with self.assertRaises(Exception) as ctx:
                    runner(program, analysis)
                self.assertEqual(ctx.exception.code, "E401")
                self.assertIn("default deny", ctx.exception.detail)

    def test_write_cannot_escape_via_relative_path(self):
        # grant on tmpdir, program writes to "../escaped.txt" -> normalized
        # path resolves outside the scope and must be denied
        src = writer_program(self.dir_str + "/../escaped.txt", "nope")
        _, err = self._run("plan", src)
        self.assertEqual(err.code, "E401")
        self.assertFalse((self.dir.parent / "escaped.txt").exists())

    def test_missing_file_is_e305_not_denial(self):
        src = reader_program(self.dir_str + "/absent.txt")
        _, err = self._run("tree", src)
        self.assertEqual(err.code, "E305")

    def test_effects_in_function_body_enforced(self):
        src = (
            "func slurp\n"
            "node 101\nop param\nindex 0\ntype string\n\n"
            "node 102\nop filesystem.read\ninput 101\noutput string\n\n"
            "node 103\nop return\ninput 102\n\n"
            "main\n\n"
            f'node 001\nop const\ntype string\nvalue "{self.dir_str}/note.txt"\n\n'
            "node 002\nop call\ncallee slurp\ninput 001\noutput string\n\n"
            "node 003\nop emit\ninput 002\n"
        )
        emits, err = self._run("plan", src)
        self.assertIsNone(err)
        self.assertEqual(emits, ["runtime decides"])


class TestEffectManifest(unittest.TestCase):
    def test_reader_manifest(self):
        program = parse_source(example("file_read.ai"))
        self.assertEqual(program_effects(program),
                         ["FILESYSTEM_READ", "PURE", "SYSTEM"])

    def test_pure_program_manifest(self):
        program = parse_source(example("arithmetic.ai"))
        self.assertEqual(program_effects(program), ["PURE", "SYSTEM"])

    def test_call_inherits_callee_effects(self):
        src = (
            "func slurp\n"
            "node 101\nop param\nindex 0\ntype string\n\n"
            "node 102\nop filesystem.read\ninput 101\noutput string\n\n"
            "node 103\nop return\ninput 102\n\n"
            "main\n\n"
            'node 001\nop const\ntype string\nvalue "x"\n\n'
            "node 002\nop call\ncallee slurp\ninput 001\noutput string\n\n"
            "node 003\nop emit\ninput 002\n"
        )
        self.assertEqual(program_effects(parse_source(src)),
                         ["FILESYSTEM_READ", "PURE", "SYSTEM"])

    def test_cli_effects_command(self):
        rc, out, _ = run_cli("effects", "examples/capability_escape.ai")
        self.assertEqual((rc, out), (0, "FILESYSTEM_READ\nPURE\nSYSTEM\n"))
        rc, out, _ = run_cli("effects", "examples/file_read.ai", "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(json.loads(out),
                         {"ok": True, "effects": ["FILESYSTEM_READ", "PURE",
                                                  "SYSTEM"]})


class TestDemoBeats(unittest.TestCase):
    """The §82 demo, exactly as a human would run it."""

    def test_beat_1_scoped_read_allowed(self):
        rc, out, _ = run_cli("run", "examples/file_read.ai",
                             "--caps", "examples/caps_demo.json")
        # note.txt ends with a newline; print adds the output line break
        self.assertEqual((rc, out),
                         (0, "The runtime decides — not the model.\n\n"))

    def test_beat_2_escape_denied_exit_4(self):
        rc, out, err = run_cli("run", "examples/capability_escape.ai",
                               "--caps", "examples/caps_demo.json")
        self.assertEqual(rc, 4)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("ERROR E401"), err)
        self.assertIn("no capability grants filesystem.read", err)

    def test_beat_3_same_program_denied_without_caps(self):
        rc, _, err = run_cli("run", "examples/file_read.ai")
        self.assertEqual(rc, 4)
        self.assertIn("default deny", err)

    def test_beat_4_expired_grant_denied_e402(self):
        expired = str(Path("examples/caps_demo_expired.json"))
        Path(expired).write_text(json.dumps({
            "subject": "agent-A91",
            "grants": [{"action": "filesystem.read",
                        "resource": "examples/incoming",
                        "expires": "2020-01-01T00:00:00Z"}],
        }), encoding="utf-8")
        self.addCleanup(lambda: Path(expired).unlink())
        rc, _, err = run_cli("run", "examples/file_read.ai", "--caps", expired)
        self.assertEqual(rc, 4)
        self.assertTrue(err.startswith("ERROR E402"), err)

    def test_beat_5_frozen_clock_admits_expired_grant(self):
        # --now freezes the authority clock: deterministic capability tests
        rc, out, _ = run_cli("run", "examples/file_read.ai",
                             "--caps", "examples/caps_demo.json",
                             "--now", "2030-01-01T00:00:00Z")
        self.assertEqual((rc, out),
                         (0, "The runtime decides — not the model.\n\n"))
        rc, _, err = run_cli("run", "examples/file_read.ai",
                             "--caps", "examples/caps_demo.json",
                             "--now", "2036-01-02T00:00:00Z")
        self.assertEqual(rc, 4)
        self.assertTrue(err.startswith("ERROR E402"), err)

    def test_malformed_caps_file_is_usage_error(self):
        rc, _, err = run_cli("run", "examples/file_read.ai", "--caps",
                             "examples/incoming/note.txt")
        self.assertEqual(rc, 3)
        self.assertIn("cannot load capability file", err)


if __name__ == "__main__":
    unittest.main()
