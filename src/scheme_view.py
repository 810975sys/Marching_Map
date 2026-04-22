# scheme_view.py
"""
自定义 QGraphicsView，支持：
1. 滚轮调整 offset y
2. Shift+滚轮调整 offset x
3. Ctrl+滚轮缩放 scale
4. 鼠标中键拖动 offset
"""
from PyQt6.QtWidgets import QGraphicsView
from PyQt6.QtCore import Qt, QPointF
from field_settings import SCALE_MIN, SCALE_MAX

class SchemeView(QGraphicsView):
    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._dragging = False
        self._last_pos = None

    def wheelEvent(self, event):
        scene = self.scene()
        if not hasattr(scene, 'field_settings'):
            return super().wheelEvent(event)
        s = scene.field_settings
        modifiers = event.modifiers()
        delta = event.angleDelta().y() / 120  # 一格为120
        if modifiers & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+滚轮缩放
            scale = s.scale * (1.1 ** delta)
            scale = max(SCALE_MIN, min(SCALE_MAX, scale))  # 限制缩放范围
            s.set_scale(scale)
            scene.update()
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            # Shift+滚轮左右平移
            offset = s.offset
            s.set_offset(offset.x() + delta * 10, offset.y())
            scene.update()
        else:
            # 普通滚轮上下平移
            offset = s.offset
            s.set_offset(offset.x(), offset.y() + delta * 10)
            scene.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._dragging = True
            self._last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.RightButton:
            self._dragging = True
            self._last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._last_pos is not None:
            scene = self.scene()
            if not hasattr(scene, 'field_settings'):
                return
            s = scene.field_settings
            pos = event.position()
            dx = pos.x() - self._last_pos.x()
            dy = pos.y() - self._last_pos.y()
            offset = s.offset
            s.set_offset(offset.x() + dx, offset.y() + dy)
            self._last_pos = pos
            scene.update()
        else:
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.MiddleButton:
            self._dragging = False
            self._last_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        elif event.button() == Qt.MouseButton.RightButton:
            self._dragging = False
            self._last_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            super().mouseReleaseEvent(event)
