from PyQt6.QtCore import QPointF, Qt
from PyQt6.QtGui import QBrush, QColor, QPen
from PyQt6.QtWidgets import QGraphicsEllipseItem, QGraphicsRectItem


class ReferenceHandleItem(QGraphicsRectItem):
    """草稿参考点拖拽手柄，用于调整绘制控制点。"""

    def __init__(self, index: int, center_scene_pos: QPointF, moved_callback, size: float = 10.0):
        half = size / 2.0
        super().__init__(-half, -half, size, size)
        self._index = index
        self._moved_callback = moved_callback
        self.setPen(QPen(QColor("#d35400"), 1.2))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1000)
        self.setPos(center_scene_pos)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            super().mousePressEvent(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def itemChange(self, change, value):
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionChange:
            # 仅上报位置，是否吸附由场景层按业务决定。
            if callable(self._moved_callback):
                adjusted = self._moved_callback(self._index, QPointF(value))
                if isinstance(adjusted, QPointF):
                    value = adjusted
        return super().itemChange(change, value)


class PerformerPointItem(QGraphicsEllipseItem):
    """可拖拽的表演者点位图元（仅在框选工具下生效）。"""

    def __init__(self, point_id: int, center_scene_pos: QPointF, moved_callback, released_callback, can_drag_callback, selected: bool, size: float = 10.0):
        radius = size / 2.0
        super().__init__(-radius, -radius, size, size)
        self.point_id = int(point_id)
        self._moved_callback = moved_callback
        self._released_callback = released_callback
        self._can_drag_callback = can_drag_callback
        self._moved_during_drag = False
        # 初始化位置时会触发 ItemPositionChange；此阶段不应触发吸附与数据写回。
        self._suspend_position_change = True
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setZValue(200)
        self.setPos(center_scene_pos)
        self._suspend_position_change = False
        self.set_selected_visual(selected)

    def set_selected_visual(self, selected: bool):
        if selected:
            self.setPen(QPen(QColor("#f39c12"), 1.8))
            self.setBrush(QBrush(QColor("#2aa6ff")))
        else:
            self.setPen(QPen(QColor("#1f5e9c"), 1))
            self.setBrush(QBrush(QColor("#2aa6ff")))

    def _can_drag(self) -> bool:
        return bool(callable(self._can_drag_callback) and self._can_drag_callback())

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and not self._can_drag():
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._moved_during_drag = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self._moved_during_drag:
            if callable(self._released_callback):
                self._released_callback(self.point_id)

    def itemChange(self, change, value):
        if (
            change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionChange
            and not self._suspend_position_change
            and self._can_drag()
        ):
            self._moved_during_drag = True
            target = QPointF(value)
            if callable(self._moved_callback):
                adjusted = self._moved_callback(self.point_id, target)
                if isinstance(adjusted, QPointF):
                    target = adjusted
            value = target
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        if self._can_drag():
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)
