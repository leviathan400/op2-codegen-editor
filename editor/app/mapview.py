from __future__ import annotations
from .common import *


class MapView(QGraphicsView):
    tileClicked = Signal(int, int)
    tileRemoved = Signal(int, int)
    tileHover = Signal(int, int)
    rectDragStarted = Signal(int, int)
    rectDragMoved = Signal(int, int)
    rectDragFinished = Signal(int, int)
    rectDragCanceled = Signal()

    def __init__(self, scene):
        super().__init__(scene)
        self.setRenderHint(QPainter.SmoothPixmapTransform, False)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setMouseTracking(True)
        self._panning = False
        self._pan_start = None
        self.rect_select_enabled = False
        self._rect_dragging = False

    def _tile(self, pos):
        sp = self.mapToScene(pos.toPoint())
        return int(sp.x() // SCENE_TILE), int(sp.y() // SCENE_TILE)

    def wheelEvent(self, event):
        f = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(f, f)

    def mousePressEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = True
            self._pan_start = event.position()
            self.setCursor(Qt.ClosedHandCursor)
        elif event.button() == Qt.LeftButton and self.rect_select_enabled:
            self._rect_dragging = True
            self.rectDragStarted.emit(*self._tile(event.position()))
        elif event.button() == Qt.RightButton and self.rect_select_enabled:
            self._rect_dragging = False
            self.rectDragCanceled.emit()
        elif event.button() == Qt.LeftButton:
            self.tileClicked.emit(*self._tile(event.position()))
        elif event.button() == Qt.RightButton:
            self.tileRemoved.emit(*self._tile(event.position()))
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._panning and self._pan_start is not None:
            d = event.position() - self._pan_start
            self._pan_start = event.position()
            self.horizontalScrollBar().setValue(int(self.horizontalScrollBar().value() - d.x()))
            self.verticalScrollBar().setValue(int(self.verticalScrollBar().value() - d.y()))
            return
        if self._rect_dragging:
            self.rectDragMoved.emit(*self._tile(event.position()))
            return
        self.tileHover.emit(*self._tile(event.position()))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._panning = False
            self.setCursor(Qt.ArrowCursor)
        elif event.button() == Qt.LeftButton and self._rect_dragging:
            self._rect_dragging = False
            self.rectDragFinished.emit(*self._tile(event.position()))
        else:
            super().mouseReleaseEvent(event)


