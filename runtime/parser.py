"""Parser: canonical .ai text format -> Program (spec/graph.md).

One canonical way to write each construct (roadmap §8): a program is a
main scope of node blocks plus optional named functions (`func <name>`).
Each block starts with `node <id>` and contains one field per line.
Node ids are globally unique across all scopes. Comments (`#`) and blank
lines are ignored. The parser is strict: unknown fields, duplicate ids,
and stray lines are errors.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .errors import StructuredError

FORMAT_VERSION = 1  # bump on breaking grammar changes; see spec/graph.md

_NODE_ID_RE = re.compile(r"[0-9]+")
_MAX_ID_DIGITS = 40  # absurdly generous; longer ids are hostile input
_FUNC_NAME_RE = re.compile(r"[a-z_][a-z0-9_]*")
_COLUMN_TYPE_RE = re.compile(r"(identity|bool|i64|f64|string)")
_COLUMN_EXTRA = ("unique",)

# Top-level field names the grammar knows about. Op-specific admissibility
# (which op accepts which fields) is enforced by the validator.
_FIELD_NAMES = ("op", "type", "value", "output", "mode", "callee", "index",
                "entity", "column", "where", "algorithm", "set", "limit",
                "when")


@dataclass
class Node:
    """One semantic graph node as written in the source file."""

    id: str
    line: int  # 1-based source line of the `node` header
    fields: dict[str, tuple[str, int]] = field(default_factory=dict)
    inputs: list[tuple[str, int]] = field(default_factory=list)

    def field(self, name: str) -> str:
        return self.fields[name][0]

    def has(self, name: str) -> bool:
        return name in self.fields


@dataclass
class Function:
    """A named subgraph: params (`op param`) + body + exactly one `return`."""

    name: str
    line: int
    nodes: dict[str, Node] = field(default_factory=dict)


@dataclass(frozen=True)
class Column:
    name: str
    type: str  # "identity" | bool | i64 | f64 | string
    unique: bool = False


@dataclass
class Entity:
    """A semantic data entity (roadmap §22): compiled to a SQLite table by
    the runtime. The AI never writes SQL — column names are grammar-checked
    identifiers and every value is a bound parameter."""

    name: str
    line: int
    columns: list[Column] = field(default_factory=list)


@dataclass
class Program:
    """Entities, main scope, and functions, in declaration order."""

    entities: dict[str, Entity]
    nodes: dict[str, Node]
    functions: dict[str, Function] = field(default_factory=dict)


def parse_source(source: str) -> Program:
    nodes: dict[str, Node] = {}
    functions: dict[str, Function] = {}
    entities: dict[str, Entity] = {}
    seen_ids: dict[str, int] = {}  # node id -> declaring line (global)
    current_scope: dict[str, Node] = nodes
    current_node: Node | None = None
    current_entity: Entity | None = None

    for lineno, raw_line in enumerate(source.splitlines(), 1):
        line = _strip_comment(raw_line).strip()
        if not line:
            continue

        parts = line.split(None, 1)
        head = parts[0]
        rest = parts[1] if len(parts) > 1 else ""

        if current_entity is not None:
            if head == "}":
                current_entity = None
            else:
                tokens = line.split()
                if len(tokens) not in (2, 3):
                    raise StructuredError(
                        code="E110", line=lineno,
                        detail=f"malformed column in entity "
                               f"{current_entity.name!r}: {line!r}",
                    )
                col_name, col_type = tokens[0], tokens[1]
                unique = len(tokens) == 3
                if len(tokens) == 3 and tokens[2] != "unique":
                    raise StructuredError(
                        code="E110", line=lineno,
                        detail=f"unknown column modifier {tokens[2]!r} "
                               f"in entity {current_entity.name!r}",
                    )
                if not _FUNC_NAME_RE.fullmatch(col_name):
                    raise StructuredError(
                        code="E110", line=lineno,
                        detail=f"column name must match [a-z_][a-z0-9_]*, "
                               f"received {col_name!r}",
                    )
                if not _COLUMN_TYPE_RE.fullmatch(col_type):
                    raise StructuredError(
                        code="E110", line=lineno,
                        detail=f"column type must be identity|bool|i64|f64|"
                               f"string, received {col_type!r}",
                    )
                current_entity.columns.append(
                    Column(name=col_name, type=col_type, unique=unique))
            continue

        if head == "format-version":
            # optional version header; a mismatched version is refused so
            # old/new runtimes never silently misread each other's files
            if rest.strip() != str(FORMAT_VERSION):
                raise StructuredError(
                    code="E109", line=lineno,
                    detail=f"unsupported format-version {rest.strip()!r} "
                           f"(this runtime writes {FORMAT_VERSION})",
                )
            continue

        if head == "protocol":
            # optional protocol compatibility range (plan SS30): the
            # program states the protocol semver it targets; a runtime
            # whose PROTOCOL_VERSION is outside [declared, next-major)
            # refuses to run it — never silently misinterpret it.
            declared = rest.strip()
            from . import PROTOCOL_VERSION
            try:
                major, minor = (int(x) for x in declared.split(".", 1))
                rt_major, rt_minor = (int(x)
                                      for x in PROTOCOL_VERSION.split(".", 1))
            except ValueError:
                raise StructuredError(
                    code="E109", line=lineno,
                    detail=f"protocol range must be '<major>.<minor>' "
                           f"(e.g. '0.2'), received {declared!r}",
                ) from None
            if (major, minor) > (rt_major, rt_minor) or major != rt_major:
                raise StructuredError(
                    code="E109", line=lineno,
                    detail=f"program requires protocol {declared} but "
                           f"this runtime implements {PROTOCOL_VERSION} "
                           f"— refusing (never silently misinterpret)",
                )
            continue

        if head == "entity" and ("{" in rest or current_node is None):
            # header form: `entity name {`. Inside an open node block the
            # brace-less form is the data-op field `entity <name>`.
            if "{" not in rest:
                raise StructuredError(
                    code="E110", line=lineno,
                    detail="entity declaration requires 'entity <name> {'",
                )
            name = rest.replace("{", "").strip()
            if not _FUNC_NAME_RE.fullmatch(name):
                raise StructuredError(
                    code="E110", line=lineno,
                    detail=f"entity name must match [a-z_][a-z0-9_]*, "
                           f"received {name!r}",
                )
            if name in entities:
                raise StructuredError(
                    code="E110", line=lineno,
                    detail=f"duplicate entity {name!r} "
                           f"(first declared on line {entities[name].line})",
                )
            current_entity = Entity(name=name, line=lineno)
            entities[name] = current_entity

        elif head == "node":
            if not rest:
                raise StructuredError(
                    code="E107", line=lineno,
                    detail="node header requires exactly one id: 'node <id>'",
                )
            node_id = rest.strip()
            if not _NODE_ID_RE.fullmatch(node_id):
                raise StructuredError(
                    code="E107", line=lineno,
                    detail=f"node id must be digits, received {node_id!r}",
                )
            if len(node_id) > _MAX_ID_DIGITS:
                raise StructuredError(
                    code="E107", line=lineno,
                    detail=f"node id exceeds {_MAX_ID_DIGITS} digits",
                )
            if node_id in seen_ids:
                raise StructuredError(
                    code="E104", line=lineno, node=node_id,
                    detail=f"duplicate node id {node_id!r} "
                           f"(first declared on line {seen_ids[node_id]})",
                )
            seen_ids[node_id] = lineno
            current_node = Node(id=node_id, line=lineno)
            current_scope[node_id] = current_node

        elif head == "func":
            if not rest:
                raise StructuredError(
                    code="E109", line=lineno,
                    detail="func header requires a name: 'func <name>'",
                )
            name = rest.strip()
            if not _FUNC_NAME_RE.fullmatch(name):
                raise StructuredError(
                    code="E109", line=lineno,
                    detail=f"function name must match [a-z_][a-z0-9_]*, "
                           f"received {name!r}",
                )
            if name in functions:
                raise StructuredError(
                    code="E109", line=lineno,
                    detail=f"duplicate function {name!r} "
                           f"(first declared on line {functions[name].line})",
                )
            function = Function(name=name, line=lineno)
            functions[name] = function
            current_scope = function.nodes
            current_node = None

        elif head == "main":
            if rest:
                raise StructuredError(
                    code="E107", line=lineno,
                    detail="header 'main' takes no arguments",
                )
            current_scope = nodes
            current_node = None

        elif current_node is None:
            raise StructuredError(
                code="E101", line=lineno,
                detail=f"statement outside any node block: {line!r}",
            )

        else:
            if head == "input":
                if not rest:
                    raise StructuredError(
                        code="E102", line=lineno, node=current_node.id,
                        detail="field 'input' requires at least one node id",
                    )
                if current_node.inputs:
                    raise StructuredError(
                        code="E102", line=lineno, node=current_node.id,
                        detail="duplicate field 'input' (list all inputs on one line)",
                    )
                current_node.inputs = [(ref, lineno) for ref in rest.split()]
            elif head in _FIELD_NAMES:
                if not rest:
                    raise StructuredError(
                        code="E102", line=lineno, node=current_node.id,
                        detail=f"field {head!r} requires a value",
                    )
                if head in current_node.fields:
                    raise StructuredError(
                        code="E102", line=lineno, node=current_node.id,
                        detail=f"duplicate field {head!r}",
                    )
                current_node.fields[head] = (rest, lineno)
            else:
                raise StructuredError(
                    code="E102", line=lineno, node=current_node.id,
                    detail=f"unknown field {head!r}",
                )

    if not nodes and not functions and not entities:
        raise StructuredError(code="E108", detail="program contains no node blocks")
    return Program(entities=entities, nodes=nodes, functions=functions)


def _strip_comment(line: str) -> str:
    """Drop a '#' comment, respecting double-quoted string literals."""
    out: list[str] = []
    in_string = False
    i = 0
    while i < len(line):
        ch = line[i]
        if in_string:
            out.append(ch)
            if ch == "\\" and i + 1 < len(line):
                out.append(line[i + 1])
                i += 2
                continue
            if ch == '"':
                in_string = False
        else:
            if ch == "#":
                break
            if ch == '"':
                in_string = True
            out.append(ch)
        i += 1
    return "".join(out)
