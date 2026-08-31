"""Architecture boundaries (hardening plan §37, §87 / H2).

Dependency direction is inward only:

    apps → adapters/runtime → core

Enforced here by import analysis: the semantic core (parser, validator,
serializer, hashing, types, errors) must never import storage, network,
process, or environment machinery — those are adapter/shell concerns.
Nothing under runtime/ may import apps, examples, or tests.
"""

import ast
import unittest
from pathlib import Path

from tests.helpers import ROOT

RUNTIME_DIR = ROOT / "runtime"

# the semantic kernel (functional core): decides, never touches
CORE_MODULES = {
    "errors", "types", "parser", "serialize", "hashing", "validator",
    "airef", "packages", "ports",   # contracts (SS13): typing only
    "budget",    # resource authority: deterministic E410 limits
}

# adapter/shell modules inside the runtime package: perform effects the
# core authorized (storage, fs, identity, sessions, evidence files)
ADAPTER_MODULES = {
    "data", "memory_store", "fsops", "identity", "session",
    "netpolicy",  # transport-policy reference (spec/netpolicy.md)
    "evidence",
    "revocation",
    "keydisk", "multisig", "delegation", "pinning", "reputation",
    "proposals", "redteam", "fuzzer",
}

FORBIDDEN_IN_CORE = {
    "sqlite3",           # storage is an adapter (data.py), never core
    "urllib", "http", "socket",  # network is a host-supplied transport
    "subprocess",        # no process spawning from semantics
    "requests",
}

FORBIDDEN_EVERYWHERE_IN_RUNTIME = {
    "apps", "examples", "tests",  # the core never reaches the shell
}


def _imports_of(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            top = node.module.split(".")[0]
            if node.level and node.module:
                # relative import: runtime.X stays in-package
                found.add(node.module.split(".")[0])
            else:
                found.add(top)
    return found


class TestBoundaries(unittest.TestCase):
    def test_core_imports_nothing_effectful(self):
        for name in sorted(CORE_MODULES):
            path = RUNTIME_DIR / f"{name}.py"
            if not path.exists():
                continue
            with self.subTest(module=name):
                offenders = _imports_of(path) & FORBIDDEN_IN_CORE
                self.assertEqual(
                    offenders, set(),
                    f"runtime/{name}.py imports effectful module(s) "
                    f"{sorted(offenders)} — the semantic core must stay "
                    "pure (hardening plan §5, §37)")

    def test_runtime_never_imports_the_shell(self):
        for path in sorted(RUNTIME_DIR.glob("*.py")) + \
                sorted((RUNTIME_DIR / "cli").glob("*.py")):
            with self.subTest(module=path.name):
                offenders = _imports_of(path) & \
                    FORBIDDEN_EVERYWHERE_IN_RUNTIME
                self.assertEqual(offenders, set(),
                                 f"{path} imports application code "
                                 f"{sorted(offenders)} — dependency "
                                 "direction is inward only")

    def test_layer_map_is_complete(self):
        """Every runtime module is classified: core or adapter. A new
        module must be placed in a layer deliberately."""
        known = CORE_MODULES | ADAPTER_MODULES | {
            "__init__", "__main__",  # package shims
            "ops", "interpreter", "plan_vm", "export",
            "repair", "capabilities",
            # release-engineering tooling (SS26/SS28/SS60): sbom,
            # signed releases, backup — shell-side, import core inward
            "sbom", "release", "backup", "bundle",
            # app shell shipped INSIDE the package so pip installs get
            # the 2066-mcp entry point with bundled tool programs
            # (runtime/programs/); imports inward only. Documented
            # exception in docs/architecture/BOUNDARIES.md.
            "mcp_server",
        }
        # ops/interpreter/plan_vm/export/repair/capabilities: the
        # execution layer — dispatch semantics against adapters
        actual = {p.stem for p in RUNTIME_DIR.glob("*.py")}
        self.assertEqual(actual - known, set(),
                         f"unclassified runtime modules: "
                         f"{sorted(actual - known)} — classify in "
                         "tests/architecture/test_boundaries.py")


if __name__ == "__main__":
    unittest.main()


class TestBundledProgramsStayInSync(unittest.TestCase):
    """runtime/programs/ carries copies so `pip install runtime-2066`
    ships working MCP tools. Copies must never drift from the canonical
    programs — same basename, byte-identical content."""

    def test_bundled_copies_match_canonical(self):
        canonical = {"hello": ROOT / "examples" / "hello.ai",
                     "calculator": ROOT / "examples" / "calculator.ai"}
        for name, source in canonical.items():
            bundled = ROOT / "runtime" / "programs" / f"{name}.ai"
            if bundled.exists():
                with self.subTest(program=name):
                    self.assertEqual(
                        bundled.read_bytes(), source.read_bytes(),
                        f"runtime/programs/{name}.ai drifted from "
                        f"{source} — regenerate the bundle")
        notes = ROOT / "examples" / "notes_app"
        for bundled in (ROOT / "runtime" / "programs").glob("*.ai"):
            origin = notes / bundled.name
            if origin.exists():
                with self.subTest(program=bundled.name):
                    self.assertEqual(bundled.read_bytes(),
                                     origin.read_bytes(),
                                     f"{bundled.name} drifted from the "
                                     "notes app — regenerate the bundle")
