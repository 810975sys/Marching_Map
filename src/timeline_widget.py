"""时间轴组件。

主要职责：
1. 维护节点与节点间拍数间隔。
2. 提供节点增删、选中与拍位定位交互。
3. 通过信号与主窗口/场景同步当前节点与时间进度。
"""

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QKeySequence, QShortcut
from PyQt6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QPushButton, QSpinBox, QVBoxLayout, QWidget, QScrollArea

class TimelineScrollArea(QScrollArea):
    """时间轴滚轮操作"""
    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()
        if delta != 0:
            step = 40
            bar = self.horizontalScrollBar()
            direction = -1 if delta > 0 else 1
            bar.setValue(bar.value() + direction * step)
            event.accept()
            return
        super().wheelEvent(event)

class NodeEditDialog(QDialog):
    """节点编辑弹窗：用于修改节点间间隔或删除当前节点。"""
    def __init__(self, node_index: int, interval: int, parent=None):
        super().__init__(parent)
        self.setWindowTitle("节点设置")
        self.delete_requested = False

        self._interval_spin = QSpinBox(self)    # 输入间隔拍数，范围1-99，默认值为当前间隔。
        self._interval_spin.setRange(1, 99)
        self._interval_spin.setValue(interval)  # 初始值为当前间隔拍数，便于调整。

        form_layout = QFormLayout()
        form_layout.addRow(f"图{node_index - 1} -> 图{node_index} 间隔拍数", self._interval_spin)

        self._button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self._delete_button = QPushButton("删除节点", self)
        self._delete_button.clicked.connect(self._on_delete_clicked)
        self._delete_button.setStyleSheet("background-color: red; color: white;")
        self._button_box.addButton(self._delete_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(self._button_box)

    def get_interval_value(self) -> int:
        """返回弹窗中设置的间隔拍数。"""
        return int(self._interval_spin.value())

    def _on_delete_clicked(self):
        self.delete_requested = True
        self.accept()


class TimelineWidget(QWidget):
    """时间轴控件：用于添加队形节点并编辑节点间拍数间隔。"""
    timelineChanged = pyqtSignal()
    nodeSelected = pyqtSignal(int)  # 选中节点的索引
    currentBeatChanged = pyqtSignal(int)    # 当前显示的拍位
    nodeAdded = pyqtSignal(int)     # 新增节点的索引
    nodeDeleted = pyqtSignal(int)   # 删除节点的索引
    nodeInserted = pyqtSignal(int)  # 插入的新节点索引

    def __init__(self, parent=None):
        super().__init__(parent)
        # 节点0始终存在。
        # graph_list[i] 表示“节点 i-1 到节点 i”的间隔拍数，因此下标0占位不用。
        self.graph_list = [0]

        # 缓存绘制几何区域，避免重复创建对象。
        self._node_rects = []
        self._plus_rect = QRect()
        self._ruler_rect = QRect()

        # 布局与尺寸参数。
        self._node_radius = 12      # 节点圆点半径
        self._left_padding = 22     # 左侧预留空间
        self._right_padding = 26    # 右侧预留空间
        self._top_row_y = 4         # 节点行Y坐标
        self._middle_top = 24       # 标尺上边Y坐标
        self._middle_bottom = 38    # 标尺下边Y坐标（同时也是当前拍位游标的下边Y坐标）
        self._bottom_row_y = 39     # 节点下方标签Y坐标（当前关闭，保留代码便于后续启用）
        self._pixels_per_beat = 32  # 每拍像素间距，控制时间轴的缩放程度；总拍数增长时控件变宽，由外层滚动区域处理溢出。
        # self._min_ruler_width = 220
        
        # 缩放范围：控制每拍显示宽度，避免过小或过大。
        self._min_pixels_per_beat = 8   # 最小每拍像素间距，过小会导致节点重叠，影响交互。
        self._max_pixels_per_beat = 80  # 最大每拍像素间距，过大会导致时间轴过长，影响整体布局。

        # 长刻度间隔（每隔多少拍绘制一根长刻度线）。
        self.long_tick_interval = 8
        # 当前选中的节点索引。
        self.selected_node = 0
        # 当前播放/指示拍位。
        self.current_beat = 0

        self.setMinimumHeight(58)
        # 使控件可接收键盘事件，便于实现快捷键
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._recalculate_width()
        # 注册 '+' 和 '=' 快捷键为新增节点（对话/子控件也能响应）
        self.quick_add_node = QShortcut(QKeySequence('+'), self)
        # 全局快捷键：在应用范围内均可触发
        self.quick_add_node.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.quick_add_node.activated.connect(lambda: self.add_node(8))

        self.quick_add_node2 = QShortcut(QKeySequence('='), self)
        self.quick_add_node2.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.quick_add_node2.activated.connect(lambda: self.add_node(8))

    def set_graph_list(self, graph_list: list[int], selected_node: int = 0, current_beat: int | None = None, emit_signals: bool = True):
        """整体恢复时间轴间隔列表。"""
        values = [int(interval) for interval in graph_list] if graph_list else [0]
        if not values or values[0] != 0:
            values = [0] + [max(1, int(interval)) for interval in values]
        else:
            values = [0] + [max(1, int(interval)) for interval in values[1:]]

        self.graph_list = values
        self.selected_node = max(0, min(int(selected_node), len(self.graph_list) - 1))
        if current_beat is None:
            self.current_beat = self.start_beat_of(self.selected_node)
        else:
            total = sum(self.graph_list[1:])
            self.current_beat = max(0, min(int(current_beat), total))

        self._recalculate_width()
        if emit_signals:
            self.timelineChanged.emit()
            self.nodeSelected.emit(self.selected_node)
            self.currentBeatChanged.emit(self.current_beat)
        self.update()

    def get_graph_list(self) -> list[int]:
        """返回当前时间轴间隔列表的副本。"""
        return list(self.graph_list)

    def add_node(self, interval: int = 8):
        """在末尾新增一个节点，默认间隔为8拍。"""
        self.graph_list.append(max(1, int(interval)))
        added_index = len(self.graph_list) - 1
        self._recalculate_width()
        self.timelineChanged.emit()
        self.nodeAdded.emit(added_index)
        self.update()

    def delete_node(self, node_index: int):
        """删除指定节点，节点0不允许删除。"""
        if node_index <= 0 or node_index >= len(self.graph_list):
            return

        # 删除中间节点时，需要把“前->删节点”和“删节点->后”两段拍数合并，
        # 这样后续节点的绝对起始拍不会变化。
        #
        # 例：0->1=8, 1->2=8，删除1后应变为 0->2=16，
        # 若只删除 graph_list[1] 会变成 0->2=8，导致后续节点拍位提前，
        # 从而影响后续图显示与后续插图插值计算。
        if node_index < len(self.graph_list) - 1:
            self.graph_list[node_index + 1] += self.graph_list[node_index]

        del self.graph_list[node_index]

        # 删除后，选中节点和当前拍位需要重新对齐，避免索引越界或指针悬空。
        self.selected_node = max(0, min(self.selected_node, len(self.graph_list) - 1))
        self.current_beat = min(self.current_beat, sum(self.graph_list[1:]))    # 当前拍位不能超过总拍数

        self._recalculate_width()
        self.timelineChanged.emit()
        self.nodeDeleted.emit(node_index)
        self.currentBeatChanged.emit(self.current_beat)
        self.update()

    def _recalculate_width(self):
        """保持每拍像素间距恒定；总拍数增长时控件变宽，由外层滚动区域处理溢出。"""
        plus_size = 24  # 加号按钮尺寸
        plus_gap = 18   # 加号按钮与最后一个节点之间的间隔，避免挤在一起影响点击。
        desired_width = self._left_padding + sum(self.graph_list[1:]) * self._pixels_per_beat + plus_gap + plus_size + self._right_padding
        self.setFixedWidth(desired_width)   # 设置宽度

    def start_beat_of(self, node_index: int) -> int:
        """计算当前图节点的起始拍位。"""
        if node_index <= 0:
            return 0
        return sum(self.graph_list[1 : node_index + 1])

    def node_start_beats(self) -> list[int]:
        """返回所有节点的起始拍数组，例如 [0, 8, 24, ...]。"""
        starts = [0]
        acc = 0
        for interval in self.graph_list[1:]:
            acc += int(interval)
            starts.append(acc)
        return starts

    def node_index_at_beat(self, beat: int) -> int | None:
        """若 beat 正好是某节点起始拍，返回节点索引；否则返回 None。"""
        target = int(beat)
        for idx, start in enumerate(self.node_start_beats()):
            if start == target:
                return idx
        return None

    def _segment_for_beat(self, beat: int) -> tuple[int, int] | None:
        """返回 beat 所在区间的左右节点索引 (left, right)。"""
        starts = self.node_start_beats()
        target = int(beat)
        for left in range(0, len(starts) - 1):
            if starts[left] < target < starts[left + 1]:
                return left, left + 1
        return None

    def insert_node_at_beat(self, beat: int) -> bool:
        """在非节点拍位插入新节点，并拆分左右间隔。

        例如：0->1 为 16 拍，若在第 8 拍插入，变为 0->new(8拍), new->1(8拍)。
        """
        total = sum(self.graph_list[1:])
        target = int(beat)
        if target <= 0 or target >= total:
            return False
        if self.node_index_at_beat(target) is not None:
            return False

        segment = self._segment_for_beat(target)
        if segment is None:
            return False

        left_idx, right_idx = segment
        left_start = self.start_beat_of(left_idx)
        old_interval = int(self.graph_list[right_idx])
        left_interval = target - left_start
        right_interval = old_interval - left_interval
        if left_interval <= 0 or right_interval <= 0:
            return False

        # 原间隔替换为左段，并在其后插入右段。
        self.graph_list[right_idx] = left_interval
        self.graph_list.insert(right_idx + 1, right_interval)

        inserted_index = right_idx
        self.selected_node = inserted_index
        self.current_beat = target
        self._recalculate_width()
        self.timelineChanged.emit()
        self.nodeInserted.emit(inserted_index)
        self.nodeSelected.emit(inserted_index)
        self.currentBeatChanged.emit(self.current_beat)
        self.update()
        return True

    def _beat_to_x(self, beat: int) -> int:
        """把拍位转换为对应的X坐标，用于绘制节点和游标。"""
        left = self._ruler_rect.left()
        right = self._ruler_rect.right()
        span = max(1, right - left)
        total = sum(self.graph_list[1:])
        if total <= 0:
            return left
        clamped = max(0, min(total, beat))
        return left + int(span * clamped / total)

    def _x_to_beat(self, x: int) -> int:
        """把X坐标转换为对应的拍位，用于点击定位和拖动节点。"""
        left = self._ruler_rect.left()
        right = self._ruler_rect.right()
        span = max(1, right - left)
        total = sum(self.graph_list[1:])
        if total <= 0:
            return 0
        clamped_x = max(left, min(right, x))
        return int(round((clamped_x - left) * total / span))

    def _compute_geometry(self):
        """根据当前拍数与尺寸参数，计算节点、加号按钮与标尺的绘制区域。"""
        self._node_rects = []
        diameter = self._node_radius * 2
        y = self._top_row_y
        plus_size = 24
        plus_gap = 18

        ruler_left = self._left_padding
        ruler_right = ruler_left + sum(self.graph_list[1:]) * self._pixels_per_beat
        self._ruler_rect = QRect(ruler_left, self._middle_top, ruler_right - ruler_left, self._middle_bottom - self._middle_top)

        for i in range(len(self.graph_list)):
            cx = self._beat_to_x(self.start_beat_of(i))
            rect = QRect(cx - self._node_radius, y, diameter, diameter)
            self._node_rects.append(rect)

        if self._node_rects:
            last = self._node_rects[-1]
            plus_x = last.right() + 18
            max_plus_x = max(self._left_padding, self.width() - self._right_padding - plus_size)
            plus_x = min(plus_x, max_plus_x)
            plus_y = y + (diameter - plus_size) // 2
            self._plus_rect = QRect(plus_x, plus_y, plus_size, plus_size)
        else:
            self._plus_rect = QRect(self._left_padding, y, 24, 24)

    def paintEvent(self, event):
        """绘制时间轴背景、刻度、节点、当前拍位游标与新增按钮。"""
        super().paintEvent(event)
        self._compute_geometry()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景
        p.fillRect(self.rect(), QColor("#f7f7f7"))

        # 顶部基线（当前默认不绘制，保留备用）
        # p.setPen(QPen(QColor("#d0d0d0"), 1))
        # p.drawLine(0, self._top_row_y + self._node_radius * 2 + 4, self.width(), self._top_row_y + self._node_radius * 2 + 4)

        # 中层标尺：仅在有第一张图（节点数大于1）后才显示
        total = sum(self.graph_list[1:])
        if len(self.graph_list) > 1:
            p.setPen(QPen(QColor("#aeaeae"), 1))
            p.drawLine(self._ruler_rect.left(), self._middle_bottom, self._ruler_rect.right(), self._middle_bottom)

            long_every = max(1, int(self.long_tick_interval))
            max_beat_for_ticks = total if total > 0 else 0
            for beat in range(0, max_beat_for_ticks + 1):
                x = self._beat_to_x(beat)
                if beat % long_every == 0:
                    p.setPen(QPen(QColor("#5f6368"), 1))
                    p.drawLine(x, self._middle_top, x, self._middle_bottom)
                    p.drawText(QRect(x - 16, self._bottom_row_y, 32, 14), Qt.AlignmentFlag.AlignCenter, str(beat))
                else:
                    p.setPen(QPen(QColor("#b0b5ba"), 1))
                    p.drawLine(x, self._middle_top + 7, x, self._middle_bottom)

        # 当前拍位游标
        cursor_x = self._beat_to_x(self.current_beat)
        p.setPen(QPen(QColor("#e74c3c"), 2))
        p.drawLine(cursor_x, self._top_row_y - 1, cursor_x, self._middle_bottom + 1)

        font = QFont(self.font())
        font.setPointSize(9)
        p.setFont(font)

        # 绘制节点
        for i, rect in enumerate(self._node_rects):
            # 节点圆点（选中节点高亮边框）
            is_selected = i == self.selected_node
            fill = QColor("#ececec") if i == 0 else QColor("#ffffff")
            border = QColor("#f39c12") if is_selected else QColor("#1f5e9c")
            border_w = 2 if is_selected else 1
            p.setPen(QPen(border, border_w))
            p.setBrush(fill)
            p.drawRect(rect)
            # p.drawEllipse(rect)

            p.setPen(QPen(QColor("#000000"), 1))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(i))

            # 节点下方起始拍标签（当前关闭，保留代码便于后续启用）
            # start_beat = self.start_beat_of(i)
            # p.setPen(QPen(QColor("#2c3e50"), 1))
            # p.drawText(
            #     QRect(rect.left() - 28, rect.bottom() + 4, rect.width() + 56, 16),
            #     Qt.AlignmentFlag.AlignCenter,
            #     # f"{start_beat}拍",
            # )

        # 末尾节点右侧“新增节点”按钮（圆形悬浮样式）
        shadow_rect = self._plus_rect.adjusted(1, 2, 1, 2)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(0, 0, 0, 38))
        p.drawEllipse(shadow_rect)

        p.setPen(QPen(QColor("#000000"), 1))
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(self._plus_rect)

        # 使用文本居中绘制 '+'，避免几何线条出现视觉偏移。
        plus_font = QFont(self.font())
        plus_font.setPointSize(15)
        plus_font.setBold(True)
        p.setFont(plus_font)
        p.setPen(QPen(QColor("#000000"), 1))
        p.drawText(self._plus_rect, Qt.AlignmentFlag.AlignCenter, "+")

    def mousePressEvent(self, event):
        """处理左键点击：选中节点、新增节点，或在标尺处定位当前拍位。"""
        if event.button() == Qt.MouseButton.LeftButton:
            # 点击节点：选中节点，并把当前拍位定位到该节点起始拍。
            for i, rect in enumerate(self._node_rects):
                if rect.contains(event.pos()):
                    self.selected_node = i
                    self.current_beat = self.start_beat_of(i)
                    self.nodeSelected.emit(i)
                    self.currentBeatChanged.emit(self.current_beat)
                    self.update()
                    event.accept()
                    return

            if self._plus_rect.contains(event.pos()):
                self.add_node(8)
                event.accept()
                return

            # 点击标尺区域：把当前拍位定位到最近的整拍。
            if self._ruler_rect.adjusted(-2, self._top_row_y - self._ruler_rect.top(), 2, 2).contains(event.pos()):
                beat = self._x_to_beat(event.pos().x())
                node_index = self.node_index_at_beat(beat)
                if node_index is not None:
                    self.selected_node = node_index
                    self.current_beat = self.start_beat_of(node_index)
                    self.nodeSelected.emit(node_index)
                else:
                    self.current_beat = beat
                self.currentBeatChanged.emit(self.current_beat)
                self.update()
                event.accept()
                return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        """双击中层非节点拍位时，在该拍位插入新方案图。"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self._ruler_rect.adjusted(-2, self._top_row_y - self._ruler_rect.top(), 2, 2).contains(event.pos()):
                beat = self._x_to_beat(event.pos().x())
                if self.insert_node_at_beat(beat):
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """右键节点弹出设置窗口：修改间隔拍数或删除该节点。"""
        pos: QPoint = event.pos()
        for i, rect in enumerate(self._node_rects):
            if rect.contains(pos):
                # 节点0没有前驱节点，因此不允许编辑间隔。
                if i == 0:
                    return

                dialog = NodeEditDialog(i, self.graph_list[i], self)
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    if dialog.delete_requested:
                        self.delete_node(i)
                    else:
                        self.graph_list[i] = dialog.get_interval_value()
                        self._recalculate_width()
                        self.timelineChanged.emit()
                        self.update()
                return

        super().contextMenuEvent(event)

    def wheelEvent(self, event):
        """按住 Ctrl 时用滚轮缩放时间轴，每次调整每拍像素宽度。"""
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            delta = event.angleDelta().y()
            if delta == 0:
                event.ignore()
                return

            step = 4 if delta > 0 else -4
            self._pixels_per_beat = max(
                self._min_pixels_per_beat,
                min(self._max_pixels_per_beat, self._pixels_per_beat + step),
            )
            self._recalculate_width()
            self.update()
            event.accept()
            return

        super().wheelEvent(event)
