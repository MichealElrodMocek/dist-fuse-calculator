"""The one-line editor canvas: keeps items in sync with the model and
implements the drawing tools."""

from __future__ import annotations

import math
from enum import Enum

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPen
from PySide6.QtWidgets import QGraphicsLineItem, QGraphicsScene, QMenu

from fusecalc.gui import style
from fusecalc.gui.document import Document
from fusecalc.gui.items import FuseItem, NodeItem, SegmentItem
from fusecalc.model import Bus, Feeder, Segment, Source, Transformer, phases_subset
from fusecalc.topology import supply_phases, transformer_load

DEFAULT_LINE_FT = 500.0
DEFAULT_CONDUCTOR = "336.4 ACSR"


class Tool(str, Enum):
    SELECT = "select"
    BUS = "bus"
    TRANSFORMER = "transformer"
    LINE = "line"
    FUSE = "fuse"


TOOL_HINTS = {
    Tool.SELECT: "Select: click to select, drag to move, drag on empty space to box-select.",
    Tool.BUS: "Bus: click to place a junction/pole. If one node is selected, the new bus "
              "is wired to it.",
    Tool.TRANSFORMER: "Transformer: click to place. If one node is selected it is wired to "
                      "it on the least-loaded available phase.",
    Tool.LINE: "Line: click a node to start, then click another node (or empty space to "
               "drop a new bus). Esc or right-click stops.",
    Tool.FUSE: "Fuse: click a line to add or remove a fuse at its upstream end.",
}


