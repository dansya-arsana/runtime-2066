"""Standard internal contracts (plan SS13) as Python Protocols.

The logical contract is stable and test-enforced; the construct here is
typing.Protocol (structural — adapters don't need to inherit anything,
they just have to BE one). Existing implementations:

    DataStorePort      -> runtime.data.DataPlane (SQLite)
                       -> runtime.memory_store.MemoryPlane (in-memory)
    TransportPort      -> any callable url -> body supplied by the host
                          (net.fetch); the runtime owns no sockets
    ClockPort          -> the `now` argument threaded through authority
                          checks (expiries, sessions) — never ambient
    HumanAuthorityPort -> runtime.keydisk (removable/encrypted disk
                          today; FIDO2/SecureElement adapters later —
                          SS42: the caller must not care which)
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class DataStorePort(Protocol):
    """Semantic storage behind data.* ops. Same program, same grants,
    any conforming store — interchangeable by test
    (tests/differential/test_stores.py)."""

    def insert(self, node_id, entity_name, values) -> int: ...
    def count(self, node_id, entity_name, where, value) -> int: ...
    def select(self, node_id, entity_name, column, where, value): ...
    def update(self, node_id, entity_name, set_col, new_value,
               where, where_value) -> int: ...
    def delete(self, node_id, entity_name, where, value) -> int: ...
    def list_rows(self, node_id, entity_name, column, where, value,
                  limit=None) -> list: ...
    def close(self) -> None: ...


@runtime_checkable
class TransportPort(Protocol):
    """Host-supplied outbound transport: url -> body text. Injected into
    execute(net=...); the core never imports network machinery."""

    def __call__(self, url: str) -> str: ...


@runtime_checkable
class ClockPort(Protocol):
    """Injected time source for expiring authority (SS39)."""

    def now(self): ...


@runtime_checkable
class HumanAuthorityPort(Protocol):
    """Human approval backend (SS42): disk key today, FIDO2/HSM later —
    one interface, swappable without touching semantics."""

    @property
    def identity(self): ...

    def sign(self, delegation: dict) -> dict: ...
