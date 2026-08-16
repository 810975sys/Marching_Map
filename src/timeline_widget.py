"""时间轴组件。

主要职责：
1. 维护节点与节点间拍数间隔。
2. 提供节点增删、选中与拍位定位交互。
3. 通过信号与主窗口/场景同步当前节点与时间进度。
4. 速度轴（展开态上栏）：分段速度设置、变速区间可视化。
5. 音频栏（展开态下栏）：音频文件占位。
"""

import math

from pathlib import Path

from PyQt6.QtCore import QPoint, QRect, Qt, pyqtSignal, QTimer
from PyQt6.QtGui import QColor, QCursor, QFont, QPainter, QPen, QPixmap, QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
    QScrollArea,
)

from src.tempo_data import Tempo
from src.audio_data import (
    AudioSegment,
    audio_duration,
    get_file_peaks,
    get_range_peaks,
    SAMPLE_RATE,
    BUCKET,
)

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
    currentBeatChanged = pyqtSignal(float)  # 当前显示的拍位（负拍前导区/播放中可为小数）
    nodeAdded = pyqtSignal(int)     # 新增节点的索引
    nodeDeleted = pyqtSignal(int)   # 删除节点的索引
    nodeInserted = pyqtSignal(int)  # 插入的新节点索引
    tempoChanged = pyqtSignal()     # 速度节点数据发生变化
    expandedChanged = pyqtSignal(bool)  # 展开/折叠状态变化
    audioChanged = pyqtSignal()     # 音频段数据发生变化
    importAudioRequested = pyqtSignal()  # 请求导入音频（点击音频栏右侧按钮）

    def __init__(self, parent=None):
        super().__init__(parent)
        # 节点0始终存在。
        # graph_list[i] 表示“节点 i-1 到节点 i”的间隔拍数，因此下标0占位不用。
        self.graph_list = [0]

        # beat_tempo: beat=0 必有默认 Tempo(120)
        self.beat_tempo: dict[int, Tempo] = {0: Tempo(start_bpm=120)}
        self.tempo_label_width = 25  # bpm 标签宽度

        # 撤销/重做管理器（由 MainWindow 注入）；用于时间轴/音频编辑的会话与一步操作记录
        self.history = None

        # 缓存绘制几何区域
        self._node_rects: list[QRect] = []
        self._plus_rect = QRect()
        self._minus_node_rect = QRect()     # 左侧虚拟 -1 节点区域（负起始拍，仅用于选择播放位置）
        self._minus_node_beat = None        # 虚拟 -1 节点对应的负起始拍（最靠左的一个）
        self._ruler_rect = QRect()
        self._tempo_rect = QRect()
        self._audio_rect = QRect()
        self._audio_add_rect = QRect()      # 音频栏右侧“导入音频”按钮区域
        self._audio_handle_w = 5            # 裁剪手柄宽度（绘制在段外侧，交互区域需外扩该宽度）

        # 音频段数据与编辑状态
        self.audio_segments: list[AudioSegment] = []
        self._audio_selected = -1               # 当前编辑的音频段索引（-1 表示无）
        self._audio_pixmap: QPixmap | None = None   # 波形缓存位图
        self._audio_unreadable: set[int] = set()    # 音频文件无法解码的段索引（渲染时记录，用于提示）
        self._beat_time_cache: list[float] | None = None  # 拍→秒累计表（依据 beat_tempo），长度 total_beats+1
        self._beat_time_cache_key: tuple | None = None    # 累计表有效性键（base, total, beat_tempo 快照）
        self._audio_drag_mode: str | None = None    # 拖拽模式: 'move'|'left'|'right'
        self._audio_drag_from_idx = -1
        self._audio_drag_beat = 0.0             # move 预览起始拍
        self._audio_drag_grab_offset = 0.0      # move 拖拽：点击时鼠标相对段起始拍的偏移（抓取点）
        self._audio_drag_target = -1            # move 拖拽：当前交换目标段索引（-1 表示无）
        self._audio_drag_orig = None            # 边界拖拽前快照 (src_start, src_end, start_beat)
        self._audio_drag_orig_starts: list[float] = []  # 拖拽开始时所有音频段的起始拍快照（right 拖拽回原位用）
        self._audio_drag_ref_x = 0.0            # 拖拽参考锚点：按下时的全局（屏幕）像素 X
        self._audio_drag_ref_beat = 0.0         # 拖拽参考锚点：按下时的鼠标拍位
        self._audio_drag_prev_beat = 0.0        # 拖拽上一次有效拍位（裁剪方向门控基准）
        self._audio_drag_last_global_x = 0.0    # 拖拽中上一次指针全局 X（自动滚动方向检测）

        # 自动向右滚动：拖拽时指针贴近/越过视口右缘则持续向右延伸，
        # 滚动速度随指针位置动态变化（指针越靠右越快）；进入触发区后
        # 即使指针不动，定时器也会持续推进延伸。
        self._auto_scroll_timer = QTimer(self)
        self._auto_scroll_timer.setInterval(16)   # ≈60fps，滚动平滑连续
        self._auto_scroll_timer.timeout.connect(self._auto_scroll_tick)
        self._auto_scroll_zone = 80        # 右缘触发区宽度（px）：指针进入该区域开始自动滚动
        self._auto_scroll_max_step = 48    # 单次 tick 最大滚动量（px），速度因子按指针位置缩放
        # 自动延伸累计拍位：进入触发区后每个 tick 按速度累加，拖拽有效拍位 =
        # 指针拍位 + 累计延伸，使指针不动时内容仍持续向右延伸；指针离开触发区
        # 后累计量冻结（保持已延伸位置），松手/新拖拽时清零。
        self._auto_scroll_beat_accum = 0.0

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
        # 开启鼠标追踪：无按键移动时也触发 mouseMoveEvent，实现悬停光标切换
        self.setMouseTracking(True)

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

        # Delete 快捷键：删除当前选中的音频段（带确认弹窗）。
        # 使用 WidgetShortcut：仅在时间轴自身聚焦时生效，
        # 避免与主窗口“删除点位”（Delete 快捷键）冲突（场景聚焦时仍用于删除点位）。
        self._shortcut_delete_audio = QShortcut(QKeySequence(Qt.Key.Key_Delete), self)
        self._shortcut_delete_audio.setContext(Qt.ShortcutContext.WidgetShortcut)
        self._shortcut_delete_audio.activated.connect(self._delete_selected_audio)

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
    
    def load_from_dict(self, data: dict, audio_data: dict | None = None, progress_cb=None):
        """整体恢复时间轴：graph_list、beat_tempo 与音频段。

        audio_data 为方案中的 "audio" 数据；为 None 或空时清空音频段。
        progress_cb 可选：预解码音频段时回调 progress_cb(done, total, name)，用于显示进度。
        """
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
        # 音频段随方案一起恢复：load_audio_from_dict 内部会先清空再重建
        self.load_audio_from_dict(
            audio_data if isinstance(audio_data, dict) else {}, progress_cb=progress_cb
        )
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
        if self.history is not None:
            self.history.begin("新增节点")
        self.graph_list.append(max(1, int(interval)))
        added_index = len(self.graph_list) - 1
        self._recalculate_width()
        self.timelineChanged.emit()
        self.nodeAdded.emit(added_index)
        self.update()
        if self.history is not None:
            self.history.commit()

    def delete_node(self, node_index: int):
        """删除指定节点，节点0不允许删除。"""
        if node_index <= 0 or node_index >= len(self.graph_list):
            return
        if self.history is not None:
            self.history.begin("删除节点")

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
        if self.history is not None:
            self.history.commit()

    def _min_axis_beat(self) -> float:
        """时间轴最左拍位（可 < 0，可为小数）。

        取 0 与所有音频段起始拍下限的最小值，返回连续浮点值（不向下取整）；
        处于 move 拖拽时把拖拽预览起始拍也计入，使负区预览即时可见。
        返回小数使拖入负拍区时轴按实际拍位平滑向左展开，
        不再按整数拍阶梯式扩展（负数拍位可精确到小数）。
        负区沿用节点 0 的速度（速度轴与节点 0 对齐）。
        """
        min_start = 0.0
        for s in self.audio_segments:
            min_start = min(min_start, float(s.start_beat))
        if self._audio_drag_mode == "move":
            min_start = min(min_start, float(self._audio_drag_beat))
        return float(min_start)

    def _spb_after_total(self) -> float:
        """最后一个节点处每拍秒数（60/BPM）。

        超出最后节点的部分不再有方案图变换，音频按“纯时间”延伸，
        这里用最后节点的拍速换算像素/秒，使波形在衔接处无缝。
        """
        total = self.total_beats()
        return max(1e-6, self._seconds_per_beat_at(max(0, total)))

    def _audio_right_time(self) -> float:
        """整轨音频结束的轨道时间（秒）。

        取最后一个节点的轨道时间与所有音频段结束时间的最大值；
        音频段可能延伸到最后一个方案图节点之后，此时超出部分按音频时间延伸。
        move 拖拽时把拖拽段预览的右缘也计入，使向右延伸（含自动延伸）时
        内容宽度随之扩展，滚动区不会在内容右缘处停下。
        """
        total = float(self.total_beats())
        max_t = self.audio_time_at_beat(total)
        for seg in self.audio_segments:
            start = min(float(seg.start_beat), total)
            t_end = self.audio_time_at_beat(start) + seg.duration_seconds
            max_t = max(max_t, t_end)
        if (self._audio_drag_mode == "move"
                and 0 <= self._audio_drag_from_idx < len(self.audio_segments)):
            seg = self.audio_segments[self._audio_drag_from_idx]
            t_end = self.audio_time_at_beat(self._audio_drag_beat) + seg.duration_seconds
            max_t = max(max_t, t_end)
        return max_t

    def _audio_right_x(self) -> float:
        """音频栏右缘 X：超出最后节点的部分按音频时间（秒）延伸，不用 beat。"""
        total = self.total_beats()
        x_total = self._beat_to_x_f(total)
        t_total = self.audio_time_at_beat(float(total))
        max_t = self._audio_right_time()
        if max_t <= t_total:
            return x_total
        return x_total + (max_t - t_total) * (self._pixels_per_beat / self._spb_after_total())

    def _audio_time_to_x(self, t: float) -> float:
        """音频轨道时间（秒）→ X 坐标。

        最后一个节点内走 beat 轴；超出后按音频时间（秒）无缝延伸。
        """
        total = self.total_beats()
        t_total = self.audio_time_at_beat(float(total))
        if t <= t_total:
            return self._beat_to_x_f(self.audio_beat_at_time(t))
        x_total = self._beat_to_x_f(total)
        return x_total + (t - t_total) * (self._pixels_per_beat / self._spb_after_total())

    def _audio_x_to_time(self, x: float) -> float:
        """X 坐标 → 音频轨道时间（秒）。

        最后一个节点内走 beat 轴；超出后按音频时间（秒）无缝延伸。
        """
        total = self.total_beats()
        min_beat = float(self._min_axis_beat())
        x_total = self._beat_to_x_f(total)
        if x <= x_total:
            beat = min_beat + (x - self._left_padding) / self._pixels_per_beat
            return self.audio_time_at_beat(beat)
        t_total = self.audio_time_at_beat(float(total))
        return t_total + (x - x_total) * (self._spb_after_total() / self._pixels_per_beat)

    def audio_end_beat(self) -> float:
        """整轨音频结束拍（可超出最后方案图节点；无音频时为总拍数）。"""
        return self.audio_beat_at_time(self._audio_right_time())

    def _recalculate_width(self):
        """按跨度（最左拍 ~ 音频右缘）计算控件宽度；时间轴按拍位固定宽度显示。

        最左拍可由音频段负起始拍决定；右缘可由音频段结束时间（超出最后节点）
        决定，超出部分按音频时间延伸，因此音频段移动/裁剪/缩放后会调用本方法重新排布。
        """
        self._beat_time_cache = None   # 拍数/速度/最左拍变化 → 拍→秒累计表失效
        self._beat_time_cache_key = None
        plus_size = 24  # 加号按钮尺寸
        plus_gap = 18   # 加号按钮与最后节点间距，避免影响点击
        audio_btn_w = 70    # 音频栏右侧“导入音频”按钮宽度
        audio_btn_gap = 10  # 音频栏右缘与按钮间距
        # min_beat = self._min_axis_beat()
        # 右缘按音频结束时间延伸（可超出最后方案图节点），波形不被截断
        right_x = self._audio_right_x()
        span_px = right_x - self._left_padding
        content_width = self._left_padding + int(round(span_px))
        # 右侧预留空间取节点加号按钮与音频按钮两者较大者，避免被裁剪。
        right_space = max(plus_gap + plus_size, audio_btn_gap + audio_btn_w)
        desired_width = content_width + right_space + self._right_padding
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
        # 节拍速度变化 → 轴对齐映射失效，且音频段结束拍（最右拍）随之变化
        self._recalculate_width()
        self._audio_pixmap = None   # 波形需按新节拍速度重新对齐
        self.tempoChanged.emit()
        self.timelineChanged.emit()
        self.update()

    def delete_tempo_at_beat(self, beat: int):
        if beat <= 0 or beat not in self.beat_tempo:
            return
        del self.beat_tempo[beat]
        # 节拍速度变化 → 轴对齐映射失效，且音频段结束拍（最右拍）随之变化
        self._recalculate_width()
        self._audio_pixmap = None   # 波形需按新节拍速度重新对齐
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

        if self.history is not None:
            self.history.begin("插入节点")
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
        if self.history is not None:
            self.history.commit()
        return True

    def _beat_to_x(self, beat: int) -> int:
        """把拍位转换为对应的X坐标（按拍位 × 每拍像素宽度，即每拍固定宽度）。"""
        return int(round(self._beat_to_x_f(beat)))

    def _x_to_beat(self, x: int) -> int:
        """把X坐标转换为对应的拍位（按每拍固定宽度反推，用于点击定位和拖动节点）。"""
        total = self.total_beats()
        if total <= 0 or self._pixels_per_beat <= 0:
            return 0
        min_beat = self._min_axis_beat()
        return int(round(min_beat + (max(self._left_padding, x) - self._left_padding) / self._pixels_per_beat))

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
        total_beats = self.total_beats()
        min_beat = self._min_axis_beat()
        ruler_right = ruler_left + int((total_beats - min_beat) * self._pixels_per_beat)
        # 音频栏右缘按音频结束时间延伸（可超出最后方案图节点），波形不被截断
        audio_right = self._audio_right_x()
        self._ruler_rect = QRect(ruler_left, ruler_top, max(1, ruler_right - ruler_left), ruler_bottom - ruler_top)

        for i in range(len(self.graph_list)):
            cx = self._beat_to_x(self.start_beat_of(i))
            rect = QRect(cx - self._node_radius, y_nodes, diameter, diameter)
            self._node_rects.append(rect)

        # 左侧虚拟 -1 节点：取最靠左的负起始拍，与音频段起始拍对齐，仅用于选择播放位置。
        neg_starts = [float(s.start_beat) for s in self.audio_segments if s.start_beat < 0]
        if neg_starts:
            self._minus_node_beat = min(neg_starts)
            cx = self._beat_to_x_f(self._minus_node_beat)
            self._minus_node_rect = QRect(
                int(round(cx)) - self._node_radius, y_nodes, diameter, diameter
            )
        else:
            self._minus_node_beat = None
            self._minus_node_rect = QRect()

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
                max(1, int(round(audio_right)) - ruler_left), self._audio_bar_height,
            )
            # 音频栏右侧“导入音频”按钮：位于音频栏右缘外侧。
            btn_w = 70
            btn_h = 22
            btn_x = self._audio_rect.right() + 10
            max_btn_x = max(self._left_padding, self.width() - self._right_padding - btn_w)
            btn_x = min(btn_x, max_btn_x)
            btn_y = self._audio_rect.top() + (self._audio_bar_height - btn_h) // 2
            self._audio_add_rect = QRect(btn_x, btn_y, btn_w, btn_h)
        else:
            self._audio_rect = QRect()
            self._audio_add_rect = QRect()

    def _audio_hit_rect(self) -> QRect:
        """音频栏交互区域：音频栏矩形左右外扩裁剪手柄宽度，覆盖段外侧手柄。

        右侧外扩 2 倍手柄宽度：右端裁剪手柄命中范围向右延伸一个 _audio_handle_w，
        使段右端即使接近/超出音频栏右缘也能被命中，源音频后续仍有内容时可持续向右拖拽。
        """
        return self._audio_rect.adjusted(-self._audio_handle_w, 0, 2 * self._audio_handle_w, 0)

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
                
    # ──────── 音频栏：数据管理 ────────
    def _seconds_per_beat_at(self, beat: int) -> float:
        """第 beat 拍（该拍起始）对应的秒/拍，即 60 / BPM（依据 beat_tempo）。

        与 _beat_from_elapsed 播放进度计算采用相同的离散语义：变速区间内
        每拍取该拍起始 BPM。轴对齐（显示与播放）均通过它实现。
        """
        bpm = max(1.0, float(self._bpm_at_beat(float(beat))))
        return 60.0 / bpm

    def _beat_time_cum(self) -> list[float]:
        """拍→秒累计表 cum[k] = 拍 (base + k) 起始的轨道时间（秒）。

        base = floor(最左拍)；轴左缘（最左拍，可为小数）时间定为 0。
        最左拍为小数时，base 位于轴左缘左侧 frac 拍，cum[0] 相应为负偏移，
        使 audio_time_at_beat(最左拍) == 0 仍成立。负区沿用节点 0 速度。
        表只覆盖到总拍数（最后方案图节点）；超出部分由 audio_time_at_beat /
        audio_beat_at_time 按最后节点拍速做纯时间线性外推，不再生成新的“拍”表项。
        """
        key = self._beat_time_key()
        if self._beat_time_cache is not None and self._beat_time_cache_key == key:
            return self._beat_time_cache
        min_beat = self._min_axis_beat()
        base = math.floor(min_beat)
        frac = min_beat - base
        total = self.total_beats()
        # 轴左缘（min_beat，可为小数）时间定为 0：base 拍位于轴左缘左侧
        # frac 拍，其时间为负偏移 -(frac * spb)，整个累计表都以此为起点，
        # 保证 audio_time_at_beat(min_beat) == 0 且拍→时间线性连续。
        offset = -(frac * self._seconds_per_beat_at(base)) if frac > 0 else 0.0
        cum = [offset]
        acc = offset
        for b in range(base, total):
            acc += self._seconds_per_beat_at(b)
            cum.append(acc)
        self._beat_time_cache = cum
        self._beat_time_cache_key = key
        return self._beat_time_cache

    def _beat_time_key(self) -> tuple:
        """拍→秒累计表的有效性键：base（最左拍向下取整）、总拍数 total 与 beat_tempo 快照。

        累计表依赖三者；任一变化（如 load_from_dict 重排 beat_tempo / audio_segments
        后尚未调用 _recalculate_width，进度回调 pump 事件触发重绘）都会使其失效。
        用“键比对”而非“仅置空”判断失效，可避免数据已变但缓存未清的空窗期
        访问过期累计表越界（IndexError）。
        """
        return (
            math.floor(self._min_axis_beat()),
            self.total_beats(),
            tuple(
                (int(k), int(v.start_bpm), v.end_bpm, int(v.duration_beats))
                for k, v in sorted(self.beat_tempo.items())
            ),
        )

    def audio_time_at_beat(self, beat: float) -> float:
        """把拍位转换为轨道时间（秒），按 beat_tempo 累计。

        负拍同样支持：时间自最左拍（可为负、可为小数）起算，负区沿用节点 0 速度。
        轴左缘（最左拍）时间为 0；向左（beat < 最左拍，左端裁剪延伸/外推）按节点 0
        拍速线性外推为负时间，避免轴向左展开时拍→时间映射出现跳变。
        超出总拍数（音频延伸到最后节点之后）的部分按最后节点拍速做纯时间线性外推，
        不再生成新的“拍”表项。
        注意负拍位必须用 math.floor 取整：int() 向零截断会让 -7.5 误落到 -7，
        使负区拍→时间映射出现阶梯跳变，波形绘制成块状“马赛克”。
        """
        min_beat = float(self._min_axis_beat())
        total = float(self.total_beats())
        beat = float(beat)
        b = math.floor(beat)
        if beat < min_beat:
            # 轴左缘左侧：按节点 0 拍速线性外推（负区速度恒定），时间为负
            base = math.floor(min_beat)
            spb = self._seconds_per_beat_at(base)
            return - (min_beat - beat) * spb
        if b > total:
            # 超出最后节点：不再有方案图变换，按最后节点拍速线性延续时间
            cum = self._beat_time_cum()
            base = math.floor(min_beat)
            t_total = cum[int(total) - base]
            return t_total + (beat - total) * self._seconds_per_beat_at(int(total))
        cum = self._beat_time_cum()
        base = math.floor(min_beat)
        t = cum[b - base]
        if beat > b:
            t += (beat - b) * self._seconds_per_beat_at(b)
        return t

    def audio_beat_at_time(self, t: float) -> float:
        """把轨道时间（秒）转换为拍位，按 beat_tempo 逆推（二分）。

        cum 下标 0 对应整数拍 base（最左拍向下取整），返回拍位可为负、可为小数。
        超出最后一个节点时间后按最后节点拍速做纯时间线性外推（仅供内部编辑/播放
        定位使用，不生成新的“拍”表项）。
        """
        cum = self._beat_time_cum()
        min_beat = float(self._min_axis_beat())
        base = math.floor(min_beat)
        total = len(cum) - 1
        if total <= 0:
            return min_beat
        if t < cum[0]:
            # 轴左缘左侧时间：按节点 0 拍速线性外推（与 audio_time_at_beat 负向延伸对应）
            spb = self._seconds_per_beat_at(base)
            return float(base) + (t - cum[0]) / max(1e-6, spb)
        lo, hi = 0, total
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if cum[mid] <= t:
                lo = mid
            else:
                hi = mid - 1
        if lo >= total:
            # 超出最后节点时间：按最后节点拍速线性外推
            spb = self._seconds_per_beat_at(int(self.total_beats()))
            return float(base + total) + (t - cum[total]) / max(1e-6, spb)
        span = cum[lo + 1] - cum[lo]
        return float(base + lo) + (t - cum[lo]) / max(1e-6, span)

    def audio_segment_end_beat(self, seg: AudioSegment) -> float:
        """该段在时间轴上的结束拍（按 beat_tempo 反推，轴对齐随节拍速度）。"""
        return self.audio_beat_at_time(
            self.audio_time_at_beat(seg.start_beat) + seg.duration_seconds
        )

    def _audio_source_time_at_beat(self, seg: AudioSegment, beat: float) -> float:
        """把拍位映射到段内源时间（秒），轴对齐依据 beat_tempo。"""
        return seg.src_start + (
            self.audio_time_at_beat(beat) - self.audio_time_at_beat(seg.start_beat)
        )

    def audio_segment_at_beat(self, beat: float):
        """返回包含拍位的 (段索引, 段)；无则返回 None。"""
        target = float(beat)
        for i, seg in enumerate(self.audio_segments):
            if seg.start_beat <= target < self.audio_segment_end_beat(seg):
                return i, seg
        return None

    # def audio_source_to_beat(self, seg_idx: int, src_time: float) -> float:
    #     """把段内源时间（秒）映射为时间轴拍位（播放同步用，依据 beat_tempo）。"""
    #     if not (0 <= seg_idx < len(self.audio_segments)):
    #         return 0.0
    #     seg = self.audio_segments[seg_idx]
    #     track_time = self.audio_time_at_beat(seg.start_beat) + (src_time - seg.src_start)
    #     return self.audio_beat_at_time(track_time)

    # def audio_beat_to_source(self, beat: float):
    #     """把时间轴拍位映射为 (段索引, 段, 源时间秒)；无覆盖返回 None。"""
    #     found = self.audio_segment_at_beat(beat)
    #     if found is None:
    #         return None
    #     idx, seg = found
    #     return idx, seg, self._audio_source_time_at_beat(seg, beat)

    def audio_to_dict(self) -> dict:
        """导出音频段数据（file 为原始文件绝对路径）。"""
        return {
            "segments": [seg.to_dict() for seg in self.audio_segments],
        }

    def _preload_audio_peaks(self, progress_cb=None):
        """预解码所有音频段源文件，填充波形缓存，避免首次展开时间轴时同步解码卡顿。

        绘制波形（_draw_audio_bar → get_range_peaks）首次遇到未解码的文件时，
        pydub 需整段解码为内存波形，会阻塞 UI（表现为展开时间轴的停顿）。本方法
        在音频数据加载/导入阶段主动调用 get_file_peaks（内部解码并缓存波形），
        把耗时前移到数据加载流程，使首次展开时波形可直接从缓存切片、即时绘制。
        文件无法解码时 get_file_peaks 返回 None，不会抛出异常。

        progress_cb 可选：每处理完一个文件回调 progress_cb(done, total, name)，
        用于在加载（需解码音频，可能耗时）期间显示进度。
        """
        n = len(self.audio_segments)
        for i, seg in enumerate(self.audio_segments):
            get_file_peaks(seg.resolve_file())
            if progress_cb is not None:
                progress_cb(i + 1, n, Path(seg.file).name)

    def load_audio_from_dict(self, data: dict, progress_cb=None):
        """从方案数据恢复音频段；file 为绝对路径，原始文件不存在则跳过。

        恢复前先进行文件存在性检查：存在缺失的音频文件时，弹出提示弹窗
        列出缺失文件，提醒用户重新导入。
        progress_cb 可选：预解码音频段时回调 progress_cb(done, total, name)，用于显示进度。
        """
        self.audio_segments = []
        self._audio_selected = -1
        self._audio_pixmap = None
        missing: list[str] = []
        if isinstance(data, dict):
            for item in data.get("segments", []):
                if not isinstance(item, dict):
                    continue
                seg = AudioSegment.from_dict(item)
                if seg.duration_seconds <= 0:
                    continue
                seg.file = seg.resolve_file()
                if not Path(seg.file).exists():
                    name = Path(seg.file).name
                    if name not in missing:
                        missing.append(name)
                    continue
                self.audio_segments.append(seg)
        if missing:
            QMessageBox.warning(
                self,
                "音频文件缺失",
                "音频文件：\n"
                + "\n".join(missing)
                + "\n已删除或移动，请重新导入。",
                QMessageBox.StandardButton.Ok,
            )
        if self.audio_segments:
            self._audio_selected = len(self.audio_segments) - 1
        # 预解码所有段源文件：把波形加载耗时从“首次展开时间轴”前移到“方案加载”
        self._preload_audio_peaks(progress_cb)
        self._recalculate_width()   # 音频可超出最后节点 → 重新按波形结束拍排布宽度
        self.update()

    def import_audio_files(self, file_paths, progress_cb=None) -> list[AudioSegment]:
        """导入音频文件，追加到现有波形右侧（各段首尾相连）。

        progress_cb 可选：每处理完一个文件回调 progress_cb(done, total, file_path)，
        用于在导入（需读取音频时长，可能耗时）期间显示进度。
        """
        if self.history is not None:
            self.history.begin("导入音频")
        added: list[AudioSegment] = []
        total = len(file_paths)
        done = 0
        for path in file_paths:
            duration = audio_duration(str(path))
            if duration <= 0:
                continue
            start_beat = self.audio_segment_end_beat(self.audio_segments[-1]) if self.audio_segments else 0.0
            seg = AudioSegment(
                file=str(path),
                src_start=0.0,
                src_end=duration,
                start_beat=start_beat,
            )
            self.audio_segments.append(seg)
            added.append(seg)
            done += 1
            if progress_cb is not None:
                progress_cb(done, total, str(path))
        if added:
            self._audio_selected = len(self.audio_segments) - 1
            self._audio_pixmap = None
            # 预解码新增段源文件：audio_duration 已完成解码，此步再补齐峰值表，
            # 确保导入后首次展开/绘制波形无需重新加载、无卡顿
            self._preload_audio_peaks()
            self.audioChanged.emit()
            self._recalculate_width()   # 音频可超出最后节点 → 重新按波形结束拍排布宽度
            self.update()
        if self.history is not None:
            if added:
                self.history.commit()
            else:
                self.history.cancel()
        return added

    def synthesize_playback_audio(self, output_path, progress_cb=None) -> bool:
        """把整条时间轴合成一段连续音频（无音频段处为静音），导出到 output_path。

        依据 beat_tempo 将拍位映射为轨道时间：总时长取到整轨音频结束时间
        （可超出最后方案图节点，超出部分按音频时间延伸）；
        每个音频段按 audio_time_at_beat(seg.start_beat) 处覆盖其源剪辑 [src_start, src_end]，
        未覆盖区域保持静音，实现“段间隙静音”的连续轨道，供播放时单一文件无缝驱动。

        progress_cb 可选：每处理完一个段回调 progress_cb(done, total, name)，
        用于在合成（需解码音频，可能耗时）期间显示进度。

        只读取各音频段的原始源文件（seg.resolve_file()）并写出独立的
        整轨文件（output_path），不修改任何 seg.file / src_start / src_end /
        start_beat，保证音频段始终引用原始源文件、可继续编辑。
        """
        try:
            from pydub import AudioSegment as PydubSegment
        except Exception:
            return False

        total = self.total_beats()
        if total <= 0:
            return False
        # 整轨时长取到音频结束时间（可超出最后方案图节点，超出部分按音频时间延伸）
        total_duration_ms = int(round(self._audio_right_time() * 1000.0))
        if total_duration_ms <= 0:
            return False

        # 底轨统一为 44.1kHz 立体声：各音频段在叠加前也会被转换到该格式，
        # 保证不同采样率/声道的段可正常叠加，且导出的整轨保持较高音质。
        out = PydubSegment.silent(duration=total_duration_ms, frame_rate=44100).set_channels(2)
        n = len(self.audio_segments)
        for i, seg in enumerate(self.audio_segments):
            if progress_cb is not None:
                progress_cb(i + 1, n, Path(seg.file).name)
            try:
                clip = PydubSegment.from_file(seg.resolve_file())
            except Exception:
                continue
            src_lo = int(round(seg.src_start * 1000.0))
            src_hi = int(round(seg.src_end * 1000.0))
            src_lo = max(0, min(src_lo, len(clip)))
            src_hi = max(src_lo, min(src_hi, len(clip)))
            clip = clip[src_lo:src_hi]
            if len(clip) <= 0:
                continue
            # 统一到与静音底轨相同的格式，避免不同采样率/声道段叠加时 overlay 报错
            clip = clip.set_frame_rate(out.frame_rate).set_channels(out.channels)
            pos_ms = int(round(self.audio_time_at_beat(seg.start_beat) * 1000.0))
            pos_ms = max(0, min(pos_ms, len(out)))
            if pos_ms + len(clip) > len(out):
                clip = clip[: len(out) - pos_ms]
            if len(clip) > 0:
                out = out.overlay(clip, position=pos_ms)

        try:
            out.export(str(output_path), format="wav")
        except Exception:
            return False
        return True

    def split_audio_at_beat(self, beat: float) -> bool:
        """在拍位处把音频段切分为两段（双击）。"""
        target = float(beat)
        found = self.audio_segment_at_beat(target)
        if found is None:
            return False
        idx, seg = found
        seg_end = self.audio_segment_end_beat(seg)
        if target <= seg.start_beat + 1e-6 or target >= seg_end - 1e-6:
            return False
        if self.history is not None:
            self.history.begin("切分音频段")
        split_src = self._audio_source_time_at_beat(seg, target)
        left = AudioSegment(
            file=seg.file, src_start=seg.src_start, src_end=split_src,
            start_beat=seg.start_beat,
        )
        right = AudioSegment(
            file=seg.file, src_start=split_src, src_end=seg.src_end,
            start_beat=target,
        )
        self.audio_segments[idx:idx + 1] = [left, right]
        self._audio_selected = idx + 1  # 选中切分后的右侧段
        self._audio_pixmap = None
        self.audioChanged.emit()
        self.update()
        if self.history is not None:
            self.history.commit()
        return True

    def _confirm_delete_audio_dialog(self, seg: AudioSegment) -> bool:
        """弹出删除音频段确认弹窗；用户确认删除返回 True。

        弹窗风格与主窗口“删除点位”保持一致：取消按钮绑定 Esc，
        “删除”按钮绑定 Delete 快捷键（并作为默认按钮支持回车确认）。
        """
        name = Path(seg.file).name
        start = round(seg.start_beat, 2)
        end = round(self.audio_segment_end_beat(seg), 2)
        dlg = QDialog(self)
        dlg.setWindowTitle("删除音频段")
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"确认删除音频段“{name}”？"))
        layout.addWidget(QLabel(f"位置：第 {start} ~ {end} 拍"))
        layout.addWidget(QLabel("删除后不可恢复。"))

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        cancel_btn = QPushButton("取消 Esc", dlg)
        cancel_btn.setShortcut("Esc")
        delete_btn = QPushButton("删除 Delete", dlg)
        delete_btn.setShortcut("Delete")
        delete_btn.setDefault(True)   # 回车 / Enter 也可确认
        delete_btn.setStyleSheet("background:#d9534f;color:white;")
        cancel_btn.clicked.connect(dlg.reject)
        delete_btn.clicked.connect(dlg.accept)
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(delete_btn)
        layout.addLayout(btn_layout)
        dlg.setLayout(layout)
        return dlg.exec() == QDialog.DialogCode.Accepted

    def _delete_audio_by_index(self, idx: int):
        """选中指定音频段并弹出确认弹窗删除；未确认则不删除。"""
        if not (0 <= idx < len(self.audio_segments)):
            return
        if self._confirm_delete_audio_dialog(self.audio_segments[idx]):
            # 删除指定音频段，并同步编辑状态、缓存与外部信号。
            if not (0 <= idx < len(self.audio_segments)):
                return
            if self.history is not None:
                self.history.begin("删除音频段")
            del self.audio_segments[idx]
            # 修正选中索引：删掉的正是选中段 → 无选中；删掉前面的段 → 选中索引前移
            if self._audio_selected == idx:
                self._audio_selected = -1
            elif self._audio_selected > idx:
                self._audio_selected -= 1
            self._audio_selected = max(-1, min(self._audio_selected, len(self.audio_segments) - 1))
            self._audio_pixmap = None
            self._audio_unreadable.clear()
            self.audioChanged.emit()
            self._recalculate_width()   # 删除后最右拍变化 → 重新排布宽度
            self.update()
            if self.history is not None:
                self.history.commit()

    def _delete_selected_audio(self):
        """Delete 快捷键：删除当前选中的音频段（带确认弹窗）。"""
        if 0 <= self._audio_selected < len(self.audio_segments):
            self._delete_audio_by_index(self._audio_selected)

    def _audio_end_beat_at(self, seg: AudioSegment, start_beat: float) -> float:
        """段以 start_beat 起始时的结束拍（按 beat_tempo 反推）。"""
        return self.audio_beat_at_time(
            self.audio_time_at_beat(start_beat) + seg.duration_seconds
        )

    def _audio_move_drop_target(self, from_idx: int, start_beat: float) -> int | None:
        """返回拖拽段（from_idx）落到 start_beat 时与其重叠的其他段索引；无则返回 None。"""
        s0 = float(start_beat)
        s1 = self._audio_end_beat_at(self.audio_segments[from_idx], s0)
        for i, other in enumerate(self.audio_segments):
            if i == from_idx:
                continue
            o1 = self.audio_segment_end_beat(other)
            if s0 < o1 and other.start_beat < s1:
                return i
        return None

    def _audio_swap_armed(self, from_idx: int, target_idx: int, mouse_beat: float) -> bool:
        """鼠标指针是否已超过目标段一半（超过才触发交换，否则松手后自动接在后面）。"""
        tseg = self.audio_segments[target_idx]
        mid = (tseg.start_beat + self.audio_segment_end_beat(tseg)) / 2.0
        if from_idx > target_idx:
            # 从后面（右侧）拖向前面的目标：指针越过目标段中点（向小的一侧）
            return mouse_beat < mid
        # 从前面（左侧）拖向后面的目标：指针越过目标段中点（向大的一侧）
        return mouse_beat > mid

    def _swap_audio_segments(self, from_idx: int, to_idx: int, preview_start: float):
        """段交换：按拖拽方向把拖拽段插到目标段的前面或后面，再按起始拍重排并解决重叠。

        - 拖拽段原本在目标段之后（from_idx > to_idx）：把拖拽段插到目标段前面；
          若预览起始拍早于目标段起始拍（拖过了目标段），则直接用预览起始拍，
          否则用目标段起始拍；目标段自动接在拖拽段之后。
        - 拖拽段原本在目标段之前（from_idx < to_idx）：把拖拽段插到目标段后面；
          后面段（目标段）start_beat 设为前面段（拖拽段）原起始拍；
          被拖拽段优先写到预览起始拍，若该位置已被占用则自动调整到空闲位置。
        之后按起始拍重排列表（保持列表顺序与时间轴顺序一致），
        若有重叠自动将重叠段后移（级联），保证相邻音频不重叠。
        """
        if not (0 <= from_idx < len(self.audio_segments)):
            return
        to_idx = max(0, min(to_idx, len(self.audio_segments) - 1))
        if to_idx == from_idx:
            return
        preview_start = float(preview_start)
        dragged = self.audio_segments[from_idx]     # 拖拽段
        target = self.audio_segments[to_idx]        # 目标段
        if from_idx > to_idx:
            # 拖拽段在后面 → 插到目标段前面
            # 预览起始拍早于目标段起始拍（拖过了目标段）时直接用预览起始拍，否则用目标段起始拍
            dragged.start_beat = min(preview_start, target.start_beat)
            # 目标段自动接在拖拽段后面
            target.start_beat = self._audio_end_beat_at(dragged, dragged.start_beat)
        else:
            # 拖拽段在前面 → 插到目标段后面
            # 后面段（目标段）start_beat 设为前面段（拖拽段）原起始拍
            front_start = dragged.start_beat
            target.start_beat = front_start
            # 被拖拽段先写到预览起始拍：若预览起始拍已被占用，
            # 由后续级联 _resolve_audio_overlaps 自动调整到空闲位置
            dragged.start_beat = preview_start
        # 按起始拍重排，保持列表顺序与时间轴顺序一致
        self.audio_segments.sort(key=lambda s: s.start_beat)
        # 级联解决重叠：重叠段自动后移，保证相邻音频不重叠
        self._resolve_audio_overlaps()
        self._audio_selected = self.audio_segments.index(dragged)
        self._audio_pixmap = None
        self.audioChanged.emit()
        self._recalculate_width()   # 交换后最右拍变化 → 重新排布宽度
        self.update()

    def _resolve_audio_overlaps(self):
        """裁剪结束后若音频段发生重叠，后移重叠段 start_beat 解除重叠。

        左端向左拖拽（延伸）会把当前段 start_beat 提前到与前一音频段重叠，
        此时把重叠段 start_beat 后移到前一段结束拍；结束拍由「起始拍 + 源时长」
        推导，后移会连带右移后续段，循环从左到右自然完成级联修复。
        源选区（src_start/src_end）保持不变，仅调整时间轴位置。
        """
        changed = False
        for i in range(1, len(self.audio_segments)):
            prev = self.audio_segments[i - 1]
            seg = self.audio_segments[i]
            prev_end = self.audio_segment_end_beat(prev)
            if seg.start_beat < prev_end:
                seg.start_beat = prev_end
                changed = True
        if changed:
            self._audio_pixmap = None
            self._recalculate_width()
            self.update()

    # ──────── 音频栏：波形渲染 ────────
    def _beat_to_x_f(self, beat: float) -> float:
        """浮点拍位 -> X 坐标（按拍位 × 每拍像素宽度，即每拍固定宽度，与 tempo 无关）。

        支持负拍：最左拍（_min_axis_beat）对应 _left_padding，负区随之向左展开。
        拍位只在最后方案图节点内有意义；超出节点由 _audio_time_to_x 按音频时间换算。
        """
        total = self.total_beats()
        min_beat = float(self._min_axis_beat())
        if total <= 0 and min_beat >= 0:
            return float(self._left_padding)
        clamped = max(min_beat, min(float(total), float(beat)))
        return self._left_padding + (clamped - min_beat) * self._pixels_per_beat

    def _pixel_to_beat_f(self, px: float) -> float:
        """音频栏内像素 X（相对音频栏左缘）-> 浮点拍位（按每拍固定宽度反推）。

        音频栏左缘对应最左拍（可为负），因此可返回负拍位。
        """
        if self._pixels_per_beat <= 0:
            return 0.0
        return self._min_axis_beat() + px / self._pixels_per_beat

    def _draw_audio_bar(self, p: QPainter):
        if self._audio_rect.isEmpty():
            return
        arect = self._audio_rect
        # 缓存位图按逻辑尺寸比较（需除以 devicePixelRatio），避免高分屏下误判尺寸失效而反复重绘
        pm = self._audio_pixmap
        pm_matches = False
        if pm is not None:
            _d = pm.devicePixelRatioF() or 1.0
            pm_matches = (
                abs(pm.width() / _d - arect.width()) <= 1
                and abs(pm.height() / _d - arect.height()) <= 1
            )
        if not pm_matches:
            # 把当前音频段波形绘制到缓存位图；随缩放/数据变化自动重绘同步显示
            arect = self._audio_rect
            if arect.isEmpty():
                self._audio_pixmap = None
                return
            pix_w = max(1, arect.width())
            pix_h = max(1, arect.height())
            # 高分屏适配：pixmap 按屏幕 devicePixelRatio 创建（QPainter 仍按逻辑坐标绘制），
            # 波形在高 DPI 屏幕上保持清晰；否则 dpr=1 的小位图被拉伸放大后会模糊到几乎看不见。
            dpr = self.devicePixelRatioF() or 1.0
            pm = QPixmap(max(1, int(round(pix_w * dpr))), max(1, int(round(pix_h * dpr))))
            pm.setDevicePixelRatio(dpr)
            pm.fill(QColor("#f0f0f0"))
            # 注意：pixmap 画刷必须用独立变量 pm_painter，不能复用函数参数 p——
            # 否则会覆盖外层窗口画刷，p.end() 后后续所有绘制（按钮/选中框等）
            # 都会落到已结束的画刷上，产生 “QPainter ... Painter not active” 报错。
            pm_painter = QPainter(pm)
            pm_painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
            mid = pix_h / 2.0
            pm_painter.setPen(QPen(QColor("#d5d5d5"), 1))
            pm_painter.drawLine(0, int(mid), pix_w, int(mid))

            bar_left = self._audio_rect.left()
            self._audio_unreadable = set()
            for idx, seg in enumerate(self.audio_segments):
                seg_t0 = self.audio_time_at_beat(seg.start_beat)
                x0 = max(0, int(round(self._beat_to_x_f(seg.start_beat) - bar_left)))
                x1 = min(pix_w, int(round(self._audio_time_to_x(seg_t0 + seg.duration_seconds) - bar_left)))
                if x1 <= x0:
                    continue
                peaks = get_range_peaks(seg.resolve_file(), seg.src_start, seg.src_end)
                if peaks is None or len(peaks) == 0:
                    self._audio_unreadable.add(idx)
                    continue
                # get_range_peaks 返回「段内」峰值数组（下标0对应源文件内 peak_base 桶）。
                # 绘制时必须把全文件桶下标换算为段内下标，否则段 src_start>0（左端裁剪、
                # 切分、或从方案加载）时 i0 会立即越界，导致该段波形一个像素都画不出来。
                peak_base = int(seg.src_start * SAMPLE_RATE) // BUCKET
                max_abs = max(float(peaks[:, 0].max()), float(peaks[:, 1].max()))
                amp = ((pix_h / 2.0) - 2.0) / max(max_abs, 1e-6)
                pm_painter.setPen(QPen(QColor("#1f5e9c"), 1))
                for px in range(x0, x1):
                    # 像素 → 轨道时间：最后一个节点内走 beat 轴，超出后按音频时间无缝延伸
                    t0 = self._audio_x_to_time(bar_left + px)
                    t1 = self._audio_x_to_time(bar_left + px + 1)
                    src_t0 = seg.src_start + (t0 - seg_t0)   # 段内源时间
                    src_t1 = seg.src_start + (t1 - seg_t0)
                    i0 = max(0, int(src_t0 * SAMPLE_RATE) // BUCKET - peak_base)
                    i1 = int(src_t1 * SAMPLE_RATE) // BUCKET + 1 - peak_base
                    if i0 >= len(peaks):
                        continue
                    i1 = min(i1, len(peaks))
                    if i1 <= i0:
                        continue
                    sub = peaks[i0:i1]
                    mn = float(sub[:, 0].min())
                    mx = float(sub[:, 1].max())
                    y0 = int(mid - mx * amp)
                    y1 = int(mid - mn * amp)
                    if y1 < y0:
                        y0, y1 = y1, y0
                    pm_painter.drawLine(px, y0, px, y1)
            pm_painter.end()
            self._audio_pixmap = pm
        if self._audio_pixmap is not None:
            p.drawPixmap(arect.topLeft(), self._audio_pixmap)
        else:
            p.fillRect(arect, QColor("#f0f0f0"))

        p.setPen(QPen(QColor("#aeaeae"), 1))
        p.drawLine(arect.left(), arect.top(), arect.right(), arect.top())

        # 音频栏右侧“导入音频”按钮（无音频段时也需绘制）
        if not self._audio_add_rect.isEmpty():
            br = self._audio_add_rect
            shadow_rect = br.adjusted(1, 2, 1, 2)
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor(0, 0, 0, 38))
            p.drawRoundedRect(shadow_rect, 4, 4)
            p.setPen(QPen(QColor("#1f5e9c"), 1))
            p.setBrush(QColor("#ffffff"))
            p.drawRoundedRect(br, 4, 4)
            btn_font = QFont(self.font())
            btn_font.setPointSize(self._node_font_size)
            p.setFont(btn_font)
            p.setPen(QPen(QColor("#1f5e9c"), 1))
            p.drawText(br, Qt.AlignmentFlag.AlignCenter, "导入音频")

        if not self.audio_segments:
            font = QFont(self.font())
            font.setPointSize(8)
            p.setFont(font)
            p.setPen(QPen(QColor("#9a9a9a"), 1))
            p.drawText(arect, Qt.AlignmentFlag.AlignCenter, "暂无音频 · 点击右侧 “导入音频”")
            return

        # 段边界线
        p.setPen(QPen(QColor("#8a8a8a"), 1))
        for seg in self.audio_segments:
            x = int(round(self._beat_to_x_f(seg.start_beat)))
            p.drawLine(x, arect.top() + 1, x, arect.bottom() - 1)

        # 选中段高亮 + 左右端点手柄
        # 注意：不要用 fillRect 做半透明填充——它在高分屏/特定合成下会被当作不透明，
        # 把下方波形整个盖住。选中指示用蓝边框 + 橙色手柄即可，波形保持可见。
        if 0 <= self._audio_selected < len(self.audio_segments):
            seg = self.audio_segments[self._audio_selected]
            left_x = int(round(self._beat_to_x_f(seg.start_beat)))
            right_x = int(round(self._audio_time_to_x(
                self.audio_time_at_beat(seg.start_beat) + seg.duration_seconds)))
            sel_rect = QRect(left_x, arect.top() + 1, max(1, right_x - left_x), arect.height() - 2)
            p.setPen(QPen(QColor("#1f5e9c"), 2))
            # 重置画刷为 NoBrush：否则 drawRect 会用上一次残留的不透明画刷
            # （“导入音频”按钮填充的白色）填充选中矩形内部，把下方波形盖住。
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(sel_rect)
            # 裁剪手柄绘制
            handle_w = self._audio_handle_w
            for hr in (QRect(left_x - handle_w, arect.top() + 2, handle_w, arect.height() - 4),
                       QRect(right_x, arect.top() + 2, handle_w, arect.height() - 4)):
                p.fillRect(hr, QColor("#f39c12"))
                p.setPen(QPen(QColor("#7a4a00"), 1))
                p.drawRect(hr)

        # 音频文件无法解码的段：显示提示，避免只剩空白灰条却无从排查
        if self._audio_unreadable:
            warn_font = QFont(self.font())
            warn_font.setPointSize(8)
            p.setFont(warn_font)
            p.setPen(QPen(QColor("#c0392b"), 1))
            for idx in sorted(self._audio_unreadable):
                if not (0 <= idx < len(self.audio_segments)):
                    continue
                seg = self.audio_segments[idx]
                wx0 = int(round(self._beat_to_x_f(seg.start_beat)))
                wx1 = int(round(self._audio_time_to_x(
                    self.audio_time_at_beat(seg.start_beat) + seg.duration_seconds)))
                if wx1 <= wx0:
                    continue
                warn_rect = QRect(wx0, arect.top() + 1, max(1, wx1 - wx0), arect.height() - 2)
                p.drawText(warn_rect, Qt.AlignmentFlag.AlignCenter, "音频文件无法读取")

        # 拖拽预览：移动时显示目标位置虚线框
        if self._audio_drag_mode == "move" and 0 <= self._audio_drag_from_idx < len(self.audio_segments):
            seg = self.audio_segments[self._audio_drag_from_idx]
            left_x = int(round(self._beat_to_x_f(self._audio_drag_beat)))
            right_x = int(round(self._audio_time_to_x(
                self.audio_time_at_beat(self._audio_drag_beat) + seg.duration_seconds)))
            drect = QRect(left_x, arect.top() + 1, max(1, right_x - left_x), arect.height() - 2)
            p.setPen(QPen(QColor("#f39c12"), 2, Qt.PenStyle.DashLine))
            p.setBrush(QColor(243, 156, 18, 40))
            p.drawRect(drect)
            p.setBrush(Qt.BrushStyle.NoBrush)

        # 交换目标预览：显示目标段在交换后将移动到的位置
        if (self._audio_drag_mode == "move"
                and 0 <= self._audio_drag_target < len(self.audio_segments)
                and 0 <= self._audio_drag_from_idx < len(self.audio_segments)):
            from_idx = self._audio_drag_from_idx
            dragged = self.audio_segments[from_idx]
            target = self.audio_segments[self._audio_drag_target]
            if from_idx > self._audio_drag_target:
                # 情况①：目标段被推到拖拽段之后（拖拽段结束时间处）
                t0_time = self.audio_time_at_beat(self._audio_drag_beat) + dragged.duration_seconds
            else:
                # 情况②：目标段挪到拖拽段原起始拍
                t0_time = self.audio_time_at_beat(dragged.start_beat)
            t1_time = t0_time + target.duration_seconds
            t_left = int(round(self._audio_time_to_x(t0_time)))
            t_right = int(round(self._audio_time_to_x(t1_time)))
            if t_right > t_left:
                trect = QRect(t_left, arect.top() + 1, max(1, t_right - t_left), arect.height() - 2)
                p.setPen(QPen(QColor("#2980b9"), 2, Qt.PenStyle.DashLine))
                p.setBrush(QColor(41, 128, 185, 40))
                p.drawRect(trect)
                p.setBrush(Qt.BrushStyle.NoBrush)

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

        # 当前拍位游标：超出最后节点的部分按音频时间移动（不用 beat）
        cursor_x = int(round(self._audio_time_to_x(self.audio_time_at_beat(self.current_beat))))
        y_top = self._top_row_y + offset_y
        y_bottom = self._middle_bottom + offset_y
        # if self._expanded and not self._audio_rect.isEmpty():
        #     y_bottom = self._audio_rect.bottom()
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

        # 左侧虚拟 -1 节点：负起始拍位置，仅用于选择播放位置，不做编辑。
        if not self._minus_node_rect.isEmpty():
            mrect = self._minus_node_rect
            p.setPen(QPen(QColor("#7f8c8d"), 1, Qt.PenStyle.DashLine))
            p.setBrush(QColor("#ffffff"))
            p.drawRect(mrect)
            p.setPen(QPen(QColor("#2c3e50"), 1))
            p.drawText(mrect, Qt.AlignmentFlag.AlignCenter, "-1")

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
            pos = event.pos()
            # “导入音频”按钮点击（音频栏右缘外侧）
            if self._expanded and self._audio_add_rect.contains(pos):
                self.importAudioRequested.emit()
                event.accept()
                return
            # 音频栏交互优先：选中/移动/裁剪音频段（含段外侧裁剪手柄）
            if self._expanded and self._audio_hit_rect().contains(pos):
                self._audio_press(pos)
                event.accept()
                return
            # 虚拟 -1 节点：仅用于选择播放位置（负拍），不做编辑；点位显示由场景以节点0呈现。
            # 游标精确对齐到该节点（可为小数拍位），不落在任意负整拍上。
            if not self._minus_node_rect.isEmpty() and self._minus_node_rect.contains(pos):
                self.current_beat = self._minus_node_beat
                self.currentBeatChanged.emit(self.current_beat)
                self.update()
                event.accept()
                return
            # 点击节点：选中节点，并把当前拍位定位到该节点起始拍
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
            # 点击标尺区域，把当前拍位定位到最近的整拍；负拍区游标只能停留在虚拟 -1 节点
            expand_y = self._node_radius * 2
            ruler_hit = self._ruler_rect.adjusted(-2, -expand_y, 2, 14)
            if ruler_hit.contains(pos) or self._tempo_rect.contains(pos):
                beat_f = self._pixel_to_beat_f(pos.x() - self._left_padding)
                if beat_f < 0:
                    # 负拍区不适用 _x_to_beat：游标只能停留在虚拟 -1 节点
                    # （仅选择播放位置，不做编辑），精确对齐该节点（可为小数拍位），
                    # 不落在任意负整拍上。
                    beat = self._minus_node_beat if self._minus_node_beat is not None else 0
                else:
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
        """双击音频栏切分音频段；双击中层非节点拍位时插入新方案图。"""
        if event.button() == Qt.MouseButton.LeftButton:
            pos = event.pos()
            # 音频栏：双击切分音频段
            if self._expanded and self._audio_rect.contains(pos):
                beat = self._pixel_to_beat_f(pos.x() - self._audio_rect.left())
                self.split_audio_at_beat(beat)
                event.accept()
                return
            if self._expanded and self._tempo_rect.contains(pos):
                beat = self._x_to_beat(pos.x())
                if beat < 0:
                    # 负拍区不适用 _x_to_beat：不在此插入速度节点（速度轴与节点 0 对齐）
                    event.accept()
                    return
                if beat in self.beat_tempo:
                    return
                current_bpm = self._bpm_at_beat(float(beat))
                dialog = TempoEditDialog(
                    beat=beat, current_bpm=current_bpm, is_new=True, parent=self,
                    total_beats=self.total_beats(),
                    tempo_keys=sorted(self.beat_tempo.keys()),
                )
                if dialog.exec() == QDialog.DialogCode.Accepted:
                    if self.history is not None:
                        self.history.begin("新增速度节点")
                    self.set_tempo_at_beat(dialog._beat_spin.value(), dialog.get_tempo(), is_new=True)
                    if self.history is not None:
                        self.history.commit()
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

    # ──────── 音频栏交互 ────────
    def _timeline_scroll_area(self):
        """向上查找包裹本控件的滚动区域（TimelineScrollArea）；未包裹时返回 None。"""
        p = self.parent()
        while p is not None:
            if isinstance(p, TimelineScrollArea):
                return p
            p = p.parent()
        return None

    def _reanchor_audio_drag_reference(self):
        """把自动延伸累计并入拖拽参考锚点，从当前手柄位置重新锚定（保留偏移）。

        指针离开自动滚动触发区、或拖拽方向反转（向左压缩）时调用：把
        _auto_scroll_beat_accum 累加的延伸拍位折入 _audio_drag_ref_beat，
        ref_x 更新为当前全局 X、累计清零。这样：
        - 压缩时手柄按“鼠标移动多少压缩多少”增量跟随（保留自动延伸的偏移，
          不会一次回到头）；
        - 再次向右延伸时从当前手柄位置按延伸流程继续（累计已清零、无残留），
          方向门控已改为只看拍位移动方向，故不会出现跳变/死区。
        重锚后 _audio_pointer_beat() 数值连续、无跳变，手柄位置保持不变。
        """
        if self._audio_drag_mode is None:
            return
        self._audio_drag_ref_beat = self._audio_pointer_beat()
        self._audio_drag_ref_x = float(QCursor.pos().x())
        self._auto_scroll_beat_accum = 0.0

    def _auto_scroll_extend(self):
        """持续跟随：时刻向右延伸，滚动速度随鼠标指针在视口内的位置动态调整。

        以鼠标指针为驱动：指针越靠近（或越过）视口右缘，延伸越快。
        - 指针离开触发区或拖拽方向反转（向左压缩）→ 停止延伸并重锚定
          （把累计延伸并入参考锚点，保留偏移），压缩按“鼠标移动多少压缩
          多少”增量跟随，累计量不再残留到下次进入触发区；
        - 指针进入/越过触发区 → 启动定时器持续向右延伸：即使指针不动，
          定时器也会持续推进内容向右、滚动区跟随，速度由指针距右缘距离
          决定（指针越靠右越快）。

        该滚动基于全局鼠标坐标，不受滚动影响，无反馈环路。
        """
        sa = self._timeline_scroll_area()
        if sa is None:
            self._auto_scroll_timer.stop()
            return
        sb = sa.horizontalScrollBar()
        if sb is None:
            self._auto_scroll_timer.stop()
            return
        vp = sa.viewport()
        vw = vp.width()
        # 指针在视口内的 X（全局坐标 → 视口局部，滚动不影响）
        pointer_x = vp.mapFromGlobal(QCursor.pos()).x()
        dist = vw - pointer_x   # >0 在右缘内侧，<=0 在右缘外侧
        # 指针全局 X 方向：向左移动表示拖拽方向反转（右端压缩 / 段左移）
        gx = float(QCursor.pos().x())
        moving_left = gx < self._audio_drag_last_global_x - 1.0
        self._audio_drag_last_global_x = gx
        if dist > self._auto_scroll_zone or moving_left:
            # 指针离开触发区，或拖拽方向反转（向左压缩）时：停止自动延伸并重锚定
            # （把累计延伸并入参考锚点，保留偏移）。压缩时手柄按“鼠标移动多少
            # 压缩多少”增量跟随，不会一次回到头；再次向右延伸时按延伸流程从当前
            # 手柄位置继续（累计已清零、无残留），不会跳到上次最远位置。
            self._auto_scroll_timer.stop()
            self._reanchor_audio_drag_reference()
            return
        # 指针进入/越过触发区：保持定时器持续向右延伸（速度每 tick 重算）
        if not self._auto_scroll_timer.isActive():
            self._auto_scroll_timer.start()

    def _auto_scroll_tick(self):
        """自动滚动定时器 tick：持续推进向右延伸，即使指针不动也会继续。

        按速度因子累加 _auto_scroll_beat_accum（延伸拍位），用它重算拖拽并
        向右滚动相同步长，使内容/拖拽目标随 tick 持续推进；指针不在触发区内
        或拖拽方向反转（向左压缩）时停止定时器并重锚定（常规由 _auto_scroll_extend
        负责停止，本方法为安全网）。
        """
        sa = self._timeline_scroll_area()
        if sa is None:
            self._auto_scroll_timer.stop()
            return
        sb = sa.horizontalScrollBar()
        if sb is None:
            self._auto_scroll_timer.stop()
            return
        vp = sa.viewport()
        vw = vp.width()
        pointer_x = vp.mapFromGlobal(QCursor.pos()).x()
        dist = vw - pointer_x
        # 方向反转（压缩）安全网：定时器仍在运行但指针已向左移动时停止并重锚，
        # 避免累计延伸把拍位持续推大、压缩被阻断
        gx = float(QCursor.pos().x())
        moving_left = gx < self._audio_drag_last_global_x - 1.0
        self._audio_drag_last_global_x = gx
        if dist > self._auto_scroll_zone or moving_left:
            self._auto_scroll_timer.stop()
            self._reanchor_audio_drag_reference()
            return
        speed = 1.0 - min(1.0, max(0.0, dist / self._auto_scroll_zone))
        step = max(1, int(round(self._auto_scroll_max_step * speed)))
        # 推进延伸：累计拍位与滚动同步前进（指针不动也持续推进）
        self._auto_scroll_beat_accum += step / self._pixels_per_beat
        # 用最新累计延伸重算拖拽（move 预览 / right 裁剪实时生效），使内容随延伸增长
        if (self._audio_drag_mode is not None and self._expanded
                and 0 <= self._audio_drag_from_idx < len(self.audio_segments)):
            self._apply_audio_drag(self._audio_pointer_beat())
        sb.setValue(max(sb.minimum(), min(sb.maximum(), sb.value() + step)))
        self.update()

    def _begin_audio_undo(self):
        """音频拖拽会话开始（撤销/重做：按下→松开视为一步）。"""
        if self.history is not None:
            self.history.begin("音频编辑")

    def _finish_audio_undo(self, changed: bool):
        """音频拖拽会话结束：真正发生变化则提交为一步，否则取消。"""
        if self.history is None:
            return
        if changed:
            self.history.commit()
        else:
            self.history.cancel()

    def _audio_press(self, pos: QPoint):
        """音频栏左键按下：切换当前编辑段，或开始拖拽（移动/裁剪）。"""
        self._audio_drag_mode = None
        self._audio_drag_from_idx = -1
        self._audio_drag_orig = None
        self._audio_drag_grab_offset = 0.0
        self._audio_drag_target = -1
        self._auto_scroll_timer.stop()       # 新拖拽会话：停止可能残留的自动滚动
        self._auto_scroll_beat_accum = 0.0   # 新拖拽会话：清除自动延伸累计
        # 起始拍快照：right 拖拽时后续段以“原位置”为下限，重叠解除后可回原位
        self._audio_drag_orig_starts = [float(s.start_beat) for s in self.audio_segments]
        x = float(pos.x())
        beat = self._pixel_to_beat_f(x - self._audio_rect.left())
        # 拖拽参考锚点：按下时的“全局（屏幕）像素 X”与鼠标拍位。
        # 拖拽中拍位 = 锚点拍位 + 全局位移 / 每拍像素，使拍位计算独立于轴扩展
        # 与自动滚动（滚动时控件在鼠标下移动、局部坐标会变，全局坐标保持稳定），
        # 避免 _min_axis_beat / 滚动导致的“拍位↔像素”映射反馈环路。
        self._audio_drag_ref_x = float(self.mapToGlobal(pos).x())
        self._audio_drag_ref_beat = beat
        self._audio_drag_prev_beat = beat   # 裁剪方向门控：按下时拍位作为初始方向基准
        self._audio_drag_last_global_x = float(self.mapToGlobal(pos).x())

        # 裁剪手柄优先（裁剪 > 切换）：手柄绘制在音频段外侧，
        # 先命中当前选中段的外侧手柄再进入裁剪，避免点击外侧手柄时
        # 被 audio_segment_at_beat 命中相邻音频段而误切换选中。
        handle_w = self._audio_handle_w
        if 0 <= self._audio_selected < len(self.audio_segments):
            seg = self.audio_segments[self._audio_selected]
            left_x = self._beat_to_x_f(seg.start_beat)
            right_x = self._audio_time_to_x(
                self.audio_time_at_beat(seg.start_beat) + seg.duration_seconds)
            if left_x - handle_w <= x <= left_x:
                # 左端拖拽裁剪：右端固定（src_end 不变），按当前显示范围对齐
                self._audio_drag_mode = "left"
                self._audio_drag_from_idx = self._audio_selected
                self._audio_drag_orig = (seg.src_start, seg.src_end, seg.start_beat)
                self._begin_audio_undo()
                self.update()
                return
            # 右端拖拽裁剪（基于原曲节选，固定 src_start）。
            # 命中范围向右延伸一个 _audio_handle_w（手柄绘制在段右端外侧），
            # 源音频后续仍有内容时可把段右端拖到音频栏更靠右的位置。
            if right_x <= x <= right_x + handle_w * 2:
                self._audio_drag_mode = "right"
                self._audio_drag_from_idx = self._audio_selected
                self._audio_drag_orig = (seg.src_start, seg.src_end, seg.start_beat)
                self._begin_audio_undo()
                self.update()
                return

        found = self.audio_segment_at_beat(beat)
        if found is None:
            self._audio_selected = -1
            self.update()
            return
        idx, seg = found
        # 左键点击切换当前编辑的音频段；段内按下进入移动（重新排序）模式。
        # 记录点击点相对段起始拍的偏移（抓取点）：拖拽时预览框按该偏移跟随鼠标，
        # 保持抓取点不跳变（而不是把预览框中心对准鼠标指针）。
        self.setFocus()   # 聚焦时间轴，使 Delete 快捷键删除该选中段生效
        self._audio_selected = idx
        self._audio_drag_mode = "move"
        self._audio_drag_from_idx = idx
        self._audio_drag_orig = (seg.src_start, seg.src_end, seg.start_beat)   # 拖拽前快照，用于松开时判断是否真正变化
        seg_len = self.audio_segment_end_beat(seg) - seg.start_beat
        self._audio_drag_grab_offset = max(0.0, min(beat - seg.start_beat, seg_len))
        self._audio_drag_beat = seg.start_beat
        self._begin_audio_undo()
        self.update()

    def _audio_pointer_beat(self) -> float:
        """当前鼠标指针在时间轴上的有效拍位。

        用按下时的固定锚点（_audio_drag_ref_x / _audio_drag_ref_beat）加全局位移
        反推，独立于轴扩展与滚动（自动滚动时控件会在鼠标下移动，局部坐标会变，
        全局坐标保持稳定），避免“拍位↔像素”映射反馈环路。
        返回指针拍位 + 自动延伸累计（_auto_scroll_beat_accum）：指针进入触发区
        后，即使指针不动，累计延伸也会持续推进有效拍位向右。
        """
        return (
            self._audio_drag_ref_beat
            + (QCursor.pos().x() - self._audio_drag_ref_x) / self._pixels_per_beat
            + self._auto_scroll_beat_accum
        )

    def _apply_audio_drag(self, beat: float):
        """按有效拍位应用当前拖拽：move 预览 / left/right 实时裁剪并同步波形。

        供鼠标移动（_audio_drag_update）与自动延伸定时器（_auto_scroll_tick）
        共用，保证自动延伸期间预览/裁剪与鼠标拖拽表现一致。
        """
        if self._audio_drag_mode == "move":
            seg = self.audio_segments[self._audio_drag_from_idx]
            # 预览框起始拍 = 有效拍位 - 抓取点偏移：跟随点击时的抓取点，而非以鼠标为中心
            # 允许负拍：拖入音乐前导区（start_beat < 0）以支持“音乐先起、队形后动”。
            self._audio_drag_beat = beat - self._audio_drag_grab_offset
            # 交换目标：预览框重叠的段，且鼠标指针已超过该段一半（超过才交换）
            self._audio_drag_target = -1
            target = self._audio_move_drop_target(self._audio_drag_from_idx, self._audio_drag_beat)
            if target is not None and self._audio_swap_armed(self._audio_drag_from_idx, target, beat):
                self._audio_drag_target = target
            self._recalculate_width()   # 拖入负区时轴向左展开，预览即时可见
            self.update()
            return
        seg = self.audio_segments[self._audio_drag_from_idx]
        orig = self._audio_drag_orig
        if orig is None:
            return
        orig_src_start, orig_src_end, orig_start = orig
        # 最小长度 0.5 秒（换算为拍，按起始拍处节拍速度）
        min_len = max(1.0, 0.5 / self._seconds_per_beat_at(int(orig_start)))
        if self._audio_drag_mode == "left":
            # 左端拖拽：右端固定（end_beat 不变、src_end 不变），按“当前显示范围”锚定——
            # 保持当前显示内容 [seg.src_start, seg.src_end] 与其拍位映射不变，
            # 只调整左端（src_begin 与 start_beat），扩展/裁剪均在左侧进行。
            # 用当前 seg 值做“增量”计算（而非按下快照 orig），并配合 audio_time_at_beat
            # 对轴左缘左侧负拍的线性外推，避免轴向左展开（min_beat 重锚）导致
            # src_start 滞后、start_beat 乱跳（负区左端裁剪）。
            # 方向判定：只看拍位移动方向（不再用指针内外侧像素判断）。手柄需严格
            # 跟随指针的移动量（鼠标移动多少、左缘就延伸/收缩多少），去掉内外侧
            # 门控后，压缩与再次延伸都能连续跟随，不会因保留自动延伸偏移而出现
            # “先保持不动、指针追上手柄后突然跳到最远位置”的跳变。
            if not (
                beat < self._audio_drag_prev_beat     # 左移 → 延伸
                or beat > self._audio_drag_prev_beat  # 右移 → 收缩
            ):
                self._audio_drag_prev_beat = beat
                return
            right_edge = self.audio_segment_end_beat(seg)
            new_start = min(beat, right_edge - min_len)
            new_src_start = seg.src_start - (
                self.audio_time_at_beat(seg.start_beat) - self.audio_time_at_beat(new_start)
            )
            if new_src_start < 0:
                # 左端源内容已到达文件头：src_begin 夹到 0，右端仍固定，重推 start_beat
                new_src_start = 0.0
                new_start = self.audio_beat_at_time(
                    self.audio_time_at_beat(right_edge) - seg.src_end
                )
            seg.src_start = new_src_start
            seg.start_beat = new_start
        else:  # right
            # 方向判定：只看拍位移动方向（不再用指针内外侧像素判断）。手柄需严格
            # 跟随指针的移动量（延伸/压缩均按“鼠标移动多少、右缘就移动多少”），
            # 去掉内外侧门控后，压缩与再次延伸都能连续跟随，不会出现“先保持不动、
            # 指针追上手柄后突然跳到最远位置”的跳变。
            if not (
                beat > self._audio_drag_prev_beat     # 右移 → 延伸
                or beat < self._audio_drag_prev_beat  # 左移 → 收缩
            ):
                self._audio_drag_prev_beat = beat
                return
            new_end = max(orig_start + min_len, beat)
            new_src_end = orig_src_start + (
                self.audio_time_at_beat(new_end) - self.audio_time_at_beat(orig_start)
            )
            dur = audio_duration(seg.file)
            if new_src_end > dur:
                new_src_end = dur
                new_end = self.audio_beat_at_time(
                    self.audio_time_at_beat(orig_start) + (dur - orig_src_start)
                )
            seg.src_end = new_src_end
            # 后续音频段不自动吸附：每个后续段 start_beat = max(原位置, 前一段结束拍)。
            # 拖拽段缩短（不重叠）时后续段回到原位置；仅在发生重叠时才后移重叠段，
            # 且只后移不提前（推移后 start_beat 最小为原值）。       
                
            # 右端拖拽后重新铺排后续段：每个后续段 start_beat = max(原位置, 前一段结束拍)。
            # 后续段不自动吸附：拖拽段缩短（不重叠）时后续段回到原位置；
            # 仅在拖拽段右端与后续段发生重叠时后移重叠段，且只后移不提前（最小为原值）。
            # 原位置取自 _audio_press 时的起始拍快照 _audio_drag_orig_starts。
            b = new_end   # 拖拽段新结束拍，作为第一个后续段的“前一段结束拍”
            for i in range(self._audio_drag_from_idx + 1, len(self.audio_segments)):
                seg = self.audio_segments[i]
                orig = self._audio_drag_orig_starts[i]
                seg.start_beat = max(orig, b)
                b = self.audio_segment_end_beat(seg)
        self._audio_drag_prev_beat = beat   # 记录本次有效拍位，供下次方向门控判断
        self._recalculate_width()   # 裁剪使最左拍变化时轴向左展开
        self._audio_pixmap = None
        self.update()

    def mouseMoveEvent(self, event):
        if self._audio_drag_mode is not None:
            # 拖拽中持续更新：按下时 Qt 已捕获鼠标，光标移出音频栏（向左进入
            # 负拍区等）也能继续跟随，拖拽预览随像素平滑移动、无整拍跳变。
            if self._expanded:
                """音频栏拖拽中更新：move 预览 / left/right 实时裁剪并同步波形。"""
                # 拖拽一律用“全局（屏幕）坐标”锚点反推拍位，而不是局部坐标；
                # 有效拍位 = 指针拍位 + 自动延伸累计（指针不动时累计持续推进向右）。
                self._apply_audio_drag(self._audio_pointer_beat())
                # 持续跟随：指针贴近/越过右缘时滚动区持续向右延伸，速度随指针位置变化
                self._auto_scroll_extend()
                event.accept()
                return
            return
        # 鼠标追踪开启后，移出音频栏也会触发本事件，
        # 因此始终调用悬停更新，以便移出手柄时能重置光标。
        # 悬停时对选中段端点手柄显示左右双向箭头光标。
        # 每次先重置光标，避免鼠标移出手柄/音频栏后残留旧光标。
        pos = event.pos()
        self.unsetCursor()
        if not (0 <= self._audio_selected < len(self.audio_segments)):
            return
        if not (self._expanded and self._audio_hit_rect().contains(pos)):
            return
        seg = self.audio_segments[self._audio_selected]
        x = float(pos.x())
        left_x = self._beat_to_x_f(seg.start_beat)
        right_x = self._audio_time_to_x(
            self.audio_time_at_beat(seg.start_beat) + seg.duration_seconds)
        handle_w = self._audio_handle_w
        # 与裁剪手柄绘制（段外侧）保持一致：左手柄/右手柄外侧区域显示双向箭头。
        # 右手柄命中范围向右延伸一个 _audio_handle_w，与 _audio_press 保持一致。
        if (left_x - handle_w <= x <= left_x
                or right_x <= x <= right_x + handle_w * 2):
            self.setCursor(QCursor(Qt.CursorShape.SizeHorCursor))
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._audio_drag_mode is None:
            super().mouseReleaseEvent(event)
            return
        mode = self._audio_drag_mode
        idx = self._audio_drag_from_idx
        orig = self._audio_drag_orig          # 拖拽前快照，用于判断是否真正发生了变化
        accum = self._auto_scroll_beat_accum  # 自动延伸累计：松开时用于有效拍位计算
        self._audio_drag_mode = None
        self._audio_drag_from_idx = -1
        self._audio_drag_orig = None
        self._audio_drag_target = -1
        self._auto_scroll_timer.stop()          # 拖拽结束：停止自动向右滚动
        self._auto_scroll_beat_accum = 0.0      # 清除自动延伸累计（下次拖拽重新计算）
        self.unsetCursor()
        if not self._expanded or not self.audio_segments or not (0 <= idx < len(self.audio_segments)):
            self._finish_audio_undo(False)
            self.update()
            return
        if mode == "move":
            seg = self.audio_segments[idx]
            # 将预览位置写回：
            # - 预览框不与其他段重叠 → 自由摆放到任意拍位（start_beat = 预览起始拍）
            # - 预览框与其他段重叠：
            #   · 鼠标指针已超过目标段一半 → 段交换（按拖拽方向插到目标段前/后）
            #   · 否则 → 自动接在目标段后面
            preview_start = self._audio_drag_beat
            # 无实际拖拽（仅点击选中后原地松开）：预览起始拍 == 原起始拍 → 不写回、不发信号，
            # 避免误触发重新合成/标记未保存
            no_move = orig is not None and abs(preview_start - orig[2]) < 1e-9
            # 与拖拽中一致：用固定锚点反推松开时的有效拍位（全局坐标，不受轴扩展/滚动影响），
            # 自动延伸期间需加上累计延伸，使“是否越过目标段一半”的判断与拖拽预览一致
            mouse_beat = self._audio_drag_ref_beat + (
                event.globalPosition().x() - self._audio_drag_ref_x
            ) / self._pixels_per_beat + accum
            # Ctrl+松开 → 复制模式：保留原段不动，在预览位置生成一份副本。
            # 无实际拖拽（仅点击原地松开）时不复制，避免在相同位置凭空多出一段。
            if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
                if no_move:
                    self._finish_audio_undo(False)
                    self.update()
                    return
                new_seg = AudioSegment(
                    file=seg.file,
                    src_start=seg.src_start,
                    src_end=seg.src_end,
                    start_beat=preview_start,
                )
                self.audio_segments.append(new_seg)
                self.audio_segments.sort(key=lambda s: s.start_beat)
                self._resolve_audio_overlaps()
                self._audio_selected = self.audio_segments.index(new_seg)
                self._recalculate_width()
                self._audio_pixmap = None
                self.audioChanged.emit()
                self.update()
                self._finish_audio_undo(True)
                return
            if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                # Shift+松开 → 整体平移：以拖拽段为基准，把「所有」音频段整体平移
                # 相同的偏移量（等于拖拽段移动的距离），各段相对位置保持不变。
                # 允许整体移入负区（音乐前导区）。
                if no_move:
                    self._finish_audio_undo(False)
                    self.update()
                    return
                orig_start = orig[2] if orig is not None else seg.start_beat
                delta = preview_start - orig_start
                for s in self.audio_segments:
                    s.start_beat += delta
                self._recalculate_width()
                self._audio_pixmap = None
                self.audioChanged.emit()
                self.update()
                self._finish_audio_undo(True)
                return
            target = self._audio_move_drop_target(idx, preview_start)
            if target is not None and self._audio_swap_armed(idx, target, mouse_beat):
                self._swap_audio_segments(idx, target, preview_start)
            elif target is not None:
                # 未超过目标段一半 → 自动接在目标段后面（不交换）
                new_start = self.audio_segment_end_beat(self.audio_segments[target])
                if no_move and abs(new_start - orig[2]) < 1e-9:
                    self._finish_audio_undo(False)
                    self.update()
                    return
                seg.start_beat = new_start
                self.audio_segments.sort(key=lambda s: s.start_beat)
                self._resolve_audio_overlaps()
                self._audio_selected = self.audio_segments.index(seg)
                self._audio_pixmap = None
                self.audioChanged.emit()
            else:
                # 自由摆放：直接写回预览起始拍，并按起始拍重排保持列表与时间轴一致
                if no_move:
                    self._finish_audio_undo(False)
                    self.update()
                    return
                seg.start_beat = preview_start
                self.audio_segments.sort(key=lambda s: s.start_beat)
                self._audio_selected = self.audio_segments.index(seg)
                self._audio_pixmap = None
                self.audioChanged.emit()
            self._recalculate_width()   # 起始拍变化后按最左拍重新排布宽度
            self.update()
            self._finish_audio_undo(True)
        else:  # left / right：拖拽已实时生效，释放时通知变化
            seg = self.audio_segments[idx]
            changed = orig is None or (seg.src_start, seg.src_end, seg.start_beat) != orig
            # 裁剪后若与相邻段重叠，自动后移 start_beat 解决重叠
            self._resolve_audio_overlaps()
            if changed:
                self._audio_pixmap = None
                self.audioChanged.emit()
            self._recalculate_width()
            self.update()
            self._finish_audio_undo(changed)

    def contextMenuEvent(self, event):
        """右键节点弹出设置窗口：修改间隔拍数或删除该节点。"""
        pos: QPoint = event.pos()

        # 右键音频栏：选中该音频段并弹出删除确认弹窗
        if self._expanded and self._audio_hit_rect().contains(pos):
            beat = self._pixel_to_beat_f(pos.x() - self._audio_rect.left())
            found = self.audio_segment_at_beat(beat)
            if found is not None:
                idx, _seg = found
                self.setFocus()          # 确保随后 Delete 快捷键作用于时间轴
                self._audio_selected = idx
                self.update()
                self._delete_audio_by_index(idx)
            return

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
                if self.history is not None:
                    self.history.begin("修改速度节点")
                new_beat = dialog._beat_spin.value()
                if dialog.delete_requested:
                    self.delete_tempo_at_beat(new_beat)
                else:
                    self.set_tempo_at_beat(new_beat, dialog.get_tempo(), is_new=False, old_beat=key)
                if self.history is not None:
                    self.history.commit()
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
                if self.history is not None:
                    self.history.begin("修改速度节点")
                new_beat = dialog._beat_spin.value()
                if dialog.delete_requested:
                    self.delete_tempo_at_beat(new_beat)
                else:
                    self.set_tempo_at_beat(new_beat, dialog.get_tempo(), is_new=False, old_beat=key)
                if self.history is not None:
                    self.history.commit()
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
                        self.delete_node(i)   # delete_node 内部自行记录撤销步骤
                    else:
                        if self.history is not None:
                            self.history.begin("修改节点间隔")
                        self.graph_list[i] = dialog.get_interval_value()
                        self._recalculate_width()
                        self.timelineChanged.emit()
                        self.update()
                        self._switch_next()
                        if self.history is not None:
                            self.history.commit()
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
            self._audio_pixmap = None   # 缩放后波形显示同步
            self.update()
            event.accept()
            return

        super().wheelEvent(event)
