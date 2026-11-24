"""Runs fuse_sizing.py on the drawing.

Two passes over the fuses, following how the solver is split up:

1. **Fault current, top-down.** The first fuse of a branch gets
   ``feederTapCurrent`` at its drawn distance from the source (the solver
   treats that whole run as the Study panel's primary conductor). A fuse
   below another fuse gets ``latFuseCurrent`` chained from the fuse above,
   one call per drawn segment so each segment's own conductor is used.
2. **Sizing, bottom-up.** ``fuseSize`` sizes each fuse from the fault current
   there, the load and largest transformer below it, and the largest fuse
   directly below it that isn't a transformer cutout (``largestChildNonTX``).
   Children are therefore sized before their parents.

Ratings fixed on a fuse are kept. Transformer cutouts get ``xfmrFuseSize``,
the 125 % rule fuseSize uses for the transformer fuse below a lateral. The
solver is called as a black box and its warnings become the fuse's note.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import asdict

from fusecalc.engine import fuse_sizing
from fusecalc.engine.api import (
    CoordinationResult,
    FeederTapInputs,
    FuseSizeInputs,
    LatFuseInputs,
    LinkSelection,
    NodeFault,
    StudyContext,
    StudyResults,
    XfmrFuseInputs,
)
from fusecalc.library import conductor_index, conductor_type_index
from fusecalc.model import CONDUCTOR_TEMPS_C, Segment, Transformer
from fusecalc.topology import transformer_load


def _temp_choice(ctx: StudyContext) -> int:
    t = ctx.feeder.settings.conductor_temp_c
    if t not in CONDUCTOR_TEMPS_C:
        raise ValueError(f"Conductor temperature must be one of {CONDUCTOR_TEMPS_C} °C")
    return CONDUCTOR_TEMPS_C.index(t)


def feeder_tap_inputs(ctx: StudyContext, seg_id: str) -> FeederTapInputs:
    """feederTapCurrent's arguments for the first fuse of a branch (on ``seg_id``).

    Raises ValueError if a conductor or temperature isn't in the solver's tables.
    """
    st, seg = ctx.feeder.settings, ctx.feeder.segments[seg_id]
    return FeederTapInputs(
        V_ll=st.nominal_kv_ll * 1000,
        feederLengthFt=ctx.tree.distance_ft[ctx.tree.upstream[seg_id]],
        soilResistivity=st.soil_resistivity_ohm_m,
        D_an=st.neutral_spacing_ft,
        S_sc=st.source_mva * 1e6,
        x_over_r=st.x_over_r,
        priSizeChoice=conductor_index(st.primary_conductor),
        priTypeChoice=conductor_type_index(st.primary_conductor_type),
        neutSizeChoice=conductor_index(st.neutral_conductor),
        neutTypeChoice=conductor_type_index(st.neutral_conductor_type),
        latPriSizeChoice=conductor_index(seg.conductor),
        latPriTypeChoice=conductor_type_index(seg.conductor_type),
        condTempChoice=_temp_choice(ctx),
    )


def lat_fuse_inputs(ctx: StudyContext, seg_id: str, i_previous: complex) -> LatFuseInputs:
    """latFuseCurrent's arguments to carry ``i_previous`` across segment ``seg_id``.

    Raises ValueError if a conductor or temperature isn't in the solver's tables.
    """
    st, seg = ctx.feeder.settings, ctx.feeder.segments[seg_id]
    return LatFuseInputs(
        V_ll=st.nominal_kv_ll * 1000,
        I_f_previous=i_previous,
        x_over_r=st.x_over_r,
        latLengthFt=seg.length_ft,
        latPriSizeChoice=conductor_index(seg.conductor),
        latPriTypeChoice=conductor_type_index(seg.conductor_type),
        latNeutSizeChoice=conductor_index(st.neutral_conductor),
        latNeutTypeChoice=conductor_type_index(st.neutral_conductor_type),
        soilResistivity=st.soil_resistivity_ohm_m,
        condTempChoice=_temp_choice(ctx),
        D_an=st.neutral_spacing_ft,
    )


def _largest_xfmr(ctx: StudyContext, seg_id: str) -> dict[str, float]:
    """Largest transformer kVA per phase at or below ``seg_id``.

    Per-phase kVA is sent as phase current x V_ph, so the solver's kVA / V_ph
    gives the right current for line-to-line units too. For line-to-neutral
    units and three-phase banks this is just the per-phase kVA.
    """
    f, tree, st = ctx.feeder, ctx.tree, ctx.feeder.settings
    kv_ph = st.nominal_kv_ll / math.sqrt(3)
    largest = dict.fromkeys("ABC", 0.0)
    for s in tree.subtree_segments(seg_id):
        node = f.nodes[tree.downstream[s]]
        if isinstance(node, Transformer):
            amps = transformer_load(node, st.nominal_kv_ll).amps
            for p in "ABC":
                largest[p] = max(largest[p], amps[p] * kv_ph)
    return largest


def xfmr_fuse_inputs(ctx: StudyContext, seg_id: str) -> XfmrFuseInputs:
    """xfmrFuseSize's arguments for the cutout on ``seg_id``."""
    largest = _largest_xfmr(ctx, seg_id)
    return XfmrFuseInputs(
        V_ll=ctx.feeder.settings.nominal_kv_ll * 1000,
        latLargestXFMR_A=round(largest["A"], 3),
        latLargestXFMR_B=round(largest["B"], 3),
        latLargestXFMR_C=round(largest["C"], 3),
    )


