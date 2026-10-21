"""Conductor library loaded from ``fusecalc/data/conductors.json``.

The list order is the conductor index ``fuseSize`` expects; see
:func:`conductor_index`.
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
def conductors() -> dict[str, Conductor]:
    data = json.loads((DATA_DIR / "conductors.json").read_text(encoding="utf-8"))
    return {c["name"]: Conductor(**c) for c in data["conductors"]}


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
