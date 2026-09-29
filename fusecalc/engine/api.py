"""Contract between the GUI and the protection engine.

The GUI builds a :class:`StudyContext` (feeder + precomputed topology), hands
it to ``engine.run(ctx)``, and displays the :class:`StudyResults` it returns.
Nothing in here imports Qt, so an engine can be developed and unit tested on
its own - see ``tests/test_engine_contract.py``.

To plug in a real engine, implement a class with a ``name`` attribute and a
``run(ctx) -> StudyResults`` method, then return it from
:func:`fusecalc.engine.default_engine`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from fusecalc.model import Feeder
from fusecalc.topology import (
    CoordinationPair,
    Issue,
    PhaseLoad,
    RadialTree,
    build_tree,
    coordination_pairs,
    segment_loads,
    validate,
)


@dataclass
class StudyContext:
    """Everything the engine needs, already worked out from the drawing.

    * ``tree.upstream[seg_id]`` is the node where that segment's fuse sits,
      so the fault current "at a fuse" is the fault at that node.
    * ``loads[seg_id]`` is the connected load downstream of a segment, by phase.
    * ``pairs`` lists each fuse with the nearest fuse upstream of it.
    """

    feeder: Feeder
    tree: RadialTree
    loads: dict[str, PhaseLoad]
    pairs: list[CoordinationPair]
    issues: list[Issue]

    @property
    def has_errors(self) -> bool:
        return any(i.severity == "error" for i in self.issues)

    def fuse_node(self, fuse_id: str) -> str | None:
        """Node where a fuse is physically located (its segment's upstream end)."""
        seg = self.feeder.fuse_segment(fuse_id)
        return self.tree.upstream.get(seg.id) if seg else None


def build_context(feeder: Feeder) -> StudyContext:
    tree = build_tree(feeder)
    return StudyContext(
        feeder=feeder,
        tree=tree,
        loads=segment_loads(feeder, tree),
        pairs=coordination_pairs(feeder, tree),
        issues=validate(feeder, tree),
    )


@dataclass
class NodeFault:
    """Fault currents at a node, in amperes (symmetrical RMS)."""

    i3ph_a: float  # maximum: bolted three-phase (only meaningful on 3-phase line)
    islg_a: float  # maximum: bolted single-line-to-ground
    imin_a: float  # minimum: e.g. SLG through fault resistance; sets fuse reach

    @property
    def imax_a(self) -> float:
        return max(self.i3ph_a, self.islg_a)


@dataclass
class LinkSelection:
    link_type: str  # "K", "T", "H" or "N"
    rating_a: float
    load_a: float  # the design load current the link was sized against
    ok: bool = True  # False if no standard link satisfies every criterion
    note: str = ""

    def label(self) -> str:
        return f"{self.rating_a:g}{self.link_type}"


@dataclass
class CoordinationResult:
    protecting_fuse: str  # downstream link, must clear first
    protected_fuse: str  # upstream link, must not be damaged
    fault_current_a: float | None = None  # max fault at the protecting fuse
    limit_a: float | None = None  # max coordinating current from the table
    status: str = "not_checked"  # "pass" | "fail" | "not_checked"
    note: str = ""

    @property
    def margin_a(self) -> float | None:
        if self.fault_current_a is None or self.limit_a is None:
            return None
        return self.limit_a - self.fault_current_a


@dataclass
class StudyResults:
    engine: str
    faults: dict[str, NodeFault] = field(default_factory=dict)  # by node id
    links: dict[str, LinkSelection] = field(default_factory=dict)  # by fuse id
    coordination: list[CoordinationResult] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    is_placeholder: bool = False

    def coordination_for(self, fuse_id: str) -> CoordinationResult | None:
        """The check of ``fuse_id`` against the fuse upstream of it."""
        return next((c for c in self.coordination if c.protecting_fuse == fuse_id), None)


class ProtectionEngine(Protocol):
    name: str

    def run(self, ctx: StudyContext) -> StudyResults: ...
