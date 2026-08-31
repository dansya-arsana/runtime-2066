import unittest

from tests.helpers import run_cli


class TestDeterminism(unittest.TestCase):
    """Repeated runs must be byte-for-byte identical (roadmap §80)."""

    def test_hello_repeated_runs_identical(self):
        results = [run_cli("run", "examples/hello.ai") for _ in range(5)]
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(results[0], (0, "Hello, World!\n", ""))

    def test_arithmetic_repeated_runs_identical(self):
        results = [run_cli("run", "examples/arithmetic.ai") for _ in range(5)]
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(results[0], (0, "50\n", ""))

    def test_json_output_deterministic(self):
        results = [run_cli("run", "examples/branch.ai", "--json") for _ in range(3)]
        self.assertEqual(len(set(results)), 1)

    def test_error_output_deterministic(self):
        results = [
            run_cli("run", "tests/invalid_programs/add_type_mismatch.ai")
            for _ in range(3)
        ]
        self.assertEqual(len(set(results)), 1)
        self.assertEqual(results[0][0], 1)


if __name__ == "__main__":
    unittest.main()
