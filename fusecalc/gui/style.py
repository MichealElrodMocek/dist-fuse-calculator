"""Colors, pens and number formatting for the one-line diagram.

There is no single industry standard for phase colors; utilities pick their
own. Change ``PHASE_COLORS`` to match the convention you want.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont

GRID = 20  # snap spacing, scene units

CANVAS_BG = QColor("#fbfbf8")
GRID_MINOR = QColor("#eeeee8")
GRID_MAJOR = QColor("#e0e0d8")
INK = QColor("#263238")  # symbols and text
LABEL_BG = QColor(251, 251, 248, 215)
SELECT = QColor("#ff8f00")
HIGHLIGHT = QColor(255, 213, 79, 150)

PHASE_COLORS = {"A": QColor("#d32f2f"), "B": QColor("#1565c0"), "C": QColor("#2e7d32")}
MULTIPHASE_COLORS = {3: QColor("#212121"), 2: QColor("#5d4037")}
LINE_WIDTHS = {3: 3.4, 2: 2.6, 1: 1.9}

STATUS_COLORS = {
    "pass": QColor("#2e7d32"),
    "fail": QColor("#c62828"),
    "warning": QColor("#ef6c00"),
    "not_checked": QColor("#9e9e9e"),
    "none": QColor("#455a64"),
}
FUSE_FILL = {"manual": QColor("#ffffff"), "auto": QColor("#e3eefc")}


def phase_color(phases: str) -> QColor:
    if len(phases) == 1:
        return PHASE_COLORS[phases]
    return MULTIPHASE_COLORS[len(phases)]


def line_width(phases: str) -> float:
    return LINE_WIDTHS[len(phases)]


def label_font(point_size: float = 7.5, bold: bool = False) -> QFont:
    font = QFont()
    font.setPointSizeF(point_size)
    font.setBold(bold)
    return font


def snap(value: float) -> float:
    return round(value / GRID) * GRID


def fmt_amps(a: float | None) -> str:
    if a is None:
        return "-"
    if abs(a) >= 1000:
        return f"{a / 1000:.2f} kA"
    return f"{a:.1f} A"


def fmt_ft(ft: float) -> str:
    return f"{ft / 5280:.2f} mi" if ft >= 5280 else f"{ft:,.0f} ft"


def fmt_kva(kva: float) -> str:
    return f"{kva:g} kVA"
