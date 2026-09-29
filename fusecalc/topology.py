"""Radial topology: orientation from the source, validation, load roll-up.

Everything here is derived from a :class:`~fusecalc.model.Feeder` and is
cheap enough to recompute on every edit.
"""

from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

from fusecalc.model import Feeder, Source, Transformer, phases_subset


@dataclass
class Issue:
    severity: str  # "error" | "warning"
    message: str
    element_id: str | None = None


@dataclass
class RadialTree:
    """The feeder oriented away from the source.

    Transformers are treated as end points: the walk never continues through
    one, so anything wired beyond a transformer shows up as unreachable.
    """

    source_id: str | None
    parent: dict[str, str | None] = field(default_factory=dict)
    parent_segment: dict[str, str] = field(default_factory=dict)  # node -> feeding segment
    children: dict[str, list[str]] = field(default_factory=dict)  # node -> child segments
    order: list[str] = field(default_factory=list)  # nodes, breadth-first from source
    distance_ft: dict[str, float] = field(default_factory=dict)
    upstream: dict[str, str] = field(default_factory=dict)  # segment -> upstream node
    downstream: dict[str, str] = field(default_factory=dict)  # segment -> downstream node
    loop_segments: list[str] = field(default_factory=list)
    unreachable: list[str] = field(default_factory=list)

    def reaches(self, node_id: str) -> bool:
        return node_id in self.parent

    def segment_order(self) -> list[str]:
        """Oriented segments, parents before children."""
        return [self.parent_segment[n] for n in self.order if n in self.parent_segment]

    def path_segments(self, node_id: str) -> list[str]:
        """Segments from ``node_id`` back up to the source (nearest first)."""
        path = []
        while node_id in self.parent_segment:
            seg_id = self.parent_segment[node_id]
            path.append(seg_id)
            node_id = self.upstream[seg_id]
        return path

    def subtree_segments(self, seg_id: str) -> list[str]:
        """``seg_id`` plus every segment downstream of it."""
        out, stack = [], [seg_id]
        while stack:
            s = stack.pop()
            out.append(s)
            stack.extend(self.children.get(self.downstream[s], []))
        return out


def build_tree(feeder: Feeder) -> RadialTree:
    src = feeder.source
    tree = RadialTree(source_id=src.id if src else None)
    if src is None:
        tree.unreachable = list(feeder.nodes)
        return tree

    adjacency: dict[str, list[tuple[str, str]]] = {n: [] for n in feeder.nodes}
    for s in feeder.segments.values():
        adjacency[s.node_a].append((s.id, s.node_b))
        adjacency[s.node_b].append((s.id, s.node_a))

    tree.parent[src.id] = None
    tree.distance_ft[src.id] = 0.0
    seen_segments: set[str] = set()
    queue = deque([src.id])
    while queue:
        node_id = queue.popleft()
        tree.order.append(node_id)
        tree.children[node_id] = []
        if isinstance(feeder.nodes[node_id], Transformer):
            continue
        for seg_id, other in adjacency[node_id]:
            if seg_id in seen_segments:
                continue
            seen_segments.add(seg_id)
            if other in tree.parent:
                tree.loop_segments.append(seg_id)
                continue
            tree.parent[other] = node_id
            tree.parent_segment[other] = seg_id
            tree.upstream[seg_id] = node_id
            tree.downstream[seg_id] = other
            tree.distance_ft[other] = tree.distance_ft[node_id] + feeder.segments[seg_id].length_ft
            tree.children[node_id].append(seg_id)
            queue.append(other)

    tree.unreachable = [n for n in feeder.nodes if n not in tree.parent]
    return tree


def supply_phases(feeder: Feeder, tree: RadialTree, node_id: str) -> str:
    """Phases available at a node (what its feeding segment carries)."""
    seg_id = tree.parent_segment.get(node_id)
    if seg_id is None:
        return "ABC"
    return feeder.segments[seg_id].phases


# ------------------------------------------------------------------ loads


@dataclass
class PhaseLoad:
    """Connected load downstream of a segment, split by phase.

    Currents are arithmetic sums of transformer full-load currents (angles
    ignored), which slightly overstates current where line-to-line and
    line-to-neutral units mix. Good enough for continuous-current screening.
    """

    kva: dict[str, float] = field(default_factory=lambda: dict.fromkeys("ABC", 0.0))
    amps: dict[str, float] = field(default_factory=lambda: dict.fromkeys("ABC", 0.0))
    transformer_count: int = 0

    @property
    def total_kva(self) -> float:
        return sum(self.kva.values())

    @property
    def max_amps(self) -> float:
        return max(self.amps.values())

    def imbalance_pct(self, phases: str = "ABC") -> float:
        """Max deviation from the average phase current, as % of the average."""
        vals = [self.amps[p] for p in phases]
        avg = sum(vals) / len(vals)
        if len(vals) < 2 or avg <= 0:
            return 0.0
        return 100.0 * max(abs(v - avg) for v in vals) / avg

    def add(self, other: PhaseLoad) -> None:
        for p in "ABC":
            self.kva[p] += other.kva[p]
            self.amps[p] += other.amps[p]
        self.transformer_count += other.transformer_count


