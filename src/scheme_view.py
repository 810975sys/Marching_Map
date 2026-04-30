# scheme_view.py
"""
自定义 QGraphicsView，支持：
1. 滚轮调整 offset y
2. Shift+滚轮调整 offset x
3. Ctrl+滚轮缩放 scale
4. 鼠标中键拖动 offset
"""
from PyQt6.QtWidgets import QGraphicsView
from PyQt6.QtCore import Qt
from field_settings import SCALE_MIN, SCALE_MAX

class SchemeView(QGraphicsView):
    """场景视图交互层：负责滚轮缩放/平移与鼠标拖拽逻辑。"""

    def __init__(self, scene, parent=None):
        super().__init__(scene, parent)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        # `_dragging` 与 `_last_pos` 用于中键/右键平移手势状态。
        self._dragging = False
        self._last_pos = None

    def _is_drawing_mode(self) -> bool:
        """当前是否处于绘图工具模式。"""
        scene = self.scene()
        return bool(scene is not None and getattr(scene, "active_tool", None) in {
            "点",
            "线段",
            "弧",
            "曲线/折线",
            "填充四边形",
            "圆",
            "多边形",
        })

    def _cancel_pan_state(self):
        """清空平移状态并恢复默认光标。"""
        self._dragging = False
        self._last_pos = None
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def wheelEvent(self, event):
        """滚轮交互：Ctrl 缩放，Shift 左右平移，默认上下平移。"""
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
        elif modifiers & Qt.KeyboardModifier.ShiftModifier:
            # Shift+滚轮左右平移
            offset = s.offset
            s.set_offset(offset.x() + delta * 10, offset.y())
        else:
            # 普通滚轮上下平移
            offset = s.offset
            s.set_offset(offset.x(), offset.y() + delta * 10)

    def mousePressEvent(self, event):
        """按键按下：绘图左键交给场景，中键/右键进入平移。"""
        if event.button() == Qt.MouseButton.LeftButton:
            self._cancel_pan_state()

        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing_mode():
            self._cancel_pan_state()
            super().mousePressEvent(event)
            return

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
        """鼠标移动：若处于平移状态则更新场景 offset。"""
        if self._dragging and self._is_drawing_mode() and event.buttons() & Qt.MouseButton.LeftButton:
            self._cancel_pan_state()
            super().mouseMoveEvent(event)
            return

        pan_buttons = event.buttons() & (Qt.MouseButton.MiddleButton | Qt.MouseButton.RightButton)
        if self._dragging and self._last_pos is not None and pan_buttons:
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
        else:
            if self._dragging and not pan_buttons:
                self._cancel_pan_state()
            super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """鼠标释放：退出平移状态并恢复光标。"""
        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing_mode():
            self._cancel_pan_state()
            super().mouseReleaseEvent(event)
            return

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
