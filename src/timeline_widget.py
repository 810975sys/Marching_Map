"""时间轴组件。

主要职责：
1. 维护节点与节点间拍数间隔。
2. 提供节点增删、选中与拍位定位交互。
3. 通过信号与主窗口/场景同步当前节点与时间进度。
4. 速度轴（展开态上栏）：分段速度设置、变速区间可视化。
5. 音频栏（展开态下栏）：音频文件占位。
"""

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal
from PyQt6.QtGui import QColor, QFont, QPainter, QPen, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from src.tempo_data import Tempo

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


class RampCheckBox(QCheckBox):
    """自定义复选框：勾选时绘制高对比度对勾，避免对勾颜色过浅与背景融为一体。"""

    def __init__(self, text: str = "", parent=None):
        super().__init__(text, parent)
        self.setFixedHeight(20)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        ind_size = 16
        offset_x = 1   # 整体向右偏移，避免视觉上贴边
        y = (self.height() - ind_size) // 2
        box = QRect(offset_x, y, ind_size, ind_size)

        if self.isChecked():
            # 勾选状态：深色填充 + 白色对勾，对比明显
            p.setPen(QPen(QColor("#1f5e9c"), 1))
            p.setBrush(QColor("#1f5e9c"))
            p.drawRoundedRect(box, 3, 3)
            pen = QPen(QColor("#ffffff"), 2)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawLine(box.left() + 4, box.top() + 8, box.left() + 7, box.top() + 11)
            p.drawLine(box.left() + 7, box.top() + 11, box.right() - 3, box.top() + 4)
        else:
            # 未勾选：白色底 + 灰色边框
            p.setPen(QPen(QColor("#5f6368"), 1))
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(box, 3, 3)

        # 文字标签
        font = self.font()
        p.setFont(font)
        p.setPen(QPen(QColor("#2c3e50"), 1))
        text_rect = QRect(offset_x + ind_size + 2, 0, self.width() - offset_x - ind_size - 2, self.height())
        p.drawText(
            text_rect,
            Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
            self.text(),
        )
        p.end()


