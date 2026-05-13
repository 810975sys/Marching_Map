from PyQt6.QtCore import QPointF, Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QPen, QPainter
from PyQt6.QtWidgets import QGraphicsEllipseItem, QGraphicsRectItem

class ReferenceHandleItem(QGraphicsRectItem):
    """草稿参考点拖拽手柄，用于调整绘制控制点。"""

    def __init__(self, index: int, center_scene_pos: QPointF, moved_callback, drag_started_callback=None, drag_finished_callback=None):
        self._size = 10.0
        half = self._size / 2.0   # 以中心点为基准创建矩形
        super().__init__(-half, -half, self._size, self._size)
        self._index = index # 点位编号
        self._moved_callback = moved_callback   # 移动回调，返回调整后的场景坐标以实现吸附等功能。
        self._drag_started_callback = drag_started_callback
        self._drag_finished_callback = drag_finished_callback
        self.setPen(QPen(QColor("#d35400"), 1.2))    # 橙色边框
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))   # 透明填充
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton) # 仅响应左键拖动
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsSelectable, False)    # 不可选中
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemIsMovable, True)        # 可移动
        self.setFlag(QGraphicsRectItem.GraphicsItemFlag.ItemSendsGeometryChanges, True) # 移动时发送位置变化事件
        self.setZValue(1000)
        self.setPos(center_scene_pos)

    @property
    def size(self) -> float:
        return self._size

    @size.setter
    def size(self, value: float) -> None:
        self.set_size(value)

    def set_size(self, size: float) -> None:
        size = float(size)
        if size <= 0.0 or size == self._size:
            return
        self._size = size
        half = size / 2.0
        self.setRect(-half, -half, size, size)

    def mousePressEvent(self, event):
        """左键响应"""
        if event.button() == Qt.MouseButton.LeftButton:
            if callable(self._drag_started_callback):
                self._drag_started_callback(self._index, QPointF(self.scenePos()))
            super().mousePressEvent(event)
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            if callable(self._drag_finished_callback):
                self._drag_finished_callback(self._index, QPointF(self.scenePos()))

    def itemChange(self, change, value):
        """位置变化时调用移动回调，获取调整后的坐标以实现吸附等功能。"""
        if change == QGraphicsRectItem.GraphicsItemChange.ItemPositionChange:
            # 仅上报位置，是否吸附由场景层按业务决定。
            if callable(self._moved_callback):
                adjusted = self._moved_callback(self._index, QPointF(value))
                if isinstance(adjusted, QPointF):
                    value = adjusted
        return super().itemChange(change, value)


class MovementControlHandleItem(QGraphicsEllipseItem):
    """双圈参考点手柄：外圈用于改变移动参考点，内圈用于实际移动选中点位。

    - 拖动外圈：触发 `outer_moved_callback(index, QPointF)`，用于改变参考点位置（吸附/重定位由回调处理）。
    - 拖动内圈：触发 `inner_moved_callback(index, QPointF)`，用于移动选中点位（回调负责按参考点计算新位置并返回调整后的坐标）。
    """

    def __init__(self, index: int, center_scene_pos: QPointF, outer_moved_callback=None, inner_moved_callback=None, drag_started_callback=None, drag_finished_callback=None):
        self._size = 32.0
        self._inner_ratio = 0.45
        half = self._size / 2.0
        super().__init__(-half, -half, self._size, self._size)
        self._index = index
        self._outer_moved_callback = outer_moved_callback
        self._inner_moved_callback = inner_moved_callback
        self._drag_started_callback = drag_started_callback
        self._drag_finished_callback = drag_finished_callback
        self._inner_radius = (self._size / 2.0) * self._inner_ratio
        self._pressed_part = None  # 'inner' or 'outer' during drag
        self.setPen(QPen(QColor("#16a085"), 1.4))
        self.setBrush(QBrush(Qt.BrushStyle.NoBrush))
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setZValue(1000)
        self.setPos(center_scene_pos)

    @property
    def size(self) -> float:
        return self._size

    @size.setter
    def size(self, value: float) -> None:
        self.set_size(value)

    @property
    def inner_ratio(self) -> float:
        return self._inner_ratio

    @inner_ratio.setter
    def inner_ratio(self, value: float) -> None:
        self.set_inner_ratio(value)

    def set_size(self, size: float) -> None:
        size = float(size)
        if size <= 0.0 or size == self._size:
            return
        self._size = size
        half = size / 2.0
        self.setRect(-half, -half, size, size)
        self._inner_radius = (self._size / 2.0) * self._inner_ratio
        self.update()

    def set_inner_ratio(self, inner_ratio: float) -> None:
        inner_ratio = float(inner_ratio)
        if inner_ratio < 0.0:
            inner_ratio = 0.0
        elif inner_ratio > 1.0:
            inner_ratio = 1.0
        if inner_ratio == self._inner_ratio:
            return
        self._inner_ratio = inner_ratio
        self._inner_radius = (self._size / 2.0) * self._inner_ratio
        self.update()
        
    def paint(self, painter: QPainter, option, widget=None):
        # 绘制外圈与内圈
        painter.setPen(self.pen())
        painter.setBrush(self.brush())
        painter.drawEllipse(self.rect())
        inner_rect = QRectF(-self._inner_radius, -self._inner_radius, self._inner_radius * 2.0, self._inner_radius * 2.0)
        painter.drawEllipse(inner_rect)

    def _which_part_at(self, pos: QPointF) -> str:
        dx = pos.x()
        dy = pos.y()
        dist = (dx * dx + dy * dy) ** 0.5
        if dist <= self._inner_radius:
            return 'inner'
        return 'outer'

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            local = event.pos()
            self._pressed_part = self._which_part_at(local)
            if callable(self._drag_started_callback):
                self._drag_started_callback(self._index, QPointF(self.scenePos()), self._pressed_part)
            event.accept()
            super().mousePressEvent(event)
            return
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and callable(self._drag_finished_callback):
            self._drag_finished_callback(self._index, QPointF(self.scenePos()), self._pressed_part)
        self._pressed_part = None

    def itemChange(self, change, value):
        if change == QGraphicsEllipseItem.GraphicsItemChange.ItemPositionChange and self._pressed_part is not None:
            target = QPointF(value)
            if self._pressed_part == 'outer' and callable(self._outer_moved_callback):
                adjusted = self._outer_moved_callback(self._index, target)
                if isinstance(adjusted, QPointF):
                    target = adjusted
            elif self._pressed_part == 'inner' and callable(self._inner_moved_callback):
                adjusted = self._inner_moved_callback(self._index, target)
                if isinstance(adjusted, QPointF):
                    target = adjusted
            value = target
        return super().itemChange(change, value)

    def hoverEnterEvent(self, event):
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        self.unsetCursor()
        super().hoverLeaveEvent(event)


