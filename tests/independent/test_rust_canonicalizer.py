"""Independent-runtime conformance (plan SS35, H8 spike).

The Rust canonicalizer (rust-canonicalizer/, zero dependencies, written
from spec/canonicalization.md sharing no code with Python) must produce
the SAME canonical hash as this runtime for every frozen corpus
program. When this passes across a full corpus, 2066 is a protocol,
not merely a codebase.

Skipped when cargo is unavailable (the Python runtime remains the
oracle; CI for the second runtime is future H8 work).
"""

import shutil
import subprocess
import unittest

from runtime import parse_source, program_hash
from tests.helpers import ROOT

CARGO = shutil.which("cargo")
CRATE = ROOT / "rust-canonicalizer"
BIN = CRATE / "target" / "release" / "canonicalize.exe"


@unittest.skipUnless(CARGO and CRATE.exists(), "cargo unavailable")
class TestRustCanonicalizer(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        subprocess.run(["cargo", "build", "--release", "--quiet"],
                       cwd=str(CRATE), check=True, timeout=600,
                       capture_output=True)

    def test_entire_frozen_corpus_hashes_identically(self):
        import json
        corpus = json.loads(
            (ROOT / "protocol" / "conformance" / "corpus.json")
            .read_text(encoding="utf-8"))["programs"]
        self.assertGreater(len(corpus), 20)
        for rel in sorted(corpus):
            with self.subTest(program=rel):
                rust = subprocess.run(
                    [str(BIN), str(ROOT / rel)],
                    capture_output=True, text=True, timeout=60)
                self.assertEqual(rust.returncode, 0, rust.stderr)
                python = program_hash(parse_source(
                    (ROOT / rel).read_text(encoding="utf-8")))
                self.assertEqual(rust.stdout.strip(), python,
                                 "independent runtime disagrees on "
                                 "canonical identity")


if __name__ == "__main__":
    unittest.main()
