"""Interpreter adapter: direct tree-walking execution of the semantic graph.

One of two execution adapters (Appendix F.3); the other is the compiled-plan
stack VM (runtime/plan_vm.py). Both share operation semantics through
runtime/ops.py and consume the same validator Analysis, so they are
equivalent by construction and verified by tests.
"""

from __future__ import annotations

from datetime import datetime
from urllib.parse import urlparse

from . import fsops, ops
from .capabilities import GrantSet
from .data import DataPlane
from .errors import StructuredError
from .parser import Node, Program
from .session import SessionVerifier
from .types import format_value
from .validator import Analysis, analyze


def execute(program: Program, analysis: Analysis | None = None, *,
            grants: GrantSet | None = None, now: datetime | None = None,
            db: DataPlane | None = None,
            sessions: SessionVerifier | None = None,
            revocations=None, net=None) -> list[object]:
    """Evaluate the graph; return emit values ordered by numeric node id.

    `grants` carries the runtime-held capability set, `db` the semantic
    data plane, `sessions` the session-token verifier, and `net` the
    host-supplied outbound transport; None (the default) denies every
    effectful operation.
    """
    if analysis is None:
        analysis = analyze(program)
    machine = _Machine(program, analysis, grants, now, db, sessions,
                       revocations, net)
    return machine.run()


def run_to_text(program: Program, analysis: Analysis | None = None) -> list[str]:
    """Execute and render each emitted value in its canonical form."""
    return [format_value(v) for v in execute(program, analysis)]


