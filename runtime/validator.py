"""Validator: deterministic type/structure checking (spec/instructions.md).

Checks run in a fixed order and fail fast on the FIRST error, so the same
program always produces the same first error (roadmap §13, §4.9):

  1. per-node structure, per scope (main first, functions in declaration order)
  2. call targets exist and arities match
  3. the function call graph is acyclic (deterministic call order computed)
  4. input references exist within their own scope
  5. per-scope topological order (DAG check)
  6. type inference: functions in callee-first order, then main
  7. main contains at least one emit
"""

from __future__ import annotations

import heapq
import re
from collections import defaultdict
from dataclasses import dataclass, field

from .errors import StructuredError
from .parser import Node, Program
from .types import TYPE_NAMES, InvalidLiteral, parse_literal

_NUMERIC = ("i64", "f64")
_ORDERED = ("i64", "f64", "string")
_COMPARE_MODES = ("eq", "ne", "lt", "le", "gt", "ge")
_INDEX_RE = re.compile(r"[0-9]+")

# Legal cast source types per target (spec/instructions.md). Everything
# else is rejected at validation time; there is no implicit coercion.
_CAST_SOURCES: dict[str, tuple[str, ...]] = {
    "i64": ("f64", "string"),
    "f64": ("i64", "string"),
    "string": ("i64", "f64", "bool"),
}


@dataclass(frozen=True)
class OpSpec:
    name: str
    required: frozenset[str]
    optional: frozenset[str]
    inputs: int | None  # None = variable arity (call)
    output_required: bool
    scope: str  # "any" | "main" | "func"


_OPS: dict[str, OpSpec] = {
    "const": OpSpec("const", frozenset({"type", "value"}), frozenset(), 0, False, "any"),
    "copy": OpSpec("copy", frozenset(), frozenset({"output"}), 1, False, "any"),
    "add": OpSpec("add", frozenset(), frozenset({"output"}), 2, True, "any"),
    "subtract": OpSpec("subtract", frozenset(), frozenset({"output"}), 2, True, "any"),
    "multiply": OpSpec("multiply", frozenset(), frozenset({"output"}), 2, True, "any"),
    "divide": OpSpec("divide", frozenset(), frozenset({"output"}), 2, True, "any"),
    "compare": OpSpec("compare", frozenset({"mode"}), frozenset({"output"}), 2, True, "any"),
    "branch": OpSpec("branch", frozenset(), frozenset({"output"}), 3, True, "any"),
    "cast": OpSpec("cast", frozenset(), frozenset({"output"}), 1, True, "any"),
    "call": OpSpec("call", frozenset({"callee"}), frozenset({"output"}), None, True, "any"),
    "param": OpSpec("param", frozenset({"type", "index"}), frozenset(), 0, False, "func"),
    "return": OpSpec("return", frozenset(), frozenset(), 1, False, "func"),
    "emit": OpSpec("emit", frozenset(), frozenset(), 1, False, "main"),
    "filesystem.read": OpSpec("filesystem.read", frozenset(), frozenset({"output"}), 1, True, "any"),
    "filesystem.write": OpSpec("filesystem.write", frozenset(), frozenset({"output"}), 2, True, "any"),
    "system.read": OpSpec("system.read", frozenset(), frozenset({"output"}), 0, False, "any"),
    "net.fetch": OpSpec("net.fetch", frozenset(), frozenset({"output"}), 1, True, "any"),
    "system.write": OpSpec("system.write", frozenset(), frozenset({"output"}), 1, False, "any"),
    "concat": OpSpec("concat", frozenset(), frozenset({"output"}), 2, True, "any"),
    "crypto.digest": OpSpec("crypto.digest", frozenset({"algorithm"}), frozenset({"output"}), 1, True, "any"),
    "data.insert": OpSpec("data.insert", frozenset({"entity"}), frozenset({"output", "when"}), None, True, "any"),
    "data.count": OpSpec("data.count", frozenset({"entity", "where"}), frozenset({"output"}), 1, True, "any"),
    "data.select": OpSpec("data.select", frozenset({"entity", "column", "where"}), frozenset({"output"}), 1, True, "any"),
    "data.update": OpSpec("data.update", frozenset({"entity", "set", "where"}), frozenset({"output", "when"}), 2, True, "any"),
    "data.delete": OpSpec("data.delete", frozenset({"entity", "where"}), frozenset({"output", "when"}), 1, True, "any"),
    "session.verify": OpSpec("session.verify", frozenset(), frozenset({"output"}), 1, True, "any"),
    "data.list": OpSpec("data.list", frozenset({"entity", "column", "where"}), frozenset({"output", "limit"}), 1, True, "any"),
    "list.length": OpSpec("list.length", frozenset(), frozenset({"output"}), 1, True, "any"),
    "list.get": OpSpec("list.get", frozenset(), frozenset({"output"}), 2, True, "any"),
    "list.join": OpSpec("list.join", frozenset(), frozenset({"output"}), 2, True, "any"),
}

