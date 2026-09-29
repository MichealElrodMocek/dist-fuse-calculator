"""Zoomable, pannable view onto the one-line scene."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QRectF, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QGraphicsView

from fusecalc.gui.scene import OneLineScene, Tool

MIN_SCALE, MAX_SCALE = 0.1, 6.0


class OneLineView(QGraphicsView):
    """Ctrl/Cmd + wheel or pinch to zoom; middle-drag or scroll to pan."""

    def __init__(self, scene: OneLineScene, parent=None) -> None:
        super().__init__(scene, parent)
        self.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setSceneRect(QRectF(-4000, -4000, 10000, 8000))
        self.viewport().setMouseTracking(True)
        self._panning = None
        self.set_tool(Tool.SELECT)

    def set_tool(self, tool: Tool) -> None:
        select = tool == Tool.SELECT
        self.setDragMode(QGraphicsView.DragMode.RubberBandDrag if select
                         else QGraphicsView.DragMode.NoDrag)
        self.viewport().setCursor(Qt.CursorShape.ArrowCursor if select
                                  else Qt.CursorShape.CrossCursor)

    # ---- zoom

    def zoom(self, factor: float) -> None:
        scale = self.transform().m11() * factor
        if MIN_SCALE <= scale <= MAX_SCALE:
            self.scale(factor, factor)

    def fit(self) -> None:
        rect = self.scene().itemsBoundingRect()
        if rect.isEmpty():
            return
        self.fitInView(rect.adjusted(-60, -60, 60, 60), Qt.AspectRatioMode.KeepAspectRatio)
        scale = self.transform().m11()
        if scale > 1.5:
            self.zoom(1.5 / scale)

    def wheelEvent(self, event) -> None:
        mods = event.modifiers()
        if mods & (Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.MetaModifier):
            self.zoom(1.0015 ** event.angleDelta().y())
            event.accept()
        else:
            super().wheelEvent(event)

    def viewportEvent(self, event) -> bool:
        if event.type() == QEvent.Type.NativeGesture and \
                event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
            self.zoom(1.0 + event.value())
            return True
        return super().viewportEvent(event)

    # ---- middle-button pan

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton:
            self._panning = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:
        if self._panning is not None:
            delta = event.position() - self._panning
            self._panning = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._panning is not None:
            self._panning = None
            self.set_tool(self.scene().tool)
            event.accept()
            return
        super().mouseReleaseEvent(event)
