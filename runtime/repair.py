"""Mechanical repair loop (roadmap §13, §80).

    generate -> validate -> reject -> explain structurally -> repair -> validate -> execute

The runtime cannot author (that is the AI's job), but it can mechanically
apply the `cast` repairs it prescribed: insert a `cast` node and rewire the
mismatched input slots. `replace` repairs stay AI-authored hints. Rounds are
bounded; every round re-validates from scratch, so the loop is deterministic.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .errors import StructuredError
from .interpreter import execute
from .parser import Node, Program, parse_source
from .serialize import serialize_program
from .validator import Analysis, analyze

_CAST_RE = re.compile(r"^cast node ([0-9]+) -> ([a-z0-9]+)$")


@dataclass
class RepairOutcome:
    repaired: bool
    rounds: int
    applied: list[str] = field(default_factory=list)
    program_text: str | None = None  # canonical repaired program (when parsed)
    validation_error: StructuredError | None = None
    runtime_error: StructuredError | None = None
    emits: list = field(default_factory=list)


def repair_source(source: str, max_rounds: int = 10, *,
                  revocations=None, sessions=None) -> RepairOutcome:
    try:
        program = parse_source(source)
    except StructuredError as exc:
        return RepairOutcome(repaired=False, rounds=0, validation_error=exc)

    applied: list[str] = []
    last_error: StructuredError | None = None
    analysis: Analysis | None = None
    for round_no in range(1, max_rounds + 1):
        try:
            analysis = analyze(program)
            last_error = None
            break
        except StructuredError as exc:
            last_error = exc
            if exc.code != "E203" or not exc.allowed_repairs:
                break
            step = _apply_cast_repair(program, exc)
            if step is None:
                break
            applied.append(f"round {round_no}: {step}")

    if last_error is not None or analysis is None:
        return RepairOutcome(
            repaired=False, rounds=len(applied), applied=applied,
            program_text=serialize_program(program),
            validation_error=last_error,
        )

    try:
        emits = (execute(program, analysis, revocations=revocations,
                         sessions=sessions)
                 if (revocations or sessions)
                 else execute(program, analysis))
    except StructuredError as exc:
        return RepairOutcome(
            repaired=True, rounds=len(applied), applied=applied,
            program_text=serialize_program(program), runtime_error=exc,
        )

    return RepairOutcome(
        repaired=True, rounds=len(applied), applied=applied,
        program_text=serialize_program(program), emits=emits,
    )


def _apply_cast_repair(program: Program, error: StructuredError) -> str | None:
    match = _CAST_RE.match(error.allowed_repairs[0])
    if match is None or error.node is None:
        return None
    target_id, target_type = match.group(1), match.group(2)
    node, scope_nodes = _find_node(program, error.node)
    if node is None:
        return None

    mismatched = [
        i for i, (ref, _) in enumerate(node.inputs)
        if ref == target_id
        and error.expected.get(f"input[{i}]") != error.received.get(f"input[{i}]")
    ]
    if not mismatched:  # fall back to every slot fed by the target node
        mismatched = [i for i, (ref, _) in enumerate(node.inputs) if ref == target_id]
    if not mismatched:
        return None

    new_id = _next_node_id(program)
    cast_node = Node(
        id=new_id, line=node.line,
        fields={
            "op": ("cast", node.line),
            "output": (target_type, node.line),
        },
        inputs=[(target_id, node.line)],
    )
    scope_nodes[new_id] = cast_node
    for i in mismatched:
        node.inputs[i] = (new_id, node.inputs[i][1])
    return (f"cast node {target_id} -> {target_type} as node {new_id} "
            f"feeding node {node.id}")


def _find_node(program: Program, node_id: str):
    if node_id in program.nodes:
        return program.nodes[node_id], program.nodes
    for function in program.functions.values():
        if node_id in function.nodes:
            return function.nodes[node_id], function.nodes
    return None, None


def _next_node_id(program: Program) -> str:
    all_ids = list(program.nodes)
    for function in program.functions.values():
        all_ids.extend(function.nodes)
    width = max([len(nid) for nid in all_ids] + [3])
    return str(max((int(nid) for nid in all_ids), default=0) + 1).zfill(width)