class OneLineScene(QGraphicsScene):
    message = Signal(str)

    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.tool = Tool.SELECT
        self.nodes: dict[str, NodeItem] = {}
        self.segments: dict[str, SegmentItem] = {}
        self.fuses: dict[str, FuseItem] = {}  # keyed by segment id
        self.show_segment_labels = True
        self._line_start: str | None = None
        self._rubber: QGraphicsLineItem | None = None
        self._drag_before: dict | None = None
        doc.changed.connect(self.sync)
        doc.reset.connect(self.rebuild)
        doc.results_changed.connect(self.refresh_results)
        self.rebuild()

    # ------------------------------------------------------------ syncing

    def rebuild(self) -> None:
        self.cancel_line()
        for group in (self.fuses, self.segments, self.nodes):
            for item in group.values():
                self.removeItem(item)
            group.clear()
        self.sync()

    def sync(self) -> None:
        f = self.doc.feeder
        for nid in [n for n in self.nodes if n not in f.nodes]:
            self.removeItem(self.nodes.pop(nid))
        for sid in [s for s in self.segments if s not in f.segments]:
            self.removeItem(self.segments.pop(sid))
        for sid in [s for s in self.fuses if s not in f.segments or f.segments[s].fuse is None]:
            self.removeItem(self.fuses.pop(sid))

        for nid in f.nodes:
            if nid not in self.nodes:
                self.nodes[nid] = NodeItem(self.doc, nid)
                self.addItem(self.nodes[nid])
        for sid, seg in f.segments.items():
            if sid not in self.segments:
                self.segments[sid] = SegmentItem(self.doc, sid)
                self.addItem(self.segments[sid])
            if seg.fuse is not None and sid not in self.fuses:
                self.fuses[sid] = FuseItem(self.doc, sid)
                self.addItem(self.fuses[sid])

        for item in self.nodes.values():
            item.sync()
        for item in self.segments.values():
            item.show_label = self.show_segment_labels
            item.update_geometry()
        for sid, item in self.fuses.items():
            item.update_geometry(self.segments[sid])
        self._update_tooltips()

    def node_moved(self, node_id: str) -> None:
        for seg in self.doc.feeder.segments_at(node_id):
            item = self.segments.get(seg.id)
            if item is None:
                continue
            item.update_geometry()
            if seg.id in self.fuses:
                self.fuses[seg.id].update_geometry(item)
            other = self.nodes.get(seg.other_end(node_id))
            if other is not None:
                other.refresh()
        self.nodes[node_id].refresh()

    def refresh_results(self) -> None:
        segments = self.doc.feeder.segments
        for sid, item in self.fuses.items():
            if sid in segments and segments[sid].fuse is not None:
                item.refresh()
        for item in self.nodes.values():
            item.refresh()
        self._update_tooltips()

    def set_show_segment_labels(self, on: bool) -> None:
        self.show_segment_labels = on
        self.sync()

    def set_highlight(self, seg_ids: set[str]) -> None:
        for sid, item in self.segments.items():
            item.highlight = sid in seg_ids
            item.update()

    def _update_tooltips(self) -> None:
        f, ctx, res = self.doc.feeder, self.doc.context, self.doc.results
        for nid, item in self.nodes.items():
            node = f.nodes[nid]
            lines = [f"<b>{node.label()}</b> ({node.kind})"]
            if isinstance(node, Transformer):
                load = transformer_load(node, f.settings.nominal_kv_ll)
                lines.append(f"{style.fmt_kva(node.kva)} on {node.phases}, "
                             f"FLA {style.fmt_amps(max(load.amps.values()))}")
            fault = res.faults.get(nid) if res else None
            if fault:
                lines.append(f"Max 3Ø: {style.fmt_amps(fault.i3ph_a)}<br>"
                             f"Max SLG: {style.fmt_amps(fault.islg_a)}<br>"
                             f"Min: {style.fmt_amps(fault.imin_a)}")
            item.setToolTip("<br>".join(lines))
        for sid, item in self.segments.items():
            seg = f.segments[sid]
            lines = [f"<b>{seg.label()}</b>  {seg.phases}  {seg.conductor}",
                     style.fmt_ft(seg.length_ft)]
            load = ctx.loads.get(sid)
            if load:
                amps = "  ".join(f"{p}: {load.amps[p]:.1f} A" for p in seg.phases)
                lines.append(f"Downstream {style.fmt_kva(load.total_kva)} "
                             f"({load.transformer_count} tx)<br>{amps}")
            item.setToolTip("<br>".join(lines))
        for sid, item in self.fuses.items():
            fuse = f.segments[sid].fuse
            lines = [f"<b>{fuse.label()}</b> ({fuse.origin})"]
            if fuse.reason:
                lines.append(fuse.reason)
            if res and fuse.id in res.links:
                link = res.links[fuse.id]
                lines.append(f"Link {link.label()} for {link.load_a:.1f} A load. {link.note}")
            coord = res.coordination_for(fuse.id) if res else None
            if coord:
                lines.append(f"vs {coord.protected_fuse}: {coord.status}. {coord.note}")
            item.setToolTip("<br>".join(lines))

    # ---------------------------------------------------------- selection

    def selected_ids(self) -> list[str]:
        return [item.element_id for item in self.selectedItems() if hasattr(item, "element_id")]

    def item_for(self, element_id: str):
        if element_id in self.nodes:
            return self.nodes[element_id]
        if element_id in self.segments:
            return self.segments[element_id]
        return next((i for i in self.fuses.values() if i.element_id == element_id), None)

    def select_element(self, element_id: str):
        item = self.item_for(element_id)
        self.clearSelection()
        if item is not None:
            item.setSelected(True)
        return item

    def _selected_node(self) -> str | None:
        nodes = [i for i in self.selectedItems() if isinstance(i, NodeItem)]
        return nodes[0].node_id if len(nodes) == 1 and len(self.selectedItems()) == 1 else None

    # --------------------------------------------------------------- tools

    def set_tool(self, tool: Tool) -> None:
        self.cancel_line()
        self.tool = tool
        self.message.emit(TOOL_HINTS[tool])

    def node_at(self, pos: QPointF) -> str | None:
        for item in self.items(pos):
            if isinstance(item, NodeItem):
                return item.node_id
        return None

    def segment_at(self, pos: QPointF) -> str | None:
        for item in self.items(pos):
            if isinstance(item, (FuseItem, SegmentItem)):
                return item.seg_id
        return None

    def mousePressEvent(self, event) -> None:
        pos = event.scenePos()
        if event.button() == Qt.MouseButton.RightButton and self._line_start:
            self.cancel_line()
            event.accept()
            return
        if event.button() != Qt.MouseButton.LeftButton or self.tool == Tool.SELECT:
            if event.button() == Qt.MouseButton.LeftButton:
                self._drag_before = self.doc.checkpoint()
            super().mousePressEvent(event)
            return
        event.accept()
        if self.tool in (Tool.BUS, Tool.TRANSFORMER):
            self.place_node(self.tool, pos)
        elif self.tool == Tool.FUSE:
            seg_id = self.segment_at(pos)
            if seg_id:
                self.toggle_fuse(seg_id)
        elif self.tool == Tool.LINE:
            self._line_click(pos)

    def mouseMoveEvent(self, event) -> None:
        if self._rubber is not None:
            line = self._rubber.line()
            line.setP2(event.scenePos())
            self._rubber.setLine(line)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        super().mouseReleaseEvent(event)
        if self._drag_before is not None:
            before, self._drag_before = self._drag_before, None
            self.doc.commit_checkpoint(before)

    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape and self._line_start:
            self.cancel_line()
            return
        super().keyPressEvent(event)

    # ---- line drawing

    def _line_click(self, pos: QPointF) -> None:
        target = self.node_at(pos)
        if self._line_start is None:
            if target is None:
                self.message.emit("Start a line on a source, bus or transformer.")
            else:
                self._start_line(target)
            return
        if target == self._line_start:
            return
        if target is None:
            new_id = self._new_bus_and_connect(self._line_start, pos)
            if new_id:
                self._start_line(new_id)
            return
        seg_id = self.connect_nodes(self._line_start, target)
        if seg_id is None:
            return
        node = self.doc.feeder.nodes[target]
        if isinstance(node, Transformer):
            self.cancel_line()
        else:
            self._start_line(target)

    def _start_line(self, node_id: str) -> None:
        self.cancel_line()
        node = self.doc.feeder.nodes[node_id]
        self._line_start = node_id
        self._rubber = QGraphicsLineItem(QLineF(node.x, node.y, node.x, node.y))
        self._rubber.setPen(QPen(style.SELECT, 1.5, Qt.PenStyle.DashLine))
        self._rubber.setZValue(20)
        self.addItem(self._rubber)

    def cancel_line(self) -> None:
        if self._rubber is not None:
            self.removeItem(self._rubber)
        self._rubber = None
        self._line_start = None

    # -------------------------------------------------------------- edits

    def place_node(self, tool: Tool, pos: QPointF) -> str:
        anchor = self._selected_node()
        if anchor and isinstance(self.doc.feeder.nodes[anchor], Transformer):
            anchor = None
        x, y = style.snap(pos.x()), style.snap(pos.y())
        with self.doc.edit() as f:
            nid = f.new_id(tool.value)
            if tool == Tool.BUS:
                f.add_node(Bus(id=nid, name=nid, x=x, y=y))
            else:
                phases = self._default_tx_phases(anchor)
                f.add_node(Transformer(id=nid, name=nid, x=x, y=y, phases=phases,
                                       kva=75.0 if len(phases) == 3 else 25.0))
            if anchor:
                _add_segment(f, self.doc, anchor, nid)
        self.select_element(nid)
        return nid

    def _default_tx_phases(self, anchor: str | None) -> str:
        """Least-loaded phase available at ``anchor`` (single-phase units)."""
        ctx = self.doc.context
        if anchor is None or not ctx.tree.reaches(anchor):
            return "A"
        avail = supply_phases(self.doc.feeder, ctx.tree, anchor)
        seg_id = ctx.tree.parent_segment.get(anchor)
        if seg_id is None:  # anchor is the source: use the whole feeder load
            seg_ids = ctx.tree.children.get(anchor, [])
        else:
            seg_ids = [seg_id]
        amps = {p: sum(ctx.loads[s].amps[p] for s in seg_ids if s in ctx.loads) for p in avail}
        return min(avail, key=lambda p: (amps[p], p))

    def _new_bus_and_connect(self, start: str, pos: QPointF) -> str | None:
        if isinstance(self.doc.feeder.nodes[start], Transformer):
            self.message.emit("A transformer is the end of a branch; start from a bus.")
            return None
        x, y = style.snap(pos.x()), style.snap(pos.y())
        with self.doc.edit() as f:
            nid = f.new_id("bus")
            f.add_node(Bus(id=nid, name=nid, x=x, y=y))
            _add_segment(f, self.doc, start, nid)
        return nid

    def connect_nodes(self, a: str, b: str) -> str | None:
        """Wire two nodes, working out which end is upstream. Returns the segment id."""
        f, tree = self.doc.feeder, self.doc.context.tree
        na, nb = f.nodes[a], f.nodes[b]
        if f.segment_between(a, b):
            self.message.emit(f"{na.label()} and {nb.label()} are already connected.")
            return None
        for n in (na, nb):
            if isinstance(n, Transformer) and f.segments_at(n.id):
                self.message.emit(f"{n.label()} is already fed; a transformer is the end "
                                  "of a branch.")
                return None
        if tree.reaches(a) and tree.reaches(b):
            self.message.emit("Both ends are already fed from the source; that would make a "
                              "loop. Feeders must be radial.")
            return None
        up, down = a, b
        if (tree.reaches(b) and not tree.reaches(a)) or isinstance(na, Transformer) \
                or isinstance(nb, Source):
            up, down = b, a
        with self.doc.edit() as feeder:
            seg_id = _add_segment(feeder, self.doc, up, down)
        return seg_id

    def toggle_fuse(self, seg_id: str) -> None:
        seg = self.doc.feeder.segments[seg_id]
        if seg.fuse is not None:
            with self.doc.edit():
                seg.fuse = None
            self.message.emit(f"Removed fuse from {seg.label()}.")
            return
        if seg.fuse_blocked:
            self.message.emit(f"{seg.label()} is marked 'no fuse here'; clear that in its "
                              "properties first.")
            return
        with self.doc.edit() as f:
            fuse = f.add_fuse(seg_id)
        self.select_element(fuse.id)

    def delete_selected(self) -> None:
        f = self.doc.feeder
        fuse_segs = [i.seg_id for i in self.selectedItems() if isinstance(i, FuseItem)]
        segs = [i.seg_id for i in self.selectedItems() if isinstance(i, SegmentItem)]
        nodes = [i.node_id for i in self.selectedItems() if isinstance(i, NodeItem)]
        if any(isinstance(f.nodes[n], Source) for n in nodes):
            self.message.emit("The source can't be deleted.")
            nodes = [n for n in nodes if not isinstance(f.nodes[n], Source)]
        if not (fuse_segs or segs or nodes):
            return
        with self.doc.edit() as feeder:
            for sid in fuse_segs:
                if sid in feeder.segments:
                    feeder.segments[sid].fuse = None
            for sid in segs:
                if sid in feeder.segments:
                    feeder.remove_segment(sid)
            for nid in nodes:
                if nid in feeder.nodes:
                    feeder.remove_node(nid)

    def contextMenuEvent(self, event) -> None:
        pos = event.scenePos()
        menu = QMenu()
        seg_id = self.segment_at(pos)
        node_id = self.node_at(pos)
        if node_id:
            node = self.doc.feeder.nodes[node_id]
            self.select_element(node_id)
            if not isinstance(node, Transformer):
                menu.addAction("Draw line from here", lambda: self._begin_line_from(node_id))
            if not isinstance(node, Source):
                menu.addAction(f"Delete {node.label()}", self.delete_selected)
        elif seg_id:
            seg = self.doc.feeder.segments[seg_id]
            self.select_element(seg_id)
            menu.addAction("Remove fuse" if seg.fuse else "Add fuse",
                           lambda: self.toggle_fuse(seg_id))
            block = menu.addAction("Never auto-place a fuse here")
            block.setCheckable(True)
            block.setChecked(seg.fuse_blocked)
            block.toggled.connect(lambda on: self._set_blocked(seg_id, on))
            menu.addSeparator()
            menu.addAction(f"Delete {seg.label()}", self.delete_selected)
        if menu.actions():
            menu.exec(event.screenPos())

    def _begin_line_from(self, node_id: str) -> None:
        for view in self.views():
            window = view.window()
            if hasattr(window, "activate_tool"):
                window.activate_tool(Tool.LINE)
        self._start_line(node_id)

    def _set_blocked(self, seg_id: str, on: bool) -> None:
        with self.doc.edit() as f:
            f.segments[seg_id].fuse_blocked = on

    # ---------------------------------------------------------- background

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:
        painter.fillRect(rect, style.CANVAS_BG)
        scale = painter.worldTransform().m11()
        for step, color in ((style.GRID, style.GRID_MINOR), (style.GRID * 5, style.GRID_MAJOR)):
            if step * scale < 6:
                continue
            painter.setPen(QPen(color, 0))
            left = math.floor(rect.left() / step) * step
            top = math.floor(rect.top() / step) * step
            x = left
            while x < rect.right():
                painter.drawLine(QLineF(x, rect.top(), x, rect.bottom()))
                x += step
            y = top
            while y < rect.bottom():
                painter.drawLine(QLineF(rect.left(), y, rect.right(), y))
                y += step


def _add_segment(f: Feeder, doc: Document, up: str, down: str) -> str:
    """Create a segment from ``up`` to ``down`` with sensible defaults:
    it carries every phase available upstream (or the transformer's phases),
    and reuses the upstream conductor."""
    tree = doc.context.tree
    avail = supply_phases(f, tree, up) if tree.reaches(up) else "ABC"
    feed = tree.parent_segment.get(up)
    conductor = f.segments[feed].conductor if feed in f.segments else DEFAULT_CONDUCTOR
    node = f.nodes[down]
    if isinstance(node, Transformer):
        if not phases_subset(node.phases, avail):
            node.phases = avail if len(avail) == 1 else avail[0]
        phases, length = node.phases, 0.0
    else:
        phases, length = avail, DEFAULT_LINE_FT
    seg_id = f.new_id("segment")
    f.add_segment(Segment(id=seg_id, name=seg_id, node_a=up, node_b=down,
                          length_ft=length, conductor=conductor, phases=phases))
    return seg_id
