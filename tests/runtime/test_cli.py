import unittest

from tests.helpers import run_cli


class TestCLI(unittest.TestCase):
    def test_run_hello(self):
        self.assertEqual(run_cli("run", "examples/hello.ai"), (0, "Hello, World!\n", ""))

    def test_run_arithmetic(self):
        rc, out, _ = run_cli("run", "examples/arithmetic.ai")
        self.assertEqual((rc, out), (0, "50\n"))

    def test_run_branch(self):
        rc, out, _ = run_cli("run", "examples/branch.ai")
        self.assertEqual((rc, out), (0, "greater\n"))

    def test_run_json_mode(self):
        rc, out, _ = run_cli("run", "examples/hello.ai", "--json")
        self.assertEqual(rc, 0)
        self.assertEqual(out, '{"emits": ["Hello, World!"], "ok": true}\n')

    def test_validate_ok(self):
        self.assertEqual(run_cli("validate", "examples/arithmetic.ai"), (0, "OK\n", ""))

    def test_validation_error_goes_to_stderr_with_exit_code_1(self):
        rc, out, err = run_cli("run", "tests/invalid_programs/add_type_mismatch.ai")
        self.assertEqual(rc, 1)
        self.assertEqual(out, "")
        self.assertTrue(err.startswith("ERROR E203\n"), err)
        self.assertIn("allowed_repairs:", err)

    def test_runtime_error_gives_exit_code_2(self):
        rc, out, err = run_cli("run", "tests/runtime/fixtures/div_zero.ai")
        self.assertEqual((rc, out), (2, ""))
        self.assertTrue(err.startswith("ERROR E301\n"), err)

    def test_missing_file_gives_exit_code_3(self):
        rc, _, err = run_cli("run", "examples/does_not_exist.ai")
        self.assertEqual(rc, 3)
        self.assertIn("cannot read", err)

    def test_bad_usage_gives_exit_code_3(self):
        self.assertEqual(run_cli("frobnicate")[0], 3)
        self.assertEqual(run_cli()[0], 3)


if __name__ == "__main__":
    unittest.main()
