"""Contract between the GUI and the fuse sizing solver.

The solver is ``fuseSize`` in :mod:`fusecalc.engine.fuse_sizing`. It sizes the
first T link of a branch from 16 scalar inputs and returns its rating. The GUI
works out those inputs for each fuse from the drawing
(:class:`FuseSizeInputs`, named exactly as ``fuseSize`` names them), calls it,
and displays the :class:`StudyResults`.

Nothing in here imports Qt, so the solver and this adapter can be tested
without a display.
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
    """The feeder plus the topology worked out from the drawing.

    * ``tree.upstream[seg_id]`` is the node where that segment's fuse sits.
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
class FuseSizeInputs:
    """One call to ``fuseSize``: its arguments, names and units unchanged.

    The ``*Choice`` fields are indices into fuseSize's own tables (condSize,
    condTempVec), not physical values.
    """

    V_ll: float  # volts, line to line
    feederLengthFt: float  # feeder primary from the source to the fuse
    soilResistivity: float  # ohm-meters
    D_an: float  # feet, closest phase conductor to the neutral
    S_sc: float  # VA, fault power at the substation transformer
    x_over_r: float
    priSizeChoice: int
    neutSizeChoice: int
    latPriSizeChoice: int
    condTempChoice: int
    latLoadA: float  # kVA downstream of the fuse, per phase
    latLoadB: float
    latLoadC: float
    latLargestXFMR_A: float  # kVA of the largest transformer downstream, per phase
    latLargestXFMR_B: float
    latLargestXFMR_C: float


@dataclass
class NodeFault:
    """Fault currents at a node, in amperes (symmetrical RMS).

    fuseSize doesn't return fault currents yet, so the GUI shows these as
    not available.
    """

    i3ph_a: float  # maximum: bolted three-phase (only meaningful on 3-phase line)
    islg_a: float  # maximum: bolted single-line-to-ground
    imin_a: float  # minimum: e.g. SLG through fault resistance; sets fuse reach

    @property
    def imax_a(self) -> float:
        return max(self.i3ph_a, self.islg_a)


@dataclass
class LinkSelection:
    """The T link for one fuse.

    ``rating_a`` is None when the fuse wasn't sized. That is ``ok`` when
    fuseSize doesn't cover the fuse (the note says why) and not ``ok`` when
    fuseSize failed or couldn't be called.
    """

    rating_a: float | None
    load_a: float  # peak phase load current downstream of the fuse
    ok: bool = True  # False if fuseSize warned or failed
    note: str = ""

    def label(self) -> str:
        return "not sized" if self.rating_a is None else f"{self.rating_a:g}T"


@dataclass
class CoordinationResult:
    """fuseSize checks coordination internally but doesn't return it yet, so
    every pair comes back ``"not_checked"``."""

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
    inputs: dict[str, FuseSizeInputs] = field(default_factory=dict)  # by fuse id
    faults: dict[str, NodeFault] = field(default_factory=dict)  # by node id
    links: dict[str, LinkSelection] = field(default_factory=dict)  # by fuse id
    coordination: list[CoordinationResult] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    def coordination_for(self, fuse_id: str) -> CoordinationResult | None:
        """The check of ``fuse_id`` against the fuse upstream of it."""
        return next((c for c in self.coordination if c.protecting_fuse == fuse_id), None)


class ProtectionEngine(Protocol):
    name: str

    def run(self, ctx: StudyContext) -> StudyResults: ...