# Effect taxonomy per operation (roadmap §4.3, Phase 3, Appendix C.2).
# `emit`/`system.read`/`system.write` are SYSTEM with an implicit grant
# (the process stdio channels — the program's own return and input path);
# filesystem effects require explicit capabilities at runtime (Phase 4).
EFFECT_OF: dict[str, str] = {
    "const": "PURE", "copy": "PURE", "add": "PURE", "subtract": "PURE",
    "multiply": "PURE", "divide": "PURE", "compare": "PURE", "branch": "PURE",
    "cast": "PURE", "call": "PURE", "param": "PURE", "return": "PURE",
    "concat": "PURE",
    "emit": "SYSTEM", "system.read": "SYSTEM", "system.write": "SYSTEM",
    "filesystem.read": "FILESYSTEM_READ",
    "filesystem.write": "FILESYSTEM_WRITE",
    "crypto.digest": "PURE",
    "session.verify": "IDENTITY",
    "data.count": "DATA_READ", "data.select": "DATA_READ",
    "data.list": "DATA_READ",
    "list.length": "PURE", "list.get": "PURE", "list.join": "PURE",
    "data.insert": "DATA_WRITE", "data.update": "DATA_WRITE",
    "data.delete": "DATA_WRITE",
    "net.fetch": "NETWORK",
}


@dataclass
class ScopeAnalysis:
    order: list[str]  # topological node ids within the scope
    types: dict[str, str] = field(default_factory=dict)


@dataclass
class Analysis:
    """Everything the interpreter needs, produced deterministically."""

    scopes: dict[str, ScopeAnalysis]  # "main" + function names
    call_order: list[str]  # function names, callees before callers
    func_returns: dict[str, str]  # function name -> return type