class TempoEditDialog(QDialog):
    """速度节点编辑弹窗：插入或修改 beat_tempo 条目。"""
    def __init__(
        self,
        beat: int,
        current_bpm: int,
        end_bpm: int | None = None,
        duration: int = 0,
        is_new: bool = True,
        parent=None,
        total_beats: int = 0,
        tempo_keys: list[int] | None = None,
    ):
        super().__init__(parent)
        self.setWindowTitle("新增速度节点" if is_new else "编辑速度节点")
        self._is_new = is_new
        self.delete_requested = False

        # 动态上限上下文：总拍数限制 _beat_spin，速度节点拍位列表用于限制变速持续拍数。
        self._total_beats = max(0, int(total_beats))
        self._tempo_keys = sorted(int(k) for k in (tempo_keys or []))

        self._beat_spin = QSpinBox(self)
        self._beat_spin.setRange(0, self._total_beats)
        self._beat_spin.setValue(int(beat))
        self._beat_spin.setEnabled(beat > 0)

        self._bpm_spin = QSpinBox(self)
        self._bpm_spin.setRange(1, 999)
        self._bpm_spin.setValue(int(current_bpm))

        self._ramp_check = RampCheckBox("变速", self)
        has_ramp = end_bpm is not None and duration > 0
        self._ramp_check.setChecked(has_ramp)

        self._end_bpm_spin = QSpinBox(self)
        self._end_bpm_spin.setRange(1, 999)
        self._end_bpm_spin.setValue(int(end_bpm) if end_bpm is not None else int(current_bpm))
        self._end_bpm_spin.setEnabled(has_ramp)

        self._duration_spin = QSpinBox(self)
        self._duration_spin.setRange(1, 999)
        self._duration_spin.setValue(int(duration) if duration > 0 else 8)
        self._duration_spin.setEnabled(has_ramp)

        self._ramp_check.toggled.connect(self._on_ramp_toggled)
        self._bpm_spin.valueChanged.connect(self._update_ok_state)
        self._end_bpm_spin.valueChanged.connect(self._update_ok_state)
        self._beat_spin.valueChanged.connect(self._update_duration_range)
        self._update_duration_range()

        form_layout = QFormLayout()
        form_layout.addRow("节拍位置", self._beat_spin)
        form_layout.addRow("速度 (BPM)", self._bpm_spin)
        form_layout.addRow(self._ramp_check)

        ramp_layout = QHBoxLayout()
        ramp_layout.addWidget(QLabel("目标 BPM"))
        ramp_layout.addWidget(self._end_bpm_spin)
        ramp_layout.addWidget(QLabel("持续拍数"))
        ramp_layout.addWidget(self._duration_spin)
        form_layout.addRow(ramp_layout)

        self._button_box = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self
        )
        if not is_new:
            self._delete_button = QPushButton("删除速度节点", self)
            self._delete_button.clicked.connect(self._on_delete_clicked)
            self._delete_button.setStyleSheet("background-color: red; color: white;")
            # beat=0 是必须存在的默认速度节点，不允许删除
            self._delete_button.setEnabled(beat > 0)
            self._button_box.addButton(self._delete_button, QDialogButtonBox.ButtonRole.DestructiveRole)
        self._button_box.accepted.connect(self.accept)
        self._button_box.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form_layout)
        layout.addWidget(self._button_box)
        self._update_ok_state()

    def _update_ok_state(self):
        """变速勾选且起始与目标 BPM 相同时，禁用 OK 按钮（变速无意义）。"""
        ok_button = self._button_box.button(QDialogButtonBox.StandardButton.Ok)
        invalid_ramp = (
            self._ramp_check.isChecked()
            and self._bpm_spin.value() == self._end_bpm_spin.value()
        )
        ok_button.setEnabled(not invalid_ramp)

    def _on_ramp_toggled(self, checked: bool):
        self._end_bpm_spin.setEnabled(checked)
        self._duration_spin.setEnabled(checked)
        self._update_ok_state()

    def _update_duration_range(self):
        """动态限制持续拍数上限：beat + duration 不得超过下一个速度节点拍位。

        无下一个速度节点时以总拍数为上限，避免变速区间越过后续速度节点。
        """
        beat = self._beat_spin.value()
        next_key = self._total_beats
        for k in self._tempo_keys:
            if k > beat:
                next_key = k
                break
        self._duration_spin.setMaximum(max(1, next_key - beat))

    def get_tempo(self) -> Tempo:
        if self._ramp_check.isChecked():
            return Tempo(
                start_bpm=int(self._bpm_spin.value()),
                end_bpm=int(self._end_bpm_spin.value()),
                duration_beats=int(self._duration_spin.value()),
            )
        return Tempo(start_bpm=int(self._bpm_spin.value()))

    def _on_delete_clicked(self):
        self.delete_requested = True
        self.accept()


