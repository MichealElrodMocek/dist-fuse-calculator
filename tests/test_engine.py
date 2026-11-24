"""The solver (fusecalc/engine/fuse_sizing.py) and the adapter between it and the drawing."""

from __future__ import annotations

import ast
import inspect
import math
import warnings
from dataclasses import fields
from pathlib import Path

import pytest

from fusecalc.engine import (
    FeederTapInputs,
    FuseSizeInputs,
    LatFuseInputs,
    XfmrFuseInputs,
    build_context,
    default_engine,
    fuse_sizing,
)
from fusecalc.library import conductor_index, conductor_names, conductor_types
from fusecalc.model import CONDUCTOR_TEMPS_C, Feeder
from fusecalc.placement import apply_plan, plan_fuses

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
DEMO = EXAMPLES / "demo_first_fuse_per_lateral.json"


def run(feeder: Feeder):
    return default_engine().run(build_context(feeder))


def solver_table(func_name: str, name: str) -> list:
    """A list literal assigned inside a fuse_sizing function, read from the source."""
    tree = ast.parse(Path(fuse_sizing.__file__).read_text(encoding="utf-8"))
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == func_name)
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {func_name}")


CURRENT_FUNCS = ("feederTapCurrent", "latFuseCurrent")


# ------------------------------------------------- protocol drift guards


@pytest.mark.parametrize("func, record", [
    ("feederTapCurrent", FeederTapInputs),
    ("latFuseCurrent", LatFuseInputs),
    ("fuseSize", FuseSizeInputs),
    ("xfmrFuseSize", XfmrFuseInputs),
])
def test_inputs_match_solver_signature(func, record):
    params = [p for p in inspect.signature(getattr(fuse_sizing, func)).parameters
              if p != "returnPhasor"]
    assert [f.name for f in fields(record)] == params


@pytest.mark.parametrize("func", CURRENT_FUNCS)
def test_conductor_library_matches_solver_tables(func):
    assert [n.lstrip("#") for n in conductor_names()] == solver_table(func, "condSize")
    assert conductor_types() == solver_table(func, "condType")
    assert list(CONDUCTOR_TEMPS_C) == solver_table(func, "condTempVec")


# ------------------------------------------------------------- solver

V_LL = 12470
TAP = dict(soilResistivity=100, D_an=4.0, S_sc=500e6, x_over_r=10, priSizeChoice=2,
           priTypeChoice=0, neutSizeChoice=2, neutTypeChoice=0, latPriSizeChoice=2,
           latPriTypeChoice=0, condTempChoice=2)
LAT = dict(x_over_r=10, latPriSizeChoice=2, latPriTypeChoice=0, latNeutSizeChoice=2,
           latNeutTypeChoice=0, soilResistivity=100, condTempChoice=2, D_an=4.0)


def test_slg_at_source_equals_bolted_three_phase():
    # Z0 = Z1 at the source, so a bolted SLG there equals the 3-phase fault
    i = fuse_sizing.feederTapCurrent(V_LL, 0, **TAP)
    assert i == pytest.approx(V_LL / math.sqrt(3) / (V_LL ** 2 / 500e6))


def test_chained_fault_current_matches_direct():
    direct = fuse_sizing.feederTapCurrent(V_LL, 20000, **TAP)
    i = fuse_sizing.feederTapCurrent(V_LL, 0, **TAP, returnPhasor=True)
    for _ in range(10):
        i = fuse_sizing.latFuseCurrent(V_LL, i, latLengthFt=2000, **LAT, returnPhasor=True)
    assert abs(i) == pytest.approx(direct)


def test_magnitude_only_chaining_still_works():
    i = fuse_sizing.feederTapCurrent(V_LL, 5000, **TAP)
    assert fuse_sizing.latFuseCurrent(V_LL, i, latLengthFt=0, **LAT) == pytest.approx(i)