def analyze(program: Program) -> Analysis:
    scopes: dict[str, dict[str, Node]] = {"main": program.nodes}
    for function in program.functions.values():
        scopes[function.name] = function.nodes

    for entity in program.entities.values():
        _check_entity(entity)

    # Pass 1 — per-node structure, per scope.
    for scope_name, scope_nodes in scopes.items():
        for node in scope_nodes.values():
            _check_node(node, scope_name, program)
        if scope_name != "main":
            _check_function_shape(scope_name, scope_nodes)

    # Pass 2 — call targets and arities.
    for scope_nodes in scopes.values():
        for node in scope_nodes.values():
            if node.field("op") != "call":
                continue
            callee = node.field("callee")
            if callee not in program.functions:
                raise StructuredError(
                    code="E210", node=node.id, operation="call", line=node.line,
                    detail=f"unknown function {callee!r}",
                )
            nparams = _params(program.functions[callee].nodes)
            if len(node.inputs) != len(nparams):
                raise StructuredError(
                    code="E211", node=node.id, operation="call", line=node.line,
                    detail=f"function {callee!r} takes {len(nparams)} argument(s), "
                           f"received {len(node.inputs)}",
                )

    # Pass 3 — call-graph acyclicity + deterministic callee-first order.
    call_order = _call_order(program)

    # Pass 4 — input references, same scope only.
    owner = {
        node_id: scope_name
        for scope_name, scope_nodes in scopes.items()
        for node_id in scope_nodes
    }
    for scope_name, scope_nodes in scopes.items():
        for node in scope_nodes.values():
            refs = [ref for ref, _ in node.inputs]
            if node.has("when"):
                refs.append(node.field("when"))
            for ref, lineno in [(r, None) for r in refs]:
                if ref not in scope_nodes:
                    detail = (f"input references node {ref!r} in another scope"
                              if ref in owner else
                              f"input references unknown node {ref!r}")
                    raise StructuredError(
                        code="E202", node=node.id,
                        operation=node.field("op"), line=lineno, detail=detail,
                    )

    # Pass 5 — per-scope DAG check + topological order.
    scope_orders = {name: _topo_order(nodes) for name, nodes in scopes.items()}

    # Pass 6 — types: functions callee-first, then main.
    analysis = Analysis(
        scopes={name: ScopeAnalysis(order=order)
                for name, order in scope_orders.items()},
        call_order=call_order,
        func_returns={},
    )
    for function_name in call_order:
        scope = analysis.scopes[function_name]
        for node_id in scope.order:
            node = scopes[function_name][node_id]
            inferred = _infer_type(node, scope.types, program, analysis)
            _check_declared_output(node, inferred)
            scope.types[node_id] = inferred
        return_node = _return_node(program.functions[function_name].nodes)
        analysis.func_returns[function_name] = scope.types[return_node.inputs[0][0]]
    main_scope = analysis.scopes["main"]
    for node_id in main_scope.order:
        node = program.nodes[node_id]
        inferred = _infer_type(node, main_scope.types, program, analysis)
        _check_declared_output(node, inferred)
        main_scope.types[node_id] = inferred

    # Pass 7 — main produces output through some channel (batch emit or
    # interactive system.write) — unless the program is declarations only
    # (a schema/library module with no executable nodes).
    if program.nodes and not any(
            node.field("op") in ("emit", "system.write")
            for node in program.nodes.values()):
        raise StructuredError(
            code="E206",
            detail="program contains no output channel (emit or system.write)",
        )

    return analysis


# --------------------------------------------------------------------------
# structural passes


def _check_entity(entity) -> None:
    """Entity shape (§22): exactly one identity column, and it comes first."""
    columns = entity.columns
    if not columns:
        raise StructuredError(
            code="E112", line=entity.line,
            detail=f"entity {entity.name!r} declares no columns",
        )
    if columns[0].name != "id" or columns[0].type != "identity":
        raise StructuredError(
            code="E112", line=entity.line,
            detail=f"entity {entity.name!r} must declare 'id identity' "
                   f"as its first column",
        )
    if any(col.type == "identity" for col in columns[1:]):
        raise StructuredError(
            code="E112", line=entity.line,
            detail=f"entity {entity.name!r} must declare exactly one "
                   f"identity column",
        )
    names = [col.name for col in columns]
    if len(names) != len(set(names)):
        raise StructuredError(
            code="E112", line=entity.line,
            detail=f"entity {entity.name!r} has duplicate column names",
        )


