"""Feeder-level study inputs, auto-placement policy, and the diagram legend."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QBrush, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from fusecalc.gui import style
from fusecalc.gui.document import Document
from fusecalc.model import LINK_TYPES

PHILOSOPHY_LABELS = {"fuse_saving": "Fuse saving", "fuse_blowing": "Fuse blowing"}
MAINLINE_LABELS = {"three_phase": "Three-phase backbone", "heaviest_path": "Heaviest-load path"}


def _spin(lo: float, hi: float, decimals: int, step: float, suffix: str) -> QDoubleSpinBox:
    spin = QDoubleSpinBox()
    spin.setRange(lo, hi)
    spin.setDecimals(decimals)
    spin.setSingleStep(step)
    spin.setSuffix(suffix)
    spin.setKeyboardTracking(False)
    return spin


class StudyPanel(QWidget):
    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.doc = doc
        self._loading = False
        layout = QVBoxLayout(self)

        feeder_box = QGroupBox("Feeder / source")
        form = QFormLayout(feeder_box)
        self.name = QLineEdit()
        self.name.editingFinished.connect(
            lambda: self._set(None, "name", self.name.text().strip() or "Untitled feeder"))
        form.addRow("Name", self.name)
        self.kv = _spin(0.1, 69, 2, 0.01, " kV LL")
        self.i3 = _spin(1, 100_000, 0, 100, " A")
        self.islg = _spin(1, 100_000, 0, 100, " A")
        self.xr = _spin(0.1, 100, 1, 0.5, "")
        self.rf = _spin(0, 200, 1, 5, " Ω")
        for label, spin, attr in (("Nominal voltage", self.kv, "nominal_kv_ll"),
                                  ("Avail. 3Ø fault", self.i3, "fault_3ph_a"),
                                  ("Avail. SLG fault", self.islg, "fault_slg_a"),
                                  ("Source X/R", self.xr, "x_over_r"),
                                  ("Min-fault Rf", self.rf, "min_fault_resistance_ohm")):
            spin.valueChanged.connect(lambda v, a=attr: self._set("settings", a, float(v)))
            form.addRow(label, spin)
        self.philosophy = QComboBox()
        for key, text in PHILOSOPHY_LABELS.items():
            self.philosophy.addItem(text, key)
        self.philosophy.activated.connect(
            lambda _i: self._set("settings", "philosophy", self.philosophy.currentData()))
        form.addRow("Philosophy", self.philosophy)
        self.link = QComboBox()
        self.link.addItems(LINK_TYPES)
        self.link.activated.connect(
            lambda _i: self._set("settings", "preferred_link_type", self.link.currentText()))
        form.addRow("Default link type", self.link)
        layout.addWidget(feeder_box)

        place_box = QGroupBox("Auto-placement rules")
        pform = QFormLayout(place_box)
        self.mainline = QComboBox()
        for key, text in MAINLINE_LABELS.items():
            self.mainline.addItem(text, key)
        self.mainline.setToolTip(
            "Three-phase backbone: every 3Ø line fed through 3Ø line is mainline.\n"
            "Heaviest-load path: only the single path carrying the most load is mainline, "
            "so 3Ø branches are fused as laterals.")
        self.mainline.activated.connect(
            lambda _i: self._set("placement", "mainline_rule", self.mainline.currentData()))
        pform.addRow("Mainline", self.mainline)
        self.checks = {}
        for attr, text in (("fuse_transformers", "Fuse every transformer"),
                           ("fuse_laterals", "Fuse laterals at the mainline"),
                           ("fuse_sublaterals", "Fuse sub-lateral branches"),
                           ("sectionalize_long_laterals", "Sectionalize long laterals")):
            box = QCheckBox(text)
            box.toggled.connect(lambda on, a=attr: self._set("placement", a, on))
            self.checks[attr] = box
            pform.addRow(box)
        self.section_ft = _spin(100, 100_000, 0, 500, " ft")
        self.section_ft.valueChanged.connect(
            lambda v: self._set("placement", "sectionalize_length_ft", float(v)))
        pform.addRow("Sectionalize after", self.section_ft)
        self.max_series = QSpinBox()
        self.max_series.setRange(1, 8)
        self.max_series.setKeyboardTracking(False)
        self.max_series.valueChanged.connect(
            lambda v: self._set("placement", "max_fuses_in_series", int(v)))
        pform.addRow("Max fuses in series", self.max_series)
        layout.addWidget(place_box)

        legend_box = QGroupBox("Legend")
        QVBoxLayout(legend_box).addWidget(LegendWidget())
        layout.addWidget(legend_box)
        layout.addStretch(1)

        doc.reset.connect(self.load)
        self.load()

    def _set(self, group: str | None, attr: str, value) -> None:
        if self._loading:
            return
        target = self.doc.feeder if group is None else getattr(self.doc.feeder, group)
        if getattr(target, attr) == value:
            return
        with self.doc.edit() as f:
            setattr(f if group is None else getattr(f, group), attr, value)

    def load(self) -> None:
        self._loading = True
        f = self.doc.feeder
        st, pol = f.settings, f.placement
        self.name.setText(f.name)
        self.kv.setValue(st.nominal_kv_ll)
        self.i3.setValue(st.fault_3ph_a)
        self.islg.setValue(st.fault_slg_a)
        self.xr.setValue(st.x_over_r)
        self.rf.setValue(st.min_fault_resistance_ohm)
        self.philosophy.setCurrentIndex(max(0, self.philosophy.findData(st.philosophy)))
        self.link.setCurrentText(st.preferred_link_type)
        self.mainline.setCurrentIndex(max(0, self.mainline.findData(pol.mainline_rule)))
        for attr, box in self.checks.items():
            box.setChecked(getattr(pol, attr))
        self.section_ft.setValue(pol.sectionalize_length_ft)
        self.max_series.setValue(pol.max_fuses_in_series)
        self._loading = False


class LegendWidget(QWidget):
    ROWS = [
        ("line", "ABC", "Three-phase (3 ticks)"),
        ("line", "AB", "Two-phase, e.g. AB (2 ticks)"),
        ("line", "A", "Phase A single-phase tap"),
        ("line", "B", "Phase B single-phase tap"),
        ("line", "C", "Phase C single-phase tap"),
        ("fuse", "pass", "Fuse - coordinates"),
        ("fuse", "fail", "Fuse - fails / no link fits"),
        ("fuse", "not_checked", "Fuse - not checked"),
        ("auto", "none", "Auto-placed fuse (blue fill)"),
    ]
    ROW_H = 20

    def sizeHint(self) -> QSize:
        return QSize(220, self.ROW_H * len(self.ROWS) + 4)

    def minimumSizeHint(self) -> QSize:
        return self.sizeHint()

    def paintEvent(self, event) -> None:
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setFont(style.label_font(8.5))
        p.fillRect(self.rect(), style.CANVAS_BG)  # same paper as the canvas, any theme
        for row, (kind, key, text) in enumerate(self.ROWS):
            y = 2 + row * self.ROW_H + self.ROW_H / 2
            if kind == "line":
                color = style.phase_color(key)
                p.setPen(QPen(color, style.line_width(key)))
                p.drawLine(QLineF(4, y, 44, y))
                p.setPen(QPen(color, 1.4))
                for k in range(len(key)):
                    c = QPointF(24 + (k - (len(key) - 1) / 2) * 5, y)
                    p.drawLine(QLineF(c + QPointF(2.2, -5.5), c + QPointF(-2.2, 5.5)))
            else:
                p.setPen(QPen(style.INK, 1.5))
                p.drawLine(QLineF(4, y, 44, y))
                fill = style.FUSE_FILL["auto" if kind == "auto" else "manual"]
                p.setPen(QPen(style.STATUS_COLORS[key], 2))
                p.setBrush(QBrush(fill))
                p.drawRect(QRectF(14, y - 4.5, 20, 9))
                p.setPen(QPen(style.INK, 1.1))
                p.drawLine(QLineF(16, y, 32, y))
            p.setPen(style.INK)
            p.drawText(QRectF(52, y - 9, 200, 18), Qt.AlignmentFlag.AlignVCenter, text)
        p.end()
