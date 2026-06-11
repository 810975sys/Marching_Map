"""
绘图区操作
"""
from PyQt6.QtWidgets import QGraphicsView
from PyQt6.QtCore import Qt
from field_info import SCALE_MIN, SCALE_MAX

class FieldMove(QGraphicsView):
    """场景视图交互层：负责滚轮缩放/平移与鼠标拖拽逻辑。"""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setMouseTracking(True)
        self.viewport().setMouseTracking(True)
        # `_dragging` 与 `_last_pos` 用于中键/右键平移手势状态。
        self._dragging = False
        self._last_pos = None

    def wheelEvent(self, event):
        """滚轮缩放"""
        # """滚轮交互：默认上下平移，Shift 左右平移，Ctrl 缩放。"""
        scene = self.scene()
        # if not hasattr(scene, 'field_info'):
        #     return super().wheelEvent(event)
        s = scene.field_info
        # modifiers = event.modifiers()
        delta = event.angleDelta().y() / 120  # 滚轮一格为120
        # if modifiers & Qt.KeyboardModifier.ControlModifier:
            # Ctrl+滚轮缩放
        # 滚轮缩放
        scale = s.scale * (1.1 ** delta)
        scale = max(SCALE_MIN, min(SCALE_MAX, scale))  # 限制缩放范围
        s.set_scale(scale)
        # elif modifiers & Qt.KeyboardModifier.ShiftModifier:
        #     # Shift+滚轮左右平移
        #     offset = s.offset
        #     s.set_offset(offset.x() + delta * 10, offset.y())
        # else:
        #     # 普通滚轮上下平移
        #     offset = s.offset
        #     s.set_offset(offset.x(), offset.y() + delta * 10)

    def mousePressEvent(self, event):
        """按键按下：绘图左键交给场景，中键/右键进入平移。"""
        # if event.button() == Qt.MouseButton.LeftButton:
        #     self._cancel_pan_state()

        # if event.button() == Qt.MouseButton.LeftButton and self._is_drawing_mode():
        #     self._cancel_pan_state()
        #     super().mousePressEvent(event)
        #     return

        if event.button() in {Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton}:
            self._dragging = True
            self._last_pos = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        else:
            super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """鼠标移动：若处于平移状态则更新场景 offset。"""
        # if self._dragging and self._is_drawing_mode() and event.buttons() & Qt.MouseButton.LeftButton:
        #     self._cancel_pan_state()
        #     super().mouseMoveEvent(event)
        #     return

        scene = self.scene()
        if scene is not None and hasattr(scene, "_update_textbox_hover_preview"):
            scene._update_textbox_hover_preview(self.mapToScene(event.position().toPoint()))

        pan_buttons = event.buttons() & (Qt.MouseButton.MiddleButton | Qt.MouseButton.RightButton)
        if self._dragging and self._last_pos is not None and pan_buttons:
            # if not hasattr(scene, 'field_info'):
            #     return
            s = scene.field_info
            pos = event.position()
            dx = pos.x() - self._last_pos.x()
            dy = pos.y() - self._last_pos.y()
            offset = s.offset
            s.set_offset(offset.x() + dx, offset.y() + dy)
            self._last_pos = pos
        else:
            if self._dragging and not pan_buttons:
                self._dragging = False
                self._last_pos = None
                self.setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放：退出平移状态并恢复光标。"""
        # if event.button() == Qt.MouseButton.LeftButton and self._is_drawing_mode():
        #     self._cancel_pan_state()
        #     super().mouseReleaseEvent(event)
        #     return

        if event.button() in {Qt.MouseButton.MiddleButton, Qt.MouseButton.RightButton}:
            self._dragging = False
            self._last_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
        else:
            super().mouseReleaseEvent(event)