class PerformerPointItem(QGraphicsEllipseItem):
    """可拖拽的表演者点位图元（仅在框选工具下生效）。"""
    def __init__(self, point_id: int, center_scene_pos: QPointF, moved_callback, released_callback, can_drag_callback, selected: bool, size: float = 10.0):
        self.radius = size / 2.0
        super().__init__(-self.radius, -self.radius, size, size)
        self.point_id = int(point_id)   # 点位ID，用于定位
        self._moved_callback = moved_callback   # 移动回调，返回调整后的场景坐标以实现吸附等功能。
        self._released_callback = released_callback # 释放回调，参数为点位ID，用于通知数据层更新点位坐标。
        self._can_drag_callback = can_drag_callback # 是否可拖动回调，返回布尔值，控制是否允许拖动（如锁定状态下不可拖动）
        self._moved_during_drag = False # 记录拖动过程中是否发生过移动，用于在释放时判断是否需要触发更新
        # 初始化位置时会触发 ItemPositionChange；此阶段不应触发吸附与数据写回。
        self._suspend_position_change = True
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemIsMovable, True)
        self.setFlag(QGraphicsEllipseItem.GraphicsItemFlag.ItemSendsGeometryChanges, True)
        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setAcceptHoverEvents(True)
        self.setZValue(200) # 确保在点位图层之上
        self.setPos(center_scene_pos)   # 设置初始位置
        self._suspend_position_change = False
        self.set_selected_visual(selected)
        
        self.dot_color = QColor("#2aa6ff")

    def set_selected_visual(self, selected: bool):
        """设置选中时的视觉效果"""
        if selected:
            self.setPen(QPen(QColor("#f39c12"), 1.8))
            self.setBrush(QBrush(QColor("#2aa6ff")))
        else:
            self.setPen(QPen(Qt.PenStyle.NoPen))
            self.setBrush(QBrush(QColor("#2aa6ff")))

    def _can_drag(self) -> bool:
        return bool(callable(self._can_drag_callback) and self._can_drag_callback())

    def mousePressEvent(self, event):
        """按键响应"""
        if event.button() == Qt.MouseButton.LeftButton and not self._can_drag():
            event.ignore()
            return
        if event.button() == Qt.MouseButton.LeftButton:
            self._moved_during_drag = False
        super().mousePressEvent(event)

    def mouseReleaseEvent(self, event):
        """按键释放响应"""
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton and self._moved_during_drag:
            if callable(self._released_callback):
                self._released_callback(self.point_id)

    def itemChange(self, change, value):
        """位置变化时调用移动回调，获取调整后的坐标以实现吸附等功能；拖动过程中记录是否发生过移动。"""
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
        """鼠标悬停时，如果可拖动则显示大小调整光标"""
        if self._can_drag():
            self.setCursor(Qt.CursorShape.SizeAllCursor)
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event):
        """鼠标离开时恢复默认光标"""
        self.unsetCursor()
        super().hoverLeaveEvent(event)