class TimelineWidget(QWidget):
    """时间轴控件：用于添加队形节点并编辑节点间拍数间隔。

    展开后分为三栏：速度轴（上）、方案图时间轴（中）、音频栏（下）。
    """
    timelineChanged = pyqtSignal()
    nodeSelected = pyqtSignal(int)  # 选中节点的索引
    currentBeatChanged = pyqtSignal(int)    # 当前显示的拍位
    nodeAdded = pyqtSignal(int)     # 新增节点的索引
    nodeDeleted = pyqtSignal(int)   # 删除节点的索引
    nodeInserted = pyqtSignal(int)  # 插入的新节点索引
    tempoChanged = pyqtSignal()     # 速度节点数据发生变化
    expandedChanged = pyqtSignal(bool)  # 展开/折叠状态变化

    def __init__(self, parent=None):
        super().__init__(parent)
        # 节点0始终存在。
        # graph_list[i] 表示“节点 i-1 到节点 i”的间隔拍数，因此下标0占位不用。
        self.graph_list = [0]

        # beat_tempo: beat=0 必有默认 Tempo(120)
        self.beat_tempo: dict[int, Tempo] = {0: Tempo(start_bpm=120)}
        self.tempo_label_width = 25  # bpm 标签宽度

        # 缓存绘制几何区域
        self._node_rects: list[QRect] = []
        self._plus_rect = QRect()
        self._ruler_rect = QRect()
        self._tempo_rect = QRect()
        self._audio_rect = QRect()

        # 布局与尺寸参数。
        self._node_radius = 12      # 节点矩形半径
        self._left_padding = 22     # 左侧预留空间
        self._right_padding = 26    # 右侧预留空间
        self._top_row_y = 4         # 节点行Y坐标
        self._middle_top = 24       # 标尺上边Y坐标
        self._middle_bottom = 38    # 标尺下边Y坐标（同时也是当前拍位游标的下边Y坐标）
        self._bottom_row_y = 39     # 节点下方标签Y坐标（当前关闭，保留代码便于后续启用）
        self._pixels_per_beat = 32  # 每拍像素间距，控制时间轴的缩放程度；总拍数增长时控件变宽，由外层滚动区域处理溢出。
        
        # 缩放范围：控制每拍显示宽度，避免过小或过大。
        self._min_pixels_per_beat = 8   # 最小每拍像素间距，过小会导致节点重叠，影响交互。
        self._max_pixels_per_beat = 80  # 最大每拍像素间距，过大会导致时间轴过长，影响整体布局。

        # 长刻度间隔（每隔多少拍绘制一根长刻度线）。
        self.long_tick_interval = 8
        # 当前选中的节点索引。
        self.selected_node = 0
        # 当前播放/指示拍位。
        self.current_beat = 0

        # 展开态
        self._expanded = False      # 是否展开速度轴与音频栏
        self._tempo_bar_height = 38 # 速度轴高度
        self._audio_bar_height = 32 # 音频栏高度
        self._beat_label_height = 14    # 标尺下方拍数标签的高度
        self._middle_y_offset = 0   # 速度轴与音频栏的Y偏移量，折叠态为0，展开态为速度轴高度
        self._collapsed_min_height = 58 # 折叠态最小高度（仅时间轴）
        # 展开态最小高度：速度轴 + 折叠态中间栏（含拍数标签） + 4px间隔 + 音频栏
        self._expanded_min_height = (
            self._tempo_bar_height
            + self._collapsed_min_height
            + 4
            + self._audio_bar_height
        )

        self.setMinimumHeight(self._collapsed_min_height)
        # 使控件可接收键盘事件，便于实现快捷键
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        # 字体大小（由 AppSettingsDock 统一管理）
        self._node_font_size = 9
        self._beat_font_size = 9

        self._recalculate_width()
        # 注册 '+' 和 '=' 快捷键为新增节点（对话/子控件也能响应）
        self.quick_add_node = QShortcut(QKeySequence('+'), self)
        # 全局快捷键：在应用范围内均可触发
        self.quick_add_node.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.quick_add_node.activated.connect(lambda: self.add_node(8))

        self.quick_add_node2 = QShortcut(QKeySequence('='), self)
        self.quick_add_node2.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.quick_add_node2.activated.connect(lambda: self.add_node(8))

        # 全局左右方向键切换节点
        self._shortcut_left = QShortcut(QKeySequence(Qt.Key.Key_Left), self)
        self._shortcut_left.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut_left.activated.connect(self._switch_prev)

        self._shortcut_right = QShortcut(QKeySequence(Qt.Key.Key_Right), self)
        self._shortcut_right.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._shortcut_right.activated.connect(self._switch_next)

    # ──────── 展开/折叠 ────────
    def set_expanded(self, expanded: bool):
        if self._expanded == expanded:
            return
        self._expanded = expanded
        self._middle_y_offset = self._tempo_bar_height if expanded else 0
        self.setMinimumHeight(self._expanded_min_height if self._expanded else self._collapsed_min_height)
        self.expandedChanged.emit(expanded)
        self.update()

    # ──────── 序列化 ────────
    def to_dict(self) -> dict:
        """导出时间轴数据，用于保存到方案文件。"""
        return {
            "graph_list": list(self.graph_list),
            "beat_tempo": {
                str(k): v.to_dict() for k, v in sorted(self.beat_tempo.items())
            },
        }
    
    def load_from_dict(self, data: dict):
        self.set_graph_list(data.get("graph_list", [0]))

        raw_tempo = data.get("beat_tempo", {0: 120})
        if not raw_tempo:
            self.beat_tempo = {0: Tempo(start_bpm=120)}
        elif isinstance(raw_tempo, dict):
            new_tempo: dict[int, Tempo] = {}
            for k, v in raw_tempo.items():
                beat = int(k)
                if isinstance(v, Tempo):
                    new_tempo[beat] = v
                else:
                    new_tempo[beat] = Tempo.from_dict(v) if isinstance(v, dict) else Tempo(start_bpm=int(v))
            if 0 not in new_tempo:
                new_tempo[0] = Tempo(start_bpm=120)
            self.beat_tempo = new_tempo
        else:
            self.beat_tempo = {0: Tempo(start_bpm=120)}

        self.selected_node = 0
        self.current_beat = 0
        self._recalculate_width()
        self.update()

    def total_beats(self) -> int:
        return sum(self.graph_list[1:])

    def set_graph_list(self, graph_list: list[int]):
        """整体恢复时间轴间隔列表。"""
        values = [int(interval) for interval in graph_list] if graph_list else [0]
        if not values or values[0] != 0:
            values = [0] + [max(1, int(interval)) for interval in values]
        else:
            values = [0] + [max(1, int(interval)) for interval in values[1:]]

        self.graph_list = values
        self.selected_node = 0
        self.current_beat = 0
        self._recalculate_width()
        self.update()

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
        self.current_beat = min(self.current_beat, self.total_beats())    # 当前拍位不能超过总拍数

        self._recalculate_width()
        self.timelineChanged.emit()
        self.nodeDeleted.emit(node_index)
        self.currentBeatChanged.emit(self.current_beat)
        self.update()

    def _recalculate_width(self):
        """保持每拍像素间距恒定；总拍数增长时控件变宽，由外层滚动区域处理溢出。"""
        plus_size = 24  # 加号按钮尺寸
        plus_gap = 18   # 加号按钮与最后节点间距，避免影响点击
        desired_width = self._left_padding + self.total_beats() * self._pixels_per_beat + plus_gap + plus_size + self._right_padding
        self.setFixedWidth(desired_width)   # 设置宽度

    # ──────── 速度轴辅助 ────────
    def _bpm_at_beat(self, beat: float) -> float:
        """返回覆盖该拍位、当前仍生效速度节点的 BPM。

        统一使用 _nearest_tempo_key 的语义：变速区间结束后该节点失效，
        回退到变速前仍生效的速度节点（与播放进度计算 _beat_from_elapsed 一致）。
        """
        key = self._nearest_tempo_key(int(beat))
        tempo = self.beat_tempo.get(key, Tempo(start_bpm=120))
        return tempo.bpm_at_offset(int(beat) - key)

    def _nearest_tempo_key(self, beat: int) -> int:
        """返回覆盖 beat 拍位的速度节点 key。

        从最大 key 向前（向小）搜索：找到第一个 ≤ beat 且有效的节点即返回。
        变速区间为半开区间 [key, key + duration_beats)：当 beat >= key + duration_beats
        时变速区间已结束（含结束拍），该节点失效，跳过并继续向前（向小）搜索，
        回退到变速前仍生效的速度节点。
        """
        for k in sorted(self.beat_tempo.keys(), reverse=True):
            if k > beat:
                continue
            tempo = self.beat_tempo[k]
            if tempo.has_ramp and beat >= k + tempo.duration_beats:
                continue  # 变速区间已结束，继续向更小的 key 搜索
            return k
        return 0

    def set_tempo_at_beat(self, beat: int, tempo: Tempo, is_new: bool = False, old_beat:int | None = None):
        """写回速度节点。

        is_new=True 表示新建（插入）新速度节点：若目标拍位已有节点则拒绝写回，
        避免覆盖已有节点；is_new=False 表示修改已有节点：直接覆盖写回。

        写回前：若目标拍位处最近生效的速度节点（_nearest_tempo_key）是变速区间，
        且其变速区间终点越过目标拍位（key + duration > target），则截断该变速区间
        的 duration，使其终点恰好等于目标拍位（key + duration == target），
        保证新节点与变速区间相接、不存在覆盖区域。
        """
        target = int(beat)

        # 截断与目标拍位重叠的变速区间，使区间终点恰好落在 target。
        # nearest_key < target 守卫：目标拍位自身的节点（key == target）不截断，
        # 避免截断正在写回或已存在于该拍位的节点。
        nearest_key = self._nearest_tempo_key(target)
        if nearest_key < target:
            nearest_tempo = self.beat_tempo.get(nearest_key)
            if nearest_tempo.has_ramp:
                ramp_end = nearest_key + nearest_tempo.duration_beats
                if ramp_end > target:
                    nearest_tempo.duration_beats = target - nearest_key

        if is_new:
            # 新建节点/修改已有节点
            self.beat_tempo[target] = tempo
        else:
            # 修改已有节点
            if target == 0:
                self.beat_tempo[0] = tempo
            else:
                if old_beat is not None:
                    del self.beat_tempo[old_beat]
                self.beat_tempo[target] = tempo
        self.tempoChanged.emit()
        self.timelineChanged.emit()
        self.update()

    def delete_tempo_at_beat(self, beat: int):
        if beat <= 0 or beat not in self.beat_tempo:
            return
        del self.beat_tempo[beat]
        self.tempoChanged.emit()
        self.timelineChanged.emit()
        self.update()

    def _beat_from_elapsed(self, start_beat: float, elapsed_minutes: float) -> float:
        """根据经过时间计算当前拍位。

        支持变速区间：BPM 随拍位线性变化（均匀变速）。
        变速区间内采用「每拍取该拍起始速度」的离散近似（本拍内速度恒定），
        避免逐帧积分；恒定速度段用公式整段推进。
        变速区间结束后该节点失效，改用 _nearest_tempo_key 向前取真正生效的速度节点，
        而不是继续沿用已结束变速节点的 end_bpm。
        """
        total = float(self.total_beats())
        if total <= 0:
            return 0.0
        beat = float(start_beat)
        remaining_seconds = float(elapsed_minutes) * 60.0
        if remaining_seconds <= 0:
            return min(beat, total)
        keys = sorted(self.beat_tempo.keys())

        while remaining_seconds > 0 and beat < total:
            # 变速区间结束后该节点失效，向前取真正生效的速度节点
            key = self._nearest_tempo_key(int(beat))
            tempo = self.beat_tempo[key]
            # 变速区间结束拍（超出后该节点失效，由 _nearest_tempo_key 回退）
            ramp_end = float(key + tempo.duration_beats) if tempo.has_ramp else beat
            # 当前段结束拍：下一个大于 beat 的速度节点或总拍数
            next_key = total
            for k in keys:
                if k > beat:
                    next_key = float(k)
                    break

            if tempo.has_ramp and beat < ramp_end:
                # 变速区间内：逐拍推进，每拍取该拍起始 BPM
                seg_end = min(next_key, ramp_end)
                while remaining_seconds > 0 and beat < seg_end:
                    bpm = max(1.0, float(tempo.bpm_at_offset(beat - key)))
                    secs = 60.0 / bpm
                    if remaining_seconds >= secs:
                        remaining_seconds -= secs
                        beat += 1.0
                    else:
                        beat += remaining_seconds / secs
                        remaining_seconds = 0.0
                continue

            # 恒定速度段：按当前拍速度整段推进
            bpm = max(1.0, float(tempo.bpm_at_offset(beat - key)))
            seg_beats = next_key - beat
            seg_seconds = seg_beats * (60.0 / bpm)
            if remaining_seconds >= seg_seconds:
                remaining_seconds -= seg_seconds
                beat = next_key
            else:
                beat += remaining_seconds * (bpm / 60.0)
                remaining_seconds = 0.0

        return min(beat, total)

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
        total = self.total_beats()
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
        total = self.total_beats()
        if total <= 0:
            return left
        clamped = max(0, min(total, beat))
        return left + int(span * clamped / total)

    def _x_to_beat(self, x: int) -> int:
        """把X坐标转换为对应的拍位，用于点击定位和拖动节点。"""
        left = self._ruler_rect.left()
        right = self._ruler_rect.right()
        span = max(1, right - left)
        total = self.total_beats()
        if total <= 0:
            return 0
        clamped_x = max(left, min(right, x))
        return int(round((clamped_x - left) * total / span))

    def _compute_geometry(self):
        """根据当前拍数与尺寸参数，计算所有绘制区域（三栏布局）。"""
        self._node_rects = []
        diameter = self._node_radius * 2
        plus_size = 24
        plus_gap = 18

        offset_y = self._middle_y_offset
        y_nodes = self._top_row_y + offset_y
        ruler_top = self._middle_top + offset_y
        ruler_bottom = self._middle_bottom + offset_y

        ruler_left = self._left_padding
        ruler_right = ruler_left + self.total_beats() * self._pixels_per_beat
        self._ruler_rect = QRect(ruler_left, ruler_top, ruler_right - ruler_left, ruler_bottom - ruler_top)

        for i in range(len(self.graph_list)):
            cx = self._beat_to_x(self.start_beat_of(i))
            rect = QRect(cx - self._node_radius, y_nodes, diameter, diameter)
            self._node_rects.append(rect)

        if self._node_rects:
            last = self._node_rects[-1]
            plus_x = last.right() + 18
            max_plus_x = max(self._left_padding, self.width() - self._right_padding - plus_size)
            plus_x = min(plus_x, max_plus_x)
            plus_y = y_nodes + (diameter - plus_size) // 2
            self._plus_rect = QRect(plus_x, plus_y, plus_size, plus_size)
        else:
            self._plus_rect = QRect(self._left_padding, y_nodes, 24, 24)

        # 速度轴区域（展开时才可见）
        if self._expanded:
            self._tempo_rect = QRect(
                self._left_padding, 0,
                ruler_right - ruler_left, self._tempo_bar_height,
            )
        else:
            self._tempo_rect = QRect()

        # 音频栏区域（展开时才可见，暂空）。
        # 顶部需避开标尺下方的拍数标签，否则灰色音频栏会盖住拍数数字。
        if self._expanded:
            if len(self.graph_list) > 1:
                beat_label_bottom = self._bottom_row_y + offset_y + self._beat_label_height
            else:
                beat_label_bottom = ruler_bottom
            audio_top = beat_label_bottom + 4
            self._audio_rect = QRect(
                self._left_padding, audio_top,
                ruler_right - ruler_left, self._audio_bar_height,
            )
        else:
            self._audio_rect = QRect()

    def paintEvent(self, event):
        """绘制时间轴背景、刻度、节点、当前拍位游标与新增按钮。"""
        super().paintEvent(event)
        self._compute_geometry()

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        # 背景
        p.fillRect(self.rect(), QColor("#f7f7f7"))

        if self._expanded:
            self._draw_tempo_bar(p)
            self._draw_audio_bar(p)
        self._draw_middle_bar(p)

    def _draw_tempo_bar(self, p: QPainter):
        if self._tempo_rect.isEmpty():
            return
        trect = self._tempo_rect
        p.fillRect(trect, QColor("#f0f0f0"))
        p.setPen(QPen(QColor("#aeaeae"), 1))
        p.drawLine(trect.left(), trect.bottom(), trect.right(), trect.bottom())
        keys = sorted(self.beat_tempo.keys())
        total = self.total_beats()
        if total <= 0:
            return
        for key in keys:
            tempo = self.beat_tempo[key]
            if not tempo.has_ramp:
                continue
            start_x = self._beat_to_x(key)
            end_beat = key + tempo.duration_beats
            end_x = self._beat_to_x(int(min(end_beat, total)))
            if end_x <= start_x:
                continue
            is_accel = tempo.end_bpm > tempo.start_bpm
            color = QColor(231, 76, 60, 60) if is_accel else QColor(52, 152, 219, 60)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(color)
            p.drawRect(QRect(start_x, trect.top() + 1, end_x - start_x, trect.height() - 2))
        font = QFont(self.font())
        font.setPointSize(self._beat_font_size)
        p.setFont(font)
        for key in keys:
            tempo = self.beat_tempo[key]
            x = self._beat_to_x(key)
            p.setPen(QPen(QColor("#5f6368"), 1))
            p.setPen(QPen(QColor("#2c3e50"), 1))
            p.drawText(QRect(x + 2, trect.top() + 1, self.tempo_label_width, trect.height() // 2 - 2),
                       Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
                       f"{tempo.start_bpm}")
            if tempo.has_ramp:
                c = QColor("#e74c3c") if tempo.end_bpm > tempo.start_bpm else QColor("#2980b9")
                p.setPen(QPen(c, 1))
                end_x = self._beat_to_x(int(min(key + tempo.duration_beats, total)))
                # p.drawLine(end_x, trect.top() + 1, end_x, trect.bottom() - 1)
                p.drawText(QRect(end_x - (self.tempo_label_width + 2), trect.bottom() - (trect.height() // 2 + 1), self.tempo_label_width, trect.height() // 2 - 2),
                           Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                           f"{tempo.end_bpm}")
            else:
                p.drawLine(x, trect.top() + 1, x, trect.bottom() - 1)
                

    def _draw_audio_bar(self, p: QPainter):
        if self._audio_rect.isEmpty():
            return
        arect = self._audio_rect
        p.fillRect(arect, QColor("#f0f0f0"))
        p.setPen(QPen(QColor("#aeaeae"), 1))
        p.drawLine(arect.left(), arect.top(), arect.right(), arect.top())

    def _draw_middle_bar(self, p: QPainter):
        total = self.total_beats()
        offset_y = self._middle_y_offset

        if len(self.graph_list) > 1:
            p.setPen(QPen(QColor("#aeaeae"), 1))
            p.drawLine(self._ruler_rect.left(), self._ruler_rect.bottom(),
                       self._ruler_rect.right(), self._ruler_rect.bottom())
            # 拍数标签字体
            beat_font = QFont(self.font())
            beat_font.setPointSize(self._beat_font_size)
            p.setFont(beat_font)

            long_every = max(1, int(self.long_tick_interval))
            bottom_label_y = self._bottom_row_y + offset_y
            for beat in range(0, total + 1):
                x = self._beat_to_x(beat)
                if beat % long_every == 0:
                    p.setPen(QPen(QColor("#5f6368"), 1))
                    p.drawLine(x, self._ruler_rect.top(), x, self._ruler_rect.bottom())
                    p.drawText(QRect(x - 16, bottom_label_y, 32, self._beat_label_height),
                               Qt.AlignmentFlag.AlignCenter, str(beat))
                else:
                    p.setPen(QPen(QColor("#b0b5ba"), 1))
                    p.drawLine(x, self._ruler_rect.top() + 7, x, self._ruler_rect.bottom())

        # 当前拍位游标
        cursor_x = self._beat_to_x(self.current_beat)
        y_top = self._top_row_y + offset_y
        y_bottom = self._middle_bottom + offset_y
        p.setPen(QPen(QColor("#e74c3c"), 2))
        p.drawLine(cursor_x, y_top - 1, cursor_x, y_bottom + 1)

        # 节点字体
        font = QFont(self.font())
        font.setPointSize(self._node_font_size)
        p.setFont(font)

        # 绘制节点
        for i in range(len(self.graph_list)):
            # 节点矩形，选中节点高亮
            cx = self._beat_to_x(self.start_beat_of(i))
            rect = QRect(cx - self._node_radius, y_top, self._node_radius * 2, self._node_radius * 2)
            is_selected = i == self.selected_node
            fill = QColor("#ececec") if i == 0 else QColor("#ffffff")
            border = QColor("#f39c12") if is_selected else QColor("#1f5e9c")
            border_w = 2 if is_selected else 1
            p.setPen(QPen(border, border_w))
            p.setBrush(fill)
            p.drawRect(rect)
            p.setPen(QPen(QColor("#000000"), 1))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, str(i))
            if i < len(self._node_rects):
                self._node_rects[i] = rect
            else:
                self._node_rects.append(rect)

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
            # 点击节点：选中节点，并把当前拍位定位到该节点起始拍
            pos = event.pos()
            for i, rect in enumerate(self._node_rects):
                if rect.contains(pos):
                    self.selected_node = i
                    self.current_beat = self.start_beat_of(i)
                    self.nodeSelected.emit(i)
                    self.currentBeatChanged.emit(self.current_beat)
                    self.update()
                    event.accept()
                    return
            if self._plus_rect.contains(pos):
                self.add_node(8)
                event.accept()
                return
            # 点击标尺区域，把当前拍位定位到最近的整拍
            expand_y = self._node_radius * 2
            ruler_hit = self._ruler_rect.adjusted(-2, -expand_y, 2, 14)
            if ruler_hit.contains(pos) or self._tempo_rect.contains(pos):
                beat = self._x_to_beat(pos.x())
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
            pos = event.pos()
            if self._expanded and self._tempo_rect.contains(pos):
                beat = self._x_to_beat(pos.x())
                if beat in self.beat_tempo:
                    return
                current_bpm = self._bpm_at_beat(float(beat))
                dialog = TempoEditDialog(
                    beat=beat, current_bpm=current_bpm, is_new=True, parent=self,
                    total_beats=self.total_beats(),
                    tempo_keys=sorted(self.beat_tempo.keys()),
                )
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    self.set_tempo_at_beat(dialog._beat_spin.value(), dialog.get_tempo(), is_new=True)
                event.accept()
                return
            expand_y = self._node_radius * 2
            ruler_hit = self._ruler_rect.adjusted(-2, -expand_y, 2, 14)
            if ruler_hit.contains(pos):
                beat = self._x_to_beat(pos.x())
                if self.insert_node_at_beat(beat):
                    event.accept()
                    return
        super().mouseDoubleClickEvent(event)

    def contextMenuEvent(self, event):
        """右键节点弹出设置窗口：修改间隔拍数或删除该节点。"""
        pos: QPoint = event.pos()
        
        # 右键速度轴区域时，弹出速度编辑对话框（修改或删除该节点）。
        if self._expanded and self._tempo_rect.contains(pos):
            beat = self._x_to_beat(pos.x())
            key = self._nearest_tempo_key(beat)
            tempo = self.beat_tempo.get(key, Tempo(start_bpm=120))
            dialog = TempoEditDialog(
                beat=key, current_bpm=tempo.start_bpm,
                end_bpm=tempo.end_bpm, duration=tempo.duration_beats,
                is_new=False, parent=self,
                total_beats=self.total_beats(),
                tempo_keys=sorted(self.beat_tempo.keys()),
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # 弹窗里可编辑节拍位置，OK 后应使用用户最终确认的拍位，
                # 而不是右键点击位置 key，否则改拍位不生效。
                new_beat = dialog._beat_spin.value()
                if dialog.delete_requested:
                    self.delete_tempo_at_beat(new_beat)
                else:
                    self.set_tempo_at_beat(new_beat, dialog.get_tempo(), is_new=False, old_beat=key)
            return
        
        # 右键速度轴右缘外侧一个定值范围（bpm 值宽度）内，定位到最后一个速度节点（tempo[-1]）。
        # 与 _nearest_tempo_key 一致：从后向前筛选，跳过变速区间已结束的节点，
        # 取总拍数处最后一个仍生效的速度节点（右缘外侧对应总拍数位置）。
        tempo_hit = self._tempo_rect.adjusted(0, 0, self.tempo_label_width + 4, 0)
        if tempo_hit.contains(pos):
            key = self._nearest_tempo_key(self.total_beats())
            tempo = self.beat_tempo.get(key, Tempo(start_bpm=120))
            dialog = TempoEditDialog(
                beat=key, current_bpm=tempo.start_bpm,
                end_bpm=tempo.end_bpm, duration=tempo.duration_beats,
                is_new=False, parent=self,
                total_beats=self.total_beats(),
                tempo_keys=sorted(self.beat_tempo.keys()),
            )
            if dialog.exec() == QDialog.DialogCode.Accepted:
                # 弹窗里可编辑节拍位置，OK 后应使用用户最终确认的拍位，
                # 而不是右键点击位置 key，否则改拍位不生效。
                new_beat = dialog._beat_spin.value()
                if dialog.delete_requested:
                    self.delete_tempo_at_beat(new_beat)
                else:
                    self.set_tempo_at_beat(new_beat, dialog.get_tempo(), is_new=False, old_beat=key)
            return
        
        # 右键设置方案图节点信息
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
                        self._switch_next()
                return

        super().contextMenuEvent(event)

    # ──────── 方向键切换 ────────

    def _switch_prev(self):
        """左方向键：若当前拍位在节点上，跳转到上一个节点（循环）；否则跳转到左侧最近的节点。
        优化：若当前编辑节点与 beat 所在节点不同，先跳转到 beat 所在节点。
        """
        total = self.total_beats()
        if total <= 0:
            return
        node_idx = self.node_index_at_beat(self.current_beat)
        if node_idx is not None:
            # 若当前编辑节点与 beat 所在节点不同，先切换至 beat 所在节点
            if node_idx != self.selected_node:
                new_idx = node_idx
            else:
                new_idx = node_idx - 1
                if new_idx < 0:
                    new_idx = len(self.graph_list) - 1
            self.selected_node = new_idx
            self.current_beat = self.start_beat_of(new_idx)
        else:
            starts = self.node_start_beats()
            target = self.current_beat
            nearest = 0
            for i, s in enumerate(starts):
                if s < target:
                    nearest = i
            self.selected_node = nearest
            self.current_beat = self.start_beat_of(nearest)
        self.nodeSelected.emit(self.selected_node)
        self.currentBeatChanged.emit(self.current_beat)
        self.update()

    def _switch_next(self):
        """右方向键：若当前拍位在节点上，跳转到下一个节点（循环）；否则跳转到右侧最近的节点。
        优化：若当前编辑节点与 beat 所在节点不同，先跳转到 beat 所在节点。
        """
        total = self.total_beats()
        if total <= 0:
            return
        node_idx = self.node_index_at_beat(self.current_beat)
        if node_idx is not None:
            # 若当前编辑节点与 beat 所在节点不同，先切换至 beat 所在节点
            if node_idx != self.selected_node:
                new_idx = node_idx
            else:
                new_idx = node_idx + 1
                if new_idx >= len(self.graph_list):
                    new_idx = 0
            self.selected_node = new_idx
            self.current_beat = self.start_beat_of(new_idx)
        else:
            starts = self.node_start_beats()
            target = self.current_beat
            nearest = len(starts) - 1
            for i, s in enumerate(starts):
                if s > target:
                    nearest = i
                    break
            self.selected_node = nearest
            self.current_beat = self.start_beat_of(nearest)
        self.nodeSelected.emit(self.selected_node)
        self.currentBeatChanged.emit(self.current_beat)
        self.update()

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
