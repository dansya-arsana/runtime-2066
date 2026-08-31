"""Canonical serializer: Program -> canonical .ai text (spec/graph.md).

Deterministic: the same program always serializes to the same bytes, with
fields in a fixed order and literals re-rendered in canonical form. This is
what the repair loop writes back, and the seed of the Phase-2 canonical IR
serialization (roadmap §15).
"""

from __future__ import annotations

from .parser import FORMAT_VERSION, Node, Program
from .types import format_value, parse_literal, quote_string

# Fixed canonical field order within a node block.
_FIELD_ORDER = ("op", "index", "type", "value", "mode", "callee", "input", "output")


def serialize_program(program: Program) -> str:
    """Canonical text: entities by name, main nodes by ascending id,
    functions by name. Column order inside an entity is semantic (insert
    binds positionally) and is preserved; everything else canonical."""

    def entity_text(entity) -> str:
        lines = [f"entity {entity.name} {{"]
        for col in entity.columns:
            modifier = " unique" if col.unique else ""
            lines.append(f"{col.name} {col.type}{modifier}")
        lines.append("}")
        return "\n".join(lines)

    blocks: list[str] = []
    for name in sorted(program.entities):
        blocks.append(entity_text(program.entities[name]))
    for node in sorted(program.nodes.values(), key=lambda n: int(n.id)):
        blocks.append(_serialize_node(node))
    for name in sorted(program.functions):
        function = program.functions[name]
        header = f"func {function.name}"
        body = [_serialize_node(n)
                for n in sorted(function.nodes.values(), key=lambda n: int(n.id))]
        blocks.append("\n".join([header, *body]))
    return "\n\n".join(blocks) + "\n"


def _serialize_node(node: Node) -> str:
    lines = [f"node {node.id}"]
    for name in _FIELD_ORDER:
        if name == "input":
            if node.inputs:
                lines.append("input " + " ".join(ref for ref, _ in node.inputs))
        elif name in node.fields:
            lines.append(f"{name} {_canonical_field(node, name)}")
    return "\n".join(lines)


def _canonical_field(node: Node, name: str) -> str:
    raw = node.field(name)
    if name == "value":
        parsed = parse_literal(node.field("type"), raw)
        if isinstance(parsed, str):
            return quote_string(parsed)
        return format_value(parsed)
    return raw
