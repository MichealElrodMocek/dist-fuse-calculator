"""Stand-in engine so the GUI has numbers to show before the real one exists.

NOT FOR ENGINEERING USE. The fault study uses one generic line impedance for
every conductor (unless the conductor library has values), the link rule is a
bare 150 % of load, and no coordination tables are consulted, so every pair
comes back "not_checked". Replace via :func:`fusecalc.engine.default_engine`.
"""

from __future__ import annotations

import cmath
import math

from fusecalc.engine.api import (
    CoordinationResult,
    LinkSelection,
    NodeFault,
    StudyContext,
    StudyResults,
)
from fusecalc.library import conductors

# Generic overhead line, ohms per mile (roughly a 336 ACSR three-phase line).
GENERIC_Z1 = complex(0.306, 0.627)
GENERIC_Z0 = complex(0.774, 1.937)
PREFERRED_RATINGS = (6, 10, 15, 25, 40, 65, 100, 140, 200)
LOAD_MARGIN = 1.5


class PlaceholderEngine:
    name = "Placeholder (not validated)"

    def run(self, ctx: StudyContext) -> StudyResults:
        res = StudyResults(engine=self.name, is_placeholder=True)
        res.messages.append(
            "Placeholder engine: generic impedances, 150% load rule, no "
            "coordination tables. Numbers are for GUI testing only.")
        if ctx.has_errors or ctx.tree.source_id is None:
            res.messages.append("Study skipped: fix the errors in the Checks tab first.")
            return res
        self._faults(ctx, res)
        self._links(ctx, res)
        self._coordination(ctx, res)
        return res

    def _faults(self, ctx: StudyContext, res: StudyResults) -> None:
        st = ctx.feeder.settings
        v_ln = st.nominal_kv_ll * 1000 / math.sqrt(3)
        angle = cmath.exp(1j * math.atan(st.x_over_r))
        z1s = v_ln / st.fault_3ph_a * angle
        z0s = 3 * v_ln / st.fault_slg_a * angle - 2 * z1s
        lib = conductors()

        z1 = {ctx.tree.source_id: z1s}
        z0 = {ctx.tree.source_id: z0s}
        for seg_id in ctx.tree.segment_order():
            seg = ctx.feeder.segments[seg_id]
            cond = lib.get(seg.conductor)
            if cond is not None and cond.has_impedance:
                lz1, lz0 = complex(cond.r1, cond.x1), complex(cond.r0, cond.x0)
            else:
                lz1, lz0 = GENERIC_Z1, GENERIC_Z0
            miles = seg.length_ft / 5280
            up, down = ctx.tree.upstream[seg_id], ctx.tree.downstream[seg_id]
            z1[down] = z1[up] + lz1 * miles
            z0[down] = z0[up] + lz0 * miles

        rf = st.min_fault_resistance_ohm
        for node_id in ctx.tree.order:
            zs, zz = z1[node_id], z0[node_id]
            res.faults[node_id] = NodeFault(
                i3ph_a=v_ln / abs(zs),
                islg_a=3 * v_ln / abs(2 * zs + zz),
                imin_a=3 * v_ln / abs(2 * zs + zz + 3 * rf),
            )

    def _links(self, ctx: StudyContext, res: StudyResults) -> None:
        default_type = ctx.feeder.settings.preferred_link_type
        for seg, fuse in ctx.feeder.fuses():
            if seg.id not in ctx.loads:
                continue
            load = ctx.loads[seg.id].max_amps
            link_type = fuse.link_type or default_type
            if fuse.rating_a:
                res.links[fuse.id] = LinkSelection(link_type, fuse.rating_a, load,
                                                   note="Rating set by user")
                continue
            need = load * LOAD_MARGIN
            rating = next((r for r in PREFERRED_RATINGS if r >= need), None)
            if rating is None:
                res.links[fuse.id] = LinkSelection(
                    link_type, PREFERRED_RATINGS[-1], load, ok=False,
                    note=f"Load needs {need:.0f} A; exceeds largest link")
            else:
                res.links[fuse.id] = LinkSelection(
                    link_type, rating, load, note=f"Smallest preferred link >= {need:.1f} A")

    def _coordination(self, ctx: StudyContext, res: StudyResults) -> None:
        for pair in ctx.pairs:
            node = ctx.tree.upstream[pair.protecting_segment]
            fault = res.faults.get(node)
            res.coordination.append(CoordinationResult(
                protecting_fuse=pair.protecting_fuse,
                protected_fuse=pair.protected_fuse,
                fault_current_a=fault.imax_a if fault else None,
                note="Coordination tables not implemented yet",
            ))
