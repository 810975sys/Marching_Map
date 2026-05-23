from PyQt6.QtCore import QPointF, Qt, QRectF
from PyQt6.QtGui import QBrush, QColor, QPen, QPainter, QFont, QTextOption
from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsItem,
    QGraphicsObject,
    QGraphicsProxyWidget,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsSimpleTextItem,
    QFrame,
    QPlainTextEdit,
)

# 全局 monkey-patch：在绘制 QGraphicsLineItem 时临时关闭抗锯齿，避免位置不同导致 1px 线宽观感不一致。
_orig_qgraphicslineitem_paint = QGraphicsLineItem.paint
def _qgraphicslineitem_paint_no_aa(self, painter, option, widget=None):
    painter.save()
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
    _orig_qgraphicslineitem_paint(self, painter, option, widget)
    painter.restore()
QGraphicsLineItem.paint = _qgraphicslineitem_paint_no_aa

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


class TextBoxEditor(QPlainTextEdit):
    """嵌入文本框的编辑器。"""

    def __init__(self, owner):
        super().__init__()
        self._owner = owner
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setLineWrapMode(QPlainTextEdit.LineWrapMode.WidgetWidth)
        self.setStyleSheet(
            "QPlainTextEdit { background: transparent; border: none; color: #000000; padding: 0px; }"
        )

    def focusInEvent(self, event):
        if callable(getattr(self._owner, "_request_selection", None)):
            self._owner._request_selection()
        super().focusInEvent(event)

    def mousePressEvent(self, event):
        if callable(getattr(self._owner, "_request_selection", None)):
            self._owner._request_selection()
        super().mousePressEvent(event)

    def set_mouse_interactive(self, interactive: bool):
        """控制编辑器是否接收鼠标事件，并同步鼠标指针样式。"""
        interactive = bool(interactive)
        transparent = not interactive
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
        viewport = self.viewport()
        if viewport is not None:
            viewport.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, transparent)
        self.setCursor(Qt.CursorShape.IBeamCursor if interactive else Qt.CursorShape.ArrowCursor)


class TextBoxItem(QGraphicsObject):
    """文本框图元：白底黑框，内部嵌入 QPlainTextEdit 用于输入与显示。"""

    def __init__(self, textbox_id: int, rect: QRectF, text: str = "", font_size: int = 14, *, selection_requested_callback=None, text_changed_callback=None):
        super().__init__()
        self.textbox_id = int(textbox_id)
        self._rect = QRectF(rect).normalized()
        self._font_size = max(1, int(font_size))
        self._selected = False
        self._editable = False
        self._mouse_interactive = True
        self._selection_requested_callback = selection_requested_callback
        self._text_changed_callback = text_changed_callback

        self._editor = TextBoxEditor(self)
        self._editor.setPlainText(str(text or ""))
        self._editor.textChanged.connect(self._on_text_changed)
        self._editor_proxy = QGraphicsProxyWidget(self)
        self._editor_proxy.setWidget(self._editor)
        self.setData(0, "textbox")
        self.setData(1, self.textbox_id)
        self._editor_proxy.setData(0, "textbox_proxy")
        self._editor_proxy.setData(1, self.textbox_id)

        self.setAcceptedMouseButtons(Qt.MouseButton.LeftButton)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable, False)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsMovable, False)
        self.setZValue(100)
        self._apply_font()
        self._sync_child_geometry()
        self._apply_editable_state()
        self._apply_mouse_interactive_state()

    def boundingRect(self) -> QRectF:
        return QRectF(self._rect)

    def _request_selection(self):
        if callable(self._selection_requested_callback):
            self._selection_requested_callback(int(self.textbox_id))

    def _on_text_changed(self):
        if callable(self._text_changed_callback):
            self._text_changed_callback(int(self.textbox_id), self.text())

    def _apply_font(self):
        font = QFont(self._editor.font())
        font.setPointSize(self._font_size)
        self._editor.setFont(font)
        self._editor.document().setDefaultFont(font)
        self._editor.setWordWrapMode(QTextOption.WrapMode.WrapAtWordBoundaryOrAnywhere)

    def _apply_editable_state(self):
        self._editor.setReadOnly(not self._editable)
        self._editor.setFocusPolicy(Qt.FocusPolicy.StrongFocus if self._editable else Qt.FocusPolicy.NoFocus)

    def _apply_mouse_interactive_state(self):
        self._editor.set_mouse_interactive(self._mouse_interactive)

    def _sync_child_geometry(self):
        margin = 4.0
        inner = QRectF(self._rect)
        inner.adjust(margin, margin, -margin, -margin)
        if inner.width() < 1.0:
            inner.setWidth(1.0)
        if inner.height() < 1.0:
            inner.setHeight(1.0)
        self._editor_proxy.setGeometry(inner)

    def set_text(self, text: str):
        if self._editor.toPlainText() == str(text or ""):
            return
        self._editor.blockSignals(True)
        self._editor.setPlainText(str(text or ""))
        self._editor.blockSignals(False)

    def text(self) -> str:
        return self._editor.toPlainText()

    def set_font_size(self, font_size: int):
        font_size = max(1, int(font_size))
        if font_size == self._font_size:
            return
        self._font_size = font_size
        self._apply_font()
        self._sync_child_geometry()

    def font_size(self) -> int:
        return int(self._font_size)

    def set_rect(self, rect: QRectF):
        rect = QRectF(rect).normalized()
        if rect == self._rect:
            return
        self.prepareGeometryChange()
        self._rect = rect
        self._sync_child_geometry()
        self.update()

    def rect(self) -> QRectF:
        return QRectF(self._rect)

    def set_selected(self, selected: bool):
        selected = bool(selected)
        if selected == self._selected:
            return
        self._selected = selected
        self.update()

    def set_mouse_interactive(self, interactive: bool):
        interactive = bool(interactive)
        if interactive == self._mouse_interactive:
            return
        self._mouse_interactive = interactive
        self._apply_mouse_interactive_state()

    def set_editable(self, editable: bool):
        editable = bool(editable)
        if editable == self._editable:
            return
        self._editable = editable
        self._apply_editable_state()
        self.update()
        if editable:
            self._editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def focus_editor(self):
        if self._editable:
            self._editor.setFocus(Qt.FocusReason.MouseFocusReason)

    def paint(self, painter: QPainter, option, widget=None):
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        rect = QRectF(self._rect).normalized()

        # 填充使用无边框模式以避免边缘像素混合
        fill_pen = QPen(Qt.PenStyle.NoPen)
        painter.setPen(fill_pen)
        painter.setBrush(QBrush(QColor("#ffffff")))
        painter.drawRect(rect)

        # 描边按像素对齐（0.5 偏移），并设置为 cosmetic 避免缩放影响笔宽
        outline_pen = QPen(QColor("#000000"), 1.0)
        outline_pen.setCosmetic(True)
        painter.setPen(outline_pen)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

        if self._selected:
            sel_pen = QPen(QColor("#f39c12"), 1.4)
            sel_pen.setCosmetic(True)
            painter.setPen(sel_pen)
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect.adjusted(0.5, 0.5, -0.5, -0.5))

        painter.restore()


class PerformerPointItem(QGraphicsEllipseItem):
    """可拖拽的表演者点位图元（仅在框选工具下生效）。"""

    def __init__(self, point_id: int = 0, center_scene_pos: QPointF = QPointF(), moved_callback = None, released_callback = None, can_drag_callback = None, selected: bool = False, size: float = 10.0):
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
        self.setZValue(960) # 确保在点位图层之上
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