def _check_node(node: Node, scope_name: str, program: Program) -> None:
    if not node.has("op"):
        raise StructuredError(
            code="E103", node=node.id, line=node.line,
            detail="missing required field 'op'",
        )
    op = node.field("op")
    if op not in _OPS:
        raise StructuredError(
            code="E201", node=node.id, line=node.line,
            detail=f"unknown operation {op!r}",
        )
    spec = _OPS[op]

    if spec.scope == "main" and scope_name != "main":
        raise StructuredError(
            code="E214", node=node.id, operation=op, line=node.line,
            detail=f"op {op!r} is only allowed in the main scope",
        )
    if spec.scope == "func" and scope_name == "main":
        raise StructuredError(
            code="E214", node=node.id, operation=op, line=node.line,
            detail=f"op {op!r} is only allowed inside a function",
        )

    for name in node.fields:
        if name == "op":
            continue  # presence and value already checked above
        if name not in spec.required and name not in spec.optional:
            raise StructuredError(
                code="E102", node=node.id, operation=op, line=node.line,
                detail=f"field {name!r} is not allowed for op {op!r}",
            )
    for name in sorted(spec.required):
        if name not in node.fields:
            raise StructuredError(
                code="E103", node=node.id, operation=op, line=node.line,
                detail=f"missing required field {name!r} for op {op!r}",
            )
    if spec.output_required and "output" not in node.fields:
        raise StructuredError(
            code="E103", node=node.id, operation=op, line=node.line,
            detail=f"missing required field 'output' for op {op!r}",
        )

    if spec.inputs is not None and len(node.inputs) != spec.inputs:
        raise StructuredError(
            code="E207", node=node.id, operation=op, line=node.line,
            detail=f"op {op!r} requires exactly {spec.inputs} input(s), "
                   f"received {len(node.inputs)}",
        )

    if op == "const":
        type_name = node.field("type")
        if type_name not in TYPE_NAMES:
            raise StructuredError(
                code="E106", node=node.id, operation=op, line=node.line,
                detail=f"unknown type {type_name!r} "
                       f"(allowed: {', '.join(TYPE_NAMES)})",
            )
        try:
            parse_literal(type_name, node.field("value"))
        except InvalidLiteral as exc:
            raise StructuredError(
                code="E105", node=node.id, operation=op, line=node.line,
                detail=exc.detail,
            ) from exc

    if op == "compare":
        mode = node.field("mode")
        if mode not in _COMPARE_MODES:
            raise StructuredError(
                code="E208", node=node.id, operation=op, line=node.line,
                detail=f"unknown compare mode {mode!r} "
                       f"(allowed: {', '.join(_COMPARE_MODES)})",
            )

    if op == "param":
        index = node.field("index")
        if not _INDEX_RE.fullmatch(index):
            raise StructuredError(
                code="E102", node=node.id, operation=op, line=node.line,
                detail=f"field 'index' must be a non-negative integer, "
                       f"received {index!r}",
            )

    if op == "crypto.digest":
        if node.field("algorithm") != "sha256":
            raise StructuredError(
                code="E102", node=node.id, operation=op, line=node.line,
                detail=f"unsupported digest algorithm {node.field('algorithm')!r} "
                       f"(allowed: sha256)",
            )

    if op.startswith("data."):
        _check_data_op(node, op, program)


def _entity_or_error(program: Program, node: Node, op: str):
    name = node.field("entity")
    entity = program.entities.get(name)
    if entity is None:
        raise StructuredError(
            code="E501", node=node.id, operation=op, line=node.line,
            detail=f"unknown entity {name!r} "
                   f"(declared: {', '.join(program.entities) or 'none'})",
        )
    return entity


def _column_or_error(entity, name: str, node: Node, op: str):
    for col in entity.columns:
        if col.name == name:
            return col
    raise StructuredError(
        code="E502", node=node.id, operation=op, line=node.line,
        detail=f"entity {entity.name!r} has no column {name!r} "
               f"(columns: {', '.join(c.name for c in entity.columns)})",
    )


def _check_data_op(node: Node, op: str, program: Program) -> None:
    """Entity/column references and identity-column protection (§22–§24)."""
    entity = _entity_or_error(program, node, op)
    if op == "data.insert":
        value_columns = [c for c in entity.columns if c.type != "identity"]
        if len(node.inputs) != len(value_columns):
            raise StructuredError(
                code="E207", node=node.id, operation=op, line=node.line,
                detail=f"entity {entity.name!r} insert takes "
                       f"{len(value_columns)} value(s) "
                       f"({', '.join(c.name for c in value_columns)}), "
                       f"received {len(node.inputs)}",
            )
        return
    if op == "data.update":
        set_col = _column_or_error(entity, node.field("set"), node, op)
        if set_col.type == "identity":
            raise StructuredError(
                code="E503", node=node.id, operation=op, line=node.line,
                detail="the identity column cannot be updated",
            )
    _column_or_error(entity, node.field("where"), node, op)
    if op == "data.select":
        _column_or_error(entity, node.field("column"), node, op)


