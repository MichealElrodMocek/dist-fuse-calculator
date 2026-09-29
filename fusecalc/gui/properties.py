"""Property editor for the selected source, bus, transformer, segment or fuse."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from fusecalc.gui import style
from fusecalc.gui.document import Document
from fusecalc.gui.scene import OneLineScene
from fusecalc.library import conductor_names
from fusecalc.model import (
    LINK_TYPES,
    PHASE_CHOICES,
    TRANSFORMER_KVA_1PH,
    TRANSFORMER_KVA_3PH,
    Feeder,
    Fuse,
    Segment,
    Source,
    Transformer,
)
from fusecalc.topology import supply_phases, transformer_load

FUSE_RATINGS = (1, 2, 3, 5, 6, 8, 10, 12, 15, 20, 25, 30, 40, 50, 65, 80, 100, 140, 200)
AUTO = "Auto"


class PropertiesPanel(QWidget):
    def __init__(self, doc: Document, scene: OneLineScene, parent=None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.scene = scene
        self.element_id: str | None = None
        self._editing = False

        layout = QVBoxLayout(self)
        self.title = QLabel()
        self.title.setStyleSheet("font-weight: 600; font-size: 13px;")
        layout.addWidget(self.title)
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        layout.addWidget(self.form_host)
        self.info = QLabel()
        self.info.setWordWrap(True)
        self.info.setTextFormat(Qt.TextFormat.RichText)
        self.info.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.info.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(self.info)
        layout.addStretch(1)

        scene.selectionChanged.connect(self.rebuild)
        doc.reset.connect(self.rebuild)
        doc.changed.connect(self._on_changed)
        doc.results_changed.connect(self.refresh_info)
        self.rebuild()

    # ------------------------------------------------------------ plumbing

    def _on_changed(self) -> None:
        if self._editing:
            self.refresh_info()
        else:
            self.rebuild()

    def _apply(self, change: Callable[[Feeder], None]) -> None:
        self._editing = True
        try:
            with self.doc.edit() as feeder:
                change(feeder)
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid value", str(exc))
            self.rebuild()
        finally:
            self._editing = False

    def _clear_form(self) -> None:
        # Swap in a fresh form and delete the old one later: rebuild can run
        # from inside a signal of one of the widgets being replaced.
        old = self.form_host
        self.form_host = QWidget()
        self.form = QFormLayout(self.form_host)
        self.form.setContentsMargins(0, 4, 0, 4)
        self.form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        self.layout().replaceWidget(old, self.form_host)
        old.hide()
        old.deleteLater()

    def rebuild(self) -> None:
        self._clear_form()
        try:
            ids = self.scene.selected_ids()
        except RuntimeError:  # scene torn down during shutdown
            return
        self.element_id = ids[0] if len(ids) == 1 else None
        element = self.doc.feeder.element(self.element_id) if self.element_id else None
        if element is None:
            self.element_id = None
            self.title.setText(f"{len(ids)} items selected" if ids else "Nothing selected")
            self.info.setText(
                "Select an element on the one-line to edit it.<br><br>"
                "<b>Tips</b><br>B / T / L / F pick the Bus, Transformer, Line and Fuse tools; "
                "V or Esc returns to Select.<br>With one node selected, placing a bus or "
                "transformer wires it to that node automatically.")
            return
        if isinstance(element, Fuse):
            self._build_fuse(element)
        elif isinstance(element, Segment):
            self._build_segment(element)
        else:
            self._build_node(element)
        self.refresh_info()

    # ---------------------------------------------------------- widgets

    def _name_row(self, element) -> None:
        edit = QLineEdit(element.name)
        edit.setPlaceholderText(element.id)

        def commit() -> None:
            el_id = element.id
            if edit.text() != element.name and self.doc.feeder.element(el_id) is not None:
                self._apply(lambda f: setattr(f.element(el_id), "name", edit.text().strip()))
        edit.editingFinished.connect(commit)
        self.form.addRow("Name", edit)

    def _phase_combo(self, current: str, on_pick: Callable[[str], None]) -> QComboBox:
        combo = QComboBox()
        combo.addItems(PHASE_CHOICES)
        combo.setCurrentText(current)
        combo.activated.connect(lambda _i: on_pick(combo.currentText()))
        return combo

    def _number_combo(self, values, current: float | None, on_value, allow_auto=False,
                      suffix="") -> QComboBox:
        combo = QComboBox()
        combo.setEditable(True)
        combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        if allow_auto:
            combo.addItem(AUTO)
        combo.addItems([f"{v:g}" for v in values])
        combo.setCurrentText(AUTO if current is None else f"{current:g}")
        if suffix:
            combo.lineEdit().setPlaceholderText(suffix)

        def commit(*_):
            text = combo.currentText().strip()
            if allow_auto and (not text or text.lower() == AUTO.lower()):
                on_value(None)
                return
            try:
                value = float(text)
            except ValueError:
                QMessageBox.warning(self, "Invalid value", f"{text!r} is not a number.")
                return
            if value <= 0:
                QMessageBox.warning(self, "Invalid value", "Value must be positive.")
                return
            on_value(value)
        combo.activated.connect(commit)
        combo.lineEdit().editingFinished.connect(commit)
        combo.lineEdit().setValidator(None if allow_auto else QDoubleValidator(0, 1e6, 2))
        return combo

    def _build_node(self, node) -> None:
        self.title.setText(f"{node.kind.title()}  {node.id}")
        self._name_row(node)
        if isinstance(node, Source):
            note = QLabel("Voltage and available fault current are set in the Study panel.")
            note.setWordWrap(True)
            self.form.addRow(note)
        elif isinstance(node, Transformer):
            nid = node.id
            sizes = TRANSFORMER_KVA_3PH if len(node.phases) == 3 else TRANSFORMER_KVA_1PH

            def set_kva(v):
                if v != node.kva:
                    self._apply(lambda f: setattr(f.nodes[nid], "kva", v))
            self.form.addRow("kVA", self._number_combo(sizes, node.kva, set_kva))

            def set_phases(p):
                if p == node.phases:
                    return

                def change(f: Feeder) -> None:
                    f.nodes[nid].phases = p
                    for seg in f.segments_at(nid):  # the drop follows the transformer
                        seg.phases = p
                self._apply(change)
            self.form.addRow("Phases", self._phase_combo(node.phases, set_phases))

    def _build_segment(self, seg: Segment) -> None:
        self.title.setText(f"Line segment  {seg.id}")
        self._name_row(seg)
        sid = seg.id

        def set_attr(attr, value):
            if getattr(seg, attr) != value:
                self._apply(lambda f: setattr(f.segments[sid], attr, value))

        self.form.addRow("Phases", self._phase_combo(seg.phases, lambda p: set_attr("phases", p)))

        length = QDoubleSpinBox()
        length.setRange(0, 500_000)
        length.setDecimals(0)
        length.setSingleStep(100)
        length.setSuffix(" ft")
        length.setKeyboardTracking(False)
        length.setValue(seg.length_ft)
        length.valueChanged.connect(lambda v: set_attr("length_ft", float(v)))
        self.form.addRow("Length", length)

        cond = QComboBox()
        cond.setEditable(True)
        cond.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        cond.addItems(conductor_names())
        cond.setCurrentText(seg.conductor)
        cond.activated.connect(lambda _i: set_attr("conductor", cond.currentText().strip()))
        cond.lineEdit().editingFinished.connect(
            lambda: set_attr("conductor", cond.currentText().strip()))
        self.form.addRow("Conductor", cond)

        has_fuse = QCheckBox("Fuse at upstream end")
        has_fuse.setChecked(seg.fuse is not None)
        has_fuse.toggled.connect(lambda _on: self.scene.toggle_fuse(sid))
        self.form.addRow("", has_fuse)

        blocked = QCheckBox("Never auto-place a fuse here")
        blocked.setChecked(seg.fuse_blocked)
        blocked.toggled.connect(lambda on: set_attr("fuse_blocked", on))
        self.form.addRow("", blocked)

    def _build_fuse(self, fuse: Fuse) -> None:
        seg = self.doc.feeder.fuse_segment(fuse.id)
        sid = seg.id
        self.title.setText(f"Fuse  {fuse.id}")
        self._name_row(fuse)

        def set_attr(attr, value):
            if getattr(fuse, attr) != value:
                def change(f: Feeder) -> None:
                    target = f.segments[sid].fuse
                    setattr(target, attr, value)
                    target.origin = "manual"  # user-edited fuses survive auto-placement
                self._apply(change)

        ltype = QComboBox()
        ltype.addItems([AUTO, *LINK_TYPES])
        ltype.setCurrentText(fuse.link_type or AUTO)
        ltype.activated.connect(
            lambda _i: set_attr("link_type", None if ltype.currentText() == AUTO
                                else ltype.currentText()))
        self.form.addRow("Link type", ltype)
        self.form.addRow("Rating (A)", self._number_combo(
            FUSE_RATINGS, fuse.rating_a, lambda v: set_attr("rating_a", v), allow_auto=True))

        origin = QLabel("Placed by auto-placement" if fuse.origin == "auto" else "Placed by you")
        self.form.addRow("Origin", origin)
        if fuse.origin == "auto":
            keep = QPushButton("Keep (mark as manual)")
            keep.clicked.connect(lambda: set_attr("origin", "manual"))
            self.form.addRow("", keep)
        remove = QPushButton("Remove fuse")
        remove.clicked.connect(lambda: self.scene.toggle_fuse(sid))
        self.form.addRow("", remove)

    # --------------------------------------------------------------- info

    def refresh_info(self) -> None:
        if self.element_id is None:
            return
        f, ctx, res = self.doc.feeder, self.doc.context, self.doc.results
        element = f.element(self.element_id)
        if element is None:
            return
        rows: list[str] = []

        def fault_rows(node_id: str) -> None:
            fault = res.faults.get(node_id) if res else None
            if fault:
                rows.extend([
                    f"Max 3Ø fault: <b>{style.fmt_amps(fault.i3ph_a)}</b>",
                    f"Max SLG fault: <b>{style.fmt_amps(fault.islg_a)}</b>",
                    f"Min fault: <b>{style.fmt_amps(fault.imin_a)}</b>",
                ])

        if isinstance(element, Fuse):
            seg = f.fuse_segment(element.id)
            at = ctx.tree.upstream.get(seg.id)
            if at:
                rows.append(f"Located at <b>{f.nodes[at].label()}</b> on {seg.label()} "
                            f"({seg.phases})")
            if element.reason:
                rows.append(f"<i>{element.reason}</i>")
            load = ctx.loads.get(seg.id)
            if load:
                rows.append(f"Protects {style.fmt_kva(load.total_kva)} in "
                            f"{load.transformer_count} transformer(s), peak phase "
                            f"{load.max_amps:.1f} A")
            if at:
                fault_rows(at)
            link = res.links.get(element.id) if res else None
            if link:
                colour = "" if link.ok else " style='color:#c62828'"
                rows.append(f"<span{colour}>Selected link: <b>{link.label()}</b> - {link.note}</span>")
            coord = res.coordination_for(element.id) if res else None
            if coord:
                margin = "-" if coord.margin_a is None else style.fmt_amps(coord.margin_a)
                rows.append(f"Coordination vs <b>{coord.protected_fuse}</b>: "
                            f"<b>{coord.status.replace('_', ' ')}</b> (fault {style.fmt_amps(coord.fault_current_a)}, "
                            f"limit {style.fmt_amps(coord.limit_a)}, margin {margin})")
                if coord.note:
                    rows.append(f"<i>{coord.note}</i>")
            elif res:
                rows.append("No fuse upstream; coordinates with the substation device.")
        elif isinstance(element, Segment):
            if element.id in ctx.tree.upstream:
                up = f.nodes[ctx.tree.upstream[element.id]]
                rows.append(f"Fed from <b>{up.label()}</b>, "
                            f"{style.fmt_ft(ctx.tree.distance_ft[up.id])} from the source")
            load = ctx.loads.get(element.id)
            if load:
                rows.append(f"Downstream load: <b>{style.fmt_kva(load.total_kva)}</b> in "
                            f"{load.transformer_count} transformer(s)")
                rows.append("<br>".join(
                    f"Phase {p}: {load.kva[p]:.1f} kVA, {load.amps[p]:.1f} A"
                    for p in element.phases))
                if len(element.phases) > 1:
                    rows.append(f"Imbalance: {load.imbalance_pct(element.phases):.0f}%")
            else:
                rows.append("Not connected to the source.")
        else:
            if ctx.tree.reaches(element.id):
                avail = supply_phases(f, ctx.tree, element.id)
                rows.append(f"Phases available here: <b>{avail}</b>")
                rows.append(f"Distance from source: {style.fmt_ft(ctx.tree.distance_ft[element.id])}")
            elif not isinstance(element, Source):
                rows.append("<span style='color:#c62828'>Not connected to the source.</span>")
            if isinstance(element, Transformer):
                load = transformer_load(element, f.settings.nominal_kv_ll)
                rows.append(f"Full-load current: {max(load.amps.values()):.1f} A per phase")
            fault_rows(element.id)

        if res is not None and res.is_placeholder:
            rows.append("<span style='color:#9e9e9e'>Values from the placeholder engine.</span>")
        self.info.setText("<br><br>".join(rows))
