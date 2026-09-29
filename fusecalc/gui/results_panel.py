"""Tabbed tables: fuses, coordination pairs, segment loads, and checks."""

from __future__ import annotations

from PySide6.QtCore import QModelIndex, QSortFilterProxyModel, Qt, Signal
from PySide6.QtGui import QBrush, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHeaderView,
    QLabel,
    QTableView,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from fusecalc.gui import style
from fusecalc.gui.document import Document

ID_ROLE = Qt.ItemDataRole.UserRole
SORT_ROLE = Qt.ItemDataRole.UserRole + 1
_TEXT = object()  # sentinel: cell is not numeric


def _cell(text: str, element_id: str | None = None, number=_TEXT, color=None) -> QStandardItem:
    """A read-only cell. Passing ``number`` (even None) makes it sort numerically."""
    item = QStandardItem(text)
    item.setEditable(False)
    if element_id:
        item.setData(element_id, ID_ROLE)
    if number is _TEXT:
        item.setData(text.lower(), SORT_ROLE)
    else:
        item.setData(float("-inf") if number is None else float(number), SORT_ROLE)
        item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
    if color is not None:
        item.setForeground(QBrush(color))
    return item


class Table(QTableView):
    """Sortable read-only table; sorting uses SORT_ROLE so numbers sort as numbers."""

    def __init__(self, headers: list[str]) -> None:
        super().__init__()
        self.source = QStandardItemModel(0, len(headers), self)
        self.source.setHorizontalHeaderLabels(headers)
        self.proxy = QSortFilterProxyModel(self)
        self.proxy.setSourceModel(self.source)
        self.proxy.setSortRole(SORT_ROLE)
        self.setModel(self.proxy)
        self.setSortingEnabled(True)
        self.sortByColumn(-1, Qt.SortOrder.AscendingOrder)  # keep insertion order until clicked
        self.verticalHeader().setVisible(False)
        self.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.setAlternatingRowColors(True)
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setStretchLastSection(True)

    def fill(self, rows: list[list[QStandardItem]]) -> None:
        self.source.removeRows(0, self.source.rowCount())
        for row in rows:
            self.source.appendRow(row)

    def element_at(self, index: QModelIndex) -> str | None:
        src = self.proxy.mapToSource(index)
        item = self.source.item(src.row(), 0)
        return item.data(ID_ROLE) if item is not None else None


def _table(headers: list[str]) -> Table:
    return Table(headers)


def _fill(table: Table, rows: list[list[QStandardItem]]) -> None:
    table.fill(rows)


