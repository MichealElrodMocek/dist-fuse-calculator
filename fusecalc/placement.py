"""Rule-based fuse placement.

The rules mirror common overhead distribution practice:

1. **Transformer** - every distribution transformer gets a primary cutout.
2. **Lateral** - every branch leaving the mainline is fused at the tap, so a
   lateral fault is cleared without locking out the feeder breaker/recloser.
3. **Sub-lateral** - where a lateral splits, the side branches are fused and
   the branch carrying the most load continues as the lateral.
4. **Sectionalizing** - a long lateral gets another fuse once the line length
   past the last upstream fuse exceeds a threshold, to limit outage extent.

The mainline itself is left to the substation breaker or line recloser.
Rules are applied in that priority order, and a candidate is skipped when it
would put more than ``max_fuses_in_series`` fuses between the source and any
transformer, since every extra link in series makes coordination harder.

Manually placed fuses are always kept and count toward the series limit.
Fuses from a previous auto-placement are discarded and re-planned.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fusecalc.model import Feeder, PlacementPolicy, Transformer
from fusecalc.topology import Issue, PhaseLoad, RadialTree, build_tree, segment_loads, validate

RULE_PRIORITY = {"transformer": 0, "lateral": 1, "sublateral": 2, "sectionalizing": 3}
RULE_LABELS = {
    "transformer": "Transformer",
    "lateral": "Lateral tap",
    "sublateral": "Sub-lateral",
    "sectionalizing": "Sectionalizing",
}


@dataclass
class FuseProposal:
    segment_id: str
    rule: str
    reason: str
    accepted: bool = True
    skip_reason: str = ""


@dataclass
class PlacementResult:
    proposals: list[FuseProposal] = field(default_factory=list)
    mainline: set[str] = field(default_factory=set)
    removed_auto: list[str] = field(default_factory=list)  # segments losing an old auto fuse
    issues: list[Issue] = field(default_factory=list)

    @property
    def accepted(self) -> list[FuseProposal]:
        return [p for p in self.proposals if p.accepted]


def find_mainline(feeder: Feeder, tree: RadialTree, loads: dict[str, PhaseLoad],
                  rule: str) -> set[str]:
    """Segments treated as mainline (protected by the upstream breaker/recloser)."""
    if tree.source_id is None:
        return set()

    def is_drop(seg_id: str) -> bool:
        return isinstance(feeder.nodes[tree.downstream[seg_id]], Transformer)

    mainline: set[str] = set()
    if rule == "heaviest_path":
        node = tree.source_id
        while True:
            options = [s for s in tree.children.get(node, []) if not is_drop(s)]
            if not options:
                break
            best = max(options, key=lambda s: (loads[s].total_kva,
                                               len(tree.subtree_segments(s))))
            mainline.add(best)
            node = tree.downstream[best]
        return mainline

    # "three_phase": every three-phase line reachable through three-phase line.
    stack = [tree.source_id]
    while stack:
        node = stack.pop()
        for s in tree.children.get(node, []):
            if feeder.segments[s].phases == "ABC" and not is_drop(s):
                mainline.add(s)
                stack.append(tree.downstream[s])
    return mainline


def _continuation(tree: RadialTree, loads: dict[str, PhaseLoad], options: list[str]) -> str:
    return max(options, key=lambda s: (loads[s].total_kva, len(tree.subtree_segments(s))))


def plan_fuses(feeder: Feeder, policy: PlacementPolicy | None = None) -> PlacementResult:
    """Propose fuse locations. Does not modify ``feeder``."""
    policy = policy or feeder.placement
    result = PlacementResult()
    result.removed_auto = [s.id for s, f in feeder.fuses() if f.origin == "auto"]

    # Plan against a copy that has only the fuses we are keeping.
    work = feeder.copy()
    for seg_id in result.removed_auto:
        work.segments[seg_id].fuse = None

    tree = build_tree(work)
    result.issues = [i for i in validate(work, tree) if i.severity == "error"]
    if tree.source_id is None:
        return result
    loads = segment_loads(work, tree)
    result.mainline = find_mainline(work, tree, loads, policy.mainline_rule)
    on_mainline = {tree.source_id} | {tree.downstream[s] for s in result.mainline}

    def is_drop(seg_id: str) -> bool:
        return isinstance(work.nodes[tree.downstream[seg_id]], Transformer)

    # ---- collect candidates by rule
    candidates: list[FuseProposal] = []
    for seg_id in tree.segment_order():
        seg = work.segments[seg_id]
        if seg.fuse is not None or seg.fuse_blocked or seg_id in result.mainline:
            continue
        up = tree.upstream[seg_id]
        up_label = work.nodes[up].label()
        if is_drop(seg_id):
            if policy.fuse_transformers:
                tx = work.nodes[tree.downstream[seg_id]]
                candidates.append(FuseProposal(
                    seg_id, "transformer",
                    f"Primary cutout for {tx.label()} ({tx.kva:g} kVA {tx.phases})"))
        elif up in on_mainline:
            if policy.fuse_laterals:
                candidates.append(FuseProposal(
                    seg_id, "lateral", f"{seg.phases} lateral tapped off the mainline at {up_label}"))
        elif policy.fuse_sublaterals:
            branches = [s for s in tree.children[up] if not is_drop(s)]
            if len(branches) > 1 and seg_id != _continuation(tree, loads, branches):
                candidates.append(FuseProposal(
                    seg_id, "sublateral", f"{seg.phases} branch off the lateral at {up_label}"))

    candidates.sort(key=lambda p: RULE_PRIORITY[p.rule])

    # ---- accept candidates in priority order under the series limit
    fused = {s.id for s, _ in work.fuses()}

    def fuses_above(seg_id: str) -> int:
        return sum(1 for s in tree.path_segments(tree.upstream[seg_id]) if s in fused)

    def fuses_below(seg_id: str) -> int:
        """Most fuses on any path below (not including) ``seg_id``."""
        best = 0
        for child in tree.children.get(tree.downstream[seg_id], []):
            best = max(best, fuses_below(child) + (child in fused))
        return best

    limit = policy.max_fuses_in_series
    for prop in candidates:
        series = fuses_above(prop.segment_id) + 1 + fuses_below(prop.segment_id)
        if series > limit:
            prop.accepted = False
            prop.skip_reason = f"Would put {series} fuses in series (limit {limit})"
        else:
            fused.add(prop.segment_id)
        result.proposals.append(prop)

    # ---- sectionalizing runs last so it sees every fuse accepted above
    if policy.sectionalize_long_laterals and policy.sectionalize_length_ft > 0:
        for seg_id in tree.segment_order():
            seg = work.segments[seg_id]
            if (seg_id in fused or seg_id in result.mainline or seg.fuse_blocked
                    or is_drop(seg_id) or loads[seg_id].total_kva <= 0):
                continue
            path = tree.path_segments(tree.upstream[seg_id])
            nearest = next((s for s in path if s in fused), None)
            if nearest is None:
                continue  # not inside a fused lateral
            run = tree.distance_ft[tree.upstream[seg_id]] - tree.distance_ft[tree.upstream[nearest]]
            if run < policy.sectionalize_length_ft:
                continue
            prop = FuseProposal(
                seg_id, "sectionalizing",
                f"{run:,.0f} ft of lateral past the fuse at "
                f"{work.nodes[tree.upstream[nearest]].label()}")
            series = fuses_above(seg_id) + 1 + fuses_below(seg_id)
            if series > limit:
                prop.accepted = False
                prop.skip_reason = f"Would put {series} fuses in series (limit {limit})"
            else:
                fused.add(seg_id)
            result.proposals.append(prop)

    return result


def apply_plan(feeder: Feeder, result: PlacementResult,
               selected: set[str] | None = None) -> list[str]:
    """Replace old auto fuses with the accepted proposals.

    ``selected`` optionally narrows which accepted segment ids to fuse (the GUI
    lets the user untick proposals). Returns the ids of the new fuses.
    """
    for seg_id in result.removed_auto:
        seg = feeder.segments.get(seg_id)
        if seg is not None and seg.fuse is not None and seg.fuse.origin == "auto":
            seg.fuse = None
    added = []
    for prop in result.accepted:
        if selected is not None and prop.segment_id not in selected:
            continue
        seg = feeder.segments.get(prop.segment_id)
        if seg is None or seg.fuse is not None:
            continue
        added.append(feeder.add_fuse(seg.id, origin="auto", reason=prop.reason).id)
    return added
