"""Semantic data runtime (roadmap §22–§24): SQLite behind data.* operations.

The AI never writes SQL (§22): entity declarations are grammar-checked,
column names become identifier-validated SQL fragments, and every value is
a bound `?` parameter — string payloads like `x'; DROP TABLE user;--` are
inert data. Every operation is capability-checked first (`data.read`,
`data.write`, `data.delete` per entity — §24: a read grant cannot delete).

Default deny: data operations with no database attached are denied, like
every other effect. Scalar in, scalar out — V0 has no collections, so the
app shell batches row-by-row through the same verified engine.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime

from .capabilities import GrantSet
from .errors import StructuredError
from .parser import Entity


class DataPlane:
    def __init__(self, db_path: str, entities: dict[str, Entity],
                 grants: GrantSet | None, now: datetime | None,
                 auto_create: bool = True, evidence=None):
        # busy timeout + WAL: concurrent engines (web server, MCP server)
        # must queue briefly instead of failing with "database is locked"
        # under parallel load.
        self.connection = sqlite3.connect(db_path, timeout=5.0)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.entities = entities
        self.grants = grants
        self.now = now
        self.evidence = evidence
        if auto_create:
            for entity in entities.values():
                self.connection.execute(self._create_table_sql(entity))
            self.connection.commit()

    def _evidence(self, action: str, resource: str, detail: str) -> None:
        if self.evidence is not None:
            self.evidence.append(action, resource, detail)

    # ---- entry points called by both adapters -----------------------------

    def insert(self, node_id: str, entity_name: str, values: list) -> int:
        entity = self._entity(node_id, "data.insert", entity_name)
        self._authorize(node_id, "data.write", entity_name)
        columns = [c for c in entity.columns if c.type != "identity"]
        names = ", ".join(c.name for c in columns)
        marks = ", ".join("?" for _ in columns)
        try:
            cursor = self.connection.execute(
                f"INSERT INTO {entity.name} ({names}) VALUES ({marks})",
                values)
            self.connection.commit()
        except sqlite3.Error as exc:
            raise self._sqlite_error(node_id, "data.insert", entity_name, exc)
        self._evidence("data.insert", entity_name,
                       f"rowid={cursor.lastrowid}")
        return cursor.lastrowid

    def count(self, node_id: str, entity_name: str, where: str,
              value) -> int:
        entity = self._entity(node_id, "data.count", entity_name)
        self._authorize(node_id, "data.read", entity_name)
        self._column(entity, node_id, "data.count", where)
        try:
            row = self.connection.execute(
                f"SELECT COUNT(*) FROM {entity.name} WHERE {where} = ?",
                (value,)).fetchone()
        except sqlite3.Error as exc:
            raise self._sqlite_error(node_id, "data.count", entity_name, exc)
        return int(row[0])

    def select(self, node_id: str, entity_name: str, column: str,
               where: str, value):
        entity = self._entity(node_id, "data.select", entity_name)
        self._authorize(node_id, "data.read", entity_name)
        col = self._column(entity, node_id, "data.select", column)
        self._column(entity, node_id, "data.select", where)
        try:
            row = self.connection.execute(
                f"SELECT {column} FROM {entity.name} WHERE {where} = ?",
                (value,)).fetchone()
        except sqlite3.Error as exc:
            raise self._sqlite_error(node_id, "data.select", entity_name, exc)
        if row is None or row[0] is None:
            return _default_value(col.type)
        return row[0]

    def update(self, node_id: str, entity_name: str, set_col: str,
               new_value, where: str, where_value) -> int:
        entity = self._entity(node_id, "data.update", entity_name)
        self._authorize(node_id, "data.write", entity_name)
        self._column(entity, node_id, "data.update", set_col)
        self._column(entity, node_id, "data.update", where)
        try:
            cursor = self.connection.execute(
                f"UPDATE {entity.name} SET {set_col} = ? WHERE {where} = ?",
                (new_value, where_value))
            self.connection.commit()
        except sqlite3.Error as exc:
            raise self._sqlite_error(node_id, "data.update", entity_name, exc)
        self._evidence("data.update", entity_name, f"rows={cursor.rowcount}")
        return cursor.rowcount

    def delete(self, node_id: str, entity_name: str, where: str,
               value) -> int:
        entity = self._entity(node_id, "data.delete", entity_name)
        self._authorize(node_id, "data.delete", entity_name)
        self._column(entity, node_id, "data.delete", where)
        try:
            cursor = self.connection.execute(
                f"DELETE FROM {entity.name} WHERE {where} = ?", (value,))
            self.connection.commit()
        except sqlite3.Error as exc:
            raise self._sqlite_error(node_id, "data.delete", entity_name, exc)
        self._evidence("data.delete", entity_name, f"rows={cursor.rowcount}")
        return cursor.rowcount

    def list_rows(self, node_id: str, entity_name: str, column: str,
                  where: str, value, limit: int | None = None) -> list:
        """Matching rows' column values ordered by id; `limit` caps count."""
        entity = self._entity(node_id, "data.list", entity_name)
        self._authorize(node_id, "data.read", entity_name)
        self._column(entity, node_id, "data.list", column)
        self._column(entity, node_id, "data.list", where)
        sql = (f"SELECT {column} FROM {entity.name} WHERE {where} = ? "
               f"ORDER BY id")
        params: list = [value]
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        try:
            rows = self.connection.execute(sql, params).fetchall()
        except sqlite3.Error as exc:
            raise self._sqlite_error(node_id, "data.list", entity_name, exc)
        return [row[0] for row in rows]

    def close(self) -> None:
        self.connection.close()

    # ---- schema migration (roadmap §25) ------------------------------------

    def schema_drift(self) -> list[dict]:
        """Diff declared entities against the actual tables.

        Safe drift: newly declared columns (additive, no data loss).
        Breaking drift: removed columns, type changes, unknown tables —
        reported with a data-loss explanation and never auto-applied.
        """
        steps: list[dict] = []
        existing_tables = {
            row[0] for row in self.connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")
        }
        sql_types = {"bool": "INTEGER", "i64": "INTEGER", "f64": "REAL",
                     "string": "TEXT"}
        for entity in self.entities.values():
            if entity.name not in existing_tables:
                steps.append({
                    "kind": "create", "entity": entity.name, "breaking": False,
                    "detail": "table does not exist yet",
                    "sql": self._create_table_sql(entity),
                })
                continue
            actual = {row[1]: row[2].upper() for row in
                      self.connection.execute(f"PRAGMA table_info({entity.name})")}
            declared = {c.name: "INTEGER" if c.type == "identity"
                        else sql_types[c.type]
                        for c in entity.columns}
            for col in entity.columns:
                if col.name not in actual:
                    steps.append({
                        "kind": "add_column", "entity": entity.name,
                        "breaking": False,
                        "detail": f"column {col.name} ({col.type}) is new",
                        "sql": (f"ALTER TABLE {entity.name} ADD COLUMN "
                                f"{col.name} {sql_types[col.type]}"),
                    })
                elif actual[col.name] != declared[col.name]:
                    steps.append({
                        "kind": "type_change", "entity": entity.name,
                        "breaking": True,
                        "detail": (f"column {col.name}: table has "
                                   f"{actual[col.name]}, program declares "
                                   f"{declared[col.name]} — conversion may "
                                   f"lose data"),
                    })
            for name in actual:
                if name != "id" and name not in declared:
                    steps.append({
                        "kind": "drop_column", "entity": self.entities[
                            entity.name].name,
                        "breaking": True,
                        "detail": (f"column {name} exists in the table but "
                                   f"not in the program — applying would "
                                   f"destroy its data"),
                    })
        return steps

    def apply_safe_steps(self, steps: list[dict]) -> int:
        """Apply only non-breaking steps (create table / add column).

        Returns the number of applied steps. Breaking steps are refused —
        destructive migration requires a human decision, never an agent's.
        """
        applied = 0
        for step in steps:
            if step["breaking"]:
                continue
            self.connection.execute(step["sql"])
            applied += 1
        self.connection.commit()
        return applied

    # ---- internals ---------------------------------------------------------

    def _entity(self, node_id: str, op: str, name: str) -> Entity:
        entity = self.entities.get(name)
        if entity is None:
            raise StructuredError(
                code="E501", node=node_id, operation=op,
                detail=f"unknown entity {name!r}",
            )
        return entity

    def _column(self, entity: Entity, node_id: str, op: str, name: str):
        for col in entity.columns:
            if col.name == name:
                return col
        raise StructuredError(
            code="E502", node=node_id, operation=op,
            detail=f"entity {entity.name!r} has no column {name!r}",
        )

    def _authorize(self, node_id: str, action: str, entity_name: str) -> None:
        if self.grants is None:
            raise StructuredError(
                code="E401", node=node_id, operation=action,
                detail="denied: no capability system attached; "
                       "data effects require explicit grants (default deny)",
            )
        self.grants.check(action, entity_name, self.now, node=node_id)

    def _create_table_sql(self, entity: Entity) -> str:
        """Built ONLY from grammar-validated identifiers and types."""
        defs = ["id INTEGER PRIMARY KEY AUTOINCREMENT"]
        for col in entity.columns:
            if col.type == "identity":
                continue
            sql_type = {"bool": "INTEGER", "i64": "INTEGER",
                        "f64": "REAL", "string": "TEXT"}[col.type]
            defs.append(f"{col.name} {sql_type}"
                        + (" UNIQUE" if col.unique else ""))
        return f"CREATE TABLE IF NOT EXISTS {entity.name} ({', '.join(defs)})"

    def _sqlite_error(self, node_id: str, op: str, entity_name: str,
                      exc: Exception) -> StructuredError:
        return StructuredError(
            code="E505", node=node_id, operation=op,
            detail=f"data error on entity {entity_name!r}: {exc}",
        )


def _default_value(col_type: str):
    if col_type == "identity" or col_type == "i64":
        return 0
    if col_type == "f64":
        return 0.0
    if col_type == "bool":
        return False
    return ""
