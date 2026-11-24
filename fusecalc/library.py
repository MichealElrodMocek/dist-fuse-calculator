"""Conductor library loaded from ``fusecalc/data/conductors.json``.

The list order is the conductor size index fuse_sizing.py expects (see
:func:`conductor_index`); materials are a separate list (see
:func:`conductor_type_index`).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"


@dataclass(frozen=True)
class Conductor:
    name: str
    description: str = ""


@lru_cache(maxsize=1)
def _data() -> dict:
    return json.loads((DATA_DIR / "conductors.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def conductors() -> dict[str, Conductor]:
    return {c["name"]: Conductor(**c) for c in _data()["conductors"]}


def conductor_names() -> list[str]:
    return list(conductors())


def conductor_index(name: str) -> int:
    """Position of ``name`` in the library, i.e. its index in fuseSize's condSize.

    Raises ValueError for a conductor fuseSize has no data for.
    """
    names = conductor_names()
    if name not in names:
        raise ValueError(f"Conductor {name!r} is not in fuseSize's table ({', '.join(names)})")
    return names.index(name)


def conductor_types() -> list[str]:
    """Conductor materials, in the order of condType in fuse_sizing.py."""
    return list(_data()["types"])


def conductor_type_index(name: str) -> int:
    """Position of ``name`` in condType (the ``*TypeChoice`` arguments).

    Raises ValueError for a material fuse_sizing has no data for.
    """
    types = conductor_types()
    if name not in types:
        raise ValueError(f"Conductor material {name!r} is not in fuse_sizing's table "
                         f"({', '.join(types)})")
    return types.index(name)
