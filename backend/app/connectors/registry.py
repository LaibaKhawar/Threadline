from __future__ import annotations

from typing import Any

from app.connectors.base import Connector

_REGISTRY: dict[str, type[Connector]] = {}


def register(cls: type[Connector]) -> type[Connector]:
    _REGISTRY[cls.kind] = cls
    return cls


def get_connector(kind: str) -> type[Connector]:
    _load()
    if kind not in _REGISTRY:
        raise KeyError(f"unknown connector {kind}")
    return _REGISTRY[kind]


def catalog() -> list[dict[str, Any]]:
    _load()
    return [
        {"kind": c.kind, "name": c.display_name, "description": c.description, "item_kinds": list(c.item_kinds),
         "requires_network": c.requires_network, "auth": c.auth, "implemented": c.implemented,
         "incremental": c.supports_incremental}
        for c in _REGISTRY.values()
    ]


def _load() -> None:
    from app.connectors import demo, google, local_files, planned  # noqa: F401