def fuse_size(i=1500, size=2, load=250, xfmr=75, child=0):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        rating = fuse_sizing.fuseSize(V_LL, i, size, load, load, load, xfmr, xfmr, xfmr, child)
    return rating, [str(w.message) for w in caught]


@pytest.mark.parametrize("kwargs, expected", [
    (dict(child=140), 200),  # used to raise UnboundLocalError
    (dict(child=200), 200),
    (dict(xfmr=1000), 200),
    (dict(xfmr=2000), 200),  # used to leave childFuse unset
])
def test_fuse_size_large_children_do_not_crash(kwargs, expected):
    assert fuse_size(**kwargs)[0] == expected


def test_fuse_size_rounds_child_up_to_a_t_size():
    assert fuse_size(child=45) == fuse_size(child=50)


@pytest.mark.parametrize("kva, link", [(15, 3), (25, 6), (50, 10), (166.7, 30)])
def test_xfmr_fuse_size_is_the_125_percent_rule(kva, link):
    assert fuse_sizing.xfmrFuseSize(V_LL, kva, kva, kva) == link


def test_xfmr_fuse_size_too_big_warns():
    with pytest.warns(UserWarning, match="more than a 200T"):
        assert fuse_sizing.xfmrFuseSize(V_LL, 1500, 0, 0) == 200


def test_fuse_size_ampacity_uses_downstream_conductor():
    # 1,200 kVA/phase needs 200T; #4 is good for 140 A, 477 for 640 A
    rating, notes = fuse_size(load=1200, size=conductor_index("#4"))
    assert rating == 140 and "too large for selected downstream primary" in notes[0]
    assert fuse_size(load=1200, size=conductor_index("477"))[0] == 200


# ------------------------------------------------------------- demo


def test_demo_sizes_every_lateral_and_keeps_cutouts():
    feeder = Feeder.load(DEMO)
    res = run(feeder)
    assert not build_context(feeder).issues
    laterals = {f.id for _, f in feeder.fuses() if f.rating_a is None}
    assert laterals == {"F1", "F2", "F3", "F4"}
    for fid in laterals:
        assert res.links[fid].ok and res.links[fid].rating_a, res.links[fid]
        assert fid in res.inputs
    for _, fuse in feeder.fuses():
        if fuse.rating_a is not None:
            assert res.links[fuse.id].rating_a == fuse.rating_a


def test_demo_matches_placement_rules():
    feeder = Feeder.load(DEMO)
    fused = {s.id for s, _ in feeder.fuses()}
    for seg in feeder.segments.values():
        seg.fuse = None
    assert {p.segment_id for p in plan_fuses(feeder).accepted} == fused


def test_inputs_for_three_phase_lateral():
    res = run(Feeder.load(DEMO))
    (tap,) = res.fault_inputs["F1"]  # first fuse of its branch: one feederTapCurrent call
    assert tap.V_ll == pytest.approx(12470)
    assert tap.S_sc == pytest.approx(50e6)
    assert tap.feederLengthFt == 3000
    assert conductor_names()[tap.priSizeChoice] == "336.4"
    assert conductor_names()[tap.latPriSizeChoice] == "1/0"
    inp = res.inputs["F1"]  # 150 kVA bank + 50 kVA on A + 50 kVA on B, 3,000 ft out
    assert inp.I_LG_mag == pytest.approx(fuse_sizing.feederTapCurrent(**vars(tap)), abs=0.1)
    assert (inp.latLoadA, inp.latLoadB, inp.latLoadC) == pytest.approx((100, 100, 50))
    assert (inp.latLargestXFMR_A, inp.latLargestXFMR_B, inp.latLargestXFMR_C) == \
        pytest.approx((50, 50, 50))
    assert conductor_names()[inp.downstreamPriSizeChoice] == "1/0"
    assert inp.largestChildNonTX == 0  # only transformer cutouts below


