import unittest

from runtime import parse_source, program_hash, serialize_program
from tests.helpers import example, run_cli

CANONICAL_HELLO = example("hello.ai")

# Same semantics, different cosmetics: comments, blank lines, field order,
# and spacing are all erased by canonical serialization.
REVIEWED_HELLO = (
    "# reviewed by agent B — formatting must not change identity\n"
    "node 002\ninput 001\nop emit\n\n"
    "node 001\nvalue \"Hello, World!\"\nop const\ntype string\n"
)


class TestProgramHash(unittest.TestCase):
    def test_deterministic(self):
        program = parse_source(CANONICAL_HELLO)
        self.assertEqual(program_hash(program), program_hash(program))

    def test_insensitive_to_cosmetics(self):
        a = program_hash(parse_source(CANONICAL_HELLO))
        b = program_hash(parse_source(REVIEWED_HELLO))
        self.assertEqual(a, b)

    def test_sensitive_to_semantics(self):
        changed = CANONICAL_HELLO.replace("Hello", "Goodbye")
        self.assertNotEqual(
            program_hash(parse_source(CANONICAL_HELLO)),
            program_hash(parse_source(changed)),
        )

    def test_distinct_programs_distinct_hashes(self):
        hashes = {
            program_hash(parse_source(example(name)))
            for name in ("hello.ai", "arithmetic.ai", "branch.ai", "call.ai")
        }
        self.assertEqual(len(hashes), 4)

    def test_hash_survives_canonical_round_trip(self):
        program = parse_source(CANONICAL_HELLO)
        canonical_text = serialize_program(program)
        re_parsed = parse_source(canonical_text)
        self.assertEqual(program_hash(program), program_hash(re_parsed))

    def test_hash_format(self):
        digest = program_hash(parse_source(CANONICAL_HELLO))
        algorithm, _, hex_part = digest.partition(":")
        self.assertEqual(algorithm, "sha256")
        self.assertEqual(len(hex_part), 64)
        int(hex_part, 16)  # must be hex

    def test_cli_hash(self):
        rc, out, _ = run_cli("hash", "examples/hello.ai")
        self.assertEqual(rc, 0)
        self.assertRegex(out, r"^sha256:[0-9a-f]{64}\n$")

    def test_cli_hash_json(self):
        rc, out, _ = run_cli("hash", "examples/hello.ai", "--json")
        self.assertEqual(rc, 0)
        self.assertIn('"hash": "sha256:', out)
        self.assertIn('"ok": true', out)

    def test_cli_hash_invalid_program(self):
        rc, _, err = run_cli("hash", "tests/invalid_programs/stray_line.ai")
        self.assertEqual(rc, 1)
        self.assertTrue(err.startswith("ERROR E101"))


if __name__ == "__main__":
    unittest.main()