def fuse_size_inputs(ctx: StudyContext, seg_id: str, i_lg: float,
                     largest_child: float) -> FuseSizeInputs:
    """fuseSize's arguments for the fuse on ``seg_id``.

    Raises ValueError if the segment's conductor isn't in the solver's tables.
    """
    f, st = ctx.feeder, ctx.feeder.settings
    kv_ph = st.nominal_kv_ll / math.sqrt(3)
    load = ctx.loads[seg_id].amps
    largest = _largest_xfmr(ctx, seg_id)
    return FuseSizeInputs(
        V_ll=st.nominal_kv_ll * 1000,
        I_LG_mag=round(i_lg, 1),
        downstreamPriSizeChoice=conductor_index(f.segments[seg_id].conductor),
        latLoadA=round(load["A"] * kv_ph, 3),
        latLoadB=round(load["B"] * kv_ph, 3),
        latLoadC=round(load["C"] * kv_ph, 3),
        latLargestXFMR_A=round(largest["A"], 3),
        latLargestXFMR_B=round(largest["B"], 3),
        latLargestXFMR_C=round(largest["C"], 3),
        largestChildNonTX=largest_child,
    )


def _call(func, inputs, **extra):
    """Call a solver function; return (result, warning messages)."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        out = func(**asdict(inputs), **extra)
    return out, [str(w.message) for w in caught]


class FuseSizeEngine:
    name = "fuse_sizing (T links)"

    def run(self, ctx: StudyContext) -> StudyResults:
        res = StudyResults(engine=self.name)
        if ctx.has_errors or ctx.tree.source_id is None:
            res.messages.append("Study skipped: fix the errors in the Checks tab first.")
            return res
        f, tree = ctx.feeder, ctx.tree
        fuses = {fuse.id: seg for seg, fuse in f.fuses() if seg.id in ctx.loads}
        parent = {p.protecting_fuse: p.protected_fuse for p in ctx.pairs}
        children: dict[str, list[str]] = {}
        for child, up in parent.items():
            children.setdefault(up, []).append(child)
        depth = {fid: len(tree.path_segments(tree.upstream[seg.id])) for fid, seg in fuses.items()}
        top_down = sorted(fuses, key=depth.__getitem__)

        phasors: dict[str, complex] = {}
        errors: dict[str, str] = {}
        for fid in top_down:
            self._fault(ctx, fid, fuses[fid], parent.get(fid), phasors, errors, res)
        for fid in reversed(top_down):
            self._link(ctx, fid, fuses[fid], children.get(fid, []), phasors, errors, res)

        for pair in ctx.pairs:
            i = phasors.get(pair.protecting_fuse)
            res.coordination.append(CoordinationResult(
                protecting_fuse=pair.protecting_fuse,
                protected_fuse=pair.protected_fuse,
                fault_current_a=abs(i) if i is not None else None,
                note="fuseSize coordinates each fuse with its largest child internally "
                     "but doesn't return the table limit, so pass/fail isn't shown",
            ))
        self._check_primary(ctx, [s.id for fid, s in fuses.items() if fid not in parent], res)
        return res

    # ------------------------------------------------------- fault current

    def _fault(self, ctx: StudyContext, fid: str, seg: Segment, up_fid: str | None,
               phasors: dict[str, complex], errors: dict[str, str], res: StudyResults) -> None:
        tree = ctx.tree
        node = tree.upstream[seg.id]
        calls: list[FeederTapInputs | LatFuseInputs] = []
        try:
            if up_fid is None:
                calls.append(feeder_tap_inputs(ctx, seg.id))
                i, notes = _call(fuse_sizing.feederTapCurrent, calls[0], returnPhasor=True)
            else:
                if up_fid not in phasors:
                    errors[fid] = f"No fault current: {up_fid} above it has none."
                    return
                i, notes = phasors[up_fid], []
                start = tree.upstream[ctx.feeder.fuse_segment(up_fid).id]
                path = tree.path_segments(node)
                path = path[:len(path) - len(tree.path_segments(start))]
                for s in reversed(path):  # from the fuse above down to this one
                    calls.append(lat_fuse_inputs(ctx, s, i))
                    i, more = _call(fuse_sizing.latFuseCurrent, calls[-1], returnPhasor=True)
                    notes += more
        except ValueError as e:
            errors[fid] = str(e)
            return
        except Exception as e:  # the solver crashed: contain it to this fuse
            errors[fid] = f"Fault current failed: {type(e).__name__}: {e}"
            return
        phasors[fid] = complex(i)
        res.fault_inputs[fid] = calls
        res.faults[node] = NodeFault(islg_a=abs(i))
        if notes:
            errors.setdefault(fid, " ".join(notes))

    # ------------------------------------------------------------- sizing

    def _link(self, ctx: StudyContext, fid: str, seg: Segment, child_fids: list[str],
              phasors: dict[str, complex], errors: dict[str, str], res: StudyResults) -> None:
        f = ctx.feeder
        load_a = ctx.loads[seg.id].max_amps
        fuse = seg.fuse
        if fuse.rating_a:
            res.links[fid] = LinkSelection(fuse.rating_a, load_a, note="Fixed rating")
            return
        if self._is_cutout(ctx, seg):
            inputs = xfmr_fuse_inputs(ctx, seg.id)
            res.inputs[fid] = inputs
            try:
                rating, notes = _call(fuse_sizing.xfmrFuseSize, inputs)
            except Exception as e:  # the solver crashed: contain it to this fuse
                res.links[fid] = LinkSelection(
                    None, load_a, ok=False, note=f"xfmrFuseSize failed: {type(e).__name__}: {e}")
                return
            res.links[fid] = LinkSelection(float(rating), load_a, ok=not notes,
                                           note=" ".join(notes) or "Transformer cutout (125% rule)")
            return
        if fid not in phasors:
            res.links[fid] = LinkSelection(None, load_a, ok=False, note=errors.get(fid, ""))
            return

        largest_child, unsized = 0.0, []
        for c in child_fids:
            if self._is_cutout(ctx, f.fuse_segment(c)):
                continue  # covered by fuseSize's largest-transformer rule
            rating = res.links[c].rating_a
            if rating is None:
                unsized.append(c)
            else:
                largest_child = max(largest_child, rating)
        try:
            inputs = fuse_size_inputs(ctx, seg.id, abs(phasors[fid]), largest_child)
        except ValueError as e:
            res.links[fid] = LinkSelection(None, load_a, ok=False, note=str(e))
            return
        res.inputs[fid] = inputs
        try:
            rating, notes = _call(fuse_sizing.fuseSize, inputs)
        except Exception as e:  # the solver crashed: contain it to this fuse
            res.links[fid] = LinkSelection(
                None, load_a, ok=False, note=f"fuseSize failed: {type(e).__name__}: {e}")
            return
        if fid in errors:  # warnings from the fault-current calls
            notes.insert(0, errors[fid])
        if unsized:
            notes.append(f"Not coordinated with {', '.join(sorted(unsized))} below "
                         "(no rating to pass as largestChildNonTX).")
        res.links[fid] = LinkSelection(float(rating), load_a, ok=not notes,
                                       note=" ".join(notes) or "Sized by fuseSize")

    @staticmethod
    def _is_cutout(ctx: StudyContext, seg: Segment) -> bool:
        return isinstance(ctx.feeder.nodes[ctx.tree.downstream[seg.id]], Transformer)

    def _check_primary(self, ctx: StudyContext, first_fuses: list[str],
                       res: StudyResults) -> None:
        """feederTapCurrent models everything between the source and the first
        fuse of a branch as one conductor; say so when the drawing disagrees."""
        st = ctx.feeder.settings
        drawn = {s for seg_id in first_fuses
                 for s in ctx.tree.path_segments(ctx.tree.upstream[seg_id])
                 if (ctx.feeder.segments[s].conductor, ctx.feeder.segments[s].conductor_type)
                 != (st.primary_conductor, st.primary_conductor_type)}
        if drawn:
            names = ", ".join(sorted(ctx.feeder.segments[s].label() for s in drawn))
            res.messages.append(
                f"feederTapCurrent treats the primary up to each branch's first fuse as "
                f"{st.primary_conductor} {st.primary_conductor_type} (Study panel), but "
                f"{names} are drawn with other conductors.")
