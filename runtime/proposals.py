"""Semantic mutation protocol (roadmap §29–§30, C.4): signed graph
proposals with deterministic merge.

Agents do not edit files; they propose node-level changes against a base
program identified by its canonical hash. The runtime then decides:

- proposals from the same base with DISJOINT changes merge automatically
  (independent mutation, §29);
- proposals touching the SAME unit with different content conflict, and
  the merge is rejected with a structured conflict report naming the unit
  and both contenders — never a silent overwrite;
- a proposal whose base hash does not match the actual base, or whose
  signature does not verify, is refused outright (E601/E602).

The "unit" of change is one serialized node (scoped), one entity
declaration, or one function declaration — exactly the granularity at
which the semantic graph is the artifact.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from . import identity
from .errors import StructuredError
from .hashing import program_hash
from .parser import Program, parse_source
from .serialize import _serialize_node

FORMAT_VERSION = 1


# ---------------------------------------------------------------------------
# unit decomposition


@dataclass
class Units:
    """A program flattened into addressable, serializable units."""

    entities: dict[str, str]      # entity name -> text
    main: dict[str, str]          # node id -> text
    functions: dict[str, dict[str, str]]  # func name -> {node id -> text}

    def to_map(self) -> dict[str, str]:
        flat: dict[str, str] = {}
        for name, text in self.entities.items():
            flat[f"entity/{name}"] = text
        for node_id, text in self.main.items():
            flat[f"main/{node_id}"] = text
        for func_name, nodes in self.functions.items():
            flat[f"func/{func_name}"] = ""  # declaration marker
            for node_id, text in nodes.items():
                flat[f"func/{func_name}/{node_id}"] = text
        return flat


def program_units(program: Program) -> Units:
    from .serialize import serialize_program  # local: entity text helper

    def entity_text(entity) -> str:
        lines = [f"entity {entity.name} {{"]
        for col in entity.columns:
            modifier = " unique" if col.unique else ""
            lines.append(f"{col.name} {col.type}{modifier}")
        lines.append("}")
        return "\n".join(lines)

    return Units(
        entities={name: entity_text(e)
                  for name, e in program.entities.items()},
        main={node.id: _serialize_node(node)
              for node in program.nodes.values()},
        functions={name: {node.id: _serialize_node(node)
                          for node in function.nodes.values()}
                   for name, function in program.functions.items()},
    )


def _rebuild_source(units: Units) -> str:
    """Deterministic source text from units (entities, main, functions)."""
    blocks: list[str] = []
    for name in sorted(units.entities):
        blocks.append(units.entities[name])
    for node_id in sorted(units.main, key=int):
        blocks.append(units.main[node_id])
    for func_name in sorted(units.functions):
        blocks.append(f"func {func_name}")
        for node_id in sorted(units.functions[func_name], key=int):
            blocks.append(units.functions[func_name][node_id])
    return "\n\n".join(blocks) + "\n"


# ---------------------------------------------------------------------------
# diff


def diff_programs(base: Program, proposed: Program) -> dict:
    base_map = program_units(base).to_map()
    prop_map = program_units(proposed).to_map()
    added = {k: v for k, v in prop_map.items() if k not in base_map}
    removed = sorted(k for k in base_map if k not in prop_map)
    changed = {k: {"from": base_map[k], "to": prop_map[k]}
               for k in base_map if k in prop_map and base_map[k] != prop_map[k]}
    return {"added": added, "removed": removed, "changed": changed}


# ---------------------------------------------------------------------------
# signed proposals


def create_proposal(base: Program, proposed: Program, agent: identity.Identity,
                    secret_hex: str, issued_at: str) -> dict:
    changes = diff_programs(base, proposed)
    core = {
        "format_version": FORMAT_VERSION,
        "agent_id": agent.agent_id,
        "algorithm": agent.algorithm,
        "public_key": agent.public_key,
        "base_hash": program_hash(base),
        "program_hash": program_hash(proposed),
        "issued_at": issued_at,
        "changes": changes,
    }
    signature = identity.sign(secret_hex, identity.canonical_json(core))
    return {**core, "signature": signature}


def verify_proposal(proposal: dict, base: Program) -> dict:
    """Fail-closed verification: signature, base hash, and shape.

    Returns the (checked) proposal; raises E6xx StructuredError on any
    problem. Verification does NOT mean acceptance — merge still decides.
    """
    for field in ("agent_id", "algorithm", "public_key", "base_hash",
                  "program_hash", "issued_at", "changes", "signature"):
        if field not in proposal:
            raise StructuredError(
                code="E604", detail=f"malformed proposal: missing {field!r}")
    core = {k: v for k, v in proposal.items() if k != "signature"}
    if not identity.verify(proposal["public_key"], proposal["signature"],
                           identity.canonical_json(core)):
        raise StructuredError(
            code="E602",
            detail=f"proposal signature FAILED for agent "
                   f"{proposal['agent_id']!r} — not from the claimed author")
    actual_base = program_hash(base)
    if proposal["base_hash"] != actual_base:
        raise StructuredError(
            code="E601",
            detail=f"proposal was made against {proposal['base_hash']} but "
                   f"the base is {actual_base} — the graph moved; re-propose")
    return proposal


# ---------------------------------------------------------------------------
# deterministic merge


_UNIT_KEY_RE = {
    "entity": re.compile(r"entity/[a-z_][a-z0-9_]*"),
    "main": re.compile(r"main/[0-9]+"),
    "func": re.compile(r"func/[a-z_][a-z0-9_]*(?:/[0-9]+)?"),
}


def merge_proposals(base: Program, proposals: list[dict]) -> dict:
    """Merge verified proposals against the base.

    Returns {"merged_text", "applied", "conflicts"} — merged_text is None
    when any conflict exists. Identical duplicate changes from two agents
    deduplicate silently; different content for the same unit conflicts.
    """
    units = program_units(base)
    for proposal in proposals:
        for kind in ("added", "changed"):
            for key in proposal["changes"].get(kind, {}):
                scope = key.split("/", 1)[0]
                pattern = _UNIT_KEY_RE.get(scope)
                if pattern is None or not pattern.fullmatch(key):
                    raise StructuredError(
                        code="E604",
                        detail=f"malformed unit key {key!r} in proposal "
                               f"from {proposal['agent_id']!r}")
    merged = Units(entities=dict(units.entities), main=dict(units.main),
                   functions={name: dict(nodes)
                              for name, nodes in units.functions.items()})
    applied: list[dict] = []
    conflicts: list[dict] = []
    # last-writer tracking per unit for conflict attribution
    touched: dict[str, dict] = {}

    def apply_change(agent_id: str, kind: str, key: str, value) -> None:
        scope, *rest = key.split("/", 2)
        if kind == "remove":
            if scope == "entity":
                merged.entities.pop(rest[0], None)
            elif scope == "main":
                merged.main.pop(rest[0], None)
            elif scope == "func":
                if len(rest) == 1:
                    merged.functions.pop(rest[0], None)
                else:
                    merged.functions.get(rest[0], {}).pop(rest[1], None)
            return
        text = value if kind == "add" else value["to"]
        if scope == "entity":
            merged.entities[rest[0]] = text
        elif scope == "main":
            merged.main[rest[0]] = text
        elif scope == "func":
            if len(rest) == 1:
                merged.functions.setdefault(rest[0], {})
            else:
                merged.functions.setdefault(rest[0], {})[rest[1]] = text

    for proposal in proposals:
        agent_id = proposal["agent_id"]
        changes = proposal["changes"]
        for kind, entries in (("add", changes.get("added", {})),
                              ("change", changes.get("changed", {})),
                              ("remove", changes.get("removed", []))):
            items = [(k, entries[k]) for k in sorted(entries)] if isinstance(
                entries, dict) else [(k, None) for k in sorted(entries)]
            for key, value in items:
                # conflict rules: same unit touched with different outcome
                if key in touched:
                    other = touched[key]
                    same = _same_outcome(other, kind, value)
                    if not same:
                        conflicts.append({
                            "unit": key,
                            "agent_a": other["agent_id"],
                            "kind_a": other["kind"],
                            "agent_b": agent_id,
                            "kind_b": kind,
                            "detail": (f"{other['agent_id']} and {agent_id} "
                                       f"both mutate {key!r} differently"),
                        })
                        continue
                touched[key] = {"agent_id": agent_id, "kind": kind,
                                "value": value}
                apply_change(agent_id, kind, key, value)
                applied.append({"agent_id": agent_id, "kind": kind, "unit": key})

    if conflicts:
        return {"merged_text": None, "applied": applied,
                "conflicts": conflicts}

    merged_text = _rebuild_source(merged)
    # a merge is not done until the reconstructed graph still validates;
    # an invalid result is a rejection with a report, not a crash
    from .validator import analyze
    try:
        analyze(parse_source(merged_text))
    except StructuredError as exc:
        return {"merged_text": None, "applied": applied,
                "conflicts": [{
                    "unit": "<whole program>",
                    "agent_a": "runtime", "kind_a": "validation",
                    "agent_b": "runtime", "kind_b": "validation",
                    "detail": f"merged program does not validate: "
                              f"{exc.detail}",
                }]}
    return {"merged_text": merged_text, "applied": applied, "conflicts": []}


def _same_outcome(record: dict, kind: str, value) -> bool:
    if record["kind"] != kind:
        return False
    old = record["value"]
    if kind == "change":
        return old["to"] == value["to"]
    return old == value
