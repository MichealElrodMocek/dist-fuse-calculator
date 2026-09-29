"""Conductor library loaded from ``fusecalc/data/conductors.json``."""

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
    r1: float | None = None  # positive-sequence ohms/mile
    x1: float | None = None
    r0: float | None = None  # zero-sequence ohms/mile
    x0: float | None = None
    ampacity_a: float | None = None

    @property
    def has_impedance(self) -> bool:
        return None not in (self.r1, self.x1, self.r0, self.x0)


@lru_cache(maxsize=1)
def conductors() -> dict[str, Conductor]:
    data = json.loads((DATA_DIR / "conductors.json").read_text(encoding="utf-8"))
    return {c["name"]: Conductor(**c) for c in data["conductors"]}


def conductor_names() -> list[str]:
    return list(conductors())
