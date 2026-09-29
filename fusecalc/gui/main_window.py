"""Main window: menus, toolbar, docks, and file handling."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QImage, QKeySequence, QPainter
from PySide6.QtWidgets import (
    QDockWidget,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QScrollArea,
)

from fusecalc.engine import ProtectionEngine, default_engine
from fusecalc.gui import icons
from fusecalc.gui.document import Document
from fusecalc.gui.placement_dialog import PlacementDialog
from fusecalc.gui.properties import PropertiesPanel
from fusecalc.gui.results_panel import ResultsPanel
from fusecalc.gui.scene import OneLineScene, Tool
from fusecalc.gui.settings_panel import StudyPanel
from fusecalc.gui.view import OneLineView
from fusecalc.topology import feeder_load

EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "examples"
FILE_FILTER = "Feeder files (*.json);;All files (*)"

GUIDE = """
<h3>Drawing a feeder</h3>
<ol>
<li>A new feeder starts with the <b>source</b> (substation). Set its voltage and available
fault current in the <b>Study</b> panel.</li>
<li>Pick the <b>Line</b> tool (L), click the source, then click empty space to drop buses
along the mainline. Click an existing node to connect to it. Esc stops.</li>
<li>Select a bus and use the <b>Transformer</b> tool (T): each click places a transformer
wired to that bus on the least-loaded available phase.</li>
<li>Select any element to edit phases, lengths, conductor, kVA, or fuse settings in the
<b>Properties</b> panel.</li>
</ol>
<h3>Phase notation</h3>
<p>Everything is drawn as a one-line. Each line's color, weight, tick marks and label show
the phases it carries (ABC, AB, B, ...). A tap can only carry phases its supply has; the
Checks tab flags violations.</p>
<h3>Protection</h3>
<p><b>Auto-place fuses</b> proposes transformer, lateral, sub-lateral and sectionalizing
fuses following the rules in the Study panel. Use the <b>Fuse</b> tool (F) to add or remove
fuses by hand; hand-placed or edited fuses are never removed by auto-placement.</p>
<p><b>Run study</b> (F5) sends the feeder to the protection engine for fault currents, link
selection and coordination checks.</p>
"""


class MainWindow(QMainWindow):
    def __init__(self, engine: ProtectionEngine | None = None) -> None:
        super().__init__()
        self.doc = Document(engine or default_engine(), self)
        self.scene = OneLineScene(self.doc, self)
        self.view = OneLineView(self.scene, self)
        self.setCentralWidget(self.view)

        self.properties = PropertiesPanel(self.doc, self.scene)
        self.study = StudyPanel(self.doc)
        self.results = ResultsPanel(self.doc)
        self.results.element_activated.connect(self.focus_element)
        self._dock("Study", self.study, Qt.DockWidgetArea.LeftDockWidgetArea, scroll=True)
        self._dock("Properties", self.properties, Qt.DockWidgetArea.RightDockWidgetArea,
                   scroll=True)
        self._dock("Results", self.results, Qt.DockWidgetArea.BottomDockWidgetArea)

        self.status_summary = QLabel()
        self.statusBar().addPermanentWidget(self.status_summary)
        self.scene.message.connect(lambda msg: self.statusBar().showMessage(msg, 10000))

        self._build_actions()
        self._build_menus()
        self._build_toolbar()

        for signal in (self.doc.changed, self.doc.reset, self.doc.results_changed):
            signal.connect(self._update_state)
        self.doc.title_changed.connect(self._update_title)
        self._update_state()
        self._update_title()
        self.resize(1480, 920)
        self.activate_tool(Tool.SELECT)

    def _dock(self, title: str, widget, area, scroll: bool = False) -> QDockWidget:
        dock = QDockWidget(title, self)
        dock.setObjectName(title)
        if scroll:
            holder = QScrollArea()
            holder.setWidgetResizable(True)
            holder.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            holder.setWidget(widget)
            widget = holder
            dock.setMinimumWidth(310)
        dock.setWidget(widget)
        self.addDockWidget(area, dock)
        return dock

    # ------------------------------------------------------------- actions

    def _action(self, text, slot=None, shortcut=None, icon=None, checkable=False,
                tip: str | None = None) -> QAction:
        act = QAction(text, self)
        if icon is not None:
            act.setIcon(icon)
        if shortcut is not None:
            if isinstance(shortcut, (list, tuple)):
                act.setShortcuts([QKeySequence(s) for s in shortcut])
            else:
                act.setShortcut(QKeySequence(shortcut))
        act.setCheckable(checkable)
        if tip:
            act.setStatusTip(tip)
            act.setToolTip(tip)
        if slot is not None:
            act.triggered.connect(slot)
        return act

    def _build_actions(self) -> None:
        Std = QKeySequence.StandardKey
        self.act_new = self._action("&New", self.file_new, Std.New)
        self.act_open = self._action("&Open...", self.file_open, Std.Open)
        self.act_save = self._action("&Save", self.file_save, Std.Save)
        self.act_save_as = self._action("Save &As...", self.file_save_as, Std.SaveAs)
        self.act_export = self._action("&Export Image...", self.export_image, "Ctrl+E")
        self.act_quit = self._action("&Quit", self.close, Std.Quit)

        self.act_undo = self._action("&Undo", self.doc.undo, Std.Undo)
        self.act_redo = self._action("&Redo", self.doc.redo, Std.Redo)
        self.act_delete = self._action("&Delete", self.scene.delete_selected,
                                       [QKeySequence.StandardKey.Delete, "Backspace"])
        # Only fire when the canvas has focus so text fields keep their keys.
        self.act_delete.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.view.addAction(self.act_delete)
        self.act_select_all = self._action("Select &All", self._select_all, Std.SelectAll)
        self.act_select_all.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)
        self.view.addAction(self.act_select_all)

        self.tool_group = QActionGroup(self)
        self.tool_actions: dict[Tool, QAction] = {}
        for tool, text, key, icon in (
                (Tool.SELECT, "Select", ["V", "Esc"], icons.select_icon()),
                (Tool.BUS, "Bus", "B", icons.bus_icon()),
                (Tool.TRANSFORMER, "Transformer", "T", icons.transformer_icon()),
                (Tool.LINE, "Line", "L", icons.line_icon()),
                (Tool.FUSE, "Fuse", "F", icons.fuse_icon())):
            act = self._action(text, lambda _c=False, t=tool: self.activate_tool(t), key, icon,
                               checkable=True, tip=f"{text} tool ({key[0] if isinstance(key, list) else key})")
            self.tool_group.addAction(act)
            self.tool_actions[tool] = act

        self.act_zoom_in = self._action("Zoom &In", lambda: self.view.zoom(1.25), Std.ZoomIn)
        self.act_zoom_out = self._action("Zoom &Out", lambda: self.view.zoom(0.8), Std.ZoomOut)
        self.act_fit = self._action("&Fit to Window", self.view.fit, "Ctrl+0")
        self.act_labels = self._action("Show Line &Labels", self.scene.set_show_segment_labels,
                                       checkable=True)
        self.act_labels.setChecked(True)

        self.act_place = self._action("&Auto-place Fuses...", self.auto_place, "Ctrl+Shift+A",
                                      icons.auto_place_icon(),
                                      tip="Propose fuse locations from the placement rules")
        self.act_clear_auto = self._action("&Clear Auto-placed Fuses", self.clear_auto_fuses)
        self.act_run = self._action("&Run Study", self.doc.run_study, "F5", icons.run_icon(),
                                    tip="Run fault study, link selection and coordination")
        self.act_auto_run = self._action("Run Study &Automatically", self.doc.set_auto_run,
                                         checkable=True)
        self.act_auto_run.setChecked(self.doc.auto_run)
        self.act_guide = self._action("&Quick Guide", self.show_guide, Std.HelpContents)
        self.act_about = self._action("&About", self.show_about)

    def _build_menus(self) -> None:
        bar = self.menuBar()
        m = bar.addMenu("&File")
        m.addActions([self.act_new, self.act_open])
        examples = sorted(EXAMPLES_DIR.glob("*.json")) if EXAMPLES_DIR.is_dir() else []
        if examples:
            sub = m.addMenu("Open &Example")
            for path in examples:
                sub.addAction(path.stem.replace("_", " ").title(),
                              lambda p=path: self.open_path(p, as_template=True))
        m.addSeparator()
        m.addActions([self.act_save, self.act_save_as, self.act_export])
        m.addSeparator()
        m.addAction(self.act_quit)

        m = bar.addMenu("&Edit")
        m.addActions([self.act_undo, self.act_redo])
        m.addSeparator()
        m.addActions([self.act_delete, self.act_select_all])

        m = bar.addMenu("&Draw")
        m.addActions(list(self.tool_actions.values()))

        m = bar.addMenu("&View")
        m.addActions([self.act_zoom_in, self.act_zoom_out, self.act_fit])
        m.addSeparator()
        m.addAction(self.act_labels)
        m.addSeparator()
        for dock in self.findChildren(QDockWidget):
            m.addAction(dock.toggleViewAction())

        m = bar.addMenu("&Protection")
        m.addActions([self.act_place, self.act_clear_auto])
        m.addSeparator()
        m.addActions([self.act_run, self.act_auto_run])

        m = bar.addMenu("&Help")
        m.addActions([self.act_guide, self.act_about])

    def _build_toolbar(self) -> None:
        tb = self.addToolBar("Tools")
        tb.setObjectName("Tools")
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
        tb.addActions(list(self.tool_actions.values()))
        tb.addSeparator()
        tb.addAction(self.act_place)
        tb.addAction(self.act_run)

    # -------------------------------------------------------------- state

    def activate_tool(self, tool: Tool) -> None:
        self.tool_actions[tool].setChecked(True)
        self.scene.set_tool(tool)
        self.view.set_tool(tool)

    def _select_all(self) -> None:
        for item in self.scene.items():
            if hasattr(item, "element_id"):
                item.setSelected(True)

    def _update_title(self) -> None:
        self.setWindowTitle(f"{self.doc.display_name()}[*] - Fuse Coordination Tool")
        self.setWindowModified(self.doc.dirty)

    def _update_state(self) -> None:
        self.act_undo.setEnabled(self.doc.can_undo())
        self.act_redo.setEnabled(self.doc.can_redo())
        ctx = self.doc.context
        errors = sum(1 for i in ctx.issues if i.severity == "error")
        warns = len(ctx.issues) - errors
        total = feeder_load(ctx.tree, ctx.loads)
        parts = [f"{total.transformer_count} transformers",
                 f"{total.total_kva:,.0f} kVA",
                 "  ".join(f"{p} {total.amps[p]:.0f} A" for p in "ABC")]
        if errors or warns:
            parts.append(f"<span style='color:#c62828'>{errors} errors, {warns} warnings</span>")
        else:
            parts.append("<span style='color:#2e7d32'>topology OK</span>")
        self.status_summary.setText("   |   ".join(parts))

    def focus_element(self, element_id: str) -> None:
        item = self.scene.select_element(element_id)
        if item is not None:
            self.view.centerOn(item.sceneBoundingRect().center())

    # --------------------------------------------------------------- files

    def maybe_save(self) -> bool:
        if not self.doc.dirty:
            return True
        answer = QMessageBox.question(
            self, "Unsaved changes", f"Save changes to {self.doc.display_name()}?",
            QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
            | QMessageBox.StandardButton.Cancel)
        if answer == QMessageBox.StandardButton.Save:
            return self.file_save()
        return answer == QMessageBox.StandardButton.Discard

    def file_new(self) -> None:
        if self.maybe_save():
            self.doc.new()
            self.view.fit()

    def file_open(self) -> None:
        if not self.maybe_save():
            return
        path, _ = QFileDialog.getOpenFileName(self, "Open feeder", str(Path.cwd()), FILE_FILTER)
        if path:
            self.open_path(Path(path), check_saved=False)

    def open_path(self, path: Path, as_template: bool = False, check_saved: bool = True) -> None:
        if check_saved and not self.maybe_save():
            return
        try:
            self.doc.open(path, as_template=as_template)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            QMessageBox.critical(self, "Could not open file", f"{path}\n\n{exc}")
            return
        self.view.fit()

    def file_save(self) -> bool:
        if self.doc.path is None:
            return self.file_save_as()
        try:
            self.doc.save()
        except OSError as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return False
        self.statusBar().showMessage(f"Saved {self.doc.path}", 5000)
        return True

    def file_save_as(self) -> bool:
        start = str(self.doc.path or Path.cwd() / f"{self.doc.feeder.name}.json")
        path, _ = QFileDialog.getSaveFileName(self, "Save feeder", start, FILE_FILTER)
        if not path:
            return False
        if not path.endswith(".json"):
            path += ".json"
        try:
            self.doc.save(path)
        except OSError as exc:
            QMessageBox.critical(self, "Could not save", str(exc))
            return False
        return True

    def export_image(self) -> None:
        path, _ = QFileDialog.getSaveFileName(self, "Export one-line", "one-line.png",
                                              "PNG image (*.png)")
        if path:
            self.render_png(path)

    def render_png(self, path: str, scale: float = 2.0) -> None:
        selected = self.scene.selectedItems()
        self.scene.clearSelection()
        rect = self.scene.itemsBoundingRect().adjusted(-40, -40, 40, 40)
        image = QImage(int(rect.width() * scale), int(rect.height() * scale),
                       QImage.Format.Format_ARGB32)
        image.fill(QColor("white"))
        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.scene.render(painter, QRectF(image.rect()), rect)
        painter.end()
        image.save(path)
        for item in selected:
            item.setSelected(True)

    def closeEvent(self, event) -> None:
        if self.maybe_save():
            event.accept()
        else:
            event.ignore()

    # ---------------------------------------------------------- protection

    def auto_place(self) -> None:
        PlacementDialog(self.doc, self.scene, self).exec()

    def clear_auto_fuses(self) -> None:
        if not any(f.origin == "auto" for _, f in self.doc.feeder.fuses()):
            self.statusBar().showMessage("No auto-placed fuses to clear.", 5000)
            return
        with self.doc.edit() as feeder:
            for seg, fuse in list(feeder.fuses()):
                if fuse.origin == "auto":
                    seg.fuse = None

    # ---------------------------------------------------------------- help

    def show_guide(self) -> None:
        QMessageBox.information(self, "Quick guide", GUIDE)

    def show_about(self) -> None:
        QMessageBox.about(self, "About", "<b>Fuse Sizing, Placement, and Coordination Tool</b>"
                          "<br>ECE 6320 term project<br>Gabriel Chamon &amp; Micheal Elrod-Mocek")
