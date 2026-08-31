"""Execution budgets (plan SS76-77, review P2): deterministic resource
authority.

Termination is NOT bounded resource consumption — a hostile agent can
submit a legal graph that exhausts memory or CPU. The budget makes
resource limits part of AUTHORITY (SS76: "authority should include
resource limits") with one canonical failure:

    E410  resource budget exceeded

Determinism rule: the countable limits (nodes, steps, literals, list
items, call depth, rows, io bytes) are checked identically in BOTH
adapters at the same semantic points, so the same program + same budget
is rejected identically — budget exhaustion is a structured error, not
a crash, timeout, or OOM. A wall-clock deadline is deliberately NOT
countable; hosts may add one outside the semantic layer.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import StructuredError


@dataclass(frozen=True)
class ExecutionBudget:
    """Resource authority for one execution. All limits inclusive-max."""
    max_nodes: int = 50_000          # nodes in the whole graph
    max_steps: int = 250_000         # node evaluations (semantic steps)
    max_graph_bytes: int = 8_000_000  # source text size
    max_literal_bytes: int = 100_000  # any single const literal
    max_list_items: int = 100_000    # one data.list result
    max_call_depth: int = 64         # nested function calls
    max_io_bytes: int = 4_000_000    # writes + fetched bodies, total
    max_rows: int = 100_000          # rows touched by one mutation


DEFAULT_BUDGET = ExecutionBudget()


def _exceeded(limit_name: str, value, limit, node: str | None,
              op: str = "budget") -> StructuredError:
    return StructuredError(
        code="E410", node=node, operation=op,
        detail=f"resource budget exceeded: {limit_name}={value} "
               f"(limit {limit})",
    )


class BudgetTracker:
    """Per-execution mutable tracker over an ExecutionBudget spec.

    Created fresh for every execute()/execute_plan() call — no shared
    state, thread-safe by construction."""

    def __init__(self, spec: ExecutionBudget | None = None):
        self.spec = spec or DEFAULT_BUDGET
        self._steps = 0
        self._io = 0

    # ---- program-level (checked once, before evaluation) ------------

    def check_program(self, program, source_bytes: int | None = None) -> None:
        nodes = len(program.nodes) + sum(len(f.nodes)
                                         for f in
                                         program.functions.values())
        if nodes > self.spec.max_nodes:
            raise _exceeded("nodes", nodes, self.spec.max_nodes, None)
        if source_bytes is not None and source_bytes > self.spec.max_graph_bytes:
            raise _exceeded("graph_bytes", source_bytes,
                            self.spec.max_graph_bytes, None)
        for scope_nodes in [program.nodes] + [f.nodes for f in
                                              program.functions.values()]:
            for node in scope_nodes.values():
                if node.field("op") == "const" and node.has("value"):
                    size = len(node.field("value"))
                    if size > self.spec.max_literal_bytes:
                        raise _exceeded("literal_bytes", size,
                                        self.spec.max_literal_bytes,
                                        node.id)

    # ---- per-step (identical semantic points in both adapters) ------

    def step(self, node_id: str | None) -> None:
        self._steps += 1
        if self._steps > self.spec.max_steps:
            raise _exceeded("steps", self._steps, self.spec.max_steps,
                            node_id)

    def call_depth(self, depth: int, node_id: str | None) -> None:
        if depth > self.spec.max_call_depth:
            raise _exceeded("call_depth", depth, self.spec.max_call_depth,
                            node_id)

    def list_len(self, items: int, node_id: str | None) -> None:
        if items > self.spec.max_list_items:
            raise _exceeded("list_items", items, self.spec.max_list_items,
                            node_id)

    def rows(self, count: int, node_id: str | None) -> None:
        if count > self.spec.max_rows:
            raise _exceeded("rows", count, self.spec.max_rows, node_id)

    def io(self, payload_bytes: int, node_id: str | None) -> None:
        self._io += payload_bytes
        if self._io > self.spec.max_io_bytes:
            raise _exceeded("io_bytes", self._io, self.spec.max_io_bytes,
                            node_id)
