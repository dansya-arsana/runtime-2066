"""In-memory storage adapter (plan SS7 adapters/storage/memory, SS14).

A second, genuinely different implementation of the DataPlane contract
(dict-of-rows instead of SQLite). It exists to PROVE adapter
independence: the same programs run against either store produce the
same results (tests/differential/test_stores.py), so "delete SQLite,
replace with PostgreSQL" is a demonstrated property, not a claim.

Authorization, entity/column validation, and evidence recording reuse
the SQLite plane's logic — only the storage engine differs.
"""

from __future__ import annotations

from .data import DataPlane, _default_value
from .errors import StructuredError


class MemoryPlane(DataPlane):
    """Same contract as DataPlane; rows live in process memory."""

    def __init__(self, entities, grants, now, evidence=None):
        # deliberately NOT calling DataPlane.__init__: no sqlite file,
        # no connection — this class only reuses its validation logic
        self.connection = None
        self.entities = entities
        self.grants = grants
        self.now = now
        self.evidence = evidence
        self._rows: dict[str, dict[int, dict]] = {
            name: {} for name in entities}
        self._next_id: dict[str, int] = {name: 1 for name in entities}

    # ---- storage primitives (everything else is inherited logic) ----

    def insert(self, node_id, entity_name, values) -> int:
        entity = self._entity(node_id, "data.insert", entity_name)
        self._authorize(node_id, "data.write", entity_name)
        value_columns = [c for c in entity.columns if c.type != "identity"]
        row = {"id": self._next_id[entity_name]}
        for column, value in zip(value_columns, values):
            row[column.name] = value
        row_id = self._next_id[entity_name]
        self._rows[entity_name][row_id] = row
        self._next_id[entity_name] += 1
        self._evidence("data.insert", entity_name, f"row={row_id}")
        return row_id

    def count(self, node_id, entity_name, where, value) -> int:
        entity = self._entity(node_id, "data.count", entity_name)
        self._authorize(node_id, "data.read", entity_name)
        self._column(entity, node_id, "data.count", where)
        return sum(1 for row in self._matching(entity_name, where, value))

    def select(self, node_id, entity_name, column, where, value):
        entity = self._entity(node_id, "data.select", entity_name)
        self._authorize(node_id, "data.read", entity_name)
        col = self._column(entity, node_id, "data.select", column)
        self._column(entity, node_id, "data.select", where)
        for row in self._matching(entity_name, where, value):
            value = row.get(column)
            return value if value is not None else _default_value(col.type)
        return _default_value(col.type)

    def update(self, node_id, entity_name, set_col, new_value,
               where, where_value) -> int:
        entity = self._entity(node_id, "data.update", entity_name)
        self._authorize(node_id, "data.write", entity_name)
        self._column(entity, node_id, "data.update", set_col)
        self._column(entity, node_id, "data.update", where)
        changed = 0
        for row in self._matching(entity_name, where, where_value):
            row[set_col] = new_value
            changed += 1
        self._evidence("data.update", entity_name, f"rows={changed}")
        return changed

    def delete(self, node_id, entity_name, where, value) -> int:
        entity = self._entity(node_id, "data.delete", entity_name)
        self._authorize(node_id, "data.delete", entity_name)
        self._column(entity, node_id, "data.delete", where)
        doomed = [row["id"] for row in
                  self._matching(entity_name, where, value)]
        for row_id in doomed:
            del self._rows[entity_name][row_id]
        self._evidence("data.delete", entity_name, f"rows={len(doomed)}")
        return len(doomed)

    def list_rows(self, node_id, entity_name, column, where, value,
                  limit=None) -> list:
        entity = self._entity(node_id, "data.list", entity_name)
        self._authorize(node_id, "data.read", entity_name)
        self._column(entity, node_id, "data.list", column)
        self._column(entity, node_id, "data.list", where)
        rows = [row.get(column) for row in
                self._matching(entity_name, where, value)]
        return rows[:limit] if limit is not None else rows

    def close(self) -> None:
        pass  # nothing to close — the point of the adapter

    # ---- helpers ---------------------------------------------------------

    def _matching(self, entity_name, where, value):
        """Rows where `where` = value, ascending id (SQLite parity)."""
        rows = self._rows.get(entity_name)
        if rows is None:
            raise StructuredError(
                code="E501", operation="data",
                detail=f"unknown entity {entity_name!r}")
        return [row for row_id in sorted(rows)
                for row in [rows[row_id]] if row.get(where) == value]