def test_fault_current_shown_at_each_fuse():
    feeder = Feeder.load(DEMO)
    ctx = build_context(feeder)
    res = default_engine().run(ctx)
    for seg, _ in feeder.fuses():
        assert res.faults[ctx.tree.upstream[seg.id]].islg_a > 0


def test_conductor_material_changes_fault_current():
    feeder = Feeder.load(DEMO)
    before = run(feeder).inputs["F1"].I_LG_mag
    feeder.settings.primary_conductor_type = "AAC"
    assert run(feeder).inputs["F1"].I_LG_mag != before


# --------------------------------------------------- recursive branch solving


def test_fuse_below_another_fuse_is_sized():
    feeder = Feeder.load(DEMO)
    child = feeder.add_fuse("L7")  # mid-lateral, below F1
    res = run(feeder)
    link = res.links[child.id]
    assert link.ok and link.rating_a, link
    assert all(isinstance(c, LatFuseInputs) for c in res.fault_inputs[child.id])
    assert res.inputs[child.id].I_LG_mag < res.inputs["F1"].I_LG_mag
    assert res.inputs["F1"].largestChildNonTX == link.rating_a
    assert res.links["F1"].rating_a > link.rating_a
    coord = res.coordination_for(child.id)
    assert coord.protected_fuse == "F1" and coord.fault_current_a == pytest.approx(
        res.inputs[child.id].I_LG_mag, abs=0.1)


def test_fixed_child_rating_feeds_parent():
    feeder = Feeder.load(DEMO)
    feeder.add_fuse("L7").rating_a = 65
    assert run(feeder).inputs["F1"].largestChildNonTX == 65


# --------------------------------------------------- fuses fuseSize can't size


def test_cutouts_on_auto_match_the_demo_ratings():
    # the demo's cutout ratings were set by hand with fuseSize's 125% rule
    feeder = Feeder.load(DEMO)
    fixed = {f.id: f.rating_a for _, f in feeder.fuses() if f.rating_a}
    for _, fuse in feeder.fuses():
        fuse.rating_a = None
    res = run(feeder)
    assert fixed and {fid: res.links[fid].rating_a for fid in fixed} == fixed
    assert all(isinstance(res.inputs[fid], XfmrFuseInputs) for fid in fixed)


def test_unknown_conductor_is_reported():
    feeder = Feeder.load(DEMO)
    feeder.segments["L6"].conductor = "795 AAC"  # F1's lateral
    link = run(feeder).links["F1"]
    assert not link.ok and "795 AAC" in link.note


def test_unknown_material_is_reported():
    feeder = Feeder.load(DEMO)
    feeder.segments["L6"].conductor_type = "Copper"
    link = run(feeder).links["F1"]
    assert not link.ok and "Copper" in link.note


# ------------------------------------------------------ fuseSize misbehaving


def test_fuse_size_warnings_become_notes(monkeypatch):
    def warns(**_):
        warnings.warn("Fault Current too high. Defaulting to maximum 200T.")
        return 200
    monkeypatch.setattr(fuse_sizing, "fuseSize", warns)
    link = run(Feeder.load(DEMO)).links["F1"]
    assert link.rating_a == 200 and not link.ok
    assert "Fault Current too high" in link.note


def test_fuse_size_exception_is_contained(monkeypatch):
    def crashes(**_):
        raise IndexError("boom")
    monkeypatch.setattr(fuse_sizing, "fuseSize", crashes)
    res = run(Feeder.load(DEMO))
    assert all(not res.links[f].ok and "IndexError" in res.links[f].note
               for f in ("F1", "F2", "F3", "F4"))


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")), ids=lambda p: p.stem)
def test_examples_run(path):
    feeder = Feeder.load(path)
    apply_plan(feeder, plan_fuses(feeder))
    res = run(feeder)
    assert set(res.links) == {f.id for _, f in feeder.fuses()}
    assert len(res.coordination) == len(build_context(feeder).pairs)
    assert not [link.note for link in res.links.values() if not link.ok]
    assert all(link.rating_a for link in res.links.values())