class _Machine:
    def __init__(self, program: Program, analysis: Analysis,
                 grants: GrantSet | None, now: datetime | None,
                 db: DataPlane | None, sessions: SessionVerifier | None,
                 revocations=None, net=None):
        self.revocations = revocations
        self.net = net
        self.program = program
        self.analysis = analysis
        self.grants = grants
        self.now = now
        self.db = db
        self.sessions = sessions

    def run(self) -> list[object]:
        main = self.program.nodes
        values: dict[str, object] = {}
        for node_id in self.analysis.scopes["main"].order:
            node = main[node_id]
            op = node.field("op")
            inputs = [values[ref] for ref, _ in node.inputs]
            if op in ("data.insert", "data.update", "data.delete")                     and node.has("when"):
                # guarded effect: guard value rides in as the last input
                inputs.append(values[node.field("when")])
            if op == "call":
                values[node_id] = self._call(node, inputs)
            else:
                values[node_id] = self._eval(node, op, inputs)

        emit_nodes = sorted(
            (n for n in main.values() if n.field("op") == "emit"),
            key=lambda n: int(n.id),
        )
        return [values[n.id] for n in emit_nodes]

    def _eval(self, node: Node, op: str, ins: list[object]) -> object:
        if op == "filesystem.read":
            return fsops.read_file(self.grants, node.id, ins[0], self.now)
        if op == "filesystem.write":
            return fsops.write_file(self.grants, node.id, ins[0], ins[1], self.now)
        if op == "system.read":
            return fsops.read_line(node.id)
        if op == "system.write":
            return fsops.write_str(node.id, ins[0])
        if op == "concat":
            return ops.concat(ins[0], ins[1])
        if op == "crypto.digest":
            return ops.digest(node.field("algorithm"), ins[0])
        if op == "session.verify":
            if self.sessions is None:
                raise StructuredError(
                    code="E401", node=node.id, operation=op,
                    detail="denied: no session verifier attached; "
                           "session tokens require --session-key (default deny)",
                )
            return self.sessions.verify(node.id, ins[0], self.now)
        if op == "data.insert":
            if node.has("when") and ins[-1] is False:
                return 0  # guarded write denied: no row, no effect
            args = ins[:-1] if node.has("when") else ins
            return self.db.insert(node.id, node.field("entity"), args) \
                if self.db else _no_db(node.id, op)
        if op == "data.count":
            return self.db.count(node.id, node.field("entity"),
                                 node.field("where"), ins[0]) \
                if self.db else _no_db(node.id, op)
        if op == "data.select":
            return self.db.select(node.id, node.field("entity"),
                                  node.field("column"), node.field("where"),
                                  ins[0]) \
                if self.db else _no_db(node.id, op)
        if op == "data.update":
            if node.has("when") and ins[-1] is False:
                return 0  # guarded write denied: zero rows touched
            return self.db.update(node.id, node.field("entity"),
                                  node.field("set"), ins[0],
                                  node.field("where"), ins[1]) \
                if self.db else _no_db(node.id, op)
        if op == "data.delete":
            if node.has("when") and ins[-1] is False:
                return 0  # guarded delete denied: zero rows touched
            return self.db.delete(node.id, node.field("entity"),
                                  node.field("where"), ins[0]) \
                if self.db else _no_db(node.id, op)
        if op == "net.fetch":
            return self._net_fetch(node, ins[0])
        if op == "data.list":
            limit = int(node.field("limit")) if node.has("limit") else None
            return self.db.list_rows(node.id, node.field("entity"),
                                     node.field("column"),
                                     node.field("where"), ins[0],
                                     limit=limit) \
                if self.db else _no_db(node.id, op)
        if op == "list.length":
            return ops.list_length(ins[0])
        if op == "list.get":
            return ops.list_get(node.id, ins[0], ins[1])
        if op == "list.join":
            return ops.list_join(ins[0], ins[1])
        return _eval_node(node, op, ins)

    def _net_fetch(self, node: Node, url: str) -> str:
        """Outbound GET, capability-gated by hostname (egress allowlist).

        The runtime owns no sockets: the HOST supplies the transport
        callable, so tests inject fakes and the graph stays hermetic.
        """
        if self.net is None:
            raise StructuredError(
                code="E401", node=node.id, operation="net.fetch",
                detail="denied: no network attached; net.fetch requires "
                       "the host to supply a transport (default deny)")
        host = urlparse(url).hostname or ""
        if not host:
            raise StructuredError(
                code="E203", node=node.id, operation="net.fetch",
                detail=f"cannot parse host from url {url!r}")
        self.grants.check("net.request", host.lower(), self.now,
                          node=node.id)
        try:
            body = self.net(url)
        except Exception as exc:
            raise StructuredError(
                code="E560", node=node.id, operation="net.fetch",
                detail=f"request to {host} failed: "
                       f"{exc.__class__.__name__}: {exc}") from exc
        return body if isinstance(body, str) else str(body)

    def _call(self, node: Node, args: list[object]) -> object:
        function = self.program.functions[node.field("callee")]
        scope = self.analysis.scopes[function.name]
        params = sorted(
            (n for n in function.nodes.values() if n.field("op") == "param"),
            key=lambda n: int(n.field("index")),
        )
        values: dict[str, object] = {}
        for param, arg in zip(params, args):
            values[param.id] = arg
        return_node: Node | None = None
        for node_id in scope.order:
            if node_id in values:  # param, already bound
                continue
            inner = function.nodes[node_id]
            op = inner.field("op")
            inputs = [values[ref] for ref, _ in inner.inputs]
            if op in ("data.insert", "data.update", "data.delete")                     and inner.has("when"):
                # guarded effect: guard value rides in as the last input
                inputs.append(values[inner.field("when")])
            if op == "call":
                values[node_id] = self._call(inner, inputs)
            else:
                values[node_id] = self._eval(inner, op, inputs)
            if op == "return":
                return_node = inner
        assert return_node is not None  # validator guarantees exactly one
        return values[return_node.id]


def _no_db(node_id: str, op: str) -> object:
    raise StructuredError(
        code="E401", node=node_id, operation=op,
        detail="denied: no database attached; data effects require --db "
               "(default deny)",
    )


def _eval_node(node: Node, op: str, ins: list[object]) -> object:
    if op == "const":
        return ops.const_value(node.field("type"), node.field("value"))
    if op == "copy":
        return ins[0]
    if op in ("add", "subtract", "multiply", "divide"):
        return ops.arith(node.id, op, ins[0], ins[1])
    if op == "compare":
        return ops.compare(node.field("mode"), ins[0], ins[1])
    if op == "branch":
        return ops.select(ins[0], ins[1], ins[2])
    if op == "cast":
        return ops.cast_value(node.id, ins[0], node.field("output"))
    if op in ("emit", "return"):
        return ins[0]
    raise AssertionError(f"unhandled op {op!r}")  # pragma: no cover