class ResultsPanel(QWidget):
    element_activated = Signal(str)

    def __init__(self, doc: Document, parent=None) -> None:
        super().__init__(parent)
        self.doc = doc
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        self.banner = QLabel()
        self.banner.setWordWrap(True)
        layout.addWidget(self.banner)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)

        self.fuses = _table(["Fuse", "At", "Phases", "Placed by", "Load A", "Max fault",
                             "Min fault", "Link", "Upstream", "Coord.", "Margin", "Note"])
        self.coord = _table(["Protecting", "Protected", "Fault at protecting", "Table limit",
                             "Margin", "Status", "Note"])
        self.loads = _table(["Segment", "From", "To", "Phases", "Length", "kVA", "Tx",
                             "A amps", "B amps", "C amps", "Imbalance %"])
        self.checks = _table(["Severity", "Element", "Message"])
        for table, title in ((self.fuses, "Fuses"), (self.coord, "Coordination"),
                             (self.loads, "Loads"), (self.checks, "Checks")):
            table.clicked.connect(lambda index, t=table: self._activate(t, index))
            self.tabs.addTab(table, title)

        doc.changed.connect(self.refresh)
        doc.reset.connect(self.refresh)
        doc.results_changed.connect(self.refresh)
        self.refresh()

    def _activate(self, table: Table, index: QModelIndex) -> None:
        element_id = table.element_at(index)
        if element_id:
            self.element_activated.emit(element_id)

    def refresh(self) -> None:
        self._banner()
        self._fill_fuses()
        self._fill_coord()
        self._fill_loads()
        self._fill_checks()

    def _banner(self) -> None:
        doc = self.doc
        if doc.results_error:
            last = doc.results_error.strip().splitlines()[-1]
            self.banner.setText(f"<span style='color:#c62828'><b>Engine error:</b> {last}</span>"
                                " (full traceback in the Checks tab)")
        elif doc.results_stale:
            self.banner.setText("<b>Results are out of date.</b> Press Run Study (F5).")
        elif doc.results is not None:
            res = doc.results
            text = f"Engine: <b>{res.engine}</b>"
            if res.is_placeholder:
                text += ("  <span style='color:#ef6c00'>- placeholder numbers, not for "
                         "engineering use</span>")
            self.banner.setText(text)
        else:
            self.banner.setText("No study results yet.")

    def _fill_fuses(self) -> None:
        f, ctx, res = self.doc.feeder, self.doc.context, self.doc.results
        rows = []
        for seg, fuse in f.fuses():
            at = ctx.tree.upstream.get(seg.id)
            fault = res.faults.get(at) if res and at else None
            link = res.links.get(fuse.id) if res else None
            coord = res.coordination_for(fuse.id) if res else None
            load = ctx.loads.get(seg.id)
            placed = "You" if fuse.origin == "manual" else "Auto"
            status = coord.status if coord else ("-" if res else "")
            margin = coord.margin_a if coord else None
            rows.append([
                _cell(fuse.label(), fuse.id),
                _cell(f.nodes[at].label() if at else "(unfed)"),
                _cell(seg.phases),
                _cell(placed),
                _cell(f"{load.max_amps:.1f}" if load else "-", number=load.max_amps if load else None),
                _cell(style.fmt_amps(fault.imax_a) if fault else "-",
                      number=fault.imax_a if fault else None),
                _cell(style.fmt_amps(fault.imin_a) if fault else "-",
                      number=fault.imin_a if fault else None),
                _cell(link.label() if link else "-",
                      color=None if not link or link.ok else style.STATUS_COLORS["fail"]),
                _cell(coord.protected_fuse if coord else "(substation)"),
                _cell(status.replace("_", " "), color=style.STATUS_COLORS.get(status)),
                _cell(style.fmt_amps(margin) if margin is not None else "-", number=margin),
                _cell(link.note if link else fuse.reason),
            ])
        _fill(self.fuses, rows)
        self.tabs.setTabText(0, f"Fuses ({len(rows)})")

    def _fill_coord(self) -> None:
        res = self.doc.results
        rows = []
        for c in res.coordination if res else []:
            rows.append([
                _cell(c.protecting_fuse, c.protecting_fuse),
                _cell(c.protected_fuse),
                _cell(style.fmt_amps(c.fault_current_a), number=c.fault_current_a),
                _cell(style.fmt_amps(c.limit_a), number=c.limit_a),
                _cell(style.fmt_amps(c.margin_a) if c.margin_a is not None else "-",
                      number=c.margin_a),
                _cell(c.status.replace("_", " "), color=style.STATUS_COLORS.get(c.status)),
                _cell(c.note),
            ])
        _fill(self.coord, rows)
        failed = sum(1 for c in res.coordination if c.status == "fail") if res else 0
        self.tabs.setTabText(1, f"Coordination ({failed} failing)" if failed else "Coordination")

    def _fill_loads(self) -> None:
        f, ctx = self.doc.feeder, self.doc.context
        rows = []
        for seg_id in ctx.tree.segment_order():
            seg, load = f.segments[seg_id], ctx.loads[seg_id]
            up, down = ctx.tree.upstream[seg_id], ctx.tree.downstream[seg_id]
            imb = load.imbalance_pct(seg.phases)
            rows.append([
                _cell(seg.label(), seg_id),
                _cell(f.nodes[up].label()),
                _cell(f.nodes[down].label()),
                _cell(seg.phases),
                _cell(style.fmt_ft(seg.length_ft), number=seg.length_ft),
                _cell(f"{load.total_kva:g}", number=load.total_kva),
                _cell(str(load.transformer_count), number=load.transformer_count),
                *[_cell(f"{load.amps[p]:.1f}" if p in seg.phases else "",
                        number=load.amps[p]) for p in "ABC"],
                _cell(f"{imb:.0f}" if len(seg.phases) > 1 else "", number=imb,
                      color=style.STATUS_COLORS["warning"] if imb > 20 else None),
            ])
        _fill(self.loads, rows)

    def _fill_checks(self) -> None:
        f, doc = self.doc.feeder, self.doc
        rows = []
        for issue in doc.context.issues:
            el = f.element(issue.element_id) if issue.element_id else None
            color = style.STATUS_COLORS["fail" if issue.severity == "error" else "warning"]
            rows.append([
                _cell(issue.severity, issue.element_id, color=color),
                _cell(el.label() if el else ""),
                _cell(issue.message),
            ])
        if doc.results_error:
            rows.append([_cell("engine", color=style.STATUS_COLORS["fail"]), _cell(""),
                         _cell(doc.results_error)])
        for msg in doc.results.messages if doc.results else []:
            rows.append([_cell("info"), _cell(""), _cell(msg)])
        _fill(self.checks, rows)
        errors = sum(1 for i in doc.context.issues if i.severity == "error")
        warns = len(doc.context.issues) - errors
        label = "Checks"
        if errors or warns:
            label += f" ({errors} errors, {warns} warnings)"
        self.tabs.setTabText(3, label)
