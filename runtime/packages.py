"""Semantic packages (hardening plan §9–§10, §88 / H3).

Programs are addressed semantically — ``package::module::unit`` — not by
filesystem location: "the filesystem path is only storage; the canonical
semantic name is identity". A package is a directory containing a
``package.ai`` manifest (package name, version, declared modules); a
module is a subdirectory; a unit is one ``.ai`` program.

Packaging never touches program content: a unit's hash is the ordinary
canonical program hash, so moving or renaming storage cannot change a
program's identity.

The manifest grammar (normative: spec/packages.md):

    package <name>
    version <semver>            # optional
    module <name>               # repeatable, order preserved

Every module directory must be declared and every declared module must
exist — the manifest is authoritative, fail closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .errors import StructuredError
from .hashing import program_hash
from .ops import const_value
from .parser import Program, parse_source
from .validator import Analysis, analyze, program_effects

# op -> capability action required at runtime (None = no capability)
_CAPABILITY_OF_OP = {
    "data.count": "data.read", "data.select": "data.read",
    "data.list": "data.read",
    "data.insert": "data.write", "data.update": "data.write",
    "data.delete": "data.delete",
    "filesystem.read": "filesystem.read",
    "filesystem.write": "filesystem.write",
    "session.verify": "session",
    "net.fetch": "net.request",
}


def _identifier(value: str, what: str) -> str:
    if not value.isidentifier():
        raise ValueError(f"{what} must be an identifier, received {value!r}")
    return value


def load_manifest(path: Path) -> "Package":
    """Parse and validate ``package.ai``. Strict: unknown fields,
    undeclared module directories, and missing declarations all fail."""
    name: str | None = None
    version = "0.0.0"
    modules: list[str] = []
    for lineno, raw in enumerate(
            path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        head, _, rest = line.partition(" ")
        rest = rest.strip()
        if head == "package" and rest:
            name = _identifier(rest, "package name")
        elif head == "version" and rest:
            version = rest
        elif head == "module" and rest:
            modules.append(_identifier(rest, "module name"))
        else:
            raise ValueError(
                f"package manifest {path}: bad line {lineno}: "
                f"{line!r} (allowed: package/version/module)")
    if name is None:
        raise ValueError(f"package manifest {path}: missing 'package <name>'")
    if not modules:
        raise ValueError(f"package manifest {path}: no modules declared")

    root = path.parent
    declared = set(modules)
    for child in sorted(root.iterdir()):
        if child.is_dir() and any(child.glob("*.ai")) \
                and child.name not in declared:
            raise ValueError(
                f"package {name!r}: module directory {child.name!r} "
                f"contains programs but is not declared in package.ai")
    for module in modules:
        if not (root / module).is_dir() or not any((root / module).glob("*.ai")):
            raise ValueError(
                f"package {name!r}: declared module {module!r} has no "
                f"programs under {root / module}")
    return Package(name=name, version=version, root=root,
                   modules={m: sorted(p.stem for p in (root / m).glob("*.ai"))
                            for m in modules})


@dataclass(frozen=True)
class Package:
    name: str
    version: str
    root: Path
    modules: dict[str, list[str]]  # module name -> unit names


@dataclass(frozen=True)
class Unit:
    address: str
    path: Path
    program: Program
    analysis: Analysis

    @property
    def hash(self) -> str:
        return program_hash(self.program)

    @property
    def node_count(self) -> int:
        total = len(self.program.nodes)
        for function in self.program.functions.values():
            total += len(function.nodes)
        return total

    @property
    def input_count(self) -> int:
        """stdin parameters: system.read nodes in main execution order."""
        order = self.analysis.scopes["main"].order
        return sum(1 for node_id in order
                   if self.program.nodes[node_id].field("op") == "system.read")

    @property
    def emit_count(self) -> int:
        return sum(1 for node in self.program.nodes.values()
                   if node.field("op") == "emit")

    @property
    def writes_stdout(self) -> bool:
        return any(node.field("op") == "system.write"
                   for node in self.program.nodes.values())

    @property
    def effects(self) -> list[str]:
        return program_effects(self.program, self.analysis)

    @property
    def entities(self) -> list[str]:
        return sorted(self.program.entities)

    def capabilities(self) -> list[str]:
        """Statically required authority: action[:scope] per effectful op.

        Data scopes are entity names; net scopes are hostnames when the
        fetched URL is a constant (dynamic URLs resolve at runtime).
        """
        caps: set[str] = set()
        for nodes in self._scopes():
            for node in nodes.values():
                op = node.field("op")
                action = _CAPABILITY_OF_OP.get(op)
                if action is None:
                    continue
                if action == "session":
                    caps.add("session verifier (host-attached)")
                    continue
                if op.startswith("data."):
                    caps.add(f"{action}:{node.field('entity')}")
                elif op == "net.fetch":
                    host = self._const_hostname(nodes, node)
                    caps.add(f"net.request:{host}" if host
                             else "net.request:<runtime url>")
                else:
                    caps.add(action)
        return sorted(caps)

    def dependencies(self) -> dict:
        """What the unit needs beyond its own graph: entities, a session
        verifier, and any constant egress hostnames."""
        hosts: set[str] = set()
        session = False
        for nodes in self._scopes():
            for node in nodes.values():
                op = node.field("op")
                if op == "session.verify":
                    session = True
                if op == "net.fetch":
                    host = self._const_hostname(nodes, node)
                    if host:
                        hosts.add(host)
        return {"entities": self.entities, "session": session,
                "hosts": sorted(hosts)}

    def _scopes(self) -> list[dict]:
        scopes = [self.program.nodes]
        scopes.extend(f.nodes for f in self.program.functions.values())
        return scopes

    @staticmethod
    def _const_hostname(nodes: dict, node) -> str | None:
        """Hostname of a net.fetch whose URL is a constant, if static."""
        if not node.inputs:
            return None
        producer = nodes.get(node.inputs[0][0])
        if producer is not None and producer.field("op") == "const" \
                and producer.field("type") == "string":
            url = const_value("string", producer.field("value"))
            return _hostname_of(url)
        return None


def _hostname_of(url: str) -> str | None:
    """Minimal scheme://host[:port]/path host extraction — kept local so
    the core imports no network machinery (boundaries test enforces)."""
    parts = url.split("://", 1)
    if len(parts) != 2:
        return None  # not a URL: net.fetch would deny it at runtime
    host = parts[1].split("/", 1)[0]
    if not host or "@" in host:
        if "@" in host:
            host = host.rsplit("@", 1)[1]
    return host.split(":", 1)[0].lower() or None


class PackageStore:
    """Loads semantic packages from a root directory (default:
    ``<repo>/programs``). Units are parsed and analyzed once, cached by
    semantic address."""

    def __init__(self, root: Path | str):
        self.root = Path(root)
        self._packages: dict[str, Package] | None = None
        self._units: dict[str, Unit] = {}

    def packages(self) -> dict[str, Package]:
        if self._packages is None:
            found: dict[str, Package] = {}
            if self.root.is_dir():
                for child in sorted(self.root.iterdir()):
                    manifest = child / "package.ai"
                    if child.is_dir() and manifest.exists():
                        package = load_manifest(manifest)
                        found[package.name] = package
            self._packages = found
        return self._packages

    def addresses(self) -> list[str]:
        return [f"{p.name}::{m}::{u}"
                for p in self.packages().values()
                for m, units in p.modules.items()
                for u in units]

    def unit(self, address: str) -> Unit:
        parts = address.split("::")
        if len(parts) != 3 or not all(parts):
            raise ValueError(
                "semantic addresses are package::module::unit "
                f"(e.g. sales::business::add), received {address!r}")
        pkg_name, module, unit_name = parts
        # identifiers only — addresses must never traverse paths
        for part in parts:
            _identifier(part, "address part")
        package = self.packages().get(pkg_name)
        if package is None:
            known = ", ".join(sorted(self.packages())) or "none installed"
            raise ValueError(f"unknown package {pkg_name!r} (have: {known})")
        if module not in package.modules:
            raise ValueError(
                f"package {pkg_name!r} has no module {module!r} "
                f"(declared: {', '.join(package.modules)})")
        if unit_name not in package.modules[module]:
            raise ValueError(
                f"unknown unit {unit_name!r} in {pkg_name}::{module} "
                f"(have: {', '.join(package.modules[module])})")
        if address not in self._units:
            path = package.root / module / f"{unit_name}.ai"
            try:
                program = parse_source(
                    path.read_text(encoding="utf-8"))
            except OSError as exc:
                raise ValueError(f"cannot read unit {address}: {exc}") from exc
            except StructuredError as exc:
                raise ValueError(
                    f"unit {address} does not validate: "
                    f"[{exc.code}] {exc.detail}") from exc
            self._units[address] = Unit(
                address=address, path=path, program=program,
                analysis=analyze(program))
        return self._units[address]


def default_store_root() -> Path:
    """Repository programs/ directory (works from source checkout and
    from the Docker image; empty when installed as a bare wheel)."""
    return Path(__file__).resolve().parents[1] / "programs"
