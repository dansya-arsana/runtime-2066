"""Plan-VM adapter: compile the validated graph to a linear plan, execute it
on a stack machine.

The second execution adapter (master roadmap Appendix F.3). Compilation
consumes the same validator Analysis as the tree-walking interpreter and
both dispatch operation semantics through runtime/ops.py, so they are
equivalent by construction — and the equivalence is proven by tests over
the full example corpus. The plan form is also the natural stepping stone
to the §10 later stages (optimizer / JIT / export backends) and to a
WASI-backed executor, because it is a linear, serializable artifact.

Instruction model (per scope; slots are SSA-like locals):

    LOAD i               push slot i
    CONST v              push literal value
    ADD SUB MUL DIV      pop b, a; push a<op>b (error attribution: node)
    CMP mode             pop b, a; push bool
    SELECT               pop f, t, cond; push t if cond else f
    CAST target          pop v; push converted value (E303/E304)
    CALL (name, argc)    pop argc args; execute function plan; push result
    EMIT                 pop v; record program output
    RETURN               pop v; return from function plan
Every value-producing instruction writes its result to slot `out`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from . import fsops, ops
from .capabilities import GrantSet
from .data import DataPlane
from .errors import StructuredError
from .parser import Node, Program
from .session import SessionVerifier
from .validator import Analysis, analyze


@dataclass(frozen=True)
class Instr:
    op: str
    arg: object = None
    node: str | None = None  # source node id, for structured error attribution
    out: int | None = None   # destination slot


@dataclass(frozen=True)
class ScopePlan:
    instrs: tuple[Instr, ...]
    slot_count: int


@dataclass
class Plan:
    main: ScopePlan
    functions: dict[str, ScopePlan]


_OP_INSTR = {"add": "ADD", "subtract": "SUB", "multiply": "MUL", "divide": "DIV"}


def compile_plan(program: Program, analysis: Analysis | None = None) -> Plan:
    """Deterministically lower the validated graph to linear plans."""
    if analysis is None:
        analysis = analyze(program)
    functions = {
        name: _compile_scope(name, program.functions[name].nodes, analysis)
        for name in analysis.call_order
    }
    return Plan(main=_compile_scope("main", program.nodes, analysis),
                functions=functions)


def execute_plan(program: Program, analysis: Analysis | None = None, *,
                 grants: GrantSet | None = None, now: datetime | None = None,
                 db: DataPlane | None = None,
                 sessions: SessionVerifier | None = None,
                 net=None) -> list[object]:
    """Adapter entry point: same contract as interpreter.execute."""
    plan = compile_plan(program, analysis)
    vm = _VM(plan, grants, now, db, sessions, net)
    vm.exec(plan.main, [])
    return vm.emits


def _compile_scope(
    scope_name: str, nodes: dict[str, Node], analysis: Analysis,
) -> tuple[Instr, ...]:
    scope = analysis.scopes[scope_name]

    slot: dict[str, int] = {}
    if scope_name != "main":
        params = sorted(
            (n for n in nodes.values() if n.field("op") == "param"),
            key=lambda n: int(n.field("index")),
        )
        for index, param in enumerate(params):
            slot[param.id] = index

    next_slot = len(slot)
    for node_id in scope.order:
        op = nodes[node_id].field("op")
        if op in ("emit", "return", "param"):
            continue  # no slot needed
        slot[node_id] = next_slot
        next_slot += 1

    instrs: list[Instr] = []
    for node_id in scope.order:
        node = nodes[node_id]
        op = node.field("op")
        for ref, _ in node.inputs:
            instrs.append(Instr("LOAD", slot[ref], node=node_id))
        if op in ("data.insert", "data.update", "data.delete")                 and node.has("when"):
            instrs.append(Instr("LOAD", slot[node.field("when")],
                                node=node_id))

        if op == "const":
            instrs.append(Instr(
                "CONST", ops.const_value(node.field("type"), node.field("value")),
                node=node_id, out=slot[node_id]))
        elif op in _OP_INSTR:
            instrs.append(Instr(_OP_INSTR[op], node=node_id, out=slot[node_id]))
        elif op == "compare":
            instrs.append(Instr("CMP", node.field("mode"), node=node_id,
                                out=slot[node_id]))
        elif op == "branch":
            instrs.append(Instr("SELECT", node=node_id, out=slot[node_id]))
        elif op == "cast":
            instrs.append(Instr("CAST", node.field("output"), node=node_id,
                                out=slot[node_id]))
        elif op == "call":
            instrs.append(Instr("CALL", (node.field("callee"), len(node.inputs)),
                                node=node_id, out=slot[node_id]))
        elif op == "filesystem.read":
            instrs.append(Instr("READ", node=node_id, out=slot[node_id]))
        elif op == "filesystem.write":
            instrs.append(Instr("WRITE", node=node_id, out=slot[node_id]))
        elif op == "system.read":
            instrs.append(Instr("STDIN", node=node_id, out=slot[node_id]))
        elif op == "net.fetch":
            instrs.append(Instr("NETFETCH", node=node_id, out=slot[node_id]))
        elif op == "system.write":
            instrs.append(Instr("STDOUT", node=node_id, out=slot[node_id]))
        elif op == "concat":
            instrs.append(Instr("CONCAT", node=node_id, out=slot[node_id]))
        elif op == "crypto.digest":
            instrs.append(Instr("DIGEST", node.field("algorithm"),
                                node=node_id, out=slot[node_id]))
        elif op == "session.verify":
            instrs.append(Instr("SESSION", node=node_id, out=slot[node_id]))
        elif op == "data.list":
            fields = {k: node.field(k)
                      for k in ("entity", "column", "where", "limit")
                      if node.has(k)}
            instrs.append(Instr("DATALIST", fields, node=node_id,
                                out=slot[node_id]))
        elif op == "list.length":
            instrs.append(Instr("LLEN", node=node_id, out=slot[node_id]))
        elif op == "list.get":
            instrs.append(Instr("LGET", node=node_id, out=slot[node_id]))
        elif op == "list.join":
            instrs.append(Instr("LJOIN", node=node_id, out=slot[node_id]))
        elif op in ("data.insert", "data.count", "data.select", "data.update",
                    "data.delete"):
            fields = {k: node.field(k) for k in
                      ("entity", "column", "set", "where") if node.has(k)}
            if node.has("when"):
                fields["_when"] = True
            fields["_argc"] = len(node.inputs)
            instrs.append(Instr("DATA", (op, fields), node=node_id,
                                out=slot[node_id]))
        elif op == "copy":
            instrs.append(Instr("STORE", node=node_id, out=slot[node_id]))
        elif op == "emit":
            instrs.append(Instr("EMIT", node=node_id))
        elif op == "return":
            instrs.append(Instr("RETURN", node=node_id))
        # param: pre-bound into its slot by the caller

    return ScopePlan(tuple(instrs), next_slot)


class _VM:
    def __init__(self, plan: Plan, grants: GrantSet | None,
                 now: datetime | None, db: DataPlane | None,
                 sessions: SessionVerifier | None, net=None):
        self.plan = plan
        self.grants = grants
        self.now = now
        self.db = db
        self.sessions = sessions
        self.net = net
        self.emits: list[object] = []

    def exec(self, scope: ScopePlan, args: list[object]) -> object | None:
        slots: list[object] = list(args) + [None] * (scope.slot_count - len(args))
        stack: list[object] = []
        for ins in scope.instrs:
            op = ins.op
            if op == "LOAD":
                stack.append(slots[ins.arg])
            elif op == "CONST":
                slots[ins.out] = ins.arg
            elif op in ("ADD", "SUB", "MUL", "DIV"):
                b = stack.pop()
                a = stack.pop()
                slots[ins.out] = ops.arith(
                    ins.node, _OP_INSTR_REV[op], a, b)
            elif op == "CMP":
                b = stack.pop()
                a = stack.pop()
                slots[ins.out] = ops.compare(ins.arg, a, b)
            elif op == "SELECT":
                if_false = stack.pop()
                if_true = stack.pop()
                condition = stack.pop()
                slots[ins.out] = ops.select(condition, if_true, if_false)
            elif op == "CAST":
                slots[ins.out] = ops.cast_value(ins.node, stack.pop(), ins.arg)
            elif op == "STORE":
                slots[ins.out] = stack.pop()
            elif op == "CALL":
                name, argc = ins.arg
                call_args = stack[len(stack) - argc:] if argc else []
                if argc:
                    del stack[len(stack) - argc:]
                slots[ins.out] = self.exec(self.plan.functions[name], call_args)
            elif op == "READ":
                slots[ins.out] = fsops.read_file(
                    self.grants, ins.node, stack.pop(), self.now)
            elif op == "WRITE":
                content = stack.pop()
                path = stack.pop()
                slots[ins.out] = fsops.write_file(
                    self.grants, ins.node, path, content, self.now)
            elif op == "STDIN":
                slots[ins.out] = fsops.read_line(ins.node)
            elif op == "NETFETCH":
                slots[ins.out] = _net_fetch(self, ins.node, stack.pop())
            elif op == "STDOUT":
                slots[ins.out] = fsops.write_str(ins.node, stack.pop())
            elif op == "CONCAT":
                b = stack.pop()
                a = stack.pop()
                slots[ins.out] = ops.concat(a, b)
            elif op == "DIGEST":
                slots[ins.out] = ops.digest(ins.arg, stack.pop())
            elif op == "SESSION":
                if not self.sessions:
                    raise StructuredError(
                        code="E401", node=ins.node, operation="session.verify",
                        detail="denied: no session verifier attached; "
                               "session tokens require --session-key "
                               "(default deny)")
                slots[ins.out] = self.sessions.verify(
                    ins.node, stack.pop(), self.now)
            elif op == "DATALIST":
                if not self.db:
                    raise StructuredError(
                        code="E401", node=ins.node, operation="data.list",
                        detail="denied: no database attached; data effects "
                               "require --db (default deny)")
                limit = (int(ins.arg["limit"])
                         if "limit" in ins.arg else None)
                slots[ins.out] = self.db.list_rows(
                    ins.node, ins.arg["entity"], ins.arg["column"],
                    ins.arg["where"], stack.pop(), limit=limit)
            elif op == "LLEN":
                slots[ins.out] = ops.list_length(stack.pop())
            elif op == "LGET":
                index = stack.pop()
                slots[ins.out] = ops.list_get(ins.node, stack.pop(), index)
            elif op == "LJOIN":
                separator = stack.pop()
                slots[ins.out] = ops.list_join(stack.pop(), separator)
            elif op == "DATA":
                op_name, fields = ins.arg
                slots[ins.out] = _dispatch_data(
                    self, op_name, fields, ins.node, stack)
            elif op == "EMIT":
                self.emits.append(stack.pop())
            elif op == "RETURN":
                return stack.pop()
            else:  # pragma: no cover
                raise AssertionError(f"unhandled instruction {op!r}")
        return None


_OP_INSTR_REV = {v: k for k, v in _OP_INSTR.items()}


def _dispatch_data(vm: "_VM", op_name: str, fields: dict, node_id: str,
                   stack: list):
    """Pop data-op arguments (in input order) and call the data plane."""
    if not vm.db:
        from .errors import StructuredError
        raise StructuredError(
            code="E401", node=node_id, operation=op_name,
            detail="denied: no database attached; data effects require --db "
                   "(default deny)")
    db = vm.db
    if op_name == "data.insert":
        argc = fields["_argc"]
        if "_when" in fields and stack.pop() is False:
            if argc:
                del stack[len(stack) - argc:]
            return 0  # guarded write denied: no row, no effect
        args = stack[len(stack) - argc:] if argc else []
        if argc:
            del stack[len(stack) - argc:]
        return db.insert(node_id, fields["entity"], args)
    if op_name == "data.update":
        if "_when" in fields and stack.pop() is False:
            stack.pop(); stack.pop()
            return 0  # guarded write denied: zero rows touched
        where_value = stack.pop()
        new_value = stack.pop()
        return db.update(node_id, fields["entity"], fields["set"], new_value,
                         fields["where"], where_value)
    value = stack.pop()
    if op_name == "data.delete":
        if "_when" in fields and stack.pop() is False:
            return 0  # guarded delete denied: zero rows touched
        return db.delete(node_id, fields["entity"], fields["where"], value)
    if op_name == "data.count":
        return db.count(node_id, fields["entity"], fields["where"], value)
    if op_name == "data.select":
        return db.select(node_id, fields["entity"], fields["column"],
                         fields["where"], value)
    return db.delete(node_id, fields["entity"], fields["where"], value)


def _net_fetch(vm: "_VM", node_id: str, url: str) -> str:
    """Outbound GET, capability-gated by hostname (same contract as the
    tree adapter's _net_fetch: host supplies the transport, default deny)."""
    from urllib.parse import urlparse
    from .errors import StructuredError

    if vm.net is None:
        raise StructuredError(
            code="E401", node=node_id, operation="net.fetch",
            detail="denied: no network attached; net.fetch requires "
                   "the host to supply a transport (default deny)")
    host = urlparse(url).hostname or ""
    if not host:
        raise StructuredError(
            code="E203", node=node_id, operation="net.fetch",
            detail=f"cannot parse host from url {url!r}")
    vm.grants.check("net.request", host.lower(), vm.now, node=node_id)
    try:
        body = vm.net(url)
    except Exception as exc:
        raise StructuredError(
            code="E560", node=node_id, operation="net.fetch",
            detail=f"request to {host} failed: "
                   f"{exc.__class__.__name__}: {exc}") from exc
    return body if isinstance(body, str) else str(body)
