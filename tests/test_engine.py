"""The adapter between the drawing and fuseSize (fusecalc/engine/fuse_sizing.py)."""

from __future__ import annotations

import ast
import inspect
import warnings
from dataclasses import fields
from pathlib import Path

import pytest

from fusecalc.engine import FuseSizeInputs, build_context, default_engine, fuse_sizing
from fusecalc.library import conductor_names
from fusecalc.model import CONDUCTOR_TEMPS_C, Feeder
from fusecalc.placement import apply_plan, plan_fuses

EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
DEMO = EXAMPLES / "demo_first_fuse_per_lateral.json"


def run(feeder: Feeder):
    return default_engine().run(build_context(feeder))


def fuse_size_table(name: str) -> list:
    """A list literal assigned inside fuseSize, read from the source."""
    tree = ast.parse(Path(fuse_sizing.__file__).read_text(encoding="utf-8"))
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "fuseSize")
    for node in ast.walk(func):
        if isinstance(node, ast.Assign) and getattr(node.targets[0], "id", None) == name:
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in fuseSize")


# ------------------------------------------------- protocol drift guards


def test_inputs_match_fuse_size_signature():
    params = list(inspect.signature(fuse_sizing.fuseSize).parameters)
    assert [f.name for f in fields(FuseSizeInputs)] == params


def test_conductor_library_matches_fuse_size_table():
    assert [n.lstrip("#") for n in conductor_names()] == fuse_size_table("condSize")


def test_conductor_temps_match_fuse_size_table():
    assert list(CONDUCTOR_TEMPS_C) == fuse_size_table("condTempVec")


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
    inp = res.inputs["F1"]  # 150 kVA bank + 50 kVA on A + 50 kVA on B, 3,000 ft out
    assert inp.V_ll == pytest.approx(12470)
    assert inp.S_sc == pytest.approx(50e6)
    assert inp.feederLengthFt == 3000
    assert (inp.latLoadA, inp.latLoadB, inp.latLoadC) == pytest.approx((100, 100, 50))
    assert (inp.latLargestXFMR_A, inp.latLargestXFMR_B, inp.latLargestXFMR_C) == \
        pytest.approx((50, 50, 50))
    assert conductor_names()[inp.priSizeChoice] == "336.4"
    assert conductor_names()[inp.latPriSizeChoice] == "1/0"


# --------------------------------------------------- fuses fuseSize can't size


def test_fuse_below_another_fuse_is_not_sized():
    feeder = Feeder.load(DEMO)
    feeder.add_fuse("L7")  # mid-lateral, below F1
    link = run(feeder).links[feeder.segments["L7"].fuse.id]
    assert link.rating_a is None and link.ok
    assert "Below F1" in link.note


def test_cutout_without_rating_is_not_sized():
    feeder = Feeder.load(DEMO)
    feeder.segments["L8"].fuse.rating_a = None
    link = run(feeder).links[feeder.segments["L8"].fuse.id]
    assert link.rating_a is None and link.ok
    assert "Transformer cutout" in link.note


def test_unknown_conductor_is_reported():
    feeder = Feeder.load(DEMO)
    feeder.segments["L6"].conductor = "795 AAC"  # F1's lateral
    link = run(feeder).links["F1"]
    assert not link.ok and "795 AAC" in link.note


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
