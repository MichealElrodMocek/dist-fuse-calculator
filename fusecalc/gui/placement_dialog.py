"""Preview auto-placement proposals and choose which to apply."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
)

from fusecalc.gui import style
from fusecalc.gui.document import Document
from fusecalc.gui.scene import OneLineScene
from fusecalc.placement import RULE_LABELS, PlacementResult, apply_plan, plan_fuses


class PlacementDialog(QDialog):
    """Lists proposed fuses; ticked ones are applied, replacing old auto fuses.

    Proposed locations are highlighted on the one-line while the dialog is open.
    """

    def __init__(self, doc: Document, scene: OneLineScene, parent=None) -> None:
        super().__init__(parent)
        self.doc = doc
        self.scene = scene
        self.result: PlacementResult = plan_fuses(doc.feeder)
        self.setWindowTitle("Auto-place fuses")
        self.resize(760, 480)

        layout = QVBoxLayout(self)
        f = doc.feeder
        accepted = self.result.accepted
        mainline = ", ".join(sorted(f.segments[s].label() for s in self.result.mainline)) or "none"
        summary = (f"<b>{len(accepted)}</b> fuse locations proposed"
                   f" ({len(self.result.proposals) - len(accepted)} skipped). "
                   f"Mainline left to the substation device: {mainline}.")
        if self.result.removed_auto:
            summary += (f"<br>{len(self.result.removed_auto)} previously auto-placed fuse(s) "
                        "will be replaced. Fuses you placed or edited are kept.")
        if self.result.issues:
            summary += ("<br><span style='color:#c62828'>The feeder has errors; fix them for "
                        "reliable placement (see Checks).</span>")
        info = QLabel(summary)
        info.setWordWrap(True)
        layout.addWidget(info)

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Segment", "Rule", "At", "Reason"])
        self.tree.setRootIsDecorated(False)
        self.tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.tree.header().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        self.tree.header().setStretchLastSection(True)
        tree = doc.context.tree
        for prop in self.result.proposals:
            seg = f.segments[prop.segment_id]
            at = f.nodes[tree.upstream[prop.segment_id]].label()
            text = prop.reason if prop.accepted else f"Skipped: {prop.skip_reason}. {prop.reason}"
            item = QTreeWidgetItem([seg.label(), RULE_LABELS[prop.rule], at, text])
            item.setData(0, Qt.ItemDataRole.UserRole, prop.segment_id)
            if prop.accepted:
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(0, Qt.CheckState.Checked)
            else:
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
                for col in range(4):
                    item.setForeground(col, QBrush(style.STATUS_COLORS["not_checked"]))
            self.tree.addTopLevelItem(item)
        self.tree.itemChanged.connect(lambda *_: self._highlight())
        self.tree.currentItemChanged.connect(self._focus)
        layout.addWidget(self.tree)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_btn = buttons.addButton("Apply", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_btn.setEnabled(bool(accepted) or bool(self.result.removed_auto))
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._highlight()

    def selected_segments(self) -> set[str]:
        out = set()
        for i in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(i)
            if item.checkState(0) == Qt.CheckState.Checked:
                out.add(item.data(0, Qt.ItemDataRole.UserRole))
        return out

    def _highlight(self) -> None:
        self.scene.set_highlight(self.selected_segments())

    def _focus(self, item: QTreeWidgetItem | None, _prev=None) -> None:
        if item is None:
            return
        seg_item = self.scene.item_for(item.data(0, Qt.ItemDataRole.UserRole))
        for view in self.scene.views():
            if seg_item is not None:
                view.ensureVisible(seg_item, 80, 80)

    def done(self, result: int) -> None:
        self.scene.set_highlight(set())
        if result == QDialog.DialogCode.Accepted:
            selected = self.selected_segments()
            with self.doc.edit() as feeder:
                apply_plan(feeder, self.result, selected)
        super().done(result)