def transformer_load(tx: Transformer, kv_ll: float) -> PhaseLoad:
    load = PhaseLoad(transformer_count=1)
    n = len(tx.phases)
    if n == 1:
        amps = tx.kva / (kv_ll / math.sqrt(3))
    elif n == 2:
        amps = tx.kva / kv_ll
    else:
        amps = tx.kva / (math.sqrt(3) * kv_ll)
    for p in tx.phases:
        load.kva[p] += tx.kva / n
        load.amps[p] += amps
    return load


def segment_loads(feeder: Feeder, tree: RadialTree) -> dict[str, PhaseLoad]:
    """Downstream connected load for every oriented segment."""
    kv = feeder.settings.nominal_kv_ll
    loads: dict[str, PhaseLoad] = {}
    for seg_id in reversed(tree.segment_order()):
        down = tree.downstream[seg_id]
        load = PhaseLoad()
        node = feeder.nodes[down]
        if isinstance(node, Transformer) and kv > 0:
            load.add(transformer_load(node, kv))
        for child in tree.children.get(down, []):
            load.add(loads[child])
        loads[seg_id] = load
    return loads


def feeder_load(tree: RadialTree, loads: dict[str, PhaseLoad]) -> PhaseLoad:
    total = PhaseLoad()
    if tree.source_id:
        for seg_id in tree.children.get(tree.source_id, []):
            total.add(loads[seg_id])
    return total


# ------------------------------------------------------------ protection


@dataclass(frozen=True)
class CoordinationPair:
    """A downstream (protecting) fuse and the nearest fuse upstream of it
    (protected). The protecting link must clear before the protected link is
    damaged, up to the fault current available at the protecting fuse."""

    protecting_fuse: str
    protected_fuse: str
    protecting_segment: str
    protected_segment: str


def upstream_fused_segment(feeder: Feeder, tree: RadialTree, seg_id: str) -> str | None:
    """Nearest segment strictly upstream of ``seg_id`` that carries a fuse."""
    for s in tree.path_segments(tree.upstream[seg_id]):
        if feeder.segments[s].fuse is not None:
            return s
    return None


def coordination_pairs(feeder: Feeder, tree: RadialTree) -> list[CoordinationPair]:
    pairs = []
    for seg_id in tree.segment_order():
        fuse = feeder.segments[seg_id].fuse
        if fuse is None:
            continue
        up = upstream_fused_segment(feeder, tree, seg_id)
        if up is not None:
            pairs.append(CoordinationPair(fuse.id, feeder.segments[up].fuse.id, seg_id, up))
    return pairs


# ------------------------------------------------------------- validation


def validate(feeder: Feeder, tree: RadialTree | None = None) -> list[Issue]:
    tree = tree or build_tree(feeder)
    issues: list[Issue] = []
    st = feeder.settings

    sources = feeder.sources()
    if not sources:
        issues.append(Issue("error", "Feeder has no source."))
    elif len(sources) > 1:
        for s in sources[1:]:
            issues.append(Issue("error", "Only one source is allowed on a radial feeder.", s.id))

    if st.nominal_kv_ll <= 0:
        issues.append(Issue("error", "Nominal voltage must be positive."))
    if st.fault_3ph_a <= 0 or st.fault_slg_a <= 0:
        issues.append(Issue("error", "Available fault currents must be positive."))

    for seg_id in tree.loop_segments:
        issues.append(Issue("error", "Segment closes a loop; the feeder must be radial.", seg_id))

    for node_id in tree.unreachable:
        node = feeder.nodes[node_id]
        if isinstance(node, Source):
            continue
        sev = "error" if isinstance(node, Transformer) else "warning"
        issues.append(Issue(sev, f"{node.label()} is not connected to the source.", node_id))

    for node in feeder.nodes.values():
        if not isinstance(node, Transformer):
            continue
        degree = len(feeder.segments_at(node.id))
        if degree > 1:
            issues.append(Issue(
                "error", f"{node.label()} has {degree} connections; a transformer must "
                "be the end of a branch.", node.id))
        if node.kva <= 0:
            issues.append(Issue("warning", f"{node.label()} has no kVA rating.", node.id))
        if tree.reaches(node.id):
            avail = supply_phases(feeder, tree, node.id)
            if not phases_subset(node.phases, avail):
                issues.append(Issue(
                    "error", f"{node.label()} is connected {node.phases} but its "
                    f"supply only carries {avail}.", node.id))

    for seg_id in tree.segment_order():
        seg = feeder.segments[seg_id]
        avail = supply_phases(feeder, tree, tree.upstream[seg_id])
        if not phases_subset(seg.phases, avail):
            issues.append(Issue(
                "error", f"{seg.label()} carries {seg.phases} but is fed from a "
                f"{avail} segment.", seg_id))
        if seg.length_ft < 0:
            issues.append(Issue("error", f"{seg.label()} has a negative length.", seg_id))

    return issues