def _check_function_shape(name: str, nodes: dict[str, Node]) -> None:
    returns = [n for n in nodes.values() if n.field("op") == "return"]
    if len(returns) != 1:
        raise StructuredError(
            code="E215", line=min(n.line for n in returns) if returns else None,
            detail=f"function {name!r} must contain exactly one return node "
                   f"(found {len(returns)})",
        )
    indexes = sorted(int(n.field("index")) for n in _params(nodes))
    if indexes != list(range(len(indexes))):
        raise StructuredError(
            code="E216", detail=f"function {name!r} param indexes must be "
                                f"exactly 0..{len(indexes) - 1}, found {indexes}",
        )


def _params(nodes: dict[str, Node]) -> list[Node]:
    return [n for n in nodes.values() if n.field("op") == "param"]


def _return_node(nodes: dict[str, Node]) -> Node:
    return next(n for n in nodes.values() if n.field("op") == "return")


# --------------------------------------------------------------------------
# ordering


def _call_order(program: Program) -> list[str]:
    names = list(program.functions)
    index_of = {name: i for i, name in enumerate(names)}
    callees: dict[str, set[str]] = {}
    for name, function in program.functions.items():
        callees[name] = {
            node.field("callee")
            for node in function.nodes.values()
            if node.has("op") and node.field("op") == "call"
        }

    indegree = {name: 0 for name in names}
    dependents: dict[str, list[str]] = defaultdict(list)
    for caller, targets in callees.items():
        for callee in targets:
            indegree[caller] += 1
            dependents[callee].append(caller)

    heap = [(index_of[name], name) for name in names if indegree[name] == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        _, name = heapq.heappop(heap)
        order.append(name)
        for caller in dependents.get(name, ()):
            indegree[caller] -= 1
            if indegree[caller] == 0:
                heapq.heappush(heap, (index_of[caller], caller))

    if len(order) != len(names):
        adjacency = {name: sorted(targets) for name, targets in callees.items()}
        cycle = _find_cycle(adjacency)
        raise StructuredError(
            code="E212", detail="call cycle: " + " -> ".join(cycle),
        )
    return order


def _topo_order(nodes: dict[str, Node]) -> list[str]:
    """Kahn topological order; ties broken by numeric node id (deterministic)."""
    dependents: dict[str, list[str]] = defaultdict(list)
    indegree: dict[str, int] = {node_id: 0 for node_id in nodes}
    for node_id, node in nodes.items():
        refs = {r for r, _ in node.inputs}
        if node.has("when"):
            refs.add(node.field("when"))  # guard evaluates before its effect
        for ref in refs:
            indegree[node_id] += 1
            dependents[ref].append(node_id)

    heap = [(int(nid), nid) for nid, degree in indegree.items() if degree == 0]
    heapq.heapify(heap)
    order: list[str] = []
    while heap:
        _, node_id = heapq.heappop(heap)
        order.append(node_id)
        for dependent in dependents.get(node_id, ()):
            indegree[dependent] -= 1
            if indegree[dependent] == 0:
                heapq.heappush(heap, (int(dependent), dependent))

    if len(order) != len(nodes):
        adjacency = {
            node_id: sorted({r for r, _ in node.inputs}, key=int)
            for node_id, node in nodes.items()
        }
        cycle = _find_cycle(adjacency)
        raise StructuredError(
            code="E204", detail="dependency cycle: " + " -> ".join(cycle),
        )
    return order


def _find_cycle(adjacency: dict[str, list[str]]) -> list[str]:
    """Deterministic DFS used only to describe a cycle already known to exist."""
    DONE, ACTIVE = 0, 1
    state: dict[str, int] = {}
    for start in adjacency:
        if start in state:
            continue
        path = [start]
        state[start] = ACTIVE
        stack = [iter(adjacency[start])]
        while stack:
            advanced = False
            for nxt in stack[-1]:
                if state.get(nxt) == ACTIVE:
                    return path[path.index(nxt):] + [nxt]
                if nxt not in state:
                    state[nxt] = ACTIVE
                    path.append(nxt)
                    stack.append(iter(adjacency.get(nxt, ())))
                    advanced = True
                    break
            if not advanced:
                state[path.pop()] = DONE
                stack.pop()
    raise AssertionError("cycle requested but none found")  # pragma: no cover


# --------------------------------------------------------------------------
# type inference


def program_effects(program: Program, analysis: Analysis | None = None) -> list[str]:
    """Static effect manifest: sorted unique effects the program can perform.

    Call nodes inherit the full effect set of the callee (transitively — the
    call graph is acyclic). This is the evidence-plane answer to "what
    authority would executing this program need?" before running it.
    """
    if analysis is None:
        analysis = analyze(program)

    def node_effects(node: Node, resolved: dict[str, set[str]]) -> set[str]:
        op = node.field("op")
        if op == "call":
            return resolved.get(node.field("callee"), set())
        return {EFFECT_OF[op]}

    scope_effects: dict[str, set[str]] = {}
    for name in analysis.call_order:
        effects: set[str] = set()
        for node in program.functions[name].nodes.values():
            effects |= node_effects(node, scope_effects)
        scope_effects[name] = effects

    main_effects: set[str] = set()
    for node in program.nodes.values():
        main_effects |= node_effects(node, scope_effects)
    return sorted(main_effects)


def _check_declared_output(node: Node, inferred: str) -> None:
    if node.has("output"):
        declared = node.field("output")
        if declared != inferred:
            raise StructuredError(
                code="E205", node=node.id, operation=node.field("op"),
                expected={"output": inferred},
                received={"output": declared},
                detail=f"declared output {declared!r} but operation yields {inferred!r}",
            )


def _infer_type(
    node: Node, types: dict[str, str], program: Program, analysis: Analysis,
) -> str:
    op = node.field("op")
    ins = [types[ref] for ref, _ in node.inputs]

    if op == "const":
        return node.field("type")
    if op == "copy":
        return ins[0]
    if op in ("add", "subtract", "multiply", "divide"):
        return _require_numeric_pair(node, op, ins)
    if op == "compare":
        return _infer_compare(node, ins)
    if op == "branch":
        return _infer_branch(node, ins)
    if op == "cast":
        return _infer_cast(node, ins)
    if op == "call":
        return _infer_call(node, ins, program, analysis)
    if op == "filesystem.read":
        _require_string(node, op, [0], ins)
        return "string"
    if op == "filesystem.write":
        _require_string(node, op, [0, 1], ins)
        return "i64"
    if op == "concat":
        if not (ins[0] == "string" and ins[1] == "string"):
            a, b = node.inputs[0][0], node.inputs[1][0]
            raise _type_error(
                node, op,
                expected={"input[0]": "string", "input[1]": "string"},
                received={"input[0]": ins[0], "input[1]": ins[1]},
                repairs=[f"cast node {a} -> string", f"cast node {b} -> string"],
            )
        return "string"
    if op == "system.read":
        return "string"
    if op == "system.write":
        _require_string(node, op, [0], ins)
        return "i64"
    if op == "crypto.digest":
        _require_string(node, op, [0], ins)
        return "string"
    if op == "net.fetch":
        _require_string(node, op, [0], ins)
        return "string"
    if op == "session.verify":
        _require_string(node, op, [0], ins)
        return "i64"
    if op == "data.list":
        entity = _entity_or_error(program, node, op)
        _column_or_error(entity, node.field("column"), node, op)
        _require_column_type(node, op, entity, node.field("where"), 0, ins)
        col = _column_or_error(entity, node.field("column"), node, op)
        if node.has("limit"):
            if not _INDEX_RE.fullmatch(node.field("limit")):
                raise StructuredError(
                    code="E102", node=node.id, operation=op, line=node.line,
                    detail=f"field 'limit' must be a non-negative integer, "
                           f"received {node.field('limit')!r}")
        return f"list<{_value_type(col.type)}>"
    if op == "list.length":
        _require_list(node, op, 0, ins)
        return "i64"
    if op == "list.get":
        _require_list(node, op, 0, ins)
        if ins[1] != "i64":
            arg_id = node.inputs[1][0]
            raise _type_error(
                node, op, expected={"input[1]": "i64"},
                received={"input[1]": ins[1]},
                repairs=[f"cast node {arg_id} -> i64"],
                detail="list index must be i64")
        return ins[0][5:-1]  # element type
    if op == "list.join":
        if ins[0] != "list<string>":
            arg_id = node.inputs[0][0]
            raise _type_error(
                node, op, expected={"input[0]": "list<string>"},
                received={"input[0]": ins[0]},
                repairs=[f"replace node {arg_id}"],
                detail="list.join joins strings")
        _require_string(node, op, [1], ins)
        return "string"
    if op.startswith("data."):
        if node.has("when"):
            # guarded effect: the `when` field references a bool node
            guard_ref = node.field("when")
            if types.get(guard_ref) != "bool":
                raise _type_error(
                    node, op,
                    expected={"when": "bool"},
                    received={"when": types.get(guard_ref, "unknown")},
                    repairs=[f"cast node {guard_ref} -> bool",
                             f"replace node {guard_ref}"],
                    detail="when guard must be bool",
                )
        return _infer_data(node, op, ins, program)
    if op in ("emit", "return"):
        return ins[0]
    if op == "param":
        return node.field("type")
    raise AssertionError(f"unhandled op {op!r}")  # pragma: no cover


def _require_string(node: Node, op: str, slots: list[int], ins: list[str]) -> None:
    for i in slots:
        if ins[i] != "string":
            arg_id = node.inputs[i][0]
            raise _type_error(
                node, op,
                expected={f"input[{i}]": "string"},
                received={f"input[{i}]": ins[i]},
                repairs=[f"cast node {arg_id} -> string", f"replace node {arg_id}"],
                detail=f"op {op!r} requires string operands",
            )


def _value_type(col_type: str) -> str:
    return "i64" if col_type == "identity" else col_type


def _require_list(node: Node, op: str, slot: int, ins: list[str]) -> None:
    if not ins[slot].startswith("list<"):
        arg_id = node.inputs[slot][0]
        raise _type_error(
            node, op,
            expected={f"input[{slot}]": "list<...>"},
            received={f"input[{slot}]": ins[slot]},
            repairs=[f"replace node {arg_id} with a data.list result"],
            detail=f"op {op!r} requires a list value",
        )


def _require_column_type(node: Node, op: str, entity, col_name: str,
                         slot: int, ins: list[str]) -> None:
    col = _column_or_error(entity, col_name, node, op)
    want = _value_type(col.type)
    if ins[slot] != want:
        arg_id = node.inputs[slot][0]
        raise _type_error(
            node, op,
            expected={f"input[{slot}]": want},
            received={f"input[{slot}]": ins[slot]},
            repairs=[f"cast node {arg_id} -> {want}", f"replace node {arg_id}"],
            detail=f"column {entity.name}.{col_name} is {col.type}",
        )


def _infer_data(node: Node, op: str, ins: list[str], program: Program) -> str:
    entity = _entity_or_error(program, node, op)
    if op == "data.insert":
        value_columns = [c for c in entity.columns if c.type != "identity"]
        for i, col in enumerate(value_columns):
            _require_column_type(node, op, entity, col.name, i, ins)
        return "i64"
    if op == "data.update":
        _require_column_type(node, op, entity, node.field("set"), 0, ins)
        _require_column_type(node, op, entity, node.field("where"), 1, ins)
        return "i64"
    _require_column_type(node, op, entity, node.field("where"), 0, ins)
    if op == "data.select":
        col = _column_or_error(entity, node.field("column"), node, op)
        return _value_type(col.type)
    return "i64"  # count / delete return row counts


def _type_error(
    node: Node, op: str, expected: dict[str, str], received: dict[str, str],
    repairs: list[str], detail: str | None = None,
) -> StructuredError:
    return StructuredError(
        code="E203", node=node.id, operation=op,
        expected=expected, received=received,
        allowed_repairs=repairs, detail=detail,
    )


def _require_numeric_pair(node: Node, op: str, ins: list[str]) -> str:
    a, b = node.inputs[0][0], node.inputs[1][0]
    t0, t1 = ins
    if t0 in _NUMERIC and t1 in _NUMERIC:
        if t0 == t1:
            return t0
        # mixed i64/f64: no implicit coercion (one canonical path, roadmap §8)
        raise _type_error(
            node, op,
            expected={"input[0]": t1, "input[1]": t1},
            received={"input[0]": t0, "input[1]": t1},
            repairs=[f"cast node {a} -> {t1}", f"cast node {b} -> {t0}"],
            detail="mixed i64/f64 operands; cast explicitly",
        )
    want = t0 if t0 in _NUMERIC else "i64"
    repairs = []
    if t0 in _NUMERIC:
        repairs = [f"cast node {b} -> {t0}", f"replace node {b}"]
    elif t1 in _NUMERIC:
        repairs = [f"cast node {a} -> {t1}", f"replace node {a}"]
    else:
        repairs = [
            f"replace node {a} with an i64 or f64 value",
            f"replace node {b} with an i64 or f64 value",
        ]
    raise _type_error(
        node, op,
        expected={"input[0]": want, "input[1]": want},
        received={"input[0]": t0, "input[1]": t1},
        repairs=repairs,
    )


def _infer_compare(node: Node, ins: list[str]) -> str:
    op = node.field("op")
    mode = node.field("mode")
    a, b = node.inputs[0][0], node.inputs[1][0]
    t0, t1 = ins
    if t0 != t1:
        raise _type_error(
            node, op,
            expected={"input[0]": t0, "input[1]": t0},
            received={"input[0]": t0, "input[1]": t1},
            repairs=[f"cast node {b} -> {t0}", f"replace node {b}"],
        )
    if mode in ("lt", "le", "gt", "ge") and t0 not in _ORDERED:
        raise _type_error(
            node, op,
            expected={"input[0]": "i64|f64|string", "input[1]": "i64|f64|string"},
            received={"input[0]": t0, "input[1]": t1},
            repairs=[f"replace node {a} with an ordered value", f"replace node {b}"],
            detail=f"mode {mode!r} requires i64, f64, or string operands",
        )
    return "bool"


def _infer_branch(node: Node, ins: list[str]) -> str:
    op = node.field("op")
    a, b, c = (ref for ref, _ in node.inputs)
    if ins[0] != "bool":
        raise _type_error(
            node, op,
            expected={"input[0]": "bool"},
            received={"input[0]": ins[0]},
            repairs=[f"cast node {a} -> bool", f"replace node {a}"],
            detail="branch condition must be bool",
        )
    if ins[1] != ins[2]:
        raise _type_error(
            node, op,
            expected={"input[1]": ins[1], "input[2]": ins[1]},
            received={"input[1]": ins[1], "input[2]": ins[2]},
            repairs=[f"cast node {c} -> {ins[1]}", f"replace node {c}"],
            detail="branch arms must have the same type",
        )
    return ins[1]


def _infer_cast(node: Node, ins: list[str]) -> str:
    target = node.field("output")
    source = ins[0]
    if source != target and source not in _CAST_SOURCES.get(target, ()):
        allowed = _CAST_SOURCES.get(target, ())
        raise _type_error(
            node, "cast",
            expected={"input[0]": "no cast needed" if source == target
                      else "|".join(allowed) if allowed else target},
            received={"input[0]": source},
            repairs=[f"replace node {node.inputs[0][0]}"],
            detail=(f"no cast from {source} to {target}"
                    if allowed or source != target else
                    f"target type {target!r} has no legal cast sources"),
        )
    return target


def _infer_call(
    node: Node, ins: list[str], program: Program, analysis: Analysis,
) -> str:
    callee = node.field("callee")
    function = program.functions[callee]
    scope = analysis.scopes[callee]
    params = sorted(_params(function.nodes), key=lambda n: int(n.field("index")))
    ptypes = [scope.types[p.id] for p in params]
    expected = {f"input[{i}]": t for i, t in enumerate(ptypes)}
    received = {f"input[{i}]": t for i, t in enumerate(ins)}
    if expected != received:
        repairs = []
        for i, (ptype, actual) in enumerate(zip(ptypes, ins)):
            if ptype != actual:
                arg_id = node.inputs[i][0]
                repairs.append(f"cast node {arg_id} -> {ptype}")
                repairs.append(f"replace node {arg_id}")
        raise _type_error(
            node, "call", expected=expected, received=received, repairs=repairs,
            detail=f"argument types must match function {callee!r} params",
        )
    return analysis.func_returns[callee]
