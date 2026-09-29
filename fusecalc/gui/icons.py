"""Toolbar icons drawn with QPainter so the repo ships no image files."""

from __future__ import annotations

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QBrush, QIcon, QPainter, QPainterPath, QPen, QPixmap, QPolygonF

from fusecalc.gui import style

SIZE = 32


def _icon(draw) -> QIcon:
    pm = QPixmap(SIZE * 2, SIZE * 2)
    pm.setDevicePixelRatio(2)
    pm.fill(Qt.GlobalColor.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    draw(p)
    p.end()
    return QIcon(pm)


def select_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        arrow = QPolygonF([QPointF(9, 5), QPointF(9, 25), QPointF(14, 20), QPointF(18, 28),
                           QPointF(21, 27), QPointF(17, 19), QPointF(24, 19)])
        p.setPen(QPen(style.INK, 1.5))
        p.setBrush(QBrush(Qt.GlobalColor.white))
        p.drawPolygon(arrow)
    return _icon(draw)


def bus_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(style.INK, 2.5))
        p.drawLine(QLineF(4, 16, 28, 16))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(style.INK))
        p.drawEllipse(QPointF(16, 16), 5, 5)
    return _icon(draw)


def transformer_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(style.PHASE_COLORS["B"], 2))
        p.setBrush(QBrush(Qt.GlobalColor.white))
        p.drawEllipse(QPointF(16, 11), 7, 7)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawEllipse(QPointF(16, 21), 7, 7)
    return _icon(draw)


def line_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(style.INK, 3, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        p.drawLine(QLineF(6, 26, 26, 6))
        p.setPen(QPen(style.INK, 1.5))
        for k in (-1, 0, 1):
            c = QPointF(16 + 3.5 * k, 16 - 3.5 * k)
            p.drawLine(QLineF(c + QPointF(-2, -4), c + QPointF(2, 4)))
    return _icon(draw)


def fuse_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(QPen(style.INK, 2))
        p.drawLine(QLineF(2, 16, 30, 16))
        p.setBrush(QBrush(Qt.GlobalColor.white))
        p.setPen(QPen(style.STATUS_COLORS["pass"], 2))
        p.drawRect(QRectF(7, 11, 18, 10))
        p.setPen(QPen(style.INK, 1.3))
        p.drawLine(QLineF(9, 16, 23, 16))
    return _icon(draw)


def auto_place_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        path = QPainterPath(QPointF(16, 3))
        for x, y in ((19, 12), (29, 13), (21, 19), (24, 29), (16, 23), (8, 29), (11, 19),
                     (3, 13), (13, 12)):
            path.lineTo(x, y)
        path.closeSubpath()
        p.setPen(QPen(style.INK, 1.2))
        p.setBrush(QBrush(style.SELECT))
        p.drawPath(path)
    return _icon(draw)


def run_icon() -> QIcon:
    def draw(p: QPainter) -> None:
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(style.STATUS_COLORS["pass"]))
        p.drawPolygon(QPolygonF([QPointF(9, 6), QPointF(26, 16), QPointF(9, 26)]))
    return _icon(draw)
