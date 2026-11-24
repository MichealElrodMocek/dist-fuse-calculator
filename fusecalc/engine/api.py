"""Contract between the GUI and the fuse sizing solver.

The solver is :mod:`fusecalc.engine.fuse_sizing`, three functions:

* ``feederTapCurrent``: SLG fault current at a point on the feeder primary
  (used at the first fuse of each branch),
* ``latFuseCurrent``: SLG fault current one lateral run further on, from the
  fault current where the run starts (used between fuses),
* ``fuseSize``: the T link for a fuse, from the fault current there, the
  load and largest transformer below it, and its largest child fuse,
* ``xfmrFuseSize``: the T link for a transformer cutout (fuseSize's 125 %
  rule on its own).

The GUI works out each function's arguments from the drawing (the
``*Inputs`` records below, named exactly as the solver names them), calls
it, and displays the :class:`StudyResults`.

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


# The ``*Choice`` fields below are indices into fuse_sizing's own tables
# (condSize, condType, condTempVec), not physical values.


@dataclass
class FeederTapInputs:
    """One call to ``feederTapCurrent``: its arguments, names and units unchanged."""

    V_ll: float  # volts, line to line
    feederLengthFt: float  # feeder primary from the source to the fuse
    soilResistivity: float  # ohm-meters
    D_an: float  # feet, closest phase conductor to the neutral
    S_sc: float  # VA, fault power at the substation transformer
    x_over_r: float
    priSizeChoice: int
    priTypeChoice: int
    neutSizeChoice: int
    neutTypeChoice: int
    latPriSizeChoice: int  # unused by feederTapCurrent; sent as the fused segment's
    latPriTypeChoice: int
    condTempChoice: int


@dataclass
class LatFuseInputs:
    """One call to ``latFuseCurrent`` for one drawn segment.

    ``I_f_previous`` is the complex fault current where the segment starts
    (``returnPhasor=True`` from the previous call), so chaining calls along a
    path is exact.
    """

    V_ll: float
    I_f_previous: complex  # A, fault current phasor at the upstream end
    x_over_r: float
    latLengthFt: float  # this segment's length
    latPriSizeChoice: int  # this segment's conductor
    latPriTypeChoice: int
    latNeutSizeChoice: int  # Study panel neutral
    latNeutTypeChoice: int
    soilResistivity: float
    condTempChoice: int
    D_an: float


@dataclass
class FuseSizeInputs:
    """One call to ``fuseSize``: its arguments, names and units unchanged."""

    V_ll: float
    I_LG_mag: float  # A, SLG fault current at the fuse
    downstreamPriSizeChoice: int  # the fused segment's conductor
    latLoadA: float  # kVA downstream of the fuse, per phase
    latLoadB: float
    latLoadC: float
    latLargestXFMR_A: float  # kVA of the largest transformer downstream, per phase
    latLargestXFMR_B: float
    latLargestXFMR_C: float
    largestChildNonTX: float  # largest fuse directly below that isn't a transformer cutout


@dataclass
class XfmrFuseInputs:
    """One call to ``xfmrFuseSize`` for a transformer cutout."""

    V_ll: float
    latLargestXFMR_A: float  # kVA of the transformer, per phase
    latLargestXFMR_B: float
    latLargestXFMR_C: float


@dataclass
class NodeFault:
    """Fault currents at a node, in amperes (symmetrical RMS).

    fuse_sizing computes the bolted SLG fault only, at fuse locations, so the
    three-phase and minimum faults stay None.
    """

    islg_a: float  # maximum: bolted single-line-to-ground
    i3ph_a: float | None = None  # maximum: bolted three-phase
    imin_a: float | None = None  # minimum: e.g. SLG through fault resistance

    @property
    def imax_a(self) -> float:
        return max(i for i in (self.i3ph_a, self.islg_a) if i is not None)


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
    """fuseSize coordinates each fuse with its largest child internally but
    doesn't return the table limit, so every pair comes back
    ``"not_checked"`` with the fault current at the protecting fuse filled in."""

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
    inputs: dict[str, FuseSizeInputs | XfmrFuseInputs] = field(default_factory=dict)  # by fuse id
    # by fuse id: the fault-current calls that reached it (one feederTapCurrent
    # for the first fuse of a branch, else one latFuseCurrent per segment from
    # the fuse above)
    fault_inputs: dict[str, list[FeederTapInputs | LatFuseInputs]] = field(default_factory=dict)
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
