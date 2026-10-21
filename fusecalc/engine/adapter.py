"""Runs ``fuseSize`` on the drawing.

``fuseSize`` sizes the first fuse of a branch: a lateral tap fuse that
coordinates with the T link its 125 % rule picks for the largest transformer
below it. For each fuse this adapter:

* keeps a rating fixed on the fuse (e.g. the demo's transformer cutouts),
* reports transformer cutouts without a fixed rating as not sized, since
  fuseSize only returns the lateral fuse,
* reports fuses with another fuse upstream as not sized, since those need
  recursive branch solving,
* otherwise builds :class:`FuseSizeInputs` from the drawing and calls
  ``fuseSize``. Its warnings become the fuse's note.

``fuse_sizing.py`` is called as a black box and kept unchanged.
"""

from __future__ import annotations

import math
import warnings
from dataclasses import asdict

from fusecalc.engine import fuse_sizing
from fusecalc.engine.api import (
    CoordinationResult,
    FuseSizeInputs,
    LinkSelection,
    StudyContext,
    StudyResults,
)
from fusecalc.library import conductor_index
from fusecalc.model import CONDUCTOR_TEMPS_C, Transformer
from fusecalc.topology import transformer_load


def fuse_size_inputs(ctx: StudyContext, seg_id: str) -> FuseSizeInputs:
    """fuseSize's arguments for the fuse on ``seg_id``, from the drawing.

    Per-phase kVA is sent as phase current x V_ph, so fuseSize's kVA / V_ph
    gives the right current for line-to-line units too. For line-to-neutral
    units and three-phase banks this is just the per-phase kVA.

    Raises ValueError if a conductor or temperature isn't in fuseSize's tables.
    """
    f, tree, st = ctx.feeder, ctx.tree, ctx.feeder.settings
    kv_ph = st.nominal_kv_ll / math.sqrt(3)
    load = ctx.loads[seg_id].amps
    largest = dict.fromkeys("ABC", 0.0)
    for s in tree.subtree_segments(seg_id):
        node = f.nodes[tree.downstream[s]]
        if isinstance(node, Transformer):
            amps = transformer_load(node, st.nominal_kv_ll).amps
            for p in "ABC":
                largest[p] = max(largest[p], amps[p] * kv_ph)
    if st.conductor_temp_c not in CONDUCTOR_TEMPS_C:
        raise ValueError(f"Conductor temperature must be one of {CONDUCTOR_TEMPS_C} °C")
    return FuseSizeInputs(
        V_ll=st.nominal_kv_ll * 1000,
        feederLengthFt=tree.distance_ft[tree.upstream[seg_id]],
        soilResistivity=st.soil_resistivity_ohm_m,
        D_an=st.neutral_spacing_ft,
        S_sc=st.source_mva * 1e6,
        x_over_r=st.x_over_r,
        priSizeChoice=conductor_index(st.primary_conductor),
        neutSizeChoice=conductor_index(st.neutral_conductor),
        latPriSizeChoice=conductor_index(f.segments[seg_id].conductor),
        condTempChoice=CONDUCTOR_TEMPS_C.index(st.conductor_temp_c),
        latLoadA=round(load["A"] * kv_ph, 3),
        latLoadB=round(load["B"] * kv_ph, 3),
        latLoadC=round(load["C"] * kv_ph, 3),
        latLargestXFMR_A=round(largest["A"], 3),
        latLargestXFMR_B=round(largest["B"], 3),
        latLargestXFMR_C=round(largest["C"], 3),
    )


class FuseSizeEngine:
    name = "fuseSize (T links)"

    def run(self, ctx: StudyContext) -> StudyResults:
        res = StudyResults(engine=self.name)
        if ctx.has_errors or ctx.tree.source_id is None:
            res.messages.append("Study skipped: fix the errors in the Checks tab first.")
            return res
        res.messages.append("Fault currents and coordination are worked out inside fuseSize "
                            "but not returned yet, so they show as not available.")
        upstream_of = {p.protecting_fuse: p.protected_fuse for p in ctx.pairs}
        sized: list[str] = []
        for seg, fuse in ctx.feeder.fuses():
            if seg.id not in ctx.loads:
                continue
            load_a = ctx.loads[seg.id].max_amps
            if fuse.rating_a:
                res.links[fuse.id] = LinkSelection(fuse.rating_a, load_a, note="Fixed rating")
            elif isinstance(ctx.feeder.nodes[ctx.tree.downstream[seg.id]], Transformer):
                res.links[fuse.id] = LinkSelection(
                    None, load_a,
                    note="Transformer cutout: fuseSize only returns the lateral fuse, "
                         "so set a rating in Properties.")
            elif fuse.id in upstream_of:
                res.links[fuse.id] = LinkSelection(
                    None, load_a,
                    note=f"Below {upstream_of[fuse.id]}: only the first fuse of a branch is "
                         "sized (recursive branch solving isn't implemented).")
            else:
                self._size(ctx, seg.id, fuse.id, load_a, res)
                sized.append(seg.id)
        for pair in ctx.pairs:
            res.coordination.append(CoordinationResult(
                protecting_fuse=pair.protecting_fuse,
                protected_fuse=pair.protected_fuse,
                note="fuseSize doesn't return coordination results yet",
            ))
        self._check_primary(ctx, sized, res)
        return res

    def _size(self, ctx: StudyContext, seg_id: str, fuse_id: str, load_a: float,
              res: StudyResults) -> None:
        try:
            inputs = fuse_size_inputs(ctx, seg_id)
        except ValueError as e:
            res.links[fuse_id] = LinkSelection(None, load_a, ok=False, note=str(e))
            return
        res.inputs[fuse_id] = inputs
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                rating = fuse_sizing.fuseSize(**asdict(inputs))
            except Exception as e:  # known crash cases are listed in the README
                res.links[fuse_id] = LinkSelection(
                    None, load_a, ok=False, note=f"fuseSize failed: {type(e).__name__}: {e}")
                return
        notes = [str(w.message) for w in caught]
        res.links[fuse_id] = LinkSelection(float(rating), load_a, ok=not notes,
                                           note=" ".join(notes) or "Sized by fuseSize")

    def _check_primary(self, ctx: StudyContext, sized: list[str], res: StudyResults) -> None:
        """fuseSize models everything between the source and a fuse as one
        conductor; say so when the drawing disagrees."""
        primary = ctx.feeder.settings.primary_conductor
        drawn = {s for seg_id in sized
                 for s in ctx.tree.path_segments(ctx.tree.upstream[seg_id])
                 if ctx.feeder.segments[s].conductor != primary}
        if drawn:
            names = ", ".join(sorted(ctx.feeder.segments[s].label() for s in drawn))
            res.messages.append(f"fuseSize treats the primary up to each fuse as {primary} "
                                f"(Study panel), but {names} are drawn with other conductors.")
