"""Release engineering (plan SS26 + SS28): SBOM and signed releases.

- SBOM: valid SPDX 2.3, deterministic under a fixed clock, names the
  runtime + cryptography + interpreter.
- Release: hashes the live tree, signs it (ed25519 envelope);
  verify-release matches the same tree, and REFUSES on any drift or a
  different signer.
"""

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from runtime import __version__
from runtime.identity import generate_identity
from runtime.release import build_release, sign_release, verify_release
from runtime.sbom import build_sbom, render_sbom
from tests.helpers import ROOT


class TestSbom(unittest.TestCase):
    def test_spdx_shape_and_determinism(self):
        from datetime import datetime, timezone
        now = datetime(2026, 8, 31, tzinfo=timezone.utc)
        first = build_sbom(now=now)
        second = build_sbom(now=now)
        self.assertEqual(render_sbom(first), render_sbom(second))
        self.assertEqual(first["spdxVersion"], "SPDX-2.3")
        names = {p["name"] for p in first["packages"]}
        self.assertIn("runtime-2066", names)
        self.assertIn("cryptography", names)
        runtime_pkg = next(p for p in first["packages"]
                           if p["name"] == "runtime-2066")
        self.assertEqual(runtime_pkg["versionInfo"], __version__)
        self.assertIn("packageVerificationCode",
                      runtime_pkg)  # content-hashable


class TestRelease(unittest.TestCase):
    def setUp(self):
        self.ident, self.secret = generate_identity("release-authority")
        import shutil
        # verify against a frozen COPY of the tree so mutations in the
        # test cannot touch the real repository
        self.tree = Path(tempfile.mkdtemp()) / "tree"
        self.tree.mkdir()
        shutil.copytree(ROOT / "runtime", self.tree / "runtime",
                        ignore=shutil.ignore_patterns("__pycache__"))
        (self.tree / "protocol" / "conformance").mkdir(parents=True)
        shutil.copyfile(
            ROOT / "protocol" / "conformance" / "corpus.json",
            self.tree / "protocol" / "conformance" / "corpus.json")
        shutil.copytree(ROOT / "spec", self.tree / "spec")

    def test_sign_and_verify_round_trip_against_tree(self):
        from datetime import datetime, timezone
        payload = build_release(
            now=datetime(2026, 8, 31, tzinfo=timezone.utc),
            tree=self.tree)
        envelope = sign_release(payload, self.ident, self.secret)
        result = verify_release(envelope, self.ident.public_key,
                                tree=self.tree)
        self.assertTrue(result["problems"] == [])
        self.assertTrue(result["ok"])
        self.assertEqual(result["runtime_version"], __version__)

    def test_any_drift_refuses(self):
        from datetime import datetime, timezone
        payload = build_release(
            now=datetime(2026, 8, 31, tzinfo=timezone.utc),
            tree=self.tree)
        envelope = sign_release(payload, self.ident, self.secret)
        victim = self.tree / "runtime" / "ops.py"
        victim.write_text(victim.read_text(encoding="utf-8") + "\n# x\n",
                          encoding="utf-8")
        result = verify_release(envelope, self.ident.public_key,
                                tree=self.tree)
        self.assertFalse(result["ok"])
        self.assertTrue(any("drifted: runtime/ops.py" in p
                            for p in result["problems"]))

    def test_wrong_signer_refuses(self):
        from datetime import datetime, timezone
        payload = build_release(
            now=datetime(2026, 8, 31, tzinfo=timezone.utc),
            tree=self.tree)
        envelope = sign_release(payload, self.ident, self.secret)
        other, _ = generate_identity("someone-else")
        result = verify_release(envelope, other.public_key,
                                tree=self.tree)
        self.assertFalse(result["ok"])

    def test_cli_end_to_end(self):
        from tests.helpers import run_cli
        with tempfile.TemporaryDirectory() as tmp:
            ident = Path(tmp) / "id.json"
            key = Path(tmp) / "key.json"
            release = Path(tmp) / "release.json"
            code, out, _ = run_cli("keygen", str(ident), "--id",
                                   "release-authority")
            self.assertEqual(code, 0, out)
            # keygen writes the secret as <stem>.key beside the identity
            key_file = ident.with_suffix(".key")
            self.assertTrue(key_file.exists(),
                            f"keygen produced "
                            f"{list(Path(tmp).iterdir())}")
            code, out, err = run_cli(
                "release", "--out", str(release), "--agent", str(ident),
                "--key", str(key_file))
            self.assertEqual(code, 0, err)
            code, out, err = run_cli(
                "verify-release", str(release), "--agent", str(ident))
            self.assertEqual(code, 0, err)
            self.assertIn("OK: tree matches signed release", out)


if __name__ == "__main__":
    unittest.main()
