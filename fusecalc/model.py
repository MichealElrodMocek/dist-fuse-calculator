"""Feeder data model.

Pure Python with no Qt imports, so the GUI, the placement rules, and the
fault/sizing engine all share one representation and the engine can be
tested without a display.

Conventions
-----------
* A feeder is a graph of nodes (one Source, Buses, Transformers) joined by
  line Segments. The GUI draws it as a one-line diagram; the phases a segment
  carries are stored as a string such as ``"ABC"``, ``"AB"`` or ``"B"``.
* Segments are undirected in storage. Direction (upstream/downstream) comes
  from a breadth-first walk out of the source, see :mod:`fusecalc.topology`.
* A Fuse lives on a segment and sits at that segment's *upstream* end, which
  matches a cutout mounted on the tap pole. A transformer's primary fuse is
  the fuse on the short "drop" segment that feeds it.
* Currents are in amperes, voltages in kV, lengths in feet, power in kVA.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import ClassVar, Iterator

SCHEMA_VERSION = 1

PHASE_ORDER = "ABC"
PHASE_CHOICES = ("ABC", "AB", "BC", "AC", "A", "B", "C")
LINK_TYPES = ("K", "T", "H", "N")
MAINLINE_RULES = ("three_phase", "heaviest_path")
PHILOSOPHIES = ("fuse_saving", "fuse_blowing")

# Common overhead pole-mount sizes; the GUI offers these but accepts any value.
TRANSFORMER_KVA_1PH = (10, 15, 25, 37.5, 50, 75, 100, 167)
TRANSFORMER_KVA_3PH = (45, 75, 112.5, 150, 225, 300, 500)


def normalize_phases(value: str) -> str:
    """Return phases in canonical ``A``/``B``/``C`` order, e.g. ``"b, a" -> "AB"``.

    Raises ValueError for unknown letters or an empty result.
    """
    letters = set()
    for ch in value.upper():
        if ch in PHASE_ORDER:
            letters.add(ch)
        elif ch not in " ,-/":
            raise ValueError(f"Invalid phase designation {value!r}")
    if not letters:
        raise ValueError("At least one phase (A, B or C) is required")
    return "".join(p for p in PHASE_ORDER if p in letters)


def phases_subset(inner: str, outer: str) -> bool:
    """True if every phase in ``inner`` is also present in ``outer``."""
    return set(inner) <= set(outer)


# --------------------------------------------------------------------- nodes


@dataclass(kw_only=True)
class Node:
    id: str
    name: str = ""
    x: float = 0.0
    y: float = 0.0

    kind: ClassVar[str] = "node"

    def label(self) -> str:
        return self.name or self.id


@dataclass(kw_only=True)
class Source(Node):
    """Substation bus / feeder head. Electrical data lives in StudySettings."""

    kind: ClassVar[str] = "source"
    phases: ClassVar[str] = "ABC"


@dataclass(kw_only=True)
class Bus(Node):
    """A junction or pole where segments meet and taps can be taken."""

    kind: ClassVar[str] = "bus"


@dataclass(kw_only=True)
class Transformer(Node):
    """Distribution transformer (a load, always the end of a branch).

    ``phases`` is the primary connection: one letter for a line-to-neutral
    single-phase unit, two letters for line-to-line, ``"ABC"`` for a bank.
    ``kva`` is the total nameplate rating of the unit or bank.
    """

    kind: ClassVar[str] = "transformer"
    kva: float = 25.0
    phases: str = "A"

    def __post_init__(self) -> None:
        self.phases = normalize_phases(self.phases)


NODE_TYPES: dict[str, type[Node]] = {cls.kind: cls for cls in (Source, Bus, Transformer)}


# ------------------------------------------------------------ segment + fuse


@dataclass(kw_only=True)
class Fuse:
    """A fuse cutout at the upstream end of a segment.

    ``link_type`` / ``rating_a`` of ``None`` mean "let the sizing engine pick".
    ``origin`` is ``"manual"`` for fuses the user placed and ``"auto"`` for
    ones the placement rules added (those are replaced on the next auto-place).
    """

    id: str
    name: str = ""
    link_type: str | None = None
    rating_a: float | None = None
    origin: str = "manual"
    reason: str = ""

    def label(self) -> str:
        return self.name or self.id


@dataclass(kw_only=True)
class Segment:
    id: str
    node_a: str
    node_b: str
    name: str = ""
    length_ft: float = 0.0
    conductor: str = ""
    phases: str = "ABC"
    fuse: Fuse | None = None
    fuse_blocked: bool = False  # user says "never put a fuse here"

    def __post_init__(self) -> None:
        self.phases = normalize_phases(self.phases)

    def label(self) -> str:
        return self.name or self.id

    def other_end(self, node_id: str) -> str:
        if node_id == self.node_a:
            return self.node_b
        if node_id == self.node_b:
            return self.node_a
        raise KeyError(f"{node_id} is not an end of segment {self.id}")


# ------------------------------------------------------------------ settings


@dataclass(kw_only=True)
class StudySettings:
    """Feeder-level inputs for the fault study and link selection."""

    nominal_kv_ll: float = 12.47
    fault_3ph_a: float = 8000.0  # available bolted 3-phase fault at the source
    fault_slg_a: float = 7000.0  # available bolted single-line-to-ground fault
    x_over_r: float = 10.0
    min_fault_resistance_ohm: float = 20.0  # used for minimum-fault currents
    philosophy: str = "fuse_saving"
    preferred_link_type: str = "K"


@dataclass(kw_only=True)
class PlacementPolicy:
    """Knobs for :func:`fusecalc.placement.plan_fuses`."""

    mainline_rule: str = "three_phase"
    fuse_transformers: bool = True
    fuse_laterals: bool = True
    fuse_sublaterals: bool = True
    sectionalize_long_laterals: bool = True
    sectionalize_length_ft: float = 5280.0
    max_fuses_in_series: int = 3


def _from_known_fields(cls, data: dict):
    """Build a dataclass ignoring unknown keys (keeps old/new files loadable)."""
    names = {f.name for f in fields(cls)}
    return cls(**{k: v for k, v in data.items() if k in names})


# -------------------------------------------------------------------- feeder


_ID_PREFIX = {"source": "SRC", "bus": "B", "transformer": "T", "segment": "L", "fuse": "F"}


@dataclass
class Feeder:
    name: str = "Untitled feeder"
    nodes: dict[str, Node] = field(default_factory=dict)
    segments: dict[str, Segment] = field(default_factory=dict)
    settings: StudySettings = field(default_factory=StudySettings)
    placement: PlacementPolicy = field(default_factory=PlacementPolicy)

    # ---- lookup

    @property
    def source(self) -> Source | None:
        return next((n for n in self.nodes.values() if isinstance(n, Source)), None)

    def sources(self) -> list[Source]:
        return [n for n in self.nodes.values() if isinstance(n, Source)]

    def transformers(self) -> list[Transformer]:
        return [n for n in self.nodes.values() if isinstance(n, Transformer)]

    def segments_at(self, node_id: str) -> list[Segment]:
        return [s for s in self.segments.values() if node_id in (s.node_a, s.node_b)]

    def segment_between(self, a: str, b: str) -> Segment | None:
        for s in self.segments.values():
            if {s.node_a, s.node_b} == {a, b}:
                return s
        return None

    def fuses(self) -> Iterator[tuple[Segment, Fuse]]:
        for s in self.segments.values():
            if s.fuse is not None:
                yield s, s.fuse

    def fuse_segment(self, fuse_id: str) -> Segment | None:
        return next((s for s, f in self.fuses() if f.id == fuse_id), None)

    def element(self, element_id: str) -> Node | Segment | Fuse | None:
        if element_id in self.nodes:
            return self.nodes[element_id]
        if element_id in self.segments:
            return self.segments[element_id]
        seg = self.fuse_segment(element_id)
        return seg.fuse if seg else None

    # ---- ids

    def new_id(self, kind: str) -> str:
        prefix = _ID_PREFIX[kind]
        used = set(self.nodes) | set(self.segments) | {f.id for _, f in self.fuses()}
        if kind == "source" and prefix not in used:
            return prefix
        n = 1
        while f"{prefix}{n}" in used:
            n += 1
        return f"{prefix}{n}"

    # ---- mutation

    def add_node(self, node: Node) -> Node:
        if node.id in self.nodes or node.id in self.segments:
            raise ValueError(f"Duplicate id {node.id}")
        if isinstance(node, Source) and self.source is not None:
            raise ValueError("A radial feeder has exactly one source")
        self.nodes[node.id] = node
        return node

    def add_segment(self, seg: Segment) -> Segment:
        if seg.id in self.segments or seg.id in self.nodes:
            raise ValueError(f"Duplicate id {seg.id}")
        for end in (seg.node_a, seg.node_b):
            if end not in self.nodes:
                raise ValueError(f"Unknown node {end}")
        if seg.node_a == seg.node_b:
            raise ValueError("A segment must join two different nodes")
        if self.segment_between(seg.node_a, seg.node_b):
            raise ValueError(f"{seg.node_a} and {seg.node_b} are already connected")
        self.segments[seg.id] = seg
        return seg

    def remove_node(self, node_id: str) -> None:
        for s in self.segments_at(node_id):
            del self.segments[s.id]
        del self.nodes[node_id]

    def remove_segment(self, seg_id: str) -> None:
        del self.segments[seg_id]

    def add_fuse(self, seg_id: str, origin: str = "manual", reason: str = "") -> Fuse:
        seg = self.segments[seg_id]
        if seg.fuse is None:
            fid = self.new_id("fuse")
            seg.fuse = Fuse(id=fid, name=fid, origin=origin, reason=reason)
        return seg.fuse

    # ---- persistence

    def to_dict(self) -> dict:
        nodes = []
        for n in self.nodes.values():
            d = asdict(n)
            d["kind"] = n.kind
            nodes.append(d)
        return {
            "schema": SCHEMA_VERSION,
            "name": self.name,
            "settings": asdict(self.settings),
            "placement": asdict(self.placement),
            "nodes": nodes,
            "segments": [asdict(s) for s in self.segments.values()],
        }

    @classmethod
    def from_dict(cls, data: dict) -> Feeder:
        feeder = cls(
            name=data.get("name", "Untitled feeder"),
            settings=_from_known_fields(StudySettings, data.get("settings", {})),
            placement=_from_known_fields(PlacementPolicy, data.get("placement", {})),
        )
        for nd in data.get("nodes", []):
            nd = dict(nd)
            node_cls = NODE_TYPES[nd.pop("kind")]
            feeder.nodes[nd["id"]] = _from_known_fields(node_cls, nd)
        for sd in data.get("segments", []):
            sd = dict(sd)
            fuse = sd.pop("fuse", None)
            seg = _from_known_fields(Segment, sd)
            seg.fuse = _from_known_fields(Fuse, fuse) if fuse else None
            feeder.segments[seg.id] = seg
        return feeder

    def save(self, path: str | Path) -> None:
        Path(path).write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> Feeder:
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))

    def copy(self) -> Feeder:
        return Feeder.from_dict(self.to_dict())


def new_feeder(name: str = "Untitled feeder") -> Feeder:
    """An empty feeder with just the source placed at the origin."""
    feeder = Feeder(name=name)
    feeder.add_node(Source(id="SRC", name="Substation", x=0.0, y=0.0))
    return feeder
