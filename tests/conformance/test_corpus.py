"""Conformance corpus (hardening plan §85/H0): canonical hashes of every
example and packaged program are FROZEN. A hash change here means a
program's semantic identity changed — that is a protocol event, not a
refactor side effect."""

import json
import unittest
from pathlib import Path

from runtime import parse_source, program_hash
from tests.helpers import ROOT

CORPUS = ROOT / "protocol" / "conformance" / "corpus.json"


class TestCorpusFrozen(unittest.TestCase):
    def test_every_corpus_hash_unchanged(self):
        frozen = json.loads(CORPUS.read_text(encoding="utf-8"))["programs"]
        self.assertTrue(frozen, "corpus must not be empty")
        for rel, expected in frozen.items():
            with self.subTest(program=rel):
                source = (ROOT / rel).read_text(encoding="utf-8")
                self.assertEqual(program_hash(parse_source(source)),
                                 expected,
                                 f"{rel}: canonical hash drifted — "
                                 "semantic content changed")

    def test_corpus_covers_all_programs(self):
        """No silent additions: every shipped .ai program must be listed
        (tests/invalid_programs fixtures are intentionally excluded)."""
        frozen = set(json.loads(
            CORPUS.read_text(encoding="utf-8"))["programs"])
        on_disk = {str(p.relative_to(ROOT)).replace("\\", "/")
                   for pattern in ("examples/*.ai", "programs/*/*.ai",
                                   "programs/*/*/*.ai")
                   for p in (ROOT).glob(pattern)
                   if p.name != "package.ai"}
        self.assertEqual(on_disk - frozen, set(),
                         "unlisted programs — freeze them deliberately in "
                         "protocol/conformance/corpus.json")
        self.assertEqual(frozen - on_disk, set(),
                         "corpus lists programs that no longer exist")


if __name__ == "__main__":
    unittest.main()
