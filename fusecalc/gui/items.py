"""QGraphicsItems for the one-line diagram.

Phase notation: every segment is drawn as a single line, but its weight,
color, hash-mark count and label say which phases it carries - heavy black
with three ticks for ABC, brown with two ticks for two-phase, and the phase
color with one tick for single-phase taps.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import (
    QBrush,
    QFontMetricsF,
    QPainter,
    QPainterPath,
    QPainterPathStroker,
    QPen,
    QPolygonF,
    QTransform,
)
from PySide6.QtWidgets import QGraphicsItem

from fusecalc.gui import style
from fusecalc.model import Source, Transformer

if TYPE_CHECKING:
    from fusecalc.gui.document import Document

SELECTABLE = QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
MOVABLE = QGraphicsItem.GraphicsItemFlag.ItemIsMovable
GEOMETRY = QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges

NODE_RADIUS = {"source": 17.0, "bus": 5.0, "transformer": 13.0}


def unit(dx: float, dy: float) -> QPointF:
    length = math.hypot(dx, dy)
    return QPointF(1, 0) if length < 1e-9 else QPointF(dx / length, dy / length)


def label_side(u: QPointF) -> QPointF:
    """Normal to direction ``u`` that points up (or right for vertical lines)."""
    n = QPointF(-u.y(), u.x())
    if n.y() > 1e-6 or (abs(n.y()) <= 1e-6 and n.x() < 0):
        n = -n
    return n


class LabelItem(QGraphicsItem):
    """Multi-line text on a translucent background; ignores the mouse."""

    PAD = 2.0

    def __init__(self, parent: QGraphicsItem | None = None, point_size: float = 7.5,
                 bold: bool = False) -> None:
        super().__init__(parent)
        self.setAcceptedMouseButtons(Qt.MouseButton.NoButton)
        self.setZValue(1)
        self._font = style.label_font(point_size, bold)
        self._text = ""
        self._color = style.INK
        self._anchor = (0.5, 0.5)
        self._rect = QRectF()

    def set_text(self, text: str, color=None) -> None:
        self.prepareGeometryChange()
        self._text = text
        if color is not None:
            self._color = color
        self._layout()
        self.update()

    def place(self, point: QPointF, direction: QPointF, gap: float) -> None:
        """Put the label beside ``point``, on the ``direction`` side."""
        self.prepareGeometryChange()
        clamp = lambda v: max(-1.0, min(1.0, v * 1.5))  # noqa: E731
        self._anchor = (0.5 - 0.5 * clamp(direction.x()), 0.5 - 0.5 * clamp(direction.y()))
        self._layout()
        self.setPos(point + direction * gap)

    def _layout(self) -> None:
        if not self._text:
            self._rect = QRectF()
            return
        fm = QFontMetricsF(self._font)
        br = fm.boundingRect(QRectF(0, 0, 2000, 2000), Qt.AlignmentFlag.AlignLeft, self._text)
        w, h = br.width() + 2 * self.PAD, br.height() + 2 * self.PAD
        ax, ay = self._anchor
        self._rect = QRectF(-w * ax, -h * ay, w, h)

    def boundingRect(self) -> QRectF:
        return self._rect

    def paint(self, painter: QPainter, option, widget=None) -> None:
        if not self._text:
            return
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(style.LABEL_BG)
        painter.drawRoundedRect(self._rect, 2, 2)
        painter.setFont(self._font)
        painter.setPen(self._color)
        ax = self._anchor[0]
        h_align = (Qt.AlignmentFlag.AlignLeft if ax < 0.25 else
                   Qt.AlignmentFlag.AlignRight if ax > 0.75 else Qt.AlignmentFlag.AlignHCenter)
        inner = self._rect.adjusted(self.PAD, self.PAD, -self.PAD, -self.PAD)
        painter.drawText(inner, h_align | Qt.AlignmentFlag.AlignTop, self._text)


# ---------------------------------------------------------------- nodes


class NodeItem(QGraphicsItem):
    def __init__(self, doc: Document, node_id: str) -> None:
        super().__init__()
        self.doc = doc
        self.node_id = node_id
        self.kind = doc.feeder.nodes[node_id].kind
        self.radius = NODE_RADIUS[self.kind]
        self.setFlags(SELECTABLE | MOVABLE | GEOMETRY)
        self.setZValue(10)
        self.label = LabelItem(self, bold=self.kind == "source")
        self.away = QPointF(0, 1)  # direction pointing away from the connected line
        self._syncing = False

    @property
    def element_id(self) -> str:
        return self.node_id

    @property
    def node(self):
        return self.doc.feeder.nodes[self.node_id]

    def sync(self) -> None:
        node = self.node
        self._syncing = True
        self.setPos(node.x, node.y)
        self._syncing = False
        self.refresh()

    def refresh(self) -> None:
        """Recompute label text/placement from the model and neighbors."""
        node = self.node
        feeder = self.doc.feeder
        neighbors = [feeder.nodes[s.other_end(node.id)] for s in feeder.segments_at(node.id)]
        if neighbors:
            mx = sum(n.x for n in neighbors) / len(neighbors)
            my = sum(n.y for n in neighbors) / len(neighbors)
            self.away = unit(node.x - mx, node.y - my)
        else:
            self.away = QPointF(0, 1)

        if isinstance(node, Source):
            st = feeder.settings
            text = f"{node.label()}\n{st.nominal_kv_ll:g} kV  ·  {st.fault_3ph_a / 1000:.1f} kA 3Ø"
            self.label.set_text(text)
            self.label.place(QPointF(), self.away, self.radius + 5)
        elif isinstance(node, Transformer):
            text = f"{node.label()}\n{style.fmt_kva(node.kva)}  {node.phases}"
            self.label.set_text(text, style.phase_color(node.phases))
            self.label.place(QPointF(), self.away, self.radius + 3)
        else:
            self.label.set_text(node.label(), style.INK)
            self.label.place(QPointF(), unit(1, -1), self.radius + 2)
        self.prepareGeometryChange()
        self.update()

    def itemChange(self, change, value):
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionChange and not self._syncing:
            return QPointF(style.snap(value.x()), style.snap(value.y()))
        if change == QGraphicsItem.GraphicsItemChange.ItemPositionHasChanged and not self._syncing:
            node = self.doc.feeder.nodes.get(self.node_id)
            if node is not None:
                node.x, node.y = self.pos().x(), self.pos().y()
                if self.scene() is not None:
                    self.scene().node_moved(self.node_id)
        return super().itemChange(change, value)

    def boundingRect(self) -> QRectF:
        r = self.radius + 5
        return QRectF(-r, -r, 2 * r, 2 * r)

    def shape(self) -> QPainterPath:
        path = QPainterPath()
        r = max(self.radius, 8) + 2
        path.addEllipse(QPointF(), r, r)
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isSelected():
            painter.setPen(QPen(style.SELECT, 2.5))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(QPointF(), self.radius + 4, self.radius + 4)
        node = self.node
        if self.kind == "source":
            painter.setPen(QPen(style.INK, 2))
            painter.setBrush(QBrush(Qt.GlobalColor.white))
            painter.drawEllipse(QPointF(), self.radius, self.radius)
            wave = QPainterPath(QPointF(-9, 0))
            wave.cubicTo(QPointF(-4.5, -11), QPointF(0, -11), QPointF(0, 0))
            wave.cubicTo(QPointF(0, 11), QPointF(4.5, 11), QPointF(9, 0))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawPath(wave)
        elif self.kind == "transformer":
            color = style.phase_color(node.phases)
            painter.setPen(QPen(color, 1.8))
            painter.setBrush(QBrush(Qt.GlobalColor.white))
            back = -self.away * 5.0  # primary winding faces the line
            painter.drawEllipse(back, 7.5, 7.5)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawEllipse(-back, 7.5, 7.5)
        else:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(style.INK))
            painter.drawEllipse(QPointF(), self.radius, self.radius)


# -------------------------------------------------------------- segments


class SegmentItem(QGraphicsItem):
    def __init__(self, doc: Document, seg_id: str) -> None:
        super().__init__()
        self.doc = doc
        self.seg_id = seg_id
        self.setFlags(SELECTABLE)
        self.setZValue(1)
        self.label = LabelItem(self)
        self.highlight = False
        self.show_label = True
        self.p_up = QPointF()
        self.p_down = QPointF()
        self.up_id = ""
        self._shape = QPainterPath()

    @property
    def element_id(self) -> str:
        return self.seg_id

    @property
    def seg(self):
        return self.doc.feeder.segments[self.seg_id]

    def is_drop(self) -> bool:
        return isinstance(self.doc.feeder.nodes[self.seg.other_end(self.up_id)], Transformer)

    def update_geometry(self) -> None:
        self.prepareGeometryChange()
        seg = self.seg
        nodes = self.doc.feeder.nodes
        self.up_id = self.doc.context.tree.upstream.get(seg.id, seg.node_a)
        up, down = nodes[self.up_id], nodes[seg.other_end(self.up_id)]
        self.p_up, self.p_down = QPointF(up.x, up.y), QPointF(down.x, down.y)
        path = QPainterPath(self.p_up)
        path.lineTo(self.p_down)
        stroker = QPainterPathStroker()
        stroker.setWidth(12)
        self._shape = stroker.createStroke(path)

        text = ""
        if self.show_label and not (self.is_drop() and seg.length_ft == 0):
            parts = [seg.phases] + ([seg.conductor] if seg.conductor else [])
            text = "  ·  ".join(parts) + f"\n{style.fmt_ft(seg.length_ft)}"
        self.label.set_text(text, style.phase_color(seg.phases))
        u = self.direction()
        self.label.place((self.p_up + self.p_down) / 2, label_side(u), 9)
        self.update()

    def direction(self) -> QPointF:
        d = self.p_down - self.p_up
        return unit(d.x(), d.y())

    def boundingRect(self) -> QRectF:
        return self._shape.boundingRect().adjusted(-8, -8, 8, 8)

    def shape(self) -> QPainterPath:
        return self._shape

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        seg = self.seg
        line = QLineF(self.p_up, self.p_down)
        width = style.line_width(seg.phases)
        if self.highlight:
            painter.setPen(QPen(style.HIGHLIGHT, 16, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(line)
        if self.isSelected():
            painter.setPen(QPen(style.SELECT, width + 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(line)
        color = style.phase_color(seg.phases)
        painter.setPen(QPen(color, width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        painter.drawLine(line)

        # One slanted tick per phase conductor at the midpoint.
        if line.length() > 50:
            u, n = self.direction(), label_side(self.direction())
            mid = (self.p_up + self.p_down) / 2
            count = len(seg.phases)
            painter.setPen(QPen(color, 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for k in range(count):
                c = mid + u * ((k - (count - 1) / 2) * 5.0)
                painter.drawLine(QLineF(c + n * 5.5 + u * 2.2, c - n * 5.5 - u * 2.2))


# ------------------------------------------------------------------ fuses


class FuseItem(QGraphicsItem):
    """ANSI fuse symbol at the upstream end of its segment."""

    W, H = 20.0, 9.0

    def __init__(self, doc: Document, seg_id: str) -> None:
        super().__init__()
        self.doc = doc
        self.seg_id = seg_id
        self.setFlags(SELECTABLE)
        self.setZValue(6)
        self.label = LabelItem(self)
        self.status = "none"
        self._angle = 0.0

    @property
    def fuse(self):
        return self.doc.feeder.segments[self.seg_id].fuse

    @property
    def element_id(self) -> str:
        return self.fuse.id

    def update_geometry(self, seg_item: SegmentItem) -> None:
        a, b = seg_item.p_up, seg_item.p_down
        length = QLineF(a, b).length()
        u = seg_item.direction()
        up_kind = self.doc.feeder.nodes[seg_item.up_id].kind
        dist = min(NODE_RADIUS[up_kind] + 17, 0.45 * length)
        self.prepareGeometryChange()
        self.setPos(a + u * dist)
        self._angle = math.degrees(math.atan2(u.y(), u.x()))
        self.refresh(-label_side(u))

    def refresh(self, side: QPointF | None = None) -> None:
        fuse = self.fuse
        results = self.doc.results
        text, self.status = fuse.label(), "none"
        if results is not None and not self.doc.results_stale:
            link = results.links.get(fuse.id)
            coord = results.coordination_for(fuse.id)
            if link is not None:
                text += f"  {link.label()}"
            self.status = coord.status if coord else "none"  # nothing upstream to check
            if link is not None and not link.ok:
                self.status = "fail"
        elif fuse.rating_a:
            text += f"  {fuse.rating_a:g}{fuse.link_type or ''}"
        self.label.set_text(text, style.STATUS_COLORS[self.status]
                            if self.status in ("fail", "pass") else style.INK)
        if side is not None:
            self.label.place(QPointF(), side, 9)
        self.update()

    def boundingRect(self) -> QRectF:
        return QRectF(-16, -16, 32, 32)

    def shape(self) -> QPainterPath:
        grab = QRectF(-self.W / 2 - 3, -self.H / 2 - 4, self.W + 6, self.H + 8)
        path = QPainterPath()
        path.addPolygon(QTransform().rotate(self._angle).map(QPolygonF(grab)))
        return path

    def paint(self, painter: QPainter, option, widget=None) -> None:
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.rotate(self._angle)
        rect = QRectF(-self.W / 2, -self.H / 2, self.W, self.H)
        if self.isSelected():
            painter.setPen(QPen(style.SELECT, 3))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(-3, -3, 3, 3))
        painter.setPen(QPen(style.STATUS_COLORS[self.status], 2))
        painter.setBrush(QBrush(style.FUSE_FILL.get(self.fuse.origin, style.FUSE_FILL["manual"])))
        painter.drawRect(rect)
        painter.setPen(QPen(style.INK, 1.2))
        painter.drawLine(QLineF(-self.W / 2 + 2, 0, self.W / 2 - 2, 0))
