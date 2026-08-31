"""Docs-for-AI are compiled artifacts, not prose: the committed reference
snapshot and the agent manual must stay in lockstep with the live runtime.
If an operation or error code is added without updating docs/ai/, these
tests fail."""

import json
import unittest
from pathlib import Path

from runtime import __version__
from runtime.airef import ai_reference
from runtime.validator import EFFECT_OF, _OPS

ROOT = Path(__file__).resolve().parents[2]
SNAPSHOT = ROOT / "docs" / "ai" / "reference.json"
MANUAL = (ROOT / "docs" / "ai" / "AGENT_MANUAL.md").read_text(encoding="utf-8")


class TestAiReference(unittest.TestCase):
    def test_snapshot_matches_live_runtime(self):
        snapshot = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(snapshot, ai_reference(__version__),
                         "docs/ai/reference.json is stale — regenerate with: "
                         "python -m runtime reference > docs/ai/reference.json")

    def test_reference_covers_every_validator_op(self):
        reference = ai_reference(__version__)
        self.assertEqual(set(reference["ops"]), set(_OPS))
        for name, entry in reference["ops"].items():
            self.assertEqual(entry["effect"], EFFECT_OF[name],
                             f"{name}: effect mismatch")

    def test_reference_reports_current_version(self):
        reference = ai_reference(__version__)
        self.assertEqual(reference["version"], __version__)


class TestAgentManual(unittest.TestCase):
    def test_manual_documents_every_operation(self):
        for op_name in _OPS:
            self.assertIn(f"`{op_name}`", MANUAL,
                          f"AGENT_MANUAL.md does not document op {op_name!r}")

    def test_manual_documents_every_error_code(self):
        reference = ai_reference(__version__)
        for code in reference["error_codes"]:
            self.assertIn(code, MANUAL,
                          f"AGENT_MANUAL.md does not document error {code}")

    def test_manual_documents_authority_rules(self):
        for required in ("default deny", "Never fabricate grant files",
                         "allowed_repairs", "--caps", "--db"):
            self.assertIn(required, MANUAL)

    def test_snapshot_is_loadable_json(self):
        parsed = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
        self.assertEqual(parsed["language"], "2066")


if __name__ == "__main__":
    unittest.main()
