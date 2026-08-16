"""
绘制方案图
"""
import math
from pathlib import Path
import copy

from PyQt6.QtWidgets import (
    QApplication,
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal, QMarginsF
from PyQt6.QtGui import QBrush, QColor, QPainter, QPainterPath, QPen, QPolygonF, QFont, QPdfWriter, QPageSize, QPageLayout

from src.field_info import FieldInfo, ZOOM_PERCENT_FACTOR
from src.field_renderer import GridRenderer
from src.scene_items import PerformerPointItem, ReferenceHandleItem, MovementControlHandleItem, TextBoxItem, ArrowItem
from src.scheme_scene_data import SchemeSceneData
from src.draw_utils import (
    _distance,
    _sample_polyline_points,
    _sample_polyline_points_with_count,
    _sample_polyline_points_with_count_and_spacing,
    _sample_curve_points,
    _build_dense_curve_points,
    _sample_closed_polyline_points_with_spacing,
    _sample_closed_polyline_points_with_count,
    _make_polygon_points,
    _circumcenter,
    _arc_path_from_three_points,
    _sample_arc_points,
    _sample_arc_points_with_count,
    _sample_arc_points_with_count_and_spacing,
    _sample_rectangle_fill_points_with_counts,
    _enforce_sampling_auto_rule,
    _enforce_sampling_shift_auto_rule,
    _sample_circle_points,
    _sample_circle_points_with_count,
    _append_unique_reference_point,
    _bilinear_point,
    _rotate_vector,
    _field_rotate_point,
    sample_on_polyline,
    _calc_interval_beats
)

# distance helper imported from scheme_helpers

class SchemeScene(SchemeSceneData, QGraphicsScene):
    """主绘图场景：管理节点点位、图形草稿与渲染。"""
    # 通知主窗口更新“绘制控制台”状态，替代阻塞式弹窗。
    draftStarted = pyqtSignal(str)  # 工具名称
    draftFinished = pyqtSignal()    # 无参数，表示草稿结束（确认或取消）
    dataChanged = pyqtSignal()      # 已确认的数据发生变化
    selectedPointsChanged = pyqtSignal(int) # 当前选中点位数量
    drawingRematchStateChanged = pyqtSignal()   # 绘图重匹配状态变化时刷新控制台按钮
    textBoxSelectionChanged = pyqtSignal(object)  # 文本框选择变化（当前选中文本框ID，未选中为 None）
    
    samplingPointCountChanged = pyqtSignal(str, int)    # 工具名称和采样点位数量
    samplingSpacingChanged = pyqtSignal(str, float)     # 工具名称和采样间距
    
    samplingShiftSpacingChanged = pyqtSignal(str, float)    # 工具名称和Shift状态下采样间距
    samplingShiftPointCountChanged = pyqtSignal(str, int)   # 工具名称和Shift状态下采样点位数量

    _single_click_tools = {"点", "线段", "弧", "填充四边形", "圆", "多边形"}

    def __init__(self, parent=None):
        super().__init__(parent)
        # 场地参数与网格绘制器。
        self.field_info = FieldInfo(self)
        self.grid_renderer = GridRenderer(self.field_info)  # 场地网格绘制器，依赖场地参数进行绘制。
        self.field_info.changed.connect(self._on_field_settings_changed)    # 场地参数变化时刷新场景显示。
        
        self._current_items = []    # 当前显示的点位图元列表，用于快速清除与重建。每次切换节点或工具时会重建。
        self._previous_items = []   # 上一个节点的点位图元列表，仅在切换节点时保留；切换工具时会立即清除。
        self._label_items = []      # 当前显示的标签图元列表，用于快速清除与重建。每次切换节点或工具时会重建。
        self._selected_point_ids = set()    # 当前选中的点位ID集合，用于批量操作和分组等功能
        self.history = None         # 撤销/重做管理器（由 MainWindow 注入）；用于点位拖拽等操作的会话记录
        
        self.setup_scene_data()     # 初始化场景数据结构
        self._draft_tool_name = None    # 当前正在使用的绘图工具名称，None表示无草稿状态；非None表示草稿状态，值为对应工具名称。
        self._draft_reference_points = []   # 当前绘图草稿的参考点坐标列表
        self._draft_preview_items = []      # 当前绘图草稿的预览图元列表
        self._pending_preview_items = []    # 当前未确认阶段的参考线预览图元列表（如曲线/折线工具在输入至少2个点位后的实时预览）
        self._draft_handle_items = []       # 当前绘图草稿的可拖动参考点图元列表（如曲线/折线工具在输入至少2个点位后的可调整参考点）
        self._pending_points = []           # 当前工具操作中尚未提交的数据点位列表，如绘制中的线段或多边形顶点等
        
        self._adjustment_active = False     # 当前是否处于 “调整” 会话中
        self._adjustment_mode = "比例"      # 调整模式：比例、伸展、倾斜、歪曲
        self._adjustment_rotation = 0.0      # 调整角度（度）
        self._adjustment_source_points = []   # 调整会话开始时的原始点位快照
        self._adjustment_preview_points = []   # 当前调整预览点位（用于渲染，不直接写回）
        self._adjustment_center = QPointF(0.0, 0.0)  # 调整参考框中心（field 坐标）
        self._adjustment_center_handle = QPointF(0.0, 0.0)  # 调整中心手柄位置（field 坐标）
        self._adjustment_preview_line_items = []  # 选中点 原始->预览 线段
        self._adjustment_half_size = QPointF(1.0, 1.0)  # 调整参考框半宽/半高（field 坐标）
        self._adjustment_corners_local = []  # 调整参考框四角的局部坐标（相对中心，未旋转）
        self._adjustment_frame_item = None   # 调整参考框图元
        self._adjustment_handle_items = []   # 调整参考框角点与中心点图元
        self._updating_adjustment_handles = False  # 是否正在同步调整手柄位置
        self._adjustment_drag_state = None   # 调整句柄拖拽快照，用于按拖拽起点计算相对位移
        self._drawing_rematch_state = {
            "active": False,
            "cursor": 0,
            "history": [],
            "preview_to_point": {},
            "point_to_preview": {},
            "candidate_point_id": None,
        }
        # 曲线模式：'polyline' 或 'curve'，默认为折线(polyline)
        self._curve_mode = 'polyline'
        self._sampling_tools = {"线段", "弧", "曲线/折线", "圆", "多边形", "填充四边形"}
        self._sampling_defaults = {
            "point_count": 1,
            "point_count_manual": False,
            "spacing_steps": 2.0,
            # 默认：点位个数自动，间距为手动（默认两步）
            "spacing_manual": True,
            "point_count_shift": 1,
            "point_count_shift_manual": False,
            "spacing_steps_shift": 2.0,
            "spacing_shift_manual": True,
            "polygon_sides": 6,
        }
        self._sampling_settings = {
            tool_name: dict(self._sampling_defaults)
            for tool_name in self._sampling_tools
        }
        self._updating_draft_handles = False    # 标记当前是否正在批量更新草稿参考点手柄位置，以避免在更新过程中触发不必要的回调与重绘。
        self._selection_rect_item = None        # 框选工具的选区矩形图元，随鼠标拖动动态调整位置与大小；仅在框选工具激活时存在，切换工具时会被清除。
        self._selection_start_position = None      # 框选工具的起始场景坐标，记录鼠标按下时的位置，用于计算选区矩形；仅在框选工具激活时有效，切换工具时会被清除。
        self._selection_current_position = None    # 框选工具的当前场景坐标，记录鼠标拖动时的位置，用于计算选区矩形；仅在框选工具激活时有效，切换工具时会被清除。
        self._selection_link_items = []     # 选中点位之间的连线图元，仅连接每个组内被选中的点。
        # 临时分组编辑状态（由 DrawingControlDock 驱动）
        self._temp_group_to_point: list[list[int]] = [[]]  # 临时分组点位列表
        self._temp_group_current_index = 0
        self._temp_group_mark_head: bool = True  # True=默认在 tail 之后插入（用户偏好标记）
        self._temp_group_line_items = []  # 临时分组连线图元
        self._temp_group_helper_items = []  # 临时分组用的 helper 圆圈图元
        self._follow_group_helper_items = []  # 跟随工具用的 group 首尾 helper 圆圈图元
        self._interval_helper_items = {}    # 间隔工具用的 helper 拖拽手柄图元 {point_id: QGraphicsEllipseItem}
        self._interval_anchor_id = None     # 间隔行进锚点 ID
        self._interval_drag_position = None  # 当前拖拽中锚点的 field 坐标 (x, y)，仅拖拽中有效，不写入 node_points
        self._interval_dragging = False      # 是否正在拖拽间隔行进 helper
        self._rotate_angle = 0.0             # 旋转工具当前角度（度）
        self._rotate_center_point = (0.0, 0.0)  # 旋转中心点 field 坐标
        self._rotate_helper_items = []       # 旋转工具用的旋转中心 helper 图元
        self._rotate_dragging = False        # 是否正在拖拽旋转中心 helper
        self._rotate_source_points = []      # 旋转工具初始点位快照（用于预览）
        self._rematch_helper_items = []     # 绘图重匹配时的原点位辅助选择圈图元
        self._point_items_by_id = {}    # 当前显示的点位图元字典，key为点位ID，value为对应的 PerformerPointItem 图元；用于快速定位与更新特定点位的图元。
        self._label_items_by_id = {}    # 当前显示的标签图元字典，key为点位ID，value为对应的 QGraphicsSimpleTextItem 图元；用于快速定位与更新特定点位的标签图元。
        
        self._textbox_items = []    # 当前显示的文本框图元列表
        self._textbox_items_by_id = {}  # 当前显示的文本框图元字典
        self._textbox_handle_items = [] # 文本框参考点手柄（对角点）
        self._textbox_hover_scene_pos = None  # 文本工具第一参考点后的鼠标吸附位置（scene 坐标）
        self._textbox_preview = []  # 文本工具下的文本框预览副本
        self._textbox_pending_points = []  # 文本工具创建文本框时的待确认两点
        self._selected_textbox_id = None   # 当前选中的预览文本框ID
        self._textbox_font_size = 8   # 文本工具默认字号

        # 箭头工具状态
        self._arrow_preview = []  # node_arrows 副本，当前编辑中的箭头列表
        self._arrow_editing_index = 0  # 当前编辑的箭头在预览列表中的索引
        self._arrow_pending_points = []  # 箭头绘制草稿参考点列表
        self._arrow_items = []  # 当前显示的 ArrowItem 图元列表
        self._arrow_handle_items = []  # 箭头参考点手柄列表
        self._arrow_draft_preview_items = []  # 箭头草稿预览线图元列表
        self._updating_arrow = False  # 箭头更新中标志，防止递归

        # 固定为启动时的初始场景大小，避免新增图元导致 sceneRect 自动变化。
        initial_field_rect = self.field_info.field_rect
        self.setSceneRect(initial_field_rect)
        
        self.export_ratio = 3.0   # 导出时的放大倍数，默认3倍。
        
        # 上一点位的绘制参数（用于预览上一节点的点位）
        self.pre_point_radius = 2.0
        self.pre_point_color = QColor("#444444")  # alpha 值控制透明度（0-255，值越大越不透明）
        
        # 点位label绘制参数
        self.label_color = QColor("#000000")
        self.label_size = 12    # label 字体大小
        self.label_offset = 15  # label 相对于点位的距离
        self.label_pos = 90     # label 相对于点位的角度，上限为360°，默认90°（下侧）
        
        #点位修改的参数
        self.helper_radius = 12


    def _reset_adjustment_state(self, reset_controls: bool = True):
        """重置调整会话状态与图元；可选是否同时重置模式与角度。"""
        self._clear_adjustment_items()
        self._adjustment_active = False
        self._adjustment_drag_state = None
        self._adjustment_source_points = []
        self._adjustment_preview_points = []
        self._adjustment_center = QPointF(0.0, 0.0)
        self._adjustment_center_handle = QPointF(0.0, 0.0)
        self._adjustment_preview_line_items = []
        self._adjustment_half_size = QPointF(1.0, 1.0)
        self._adjustment_corners_local = []
        if reset_controls:
            self._adjustment_mode = "比例"
            self._adjustment_rotation = 0.0

    def _on_field_settings_changed(self):
        """场地配置变化后刷新场景绘制。"""
        self._render_points_for_active_node()
        self.update()

    def set_preview_sub_beat(self, beat_float: float):
        """按浮点拍位渲染 sub-beat 预览（仅供播放演示，不写回数据、不触发 dataChanged）。"""
        beat_float = max(0.0, float(beat_float))
        total_beats = sum(self.parent().timelineMainWidget.graph_list[1:]) if self.parent() is not None else 0
        if total_beats > 0:
            beat_float = min(beat_float, float(total_beats))
        # 不修改 self.preview_beat（保持当前编辑状态不变）
        self._render_points_for_sub_beat(beat_float)
        self.update()

    def _render_points_for_sub_beat(self, beat_float: float):
        """按浮点拍位重建点位图元（不改变内部状态，仅渲染）。"""
        self._clear_overlay_items()

        # ── 1) 手动查找 beat_float 所在的区间（包容左边界，支持 sub-beat） ──
        starts = [self._node_start_beat(i) for i in range(len(self.node_points))]
        left_node = None
        right_node = None
        for left in range(len(starts) - 1):
            if starts[left] <= beat_float < starts[left + 1]:
                left_node, right_node = left, left + 1
                break

        # ── 2) 精确命中节点起始拍（容差 0.001 拍） ──
        int_beat = int(beat_float)
        node_at_beat = self._node_index_at_beat(int_beat)
        is_exact_node = (
            node_at_beat is not None
            and abs(beat_float - float(int_beat)) < 0.001
        )

        if is_exact_node:
            # 拍位落在节点起始拍 → 直接渲染该节点
            preview_node = node_at_beat
            if preview_node > 0:
                for point in self.node_points[preview_node - 1]:
                    self._draw_point_item(point, pre_view=True, draw_label=False)
            current_points = self._points_for_node_render(preview_node)

        elif left_node is not None and right_node is not None:
            # 拍位在区间内 → sub-beat 插值
            for point in self.node_points[left_node]:
                self._draw_point_item(point, pre_view=True, draw_label=False)
            current_points = self._interpolate_points_at_sub_beat(
                left_node, right_node, beat_float)

        else:
            # 降级：显示当前活动节点
            if self.active_node > 0:
                for point in self.node_points[self.active_node - 1]:
                    self._draw_point_item(point, pre_view=True, draw_label=False)
            current_points = self._points_for_node_render(self.active_node)

        for point in current_points:
            self._draw_point_item(point, pre_view=False, draw_label=True)

        # self._draw_textbox_items()

    def load_confirmed_state(self, data: dict, node_count: int | None = None):
        """恢复已确认的方案图数据，并清理当前编辑中的临时状态。"""
        super().load_confirmed_state(data, node_count=node_count)
        self._selected_point_ids.clear()
        self._reset_adjustment_state(reset_controls=True)
        self._clear_selection_rect()
        self._draft_tool_name = None
        self._draft_reference_points = []
        self._pending_points = []
        self._clear_draft_items()
        self._clear_pending_preview_items()
        self._clear_adjustment_items()
        self._reset_drawing_rematch_state(active=False)
        self._textbox_preview = []
        self._textbox_pending_points = []
        self._selected_textbox_id = None
        self._clear_interval_helpers()
        self._arrow_preview = []
        self._arrow_editing_index = 0
        self._arrow_pending_points = []
        self._clear_arrow_items()
        self._clear_overlay_items()

    def _ensure_textbox_ids(self, textboxes: list[dict]):
        for tb in textboxes:
            if int(tb.get("id", 0)) <= 0:
                tb["id"] = int(self._next_textbox_id)
                self._next_textbox_id += 1

    def _emit_textbox_selection_changed(self):
        selected = self._selected_preview_textbox()
        if selected is None:
            self.textBoxSelectionChanged.emit(None)
            return
        self.textBoxSelectionChanged.emit(int(selected.get("id", -1)))

    def selected_textbox_font_size(self) -> int:
        """返回当前选中文本框字号；无选中时返回当前默认字号。"""
        selected = self._selected_preview_textbox()
        if selected is None:
            return int(self._textbox_font_size)
        selected_id = int(selected.get("id", -1))
        item = self._textbox_items_by_id.get(selected_id)
        if item is not None:
            return int(item.font_size())
        return int(selected.get("font_size", self._textbox_font_size))

    def _selected_preview_textbox(self) -> dict | None:
        if self._selected_textbox_id is None:
            return None
        for tb in self._textbox_preview:
            if int(tb.get("id", -1)) == int(self._selected_textbox_id):
                return tb
        return None

    def _set_selected_textbox_id(self, textbox_id: int | None, *, refresh: bool = True):
        self._selected_textbox_id = int(textbox_id) if textbox_id is not None else None
        self._emit_textbox_selection_changed()
        self._sync_textbox_item_states()
        if refresh and self.active_tool == "文本":
            self._render_points_for_active_node()

    def _clear_textbox_items(self):
        for item in self._textbox_items:
            self.removeItem(item)
        self._textbox_items = []
        self._textbox_items_by_id = {}

    def _clear_textbox_handles(self):
        for item in self._textbox_handle_items:
            self.removeItem(item)
        self._textbox_handle_items = []

    def _field_rect_from_textbox(self, textbox: dict) -> QRectF:
        p1 = self._field_to_scene(float(textbox.get("x1", 0.0)), float(textbox.get("y1", 0.0)))
        p2 = self._field_to_scene(float(textbox.get("x2", 0.0)), float(textbox.get("y2", 0.0)))
        return QRectF(p1, p2).normalized()

    def _draw_textbox_items(self):
        self._clear_textbox_items()
        node_at_beat = self._node_index_at_beat(self.preview_beat)
        if self.active_tool == "文本":
            textboxes = self._textbox_preview if self._is_current_beat_editable() else []
        elif node_at_beat is not None:
            textboxes = self.node_textboxes.get(node_at_beat, [])
        else:
            textboxes = []

        for tb in textboxes:
            tb_id = int(tb.get("id", -1))
            rect = self._field_rect_from_textbox(tb)
            item = TextBoxItem(
                textbox_id=tb_id,
                rect=rect,
                text=str(tb.get("text", "")),
                font_size=int(tb.get("font_size", self._textbox_font_size)),
                selection_requested_callback=lambda selected_id, self=self: self._set_selected_textbox_id(selected_id, refresh=False),
                text_changed_callback=self._on_textbox_item_text_changed,
            )
            item.setData(0, "textbox")
            item.setData(1, tb_id)
            item.setAcceptedMouseButtons(Qt.MouseButton.LeftButton if self.active_tool == "文本" else Qt.MouseButton.NoButton)
            item.set_mouse_interactive(self.active_tool == "文本")
            self.addItem(item)
            self._textbox_items.append(item)
            self._textbox_items_by_id[tb_id] = item
            item.set_selected(tb_id == self._selected_textbox_id)
            item.set_editable(self.active_tool == "文本" and self._is_current_beat_editable() and tb_id == self._selected_textbox_id)

    def _sync_textbox_item_states(self):
        if not self._textbox_items:
            return

        is_text_mode = self.active_tool == "文本"
        is_editable = is_text_mode and self._is_current_beat_editable()
        selected_id = self._selected_textbox_id
        for item in self._textbox_items:
            tb_id = int(item.textbox_id)
            item.set_selected(tb_id == selected_id)
            item.set_editable(is_editable and tb_id == selected_id)

        if is_text_mode:
            self._clear_textbox_handles()
            if is_editable and selected_id is not None:
                self._rebuild_textbox_handles()

    def _rebuild_textbox_handles(self):
        self._clear_textbox_handles()
        if self.active_tool != "文本" or not self._is_current_beat_editable():
            return
        selected = self._selected_preview_textbox()
        if selected is None:
            return
        p1 = self._field_to_scene(float(selected.get("x1", 0.0)), float(selected.get("y1", 0.0)))
        p2 = self._field_to_scene(float(selected.get("x2", 0.0)), float(selected.get("y2", 0.0)))
        for index, pos in enumerate([p1, p2]):
            handle = ReferenceHandleItem(index=index, center_scene_pos=pos, moved_callback=self._on_textbox_handle_moved)
            handle.setZValue(100)
            self.addItem(handle)
            self._textbox_handle_items.append(handle)

    def _on_textbox_handle_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        selected = self._selected_preview_textbox()
        if selected is None:
            return scene_pos
        fx, fy = self._scene_to_field(scene_pos)
        fx, fy = self._snap_field_point(fx, fy)
        if int(index) == 0:
            selected["x1"] = float(fx)
            selected["y1"] = float(fy)
        else:
            selected["x2"] = float(fx)
            selected["y2"] = float(fy)
        tb_id = int(selected.get("id", -1))
        item = self._textbox_items_by_id.get(tb_id)
        if item is not None:
            item.set_rect(self._field_rect_from_textbox(selected))
        return self._field_to_scene(fx, fy)

    def _on_textbox_item_text_changed(self, textbox_id: int, text: str):
        for textbox in self._textbox_preview:
            if int(textbox.get("id", -1)) == int(textbox_id):
                textbox["text"] = str(text)
                break

    def _enter_textbox_mode(self):
        self._textbox_preview = [dict(tb) for tb in self.node_textboxes.get(int(self.active_node), [])]
        self._ensure_textbox_ids(self._textbox_preview)
        self._textbox_pending_points = []
        self._textbox_hover_scene_pos = None
        self._set_selected_textbox_id(None)

    def _exit_textbox_mode(self):
        self._textbox_preview = []
        self._textbox_pending_points = []
        self._textbox_hover_scene_pos = None
        self._set_selected_textbox_id(None)
        self._clear_textbox_handles()

    def set_textbox_font_size(self, font_size: int):
        self._textbox_font_size = max(1, int(font_size))
        selected = self._selected_preview_textbox()
        if selected is not None:
            selected["font_size"] = int(self._textbox_font_size)
            item = self._textbox_items_by_id.get(int(selected.get("id", -1)))
            if item is not None:
                item.set_font_size(int(self._textbox_font_size))
            self._emit_textbox_selection_changed()

    def delete_selected_textbox(self):
        if self.active_tool != "文本":
            return False
        selected = self._selected_preview_textbox()
        if selected is None:
            return False
        selected_id = int(selected.get("id", -1))
        self._textbox_preview = [tb for tb in self._textbox_preview if int(tb.get("id", -1)) != selected_id]
        self._set_selected_textbox_id(None)
        self._render_points_for_active_node()
        return True

    def confirm_textbox_preview(self):
        if self.active_tool != "文本" or not self._is_current_beat_editable():
            return False
        for textbox in self._textbox_preview:
            item = self._textbox_items_by_id.get(int(textbox.get("id", -1)))
            if item is not None:
                textbox["text"] = item.text()
                textbox["font_size"] = item.font_size()
        self.node_textboxes[self.active_node] = [dict(tb) for tb in self._textbox_preview]
        max_id = max((int(tb.get("id", 0)) for tb in self.node_textboxes[self.active_node]), default=0)
        self._next_textbox_id = max(int(self._next_textbox_id), max_id + 1)
        self._textbox_pending_points = []
        self._set_selected_textbox_id(None)
        self._render_points_for_active_node()
        self.dataChanged.emit()
        return True

    def cancel_textbox_preview(self):
        if self.active_tool != "文本":
            return
        self._textbox_preview = [dict(tb) for tb in self.node_textboxes.get(int(self.active_node), [])]
        self._textbox_pending_points = []
        self._set_selected_textbox_id(None)
        self._render_points_for_active_node()

    def _ordered_selected_point_ids_for_drawing(self) -> list[int]:
        """按当前节点顺序返回被选中的点位 ID。"""
        if not self._selected_point_ids:
            return []
        return [
            int(point.get("id", -1))
            for point in self.node_points[self.active_node]
            if int(point.get("id", -1)) in self._selected_point_ids
        ]

    def _current_drawing_preview_points(self) -> list[tuple[float, float]]:
        """返回当前绘图流程用于确认的预览点位。"""
        tool_name = self._draft_tool_name
        refs = list(self._draft_reference_points)
        if (not tool_name or not refs) and self.active_tool == "曲线/折线" and len(self._pending_points) >= 2:
            tool_name = "曲线/折线"
            refs = list(self._pending_points)
        if not tool_name or not refs:
            return []
        return self._generate_performer_points(tool_name, refs)

    def _reset_drawing_rematch_state(self, active: bool = False):
        """重置绘图重匹配状态。"""
        self._drawing_rematch_state = {
            "active": bool(active),
            "cursor": 0,
            "history": [],
            "preview_to_point": {},
            "point_to_preview": {},
            "candidate_point_id": None,
        }

    def _drawing_rematch_snapshot(self) -> dict:
        """返回绘图重匹配状态快照。"""
        state = getattr(self, "_drawing_rematch_state", {})
        selected_ids = self._ordered_selected_point_ids_for_drawing()
        preview_points = self._current_drawing_preview_points()
        preview_count = len(preview_points)
        active = bool(state.get("active", False)) and bool(selected_ids) and preview_count > 0
        cursor = max(0, min(int(state.get("cursor", 0)), preview_count))
        preview_to_point = {int(k): int(v) for k, v in state.get("preview_to_point", {}).items()}
        point_to_preview = {int(k): int(v) for k, v in state.get("point_to_preview", {}).items()}
        committed_preview_indexes = {idx for idx in preview_to_point.keys() if 0 <= idx < preview_count}
        matched_ids = {point_id for point_id in point_to_preview.keys() if point_id in selected_ids}
        candidate_point_id = state.get("candidate_point_id")
        if candidate_point_id is not None:
            candidate_point_id = int(candidate_point_id)
        current_preview_index = cursor if active and cursor < preview_count else None
        current_point_id = None
        if current_preview_index is not None and current_preview_index < len(selected_ids):
            current_point_id = int(selected_ids[current_preview_index])
        resolved_point_id = candidate_point_id if candidate_point_id is not None else current_point_id
        all_selected_matched = bool(selected_ids) and all(point_id in matched_ids for point_id in selected_ids)
        keep_enabled = bool(
            active
            and current_preview_index is not None
            and current_preview_index not in committed_preview_indexes
            and current_point_id is not None
            and resolved_point_id is not None
        )
        return {
            "active": active,
            "selected_ids": selected_ids,
            "preview_points": preview_points,
            "preview_count": preview_count,
            "cursor": cursor,
            "current_preview_index": current_preview_index,
            "current_point_id": current_point_id,
            "resolved_point_id": resolved_point_id,
            "preview_to_point": preview_to_point,
            "point_to_preview": point_to_preview,
            "committed_preview_indexes": committed_preview_indexes,
            "matched_ids": matched_ids,
            "candidate_point_id": candidate_point_id,
            "all_selected_matched": all_selected_matched,
            "rematch_enabled": bool(selected_ids) and preview_count > 0,
            "previous_enabled": bool(state.get("history", [])),
            "next_enabled": active and current_preview_index is not None and not all_selected_matched,
            "keep_enabled": keep_enabled,
            # 注：确认按钮的可用性由界面层决定，此处不再返回 confirm_enabled 字段以避免冗余。
        }

    def start_drawing_rematch(self):
        """在绘图流程中清空匹配并从第一个预览点位重新分配。"""
        snapshot = self._drawing_rematch_snapshot()
        if not snapshot["rematch_enabled"]:
            return False
        self._reset_drawing_rematch_state(active=True)
        self._render_points_for_active_node()
        self.drawingRematchStateChanged.emit()
        return True

    def drawing_match_set_candidate(self, point_id: int):
        """为当前预览点位设置候选原点位（未确认）。"""
        snapshot = self._drawing_rematch_snapshot()
        if not snapshot["active"]:
            return False
        current_preview_index = snapshot["current_preview_index"]
        if current_preview_index is None:
            return False
        point_id = int(point_id)
        if point_id not in snapshot["selected_ids"]:
            return False
        self._drawing_rematch_state["candidate_point_id"] = point_id
        self._render_points_for_active_node()
        self.drawingRematchStateChanged.emit()
        return True

    def drawing_match_previous(self):
        """回退上一条匹配记录。"""
        state = getattr(self, "_drawing_rematch_state", None)
        if not state or not bool(state.get("active", False)):
            return False
        history = state.get("history", [])
        if not history:
            return False
        action = history.pop()
        state["candidate_point_id"] = None
        state["cursor"] = max(0, int(action.get("cursor_before", 0)))
        if action.get("action") == "keep":
            preview_index = int(action.get("preview_index", -1))
            point_id = int(action.get("point_id", -1))
            previous_preview_index = action.get("previous_preview_index")
            previous_point_id = action.get("previous_point_id")
            preview_to_point = state.get("preview_to_point", {})
            point_to_preview = state.get("point_to_preview", {})
            preview_to_point.pop(preview_index, None)
            point_to_preview.pop(point_id, None)
            if previous_preview_index is not None:
                previous_preview_index = int(previous_preview_index)
                preview_to_point[previous_preview_index] = point_id
                point_to_preview[point_id] = previous_preview_index
            if previous_point_id is not None:
                previous_point_id = int(previous_point_id)
                preview_to_point[preview_index] = previous_point_id
                point_to_preview[previous_point_id] = preview_index
        self._render_points_for_active_node()
        self.drawingRematchStateChanged.emit()
        return True

    def drawing_match_next(self):
        """跳过当前预览点位。"""
        snapshot = self._drawing_rematch_snapshot()
        if not snapshot["active"]:
            return False
        current_preview_index = snapshot["current_preview_index"]
        if current_preview_index is None:
            return False
        state = self._drawing_rematch_state
        state.setdefault("history", []).append({
            "action": "skip",
            "cursor_before": int(current_preview_index),
            "preview_index": int(current_preview_index),
        })
        state["cursor"] = int(current_preview_index) + 1
        state["candidate_point_id"] = None
        self._render_points_for_active_node()
        self.drawingRematchStateChanged.emit()
        return True

    def drawing_match_keep(self):
        """确认当前预览点对应的原点位匹配并继续前进。"""
        snapshot = self._drawing_rematch_snapshot()
        if not snapshot["keep_enabled"]:
            return False
        state = self._drawing_rematch_state
        preview_index = int(snapshot["current_preview_index"])
        point_id = int(snapshot["resolved_point_id"])
        preview_to_point = state.setdefault("preview_to_point", {})
        point_to_preview = state.setdefault("point_to_preview", {})
        previous_preview_index = point_to_preview.get(point_id)
        previous_point_id = preview_to_point.get(preview_index)
        if previous_preview_index is not None and int(previous_preview_index) != preview_index:
            preview_to_point.pop(int(previous_preview_index), None)
        if previous_point_id is not None and int(previous_point_id) != point_id:
            point_to_preview.pop(int(previous_point_id), None)
        preview_to_point[preview_index] = point_id
        point_to_preview[point_id] = preview_index
        state.setdefault("history", []).append({
            "action": "keep",
            "cursor_before": preview_index,
            "preview_index": preview_index,
            "point_id": point_id,
            "previous_preview_index": previous_preview_index,
            "previous_point_id": previous_point_id,
        })
        state["cursor"] = preview_index + 1
        state["candidate_point_id"] = None
        self._render_points_for_active_node()
        self.drawingRematchStateChanged.emit()
        return True

    def drawBackground(self, painter, rect):
        """场景背景绘制入口。"""
        self.grid_renderer.draw_background_grid(painter, rect)
        self.grid_renderer.draw_field_lines(painter)
        self.grid_renderer.draw_field_labels(painter)

    def _pdf_export_page_orientation(self) -> QPageLayout.Orientation:
        """根据场地宽高选择 PDF 页面方向。"""
        return (
            QPageLayout.Orientation.Landscape
            if float(self.field_info.field_width) >= float(self.field_info.field_height)
            else QPageLayout.Orientation.Portrait
        )

    def _pdf_export_content_padding(self, export_scale: float) -> tuple[float, float, float]:
        """计算 PDF 内容区留白（水平、上、下），下侧留白约为上侧的两倍。

        返回 (horizontal_padding, top_padding, bottom_padding)。
        """
        # print("计算 PDF 导出内容留白，export_scale:", export_scale)
        font_px = float(self.field_info.label_zoom) * export_scale
        offset_px = max(float(abs(self.field_info.label_x_offset)) + font_px,
                        float(abs(self.field_info.label_y_offset)) + font_px)

        # 保持原先对水平留白的保护规则
        horizontal_padding = max(64.0, offset_px * 2.0)

        # 设定上/下不对称：上侧取较小的基准，下侧约为上侧的两倍并至少保持与旧逻辑相同的下限
        top_padding = max(64.0, offset_px * 2.0)
        bottom_padding = max(128.0, top_padding * 2.0)

        return horizontal_padding, top_padding, bottom_padding

    def _pdf_export_layout(self, page_rect: QRectF) -> tuple[float, QPointF]:
        """计算导出缩放与偏移，给坐标标签预留页面边距。"""
        field_rect = self.field_info.field_rect
        field_width = float(field_rect.width())
        field_height = float(field_rect.height())
        page_width = float(page_rect.width())
        page_height = float(page_rect.height())

        # 初步以页面尺寸估算缩放，再根据留白重新计算最终缩放与偏移。
        export_scale = min(page_width / field_width, page_height / field_height)

        hpad, top_pad, bottom_pad = self._pdf_export_content_padding(export_scale)
        content_left = float(page_rect.left()) + hpad
        content_top = float(page_rect.top()) + top_pad
        content_width = page_width - hpad * 2.0
        content_height = page_height - top_pad - bottom_pad

        export_scale = min(content_width / field_width, content_height / field_height)

        # 重新基于最终缩放计算留白（以应对 label 尺寸随缩放变化）
        hpad, top_pad, bottom_pad = self._pdf_export_content_padding(export_scale)
        content_left = float(page_rect.left()) + hpad
        content_top = float(page_rect.top()) + top_pad
        content_width = page_width - hpad * 2.0
        content_height = page_height - top_pad - bottom_pad

        export_scale = min(content_width / field_width, content_height / field_height)

        offset_x = content_left + (content_width - field_width * export_scale) / 2.0 - float(field_rect.left()) * export_scale
        offset_y = content_top + (content_height - field_height * export_scale) / 2.0 - float(field_rect.top()) * export_scale
        return export_scale, QPointF(offset_x, offset_y)

    def _make_pdf_export_field_info(self, export_scale: float, export_offset: QPointF) -> FieldInfo:
        """复制一份场地配置供 PDF 导出使用。"""
        export_field_info = FieldInfo(None)
        export_field_info.load_from_dict(self.field_info.to_dict())
        # 导出缩放不走 FieldInfo.set_scale，避免被 SCALE_MAX 裁剪。
        export_field_info.scale = export_scale
        export_field_info.label_zoom = self.field_info.label_zoom / self.export_ratio
        export_field_info.set_offset(float(export_offset.x()), float(export_offset.y()))
        return export_field_info

    def _draw_pdf_export_background(self, painter: QPainter, scene_rect: QRectF, export_scale: float, export_offset: QPointF):
        """按导出坐标系绘制背景网格、场地线和坐标。"""
        export_field_info = self._make_pdf_export_field_info(export_scale, export_offset)
        export_grid_renderer = GridRenderer(export_field_info)
        field_rect = self.field_info.field_rect
        field_scene_rect = QRectF(
            float(field_rect.left()) * export_scale + float(export_offset.x()),
            float(field_rect.top()) * export_scale + float(export_offset.y()),
            float(field_rect.width()) * export_scale,
            float(field_rect.height()) * export_scale,
        )
        export_grid_renderer.draw_background_grid(painter, field_scene_rect)
        export_grid_renderer.draw_field_lines(painter)
        export_grid_renderer.draw_field_labels(painter, max_font_size=36)

    def _add_pdf_export_point_items(self, scene: QGraphicsScene, point: dict, export_scale: float, export_offset: QPointF):
        """向临时导出场景添加一个点位及其标签。"""
        field_x = float(point.get("x", 0.0))
        field_y = float(point.get("y", 0.0))
        pos = QPointF(field_x * export_scale + float(export_offset.x()), field_y * export_scale + float(export_offset.y()))
        font_scale = export_scale
        size_scale = font_scale

        dot_radius = 5.0 * self.export_ratio
        dot = QGraphicsEllipseItem(pos.x() - dot_radius, pos.y() - dot_radius, dot_radius * 2.0, dot_radius * 2.0)
        dot.setPen(QPen(Qt.PenStyle.NoPen))
        dot.setBrush(QBrush(PerformerPointItem.dot_color))
        dot.setZValue(960)
        scene.addItem(dot)

        label = QGraphicsSimpleTextItem(self._get_point_label_text(int(point.get("id", 0))))
        font = QFont()
        font.setPointSizeF(float(self.label_size * self.export_ratio))
        label.setFont(font)
        label.setBrush(QBrush(self.label_color))
        angle_deg = int(self.label_pos) % 360
        angle_rad = math.radians(angle_deg)
        dx = math.cos(angle_rad) * float(self.label_offset) * self.export_ratio
        dy = math.sin(angle_rad) * float(self.label_offset) * self.export_ratio
        br = label.boundingRect()
        label.setPos(pos.x() + dx - br.width() / 2.0, pos.y() + dy - br.height() / 2.0)
        label.setZValue(965)
        scene.addItem(label)

    def _add_pdf_export_textbox_items(self, scene: QGraphicsScene, textbox: dict, export_scale: float, export_offset: QPointF):
        """向临时导出场景添加一个文本框。"""
        from src.scene_items import TextBoxItem
        font_scale = export_scale
        p1 = QPointF(float(textbox.get("x1", 0.0)) * export_scale + float(export_offset.x()), float(textbox.get("y1", 0.0)) * export_scale + float(export_offset.y()))
        p2 = QPointF(float(textbox.get("x2", 0.0)) * export_scale + float(export_offset.x()), float(textbox.get("y2", 0.0)) * export_scale + float(export_offset.y()))
        rect = QRectF(p1, p2).normalized()
        item = TextBoxItem(
            textbox_id=int(textbox.get("id", 0)),
            rect=rect,
            text=str(textbox.get("text", "")),
            font_size=max(1, int(round(float(textbox.get("font_size", self._textbox_font_size)) * self.export_ratio))),
            selection_requested_callback=None,
            text_changed_callback=None,
        )
        item.set_selected(False)
        item.set_editable(False)
        item.set_mouse_interactive(False)
        item.setZValue(100)
        scene.addItem(item)

    def _add_pdf_export_arrow_items(self, scene: QGraphicsScene, arrow: dict, export_scale: float, export_offset: QPointF, *, negate: bool = False):
        """向临时导出场景添加一个箭头。negate=True 时对坐标取负（表演视角）。"""
        field_pts = arrow.get('points', [])
        if not field_pts or len(field_pts) < 2:
            return
        sign = -1.0 if negate else 1.0
        scene_pts = [
            (sign * float(p[0]) * export_scale + float(export_offset.x()),
             sign * float(p[1]) * export_scale + float(export_offset.y()))
            for p in field_pts
        ]
        item = ArrowItem(
            arrow_index=-1,
            arrow_type=arrow.get('type', 'line'),
            points=scene_pts,
            style=dict(arrow.get('style', {'forward': True, 'backward': False, 'mid': False})),
            clicked_callback=None,
            is_current=False,
            arrow_size=ArrowItem.arrow_size * self.export_ratio,
        )
        # 导出时线条粗细同步放大
        export_pen = QPen(ArrowItem.normal_color, ArrowItem.normal_width * self.export_ratio / 2.0)
        export_pen.setCosmetic(True)
        item.setPen(export_pen)
        item.set_mouse_interactive(False)
        item.setZValue(800)
        scene.addItem(item)

    def _build_pdf_export_scene(self, node_index: int, page_cnt: int, export_scale: float, export_offset: QPointF) -> QGraphicsScene:
        """为单个方案图节点构建临时导出场景。"""
        export_scene = QGraphicsScene()
        if node_index >= 1:
            for point in self.node_points[node_index - 1]:
                pos = QPointF(float(point.get("x", 0.0)) * export_scale + float(export_offset.x()), float(point.get("y", 0.0)) * export_scale + float(export_offset.y()))
                pre_dot_radius = self.pre_point_radius * self.export_ratio
                pre_dot = QGraphicsEllipseItem(pos.x() - pre_dot_radius, pos.y() - pre_dot_radius, pre_dot_radius * 2.0, pre_dot_radius * 2.0)
                pre_dot.setPen(QPen(Qt.PenStyle.NoPen))
                pre_dot.setBrush(QBrush(self.pre_point_color))
                pre_dot.setZValue(950)
                export_scene.addItem(pre_dot)
        for point in self.node_points[node_index]:
            self._add_pdf_export_point_items(export_scene, point, export_scale, export_offset)
        for textbox in self.node_textboxes.get(node_index, []):
            self._add_pdf_export_textbox_items(export_scene, textbox, export_scale, export_offset)
        for arrow in self.node_arrows.get(node_index, []):
            self._add_pdf_export_arrow_items(export_scene, arrow, export_scale, export_offset, negate=False)

        return export_scene

    def export_origin_pdf(self, file_path: str | Path, cnt_per_page: list[int] | None = None):
        """将每个方案图节点导出为一页 A4 PDF。"""
        output_path = Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        writer = QPdfWriter(str(output_path))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(self._pdf_export_page_orientation())
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        writer.setTitle("Marching Map Export")
        writer.setCreator("Marching Map Editor")
        writer.setResolution(300)

        page_rect = QRectF(writer.pageLayout().paintRectPixels(writer.resolution()))
        if page_rect.isNull() or page_rect.width() <= 0 or page_rect.height() <= 0:
            page_rect = QRectF(writer.pageLayout().fullRectPixels(writer.resolution()))

        painter = QPainter(writer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        export_scale, export_offset = self._pdf_export_layout(page_rect)
        for node_index, page_cnt in enumerate(cnt_per_page):
            if node_index > 0:
                writer.newPage()
            export_scene = self._build_pdf_export_scene(node_index, page_cnt, export_scale, export_offset)
            export_scene.setSceneRect(page_rect)

            painter.save()
            self._draw_pdf_export_background(painter, page_rect, export_scale, export_offset)
            export_scene.render(painter, page_rect, page_rect, Qt.AspectRatioMode.IgnoreAspectRatio)
            painter.restore()

            # 在下侧留白区域绘制页脚文本，左对齐、上对齐，并紧贴内容区下边缘显示
            field_rect = self.field_info.field_rect
            page_height = float(page_rect.height())
            padding = min(self._pdf_export_content_padding(export_scale))
            content_bottom = float(page_rect.bottom())
            content_top = float(page_rect.top())
            content_height = page_height - padding
            footer_rect = QRectF(
                250,
                export_offset.y() * 2, 
                field_rect.width() * export_scale,
                padding,
            )

            font = QFont()
            font.setPointSizeF(12)
            painter.setFont(font)
            painter.setPen(QPen(QColor("#000000")))

            if node_index == 0:
                footer_text = f'set：#{node_index+1}'
            else:
                footer_text = f'set：#{node_index+1}   节拍：{page_cnt}'
            painter.drawText(footer_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, footer_text)
            painter.drawText(footer_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, '指挥视角')

        painter.end()

    def export_upsidedown_pdf(self, file_path: str | Path, cnt_per_page: list[int] | None = None):
        """将每个方案图节点导出为一页 A4 PDF（表演视角），仅将构建导出场景时的 x,y 坐标取负。"""
        output_path = Path(file_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        writer = QPdfWriter(str(output_path))
        writer.setPageSize(QPageSize(QPageSize.PageSizeId.A4))
        writer.setPageOrientation(self._pdf_export_page_orientation())
        writer.setPageMargins(QMarginsF(0, 0, 0, 0))
        writer.setTitle("Marching Map Export")
        writer.setCreator("Marching Map Editor")
        writer.setResolution(300)

        page_rect = QRectF(writer.pageLayout().paintRectPixels(writer.resolution()))
        if page_rect.isNull() or page_rect.width() <= 0 or page_rect.height() <= 0:
            page_rect = QRectF(writer.pageLayout().fullRectPixels(writer.resolution()))

        painter = QPainter(writer)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)
        export_scale, export_offset = self._pdf_export_layout(page_rect)
        for node_index, page_cnt in enumerate(cnt_per_page):
            if node_index > 0:
                writer.newPage()

            # 使用 _build_pdf_export_scene 的逻辑，但在使用点/文本框坐标时将 x,y 取负。
            export_scene = QGraphicsScene()
            if node_index >= 1:
                for point in self.node_points[node_index - 1]:
                    px = -float(point.get("x", 0.0))
                    py = -float(point.get("y", 0.0))
                    pos = QPointF(px * export_scale + float(export_offset.x()), py * export_scale + float(export_offset.y()))
                    pre_dot_radius = self.pre_point_radius * self.export_ratio
                    pre_dot = QGraphicsEllipseItem(pos.x() - pre_dot_radius, pos.y() - pre_dot_radius, pre_dot_radius * 2.0, pre_dot_radius * 2.0)
                    pre_dot.setPen(QPen(Qt.PenStyle.NoPen))
                    pre_dot.setBrush(QBrush(self.pre_point_color))
                    pre_dot.setZValue(950)
                    export_scene.addItem(pre_dot)

            # 为复用原有的添加函数，传入坐标取负的临时字典
            for point in self.node_points[node_index]:
                tmp = dict(point)
                tmp["x"] = -float(point.get("x", 0.0))
                tmp["y"] = -float(point.get("y", 0.0))
                self._add_pdf_export_point_items(export_scene, tmp, export_scale, export_offset)

            for textbox in self.node_textboxes.get(node_index, []):
                tmp_tb = dict(textbox)
                tmp_tb["x1"] = -float(textbox.get("x1", 0.0))
                tmp_tb["y1"] = -float(textbox.get("y1", 0.0))
                tmp_tb["x2"] = -float(textbox.get("x2", 0.0))
                tmp_tb["y2"] = -float(textbox.get("y2", 0.0))
                self._add_pdf_export_textbox_items(export_scene, tmp_tb, export_scale, export_offset)

            for arrow in self.node_arrows.get(node_index, []):
                self._add_pdf_export_arrow_items(export_scene, arrow, export_scale, export_offset, negate=True)

            export_scene.setSceneRect(page_rect)

            painter.save()
            self._draw_pdf_export_background(painter, page_rect, export_scale, export_offset)
            export_scene.render(painter, page_rect, page_rect, Qt.AspectRatioMode.IgnoreAspectRatio)
            painter.restore()

            # 页脚文本（右侧写表演视角）
            field_rect = self.field_info.field_rect
            page_height = float(page_rect.height())
            padding = min(self._pdf_export_content_padding(export_scale))
            content_bottom = float(page_rect.bottom())
            content_top = float(page_rect.top())
            content_height = page_height - padding
            footer_rect = QRectF(
                250,
                export_offset.y() * 2, 
                field_rect.width() * export_scale,
                padding,
            )

            font = QFont()
            font.setPointSizeF(12)
            painter.setFont(font)
            painter.setPen(QPen(QColor("#000000")))

            if node_index == 0:
                footer_text = f'set：#{node_index+1}'
            else:
                footer_text = f'set：#{node_index+1}   节拍：{page_cnt}'
            painter.drawText(footer_rect, Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, footer_text)
            painter.drawText(footer_rect, Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop, '表演者视角')

        painter.end()

    def _clear_overlay_items(self):
        """清除当前所有点位与标签图元，准备重建。"""
        for item in self._current_items + self._previous_items + self._label_items + self._selection_link_items + self._rematch_helper_items + self._textbox_items + self._textbox_handle_items + self._temp_group_helper_items + self._follow_group_helper_items + self._rotate_helper_items + self._pending_preview_items + self._arrow_items + self._arrow_handle_items + self._arrow_draft_preview_items:
            self.removeItem(item)
        self._current_items = []
        self._previous_items = []
        self._label_items = []
        self._selection_link_items = []
        self._rematch_helper_items = []
        self._textbox_items = []
        self._textbox_items_by_id = {}
        self._textbox_handle_items = []
        self._temp_group_helper_items = []
        self._follow_group_helper_items = []
        self._clear_rotate_helpers()
        self._pending_preview_items = []
        self._arrow_items = []
        self._arrow_handle_items = []
        self._arrow_draft_preview_items = []
        self._point_items_by_id = {}
        self._label_items_by_id = {}

    def set_active_tool(self, tool_name: str):
        """切换当前工具并清空临时草稿。"""
        previous_tool = self.active_tool
        if previous_tool == "文本" and tool_name != "文本":
            self._exit_textbox_mode()
        if previous_tool == "分组" and tool_name != "分组":
            self.clear_temp_groups()
        if previous_tool == "跟随" and tool_name != "跟随":
            self._clear_follow_group_helper_items()
        if previous_tool == "间隔" and tool_name != "间隔":
            self._interval_dragging = False
            self._clear_interval_helpers()
        if previous_tool == "旋转" and tool_name != "旋转":
            self._rotate_dragging = False
            self._clear_rotate_helpers()
        if previous_tool == "箭头" and tool_name != "箭头":
            self._exit_arrow_mode()
            
        if tool_name in {"选择", "框选"}:
            self._selected_point_ids.clear()
    
        if self._selected_point_ids:
            self.sync_sampling_values_from_selection(previous_tool)
        else:
            self.reset_sampling_defaults(previous_tool)

        self.active_tool = tool_name
        self._pending_points = []   # 清空草稿点位
        self._reset_drawing_rematch_state(active=False)
        self._clear_selection_rect()    # 清除框选工具的选区矩形和相关状态
        self._clear_draft()             # 清除绘图工具的草稿图形
        if tool_name != "调整":
            self._reset_adjustment_state(reset_controls=True)
        if tool_name in self._sampling_tools:
            self.sync_sampling_values_from_selection(tool_name)
        if tool_name == "文本":
            self._enter_textbox_mode()
        if tool_name == "旋转" and self._selected_point_ids:
            self.begin_rotate()
        if tool_name == "箭头":
            self._enter_arrow_mode()
        self._render_points_for_active_node()   # 刷新点位显示
        # 点位修改时：将选中点位预览重置到上一张图的位置（仅视觉，不修改 node_points）
        if tool_name in {"路径", "跟随", "间隔"} and self._selected_point_ids and self.active_node > 0:
            self._reset_selected_points_to_prev_visual()
        if tool_name == "调整" and self._selected_point_ids:
            self.begin_adjustment()
        self.drawingRematchStateChanged.emit()

    def _reset_selected_points_to_prev_visual(self):
        """将选中点位图元视觉移动到上一张图位置（不修改 node_points）。"""
        prev_node = self.active_node - 1
        for point in self.node_points[prev_node]:
            pid = int(point.get("id", -1))
            if pid not in self._selected_point_ids:
                continue
            item = self._point_items_by_id.get(pid)
            if item is None:
                continue
            prev_x, prev_y = float(point["x"]), float(point["y"])
            new_pos = self._field_to_scene(prev_x, prev_y)
            item.setPos(new_pos)
            # 同步标签位置
            label = self._label_items_by_id.get(pid)
            if label is not None:
                angle_deg = int(self.label_pos) % 360
                angle_rad = math.radians(angle_deg)
                dx_val = math.cos(angle_rad) * float(self.label_offset)
                dy_val = math.sin(angle_rad) * float(self.label_offset)
                br = label.boundingRect()
                label.setPos(new_pos.x() + dx_val - br.width() / 2.0, new_pos.y() + dy_val - br.height() / 2.0)
        # 刷新组内连线
        self._refresh_selected_group_links()
        # 间隔行进：同步 helper 圆圈到移动后的点位位置
        if self.active_tool == "间隔":
            for _pid, h in self._interval_helper_items.items():
                p_item = self._point_items_by_id.get(_pid)
                if p_item is not None:
                    h.setPos(p_item.scenePos())

    def set_active_node(self, node_index: int):
        """切换当前时间轴节点并刷新显示。"""
        if self.active_tool == "调整" and self._adjustment_active:
            self._reset_adjustment_state(reset_controls=True)

        # 切换节点时中止任何正在进行的 helper 拖拽
        self._rotate_dragging = False
        self._interval_dragging = False

        self.active_node = max(0, int(node_index))  # 确保节点索引非负
        self.ensure_node_exists(self.active_node)   # 确保目标节点存在，若不存在则初始化
        self._pending_points = []   # 清空草稿点位
        self._reset_drawing_rematch_state(active=False)
        self._selected_point_ids.clear()
        self._clear_selection_rect()
        self._clear_draft()
        if self.active_tool == "文本":
            self._enter_textbox_mode()
        if self.active_tool == "箭头":
            self._enter_arrow_mode()
        self._render_points_for_active_node()
        self.drawingRematchStateChanged.emit()

    def _clear_selection_rect(self):
        """清除框选工具的选区矩形和相关状态。"""
        if self._selection_rect_item is not None:
            self.removeItem(self._selection_rect_item)
            self._selection_rect_item = None
        self._selection_start_position = None
        self._selection_current_position = None

    def _update_selection_rect_item(self):
        """更新框选工具的选区矩形图元位置与大小。"""
        if self._selection_start_position is None or self._selection_current_position is None:
            return
        rect = QRectF(self._selection_start_position, self._selection_current_position).normalized()
        if self._selection_rect_item is None:
            self._selection_rect_item = QGraphicsRectItem(rect)
            self._selection_rect_item.setPen(QPen(QColor("#d35400"), 1.2, Qt.PenStyle.DashLine))
            self._selection_rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self._selection_rect_item.setZValue(980)
            self.addItem(self._selection_rect_item)
        else:
            self._selection_rect_item.setRect(rect)

    def _select_points_in_scene_rect(self, scene_rect: QRectF, tool_name: str, event):
        """根据给定的场景矩形框选点位，更新选中状态并刷新显示。"""
        if scene_rect.width() <= 1e-6 and scene_rect.height() <= 1e-6:
            return
        selected_ids = set()
        select_groups = set()
        for point in self.node_points[self.active_node]:
            point_id = int(point['id'])
            if point_id in selected_ids:
                continue
            pos = self._field_to_scene(point["x"], point["y"])
            if scene_rect.contains(pos):
                selected_ids.add(point_id)
                point_group = point.get("group_id")
                if point_group is not None:
                    select_groups.add(int(point_group))

        if tool_name == '选择':
            for group_id in select_groups:
                group_info = self.group_to_point[group_id]
                for group_point_id in group_info.get("point_ids", []):
                    selected_ids.add(int(group_point_id))

        modifiers = event.modifiers()
        if (modifiers & Qt.KeyboardModifier.ControlModifier) and self.active_tool == "框选":
            self._selected_point_ids.update(selected_ids)
        else:
            self._selected_point_ids = selected_ids
        self._refresh_point_selection_visuals()

    def _refresh_point_selection_visuals(self):
        """刷新当前点位图元的选中状态视觉效果，并发出选中点位数量变化信号。"""
        if getattr(self, "_drawing_rematch_state", {}).get("active", False):
            self._reset_drawing_rematch_state(active=False)
        for point_id, item in self._point_items_by_id.items():
            item.set_selected_visual(point_id in self._selected_point_ids)
        self._refresh_selected_group_links()
        self.selectedPointsChanged.emit(len(self._selected_point_ids))
        self.drawingRematchStateChanged.emit()

    def _clear_selection_link_items(self):
        """清除选中点位之间的连线图元。"""
        for item in self._selection_link_items:
            self.removeItem(item)
        self._selection_link_items = []
        
    def _draw_temp_group_links(self, groups: list[list[int]]):
        """在当前场景中临时绘制点位组内连线（不修改 _selection_link_items）。"""
        self._temp_group_line_items = []
        pen = QPen(QColor("#f39c12"), 4, Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)

        for idx, group in enumerate(groups):
            if len(group) < 2:
                continue
            if idx == self._temp_group_current_index:
                pen.setColor(QColor("#00cc00"))
                pen.setWidth(4)
            else:
                pen.setColor(QColor("#f39c12"))
                pen.setWidth(4)
            previous_point_id = group[0]
            for current_point_id in group[1:]:
                previous_item = self._point_items_by_id.get(previous_point_id)
                current_item = self._point_items_by_id.get(current_point_id)
                if previous_item is not None and current_item is not None:
                    previous_pos = previous_item.scenePos()
                current_pos = current_item.scenePos()
                line_item = QGraphicsLineItem(
                    previous_pos.x(),
                    previous_pos.y(),
                    current_pos.x(),
                    current_pos.y(),
                )
                line_item.setPen(pen)
                line_item.setZValue(150)
                self.addItem(line_item)
                self._temp_group_line_items.append(line_item)
                previous_point_id = current_point_id

    def _clear_temp_group_items(self):
        """清除临时分组绘制的线与 helper 圆。"""
        for it in getattr(self, "_temp_group_line_items", []):
            self.removeItem(it)
        self._temp_group_line_items = []
        for it in getattr(self, "_temp_group_helper_items", []):
            self.removeItem(it)
        self._temp_group_helper_items = []

    def _clear_follow_group_helper_items(self):
        """清除跟随工具的首尾 helper。"""
        for it in getattr(self, "_follow_group_helper_items", []):
            self.removeItem(it)
        self._follow_group_helper_items = []

    def _follow_group_point_ids_for_group(self, group_info: dict) -> list[int]:
        """返回跟随模式下该组的点位顺序；leader 始终排在第一位。"""
        point_ids = [int(pid) for pid in group_info['point_ids'] if pid in self._selected_point_ids]
        if not point_ids:
            return []
        if group_info["leader"]:
            return point_ids
        return list(reversed(point_ids))

    def _follow_group_point_ids_for_point_id(self, point_id: int) -> list[int]:
        """返回点位在跟随模式下所属组的 leader-first 点位顺序。"""
        # point = self._find_point_by_id(point_id)
        point = self._find_point_in_node(self.active_node, point_id)
        group_id = point['group_id']
        if group_id is None:
            return []
        if group_id < 0 or group_id >= len(self.group_to_point):
            return []
        return self._follow_group_point_ids_for_group(self.group_to_point[group_id])

    def _toggle_follow_group_leader(self, group_id: int) -> bool:
        """切换指定组的 leader 端点（首/尾互换）。"""
        if group_id < 0 or group_id >= len(self.group_to_point):
            return False
        group_info = self.group_to_point[group_id]
        point_ids = group_info["point_ids"]
        if len(point_ids) < 2:
            return False
        group_info["leader"] = not group_info["leader"]
        return True

    def _get_anchor(self) -> int:
        cur_node_points = self.node_points[self.active_node]
        active_groups = list({cur_node_points[id]['group_id'] for id in self._selected_point_ids})
        min_gid = min(active_groups)
        min_group = self.group_to_point[min_gid]
        ordered_ids = self._follow_group_point_ids_for_group(min_group)
        anchor_point_id = next(
            pid for pid in ordered_ids
        )
        return anchor_point_id

    def _draw_follow_group_helpers(self):
        """在跟随模式下为每组首尾绘制可点击 helper。"""
        self._clear_follow_group_helper_items()
        if self.active_tool != "跟随":
            return

        node_groups = self.node_to_group[self.active_node]
        for group_id in node_groups:
            if group_id < 0 or group_id >= len(self.group_to_point):
                continue
            group_info = self.group_to_point[group_id]
            point_ids = [int(pid) for pid in group_info['point_ids'] if pid in self._selected_point_ids]
            if len(point_ids) < 2:
                continue
            leader_first_ids = self._follow_group_point_ids_for_group(group_info)
            if len(leader_first_ids) < 2:
                continue
            leader_id = int(leader_first_ids[0])
            tail_id = int(leader_first_ids[-1])
            for pid in (leader_id, tail_id):
                item = self._point_items_by_id.get(pid)
                if item is None:
                    continue
                pos = item.scenePos()
                helper_radius = self.helper_radius
                helper = QGraphicsEllipseItem(
                    pos.x() - helper_radius,
                    pos.y() - helper_radius,
                    helper_radius * 2,
                    helper_radius * 2,
                )
                helper.setPen(QPen(QColor("#000000"), 1.4))
                if pid == leader_id:
                    if pid == self._get_anchor():
                        helper.setBrush(QBrush(QColor("#ff4d4d")))
                    else:
                        # 非 anchor 的 leader 端点刷绿
                        helper.setBrush(QBrush(QColor("#00cc00")))
                else:
                    helper.setBrush(QBrush(QColor(255, 193, 7, 40)))
                helper.setZValue(1010)
                helper.setData(0, "follow_group_helper")
                helper.setData(1, int(group_id))
                helper.setData(2, int(pid))
                self.addItem(helper)
                self._follow_group_helper_items.append(helper)

    def _clear_interval_helpers(self, full_reset: bool = True):
        """清除间隔行进工具的 helper 拖拽手柄。"""
        for it in getattr(self, "_interval_helper_items", {}).values():
            self.removeItem(it)
        self._interval_helper_items = {}
        # 注意：不重置 _interval_dragging，拖拽标志由 mousePress/Release 和切换工具时管理
        if full_reset:
            self._interval_anchor_id = None
            self._interval_drag_position = None

    def _clear_rotate_helpers(self):
        """清除旋转工具的 helper 图元。"""
        for it in getattr(self, "_rotate_helper_items", []):
            self.removeItem(it)
        self._rotate_helper_items = []
        # 注意：不重置 _rotate_dragging，拖拽标志由 mousePress/Release 和切换工具时管理

    def _draw_rotate_helpers(self):
        """在旋转模式下绘制可拖动的旋转中心 helper。"""
        self._clear_rotate_helpers()
        if self.active_tool != "旋转":
            return
        if not self._selected_point_ids:
            return
        cx, cy = self._rotate_center_point
        scene_pos = self._field_to_scene(cx, cy)
        helper_radius = self.helper_radius
        helper = QGraphicsEllipseItem(
            scene_pos.x() - helper_radius,
            scene_pos.y() - helper_radius,
            helper_radius * 2,
            helper_radius * 2,
        )
        helper.setPen(QPen(QColor("#e74c3c"), 2.0))
        helper.setBrush(QBrush(QColor(0, 0, 0, 0)))
        helper.setZValue(1000)
        helper.setData(0, "rotate_helper")
        helper.setData(1, "center")
        self.addItem(helper)
        self._rotate_helper_items.append(helper)

        # 十字准线标记旋转中心
        cross_size = helper_radius * 0.5
        pen_cross = QPen(QColor("#e74c3c"), 2.0, Qt.PenStyle.DashLine)
        pen_cross.setCosmetic(True)
        h_line = QGraphicsLineItem(scene_pos.x() - cross_size, scene_pos.y(), scene_pos.x() + cross_size, scene_pos.y())
        h_line.setPen(pen_cross)
        h_line.setZValue(999)
        self.addItem(h_line)
        self._rotate_helper_items.append(h_line)
        v_line = QGraphicsLineItem(scene_pos.x(), scene_pos.y() - cross_size, scene_pos.x(), scene_pos.y() + cross_size)
        v_line.setPen(pen_cross)
        v_line.setZValue(999)
        self.addItem(v_line)
        self._rotate_helper_items.append(v_line)

    def begin_rotate(self):
        """进入旋转模式：以上一张图对应点位的位置为起始，以选中点位中心为默认旋转中心，角度归零。"""
        if not self._selected_point_ids:
            return

        prev_points = self.node_points[self.active_node - 1]
        source_points = [
            p for p in prev_points
            if int(p.get("id", -1)) in self._selected_point_ids
        ]
        if not source_points:
            return

        min_x = min(float(p["x"]) for p in source_points)
        max_x = max(float(p["x"]) for p in source_points)
        min_y = min(float(p["y"]) for p in source_points)
        max_y = max(float(p["y"]) for p in source_points)
        self._rotate_center_point = ((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
        self._rotate_angle = 0.0
        self._rotate_source_points = [dict(p) for p in source_points]
        self._rotate_dragging = False

    def set_rotate_angle(self, angle: float):
        """设置旋转角度并刷新预览。"""
        self._rotate_angle = float(angle)
        self._refresh_rotate_preview()

    def _refresh_rotate_preview(self):
        """根据当前旋转中心和角度更新选中点位的预览位置（不写回 node_points）。"""
        if self.active_tool != "旋转":
            return
        cx, cy = self._rotate_center_point
        angle_deg = self._rotate_angle
        for src in self._rotate_source_points:
            pid = int(src.get("id", -1))
            item = self._point_items_by_id.get(pid)
            if item is None:
                continue
            rx, ry = _field_rotate_point(
                (float(src["x"]), float(src["y"])),
                (cx, cy),
                angle_deg,
            )
            item.setPos(self._field_to_scene(rx, ry))
            # 同步标签位置
            label = self._label_items_by_id.get(pid)
            if label is not None:
                pos = self._field_to_scene(rx, ry)
                angle_label = int(self.label_pos) % 360
                angle_rad = math.radians(angle_label)
                dx = math.cos(angle_rad) * float(self.label_offset)
                dy = math.sin(angle_rad) * float(self.label_offset)
                br = label.boundingRect()
                label.setPos(pos.x() + dx - br.width() / 2.0, pos.y() + dy - br.height() / 2.0)

        # 绘制原始位置到预览位置的弧线（仅绘制第一个点位的弧线）
        for item in getattr(self, "_adjustment_preview_line_items", []):
            self.removeItem(item)
        self._adjustment_preview_line_items = []
        if abs(angle_deg) > 1e-6 and self._rotate_source_points:
            src = self._rotate_source_points[0]
            pid = int(src.get("id", -1))
            rx, ry = _field_rotate_point(
                (float(src["x"]), float(src["y"])),
                (cx, cy),
                angle_deg,
            )
            # 沿旋转路径插值采样，构建弧线
            steps = 30
            path = QPainterPath()
            start_pt = self._field_to_scene(float(src["x"]), float(src["y"]))
            path.moveTo(start_pt)
            for i in range(1, steps + 1):
                t = i / steps
                interp_angle = angle_deg * t
                ix, iy = _field_rotate_point(
                    (float(src["x"]), float(src["y"])),
                    (cx, cy),
                    interp_angle,
                )
                path.lineTo(self._field_to_scene(ix, iy))

            arc_item = QGraphicsPathItem(path)
            pen = QPen(QColor("#000000"), 1)
            pen.setCosmetic(True)
            arc_item.setPen(pen)
            arc_item.setZValue(885)
            self.addItem(arc_item)
            self._adjustment_preview_line_items.append(arc_item)

        self._refresh_selected_group_links()
        self._draw_rotate_helpers()

    def _on_rotate_center_moved(self, scene_pos: QPointF) -> QPointF:
        """旋转中心 helper 拖动时更新中心点并刷新预览。"""
        fx, fy = self._scene_to_field(scene_pos)
        fx, fy = self._snap_field_point(fx, fy)
        self._rotate_center_point = (float(fx), float(fy))
        self._refresh_rotate_preview()
        return self._field_to_scene(fx, fy)

    def confirm_rotate(self):
        """确认旋转：将旋转后的点位写回 node_points，记录 node_paths。"""
        if self.active_tool != "旋转" or not self._rotate_source_points:
            return
        cx, cy = self._rotate_center_point
        angle_deg = self._rotate_angle
        members = []
        for src in self._rotate_source_points:
            pid = int(src.get("id", -1))
            members.append(pid)
            rx, ry = _field_rotate_point(
                (float(src["x"]), float(src["y"])),
                (cx, cy),
                angle_deg,
            )
            p = self._find_point_in_node(self.active_node, pid)
            if p is not None:
                p["x"] = float(rx)
                p["y"] = float(ry)

        self.clear_selected_point_in_path(self.active_node)
        self._upsert_node_path_entry(
            self.active_node,
            'rotate',
            anchor_id=sorted(members)[0],
            members=members,
            rotate_info=((float(cx), float(cy)), float(angle_deg)),
        )
        self._clear_rotate_helpers()
        self._rotate_dragging = False
        self._rotate_source_points = []
        self._rotate_angle = 0.0
        self.node_manual_edited[self.active_node] = True
        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
        self._render_points_for_active_node()
        self.dataChanged.emit()

    def cancel_rotate(self):
        """取消旋转：恢复原始点位位置，保留原始快照供后续编辑。"""
        self._rotate_dragging = False
        self._rotate_angle = 0.0
        # 同步界面上旋转角度旋钮置 0
        parent = self.parent()
        dock = getattr(parent, "drawingControlDock", None) if parent is not None else None
        if dock is not None:
            dock.setRotateAngle(0.0)
        # 清理预览连线
        for item in getattr(self, "_adjustment_preview_line_items", []):
            self.removeItem(item)
        self._adjustment_preview_line_items = []
        # 使用原始点位快照恢复视觉位置（不写回 node_points，不清除 _rotate_source_points）
        for src in self._rotate_source_points:
            pid = int(src.get("id", -1))
            item = self._point_items_by_id.get(pid)
            if item is None:
                continue
            item.setPos(self._field_to_scene(float(src["x"]), float(src["y"])))
            # 同步标签位置
            label = self._label_items_by_id.get(pid)
            if label is not None:
                pos = self._field_to_scene(float(src["x"]), float(src["y"]))
                angle_deg = int(self.label_pos) % 360
                angle_rad = math.radians(angle_deg)
                dx = math.cos(angle_rad) * float(self.label_offset)
                dy = math.sin(angle_rad) * float(self.label_offset)
                br = label.boundingRect()
                label.setPos(pos.x() + dx - br.width() / 2.0, pos.y() + dy - br.height() / 2.0)
        self._refresh_selected_group_links()
        # 重新绘制 helper，保持可继续编辑的状态
        self._draw_rotate_helpers()

    # ──────────────── 箭头工具 ────────────────

    def _enter_arrow_mode(self):
        """进入箭头编辑模式：复制当前节点的 node_arrows 到预览列表。"""
        node_idx = self.active_node
        src_arrows = self.node_arrows.get(node_idx, [])
        self._arrow_preview = [
            {
                'type': a.get('type', 'line'),
                'points': [tuple(p) for p in a.get('points', [])],
                'style': dict(a.get('style', {'forward': True, 'backward': False, 'mid': False})),
            }
            for a in src_arrows
        ]
        self._arrow_editing_index = 0
        self._arrow_pending_points = []
        self._clear_arrow_items()
        if self._arrow_preview:
            self._new_arrow_from_current()

    def _exit_arrow_mode(self):
        """退出箭头编辑模式，清空临时状态。"""
        # 若有未完成的草稿箭头，先完成它
        self._finalize_arrow_draft()
        self._arrow_preview = []
        self._arrow_editing_index = 0
        self._arrow_pending_points = []
        self._clear_arrow_items()

    def _clear_arrow_items(self):
        """清除箭头相关图元。"""
        for item in self._arrow_items + self._arrow_handle_items + self._arrow_draft_preview_items:
            self.removeItem(item)
        self._arrow_items = []
        self._arrow_handle_items = []
        self._arrow_draft_preview_items = []

    def _clear_arrow_draft_preview_items(self):
        """仅清除箭头草稿预览线（不触碰手柄）。"""
        for item in self._arrow_draft_preview_items:
            self.removeItem(item)
        self._arrow_draft_preview_items = []

    def _clear_arrow_draft_handles(self):
        """仅清除箭头草稿手柄（不触碰预览线）。"""
        for item in self._arrow_handle_items:
            self.removeItem(item)
        self._arrow_handle_items = []

    def _current_arrow_entry(self) -> dict | None:
        """获取当前编辑的箭头条目。"""
        if 0 <= self._arrow_editing_index < len(self._arrow_preview):
            return self._arrow_preview[self._arrow_editing_index]
        return None

    def _on_arrow_clicked(self, arrow_index: int):
        """点击已有 ArrowItem 时切换到该箭头。"""
        if self.active_tool != "箭头":
            return
        if 0 <= int(arrow_index) < len(self._arrow_preview):
            self._arrow_editing_index = int(arrow_index)
            self._arrow_pending_points = []
            self._render_points_for_active_node()
            self._sync_arrow_dock_state()

    def _sync_arrow_dock_state(self):
        """将当前箭头状态同步到控制台。"""
        parent = self.parent()
        dock = getattr(parent, "drawingControlDock", None)
        if dock is None:
            return
        entry = self._current_arrow_entry()
        # 同步箭头类型下拉框
        type_map = {'line': 0, 'curve': 1, 'circle': 2}
        arrow_type = entry.get('type', 'line') if entry else 'line'
        dock.arrowTypeCombo.blockSignals(True)
        dock.arrowTypeCombo.setCurrentIndex(type_map.get(arrow_type, 0))
        dock.arrowTypeCombo.blockSignals(False)
        # 同步勾选框
        style = entry.get('style', {}) if entry else {}
        dock.arrowForwardCheck.blockSignals(True)
        dock.arrowForwardCheck.setChecked(bool(style.get('forward', True)))
        dock.arrowForwardCheck.blockSignals(False)
        
        dock.arrowBackwardCheck.blockSignals(True)
        dock.arrowBackwardCheck.setChecked(bool(style.get('backward', False)))
        dock.arrowBackwardCheck.blockSignals(False)
        
        dock.arrowMidCheck.blockSignals(True)
        dock.arrowMidCheck.setChecked(bool(style.get('mid', False)))
        dock.arrowMidCheck.blockSignals(False)
        # 删除按钮可用状态
        dock.setDeleteArrowEnabled(entry is not None)
        # 新箭头按钮：当前节点有已确认箭头，或当前预览箭头已绘制 ≥2 点时可用（已确认点数 + 草稿点数）
        has_confirmed = bool(self.node_arrows.get(self.active_node))
        total_points = (len(entry.get('points', [])) if entry else 0) + len(self._arrow_pending_points)
        current_ready = entry is not None and total_points >= 2
        dock.setNewArrowEnabled(has_confirmed or current_ready)

    def _on_arrow_setting_changed(self):
        """控制台中箭头类型或样式改变时，更新当前编辑箭头并刷新预览。"""
        if self.active_tool != "箭头":
            return
        parent = self.parent()
        dock = getattr(parent, "drawingControlDock", None)
        if dock is None:
            return

        entry = self._current_arrow_entry()
        if entry is None:
            return

        # 读取类型
        type_text = dock.arrowTypeCombo.currentText()
        type_map = {'折线': 'line', '曲线': 'curve', '圆': 'circle'}
        entry['type'] = type_map.get(type_text, 'line')

        # 读取样式
        entry['style'] = {
            'forward': dock.arrowForwardCheck.isChecked(),
            'backward': dock.arrowBackwardCheck.isChecked(),
            'mid': dock.arrowMidCheck.isChecked(),
        }
        
        if entry['type'] == 'circle':
            # 圆形强制取前两个点，超出部分丢弃（包括参考点）
            entry['points'] = entry.get('points', [])[:2]
            self._arrow_pending_points = self._arrow_pending_points[:2]

        self._render_points_for_active_node()
        # dataChanged 由调用方（主窗口）在需要持久化时单独触发，此处仅刷新预览。

    def _delete_current_arrow(self):
        """删除当前编辑的箭头。"""
        if self.active_tool != "箭头":
            return
        if 0 <= self._arrow_editing_index < len(self._arrow_preview):
            del self._arrow_preview[self._arrow_editing_index]
            if self._arrow_editing_index >= len(self._arrow_preview):
                self._arrow_editing_index = max(0, len(self._arrow_preview) - 1)
            self._arrow_pending_points = []
            self._render_points_for_active_node()
            self._sync_arrow_dock_state()
            self.dataChanged.emit()

    def _new_arrow_from_current(self):
        """暂存当前箭头（保留在预览中），开始绘制下一个新箭头。
        若已存在 points 为空的箭头，则切换到该箭头而非新建。"""
        if self.active_tool != "箭头":
            return
        # 先完成当前草稿
        self._finalize_arrow_draft()
        self._arrow_pending_points = []
        # 先查找是否已存在 points 为空的箭头
        for idx, entry in enumerate(self._arrow_preview):
            if not entry.get('points') or len(entry['points']) == 0:
                self._arrow_editing_index = idx
                self._render_points_for_active_node()
                self._sync_arrow_dock_state()
                return
        # 不存在空箭头时才新建
        self._arrow_editing_index = len(self._arrow_preview)
        self._arrow_preview.append({
            'type': 'line',
            'points': [],
            'style': {'forward': True, 'backward': False, 'mid': False},
        })
        self._render_points_for_active_node()
        self._sync_arrow_dock_state()

    def _draw_arrow_items(self):
        """在场景中绘制所有预览箭头。"""
        self._clear_arrow_items()
        if self.active_tool != "箭头":
            return

        for idx, entry in enumerate(self._arrow_preview):
            pts = entry.get('points', [])
            if not pts:
                continue
            # 将 field 坐标转为 scene 坐标
            scene_pts = [(self._field_to_scene(x, y).x(), self._field_to_scene(x, y).y()) for x, y in pts]
            arrow_item = ArrowItem(
                arrow_index=idx,
                arrow_type=entry.get('type', 'line'),
                points=scene_pts,
                style=entry.get('style', {}),
                clicked_callback=self._on_arrow_clicked,
                is_current=(idx == self._arrow_editing_index),
            )
            self.addItem(arrow_item)
            self._arrow_items.append(arrow_item)

        # 为当前编辑箭头的参考点绘制手柄
        entry = self._current_arrow_entry()
        if entry is not None:
            for pi, (fx, fy) in enumerate(entry.get('points', [])):
                scene_pos = self._field_to_scene(fx, fy)
                handle = ReferenceHandleItem(
                    index=pi,
                    center_scene_pos=scene_pos,
                    moved_callback=self._on_arrow_handle_moved,
                )
                self.addItem(handle)
                self._arrow_handle_items.append(handle)

    def _on_arrow_handle_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        """箭头参考点手柄拖动时更新当前箭头点位并直接刷新 ArrowItem 路径。"""
        if self._updating_arrow:
            return scene_pos
        entry = self._current_arrow_entry()
        if entry is None:
            return scene_pos
        x, y = self._scene_to_field(scene_pos)
        x, y = self._snap_field_point(x, y)
        pts = entry.get('points', [])
        if 0 <= int(index) < len(pts):
            pts[int(index)] = (float(x), float(y))
        # 直接更新已有 ArrowItem 的路径，不重建
        for item in self._arrow_items:
            if isinstance(item, ArrowItem) and item.arrow_index == self._arrow_editing_index:
                scene_pts = [(self._field_to_scene(px, py).x(), self._field_to_scene(px, py).y()) for px, py in pts]
                item.set_arrow_data(entry.get('type', 'line'), scene_pts, entry.get('style', {}))
                break
        return self._field_to_scene(x, y)

    def _draw_arrow_draft_preview_lines(self):
        """仅绘制箭头草稿的预览线（不绘制手柄），供拖动时调用。"""
        if self.active_tool != "箭头" or len(self._arrow_pending_points) < 2:
            return

        refs = self._arrow_pending_points
        pen = QPen(QColor("#d35400"), 1.3, Qt.PenStyle.DashLine)
        pen.setCosmetic(True)

        arrow_type = 'line'
        entry = self._current_arrow_entry()
        if entry:
            arrow_type = entry.get('type', 'line')

        item = None
        if arrow_type == 'line':
            # 多段折线预览
            path = QPainterPath()
            path.moveTo(self._field_to_scene(*refs[0]))
            for p in refs[1:]:
                path.lineTo(self._field_to_scene(*p))
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(890)
        elif arrow_type == 'curve':
            # 平滑曲线预览（≥3 点用 Catmull-Rom，2 点即直线）
            path = QPainterPath()
            path.moveTo(self._field_to_scene(*refs[0]))
            if len(refs) == 2:
                path.lineTo(self._field_to_scene(*refs[1]))
            else:
                n = len(refs)
                for i in range(n - 1):
                    p0 = refs[i - 1] if i - 1 >= 0 else refs[i]
                    p1 = refs[i]
                    p2 = refs[i + 1]
                    p3 = refs[i + 2] if i + 2 < n else refs[i + 1]
                    c1x = p1[0] + (p2[0] - p0[0]) / 6.0
                    c1y = p1[1] + (p2[1] - p0[1]) / 6.0
                    c2x = p2[0] - (p3[0] - p1[0]) / 6.0
                    c2y = p2[1] - (p3[1] - p1[1]) / 6.0
                    path.cubicTo(
                        self._field_to_scene(c1x, c1y),
                        self._field_to_scene(c2x, c2y),
                        self._field_to_scene(*p2),
                    )
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            item.setZValue(890)
        elif arrow_type == 'circle' and len(refs) >= 2:
            center = self._field_to_scene(*refs[0])
            r = math.hypot(refs[0][0] - refs[1][0], refs[0][1] - refs[1][1]) * float(self.field_info.scale)
            item = QGraphicsEllipseItem(center.x() - r, center.y() - r, r * 2, r * 2)
            item.setPen(pen)
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            item.setZValue(890)

        if item is not None:
            self.addItem(item)
            self._arrow_draft_preview_items.append(item)

        # 用 _arrow_pending_points 绘制临时箭头头预览（转换为 scene 坐标）
        if len(refs) >= 2 and entry:
            scene_pts = [(self._field_to_scene(x, y).x(), self._field_to_scene(x, y).y()) for x, y in refs]
            from src.scene_items import ArrowItem
            preview_arrow = ArrowItem(
                arrow_index=-1,
                arrow_type=arrow_type,
                points=scene_pts,
                style=entry.get('style', {'forward': True, 'backward': False, 'mid': False}),
                is_current=False,
            )
            preview_arrow.setPen(QPen(QColor("#d35400"), 1.8))
            preview_arrow.setZValue(895)
            self.addItem(preview_arrow)
            self._arrow_draft_preview_items.append(preview_arrow)

    def _draw_arrow_draft_preview(self):
        """绘制箭头工具下正在绘制中的箭头草稿预览（包含预览线和手柄）。"""
        if self.active_tool != "箭头":
            return

        self._updating_arrow = True
        # 绘制 pending points 的参考线预览
        self._draw_arrow_draft_preview_lines()

        # 为 pending points 绘制参考点手柄
        for pi, (fx, fy) in enumerate(self._arrow_pending_points):
            scene_pos = self._field_to_scene(fx, fy)
            handle = ReferenceHandleItem(
                index=pi,
                center_scene_pos=scene_pos,
                moved_callback=self._on_arrow_pending_handle_moved,
            )
            self.addItem(handle)
            self._arrow_handle_items.append(handle)
        self._updating_arrow = False

    def _on_arrow_pending_handle_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        """箭头草稿参考点拖动回调（仅刷新预览线，不重建手柄避免递归）。"""
        if self._updating_arrow:
            return scene_pos
        if 0 <= int(index) < len(self._arrow_pending_points):
            x, y = self._scene_to_field(scene_pos)
            x, y = self._snap_field_point(x, y)
            self._arrow_pending_points[int(index)] = (float(x), float(y))
            # 仅清除并重绘草稿预览线，不重建手柄
            self._clear_arrow_draft_preview_items()
            self._draw_arrow_draft_preview_lines()
            self.update()
        return self._field_to_scene(
            *self._snap_field_point(*self._scene_to_field(scene_pos)))

    def confirm_current_arrow(self):
        """确认箭头编辑：将预览写回 node_arrows。"""
        if self.active_tool != "箭头":
            return False

        # 若有正在绘制的草稿箭头，先完成它
        self._finalize_arrow_draft()

        # 清除空的箭头条目
        self._arrow_preview = [
            a for a in self._arrow_preview
            if a.get('points') and len(a.get('points', [])) >= 2
        ]

        if self._arrow_preview:
            self.node_arrows[self.active_node] = [
                {
                    'type': a['type'],
                    'points': [list(p) for p in a['points']],
                    'style': dict(a['style']),
                }
                for a in self._arrow_preview
            ]
        elif self.active_node in self.node_arrows:
            del self.node_arrows[self.active_node]

        self.node_manual_edited[self.active_node] = True
        self._arrow_pending_points = []
        # 从 node_arrows 重载 _arrow_preview，消除旧引用，确保后续渲染数据一致。
        # 外部收到 dataChanged 后会调用 set_active_tool 切换工具，
        # _exit_arrow_mode 清空 _arrow_preview，else 分支从 node_arrows 接管绘制。
        src_arrows = self.node_arrows.get(self.active_node, [])
        self._arrow_preview = [
            {
                'type': a.get('type', 'line'),
                'points': [tuple(p) for p in a.get('points', [])],
                'style': dict(a.get('style', {'forward': True, 'backward': False, 'mid': False})),
            }
            for a in src_arrows
        ]
        self._arrow_editing_index = 0
        self.dataChanged.emit()
        return True

    def cancel_current_arrow(self):
        """取消箭头编辑：丢弃所有未确认的修改，从 node_arrows 重新加载。"""
        self._arrow_pending_points = []
        # 从 node_arrows 重新加载预览，丢弃所有未确认的修改
        self._clear_arrow_items()
        self._enter_arrow_mode()
        self._render_points_for_active_node()
        self._sync_arrow_dock_state()

    def _finalize_arrow_draft(self):
        """若当前有未完成的箭头草稿，将其写入当前编辑箭头。"""
        entry = self._current_arrow_entry()
        if entry is not None and len(self._arrow_pending_points) >= 2:
            pts = [tuple(p) for p in self._arrow_pending_points]
            if entry.get('type') == 'circle':
                pts = pts[:2]
            entry['points'] = pts
        self._arrow_pending_points = []

    def _draw_interval_helpers(self):
        """在间隔行进模式下增量更新所有选中点位的 helper 圆圈。"""
        if self.active_tool != "间隔":
            self._clear_interval_helpers(full_reset=False)
            return
        if not self._selected_point_ids:
            self._clear_interval_helpers(full_reset=False)
            return

        selected_ids = set(int(pid) for pid in self._selected_point_ids)

        # step 1: 移除已被取消选中的 helper
        stale_ids = [
            pid for pid in self._interval_helper_items
            if pid is None or pid not in selected_ids
        ]
        for pid in stale_ids:
            h = self._interval_helper_items.pop(pid)
            self.removeItem(h)

        helper_radius = self.helper_radius

        # step 2: 为新增选中点创建 helper，已有则仅更新位置
        for pid in selected_ids:
            item = self._point_items_by_id.get(int(pid))
            if item is None:
                continue
            pos = item.scenePos()

            existing = self._interval_helper_items.get(int(pid))
            if existing is not None:
                existing.setPos(pos)
                # 同步更新矩形尺寸以反映 helper_radius 的变化
                existing.setRect(-helper_radius, -helper_radius, helper_radius * 2, helper_radius * 2)
                continue

            helper = QGraphicsEllipseItem(
                -helper_radius,
                -helper_radius,
                helper_radius * 2,
                helper_radius * 2,
            )
            helper.setPos(pos)
            helper.setPen(QPen(QColor("#d35400"), 1.4))
            helper.setBrush(QBrush(QColor(0, 0, 0, 0)))
            helper.setZValue(1000)
            helper.setData(0, "interval_helper")
            helper.setData(1, int(pid))
            self.addItem(helper)
            self._interval_helper_items[int(pid)] = helper

    def _on_interval_drag_started(self, point_id: int, scene_pos: QPointF):
        """间隔行进 helper 拖动开始时：记录原始位置快照并设置该点为锚点。"""
        self._interval_anchor_id = int(point_id)
        self._interval_drag_position = None
        # 切换到新锚点时，清空所有预览图元，并复原之前被移动过视觉效果的点位
        for item in getattr(self, "_pending_preview_items", []):
            self.removeItem(item)
        self._pending_preview_items = []
        self._clear_draft_items()
        # 将所有 PerformerPointItem 恢复到 node_points[active_node] 位置
        for p in self.node_points[self.active_node]:
            pid = int(p.get("id", -1))
            item = self._point_items_by_id.get(pid)
            if item is not None:
                item.setPos(self._field_to_scene(float(p.get("x", 0.0)), float(p.get("y", 0.0))))
        # helper 同步移到正确位置（不重建，避免丢失鼠标事件）
        for pid, h in self._interval_helper_items.items():
            p_item = self._point_items_by_id.get(pid)
            if p_item is not None:
                h.setPos(p_item.scenePos())
        # 以 active_node - 1 为基准记录原始位置
        src_node = max(0, self.active_node - 1)
        self._clear_draft_items()
        # 将选中点位视觉重置到上一张图位置
        self._reset_selected_points_to_prev_visual()

    def _on_interval_helper_moved(self, point_id: int, scene_pos: QPointF) -> QPointF:
        """间隔行进 helper 拖动中：计算锚点偏移并预览全组移动。"""
        fx, fy = self._scene_to_field(scene_pos)
        fx, fy = self._snap_field_point(fx, fy)

        if self._interval_anchor_id is None:
            return self._field_to_scene(fx, fy)

        anchor_id = self._interval_anchor_id
        orig = self._find_point_in_node(self.active_node - 1, anchor_id)

        # 存储拖拽位置到临时变量，不修改 node_points
        self._interval_drag_position = (fx, fy)

        # 仅同步更新 PerformerPointItem 的视觉位置（不写回 node_points）
        anchor_item = self._point_items_by_id.get(anchor_id)
        if anchor_item is not None:
            new_scene_pos = self._field_to_scene(fx, fy)
            anchor_item.setPos(new_scene_pos)

        # 同步锚点的 helper 圆圈跟随 PerformerPointItem 移动
        h = self._interval_helper_items.get(int(anchor_id))
        if h is not None:
            h.setPos(new_scene_pos)

        # 清空上一次的预览图元
        for item in getattr(self, "_pending_preview_items", []):
            self.removeItem(item)
        self._pending_preview_items = []

        # 锚点的移动向量（总共移动量）
        dx = fx - orig['x']
        dy = fy - orig['y']

        # 获取 fall/stop 设置
        parent = self.parent()
        dock = getattr(parent, "drawingControlDock", None)
        fall_count = 2
        stop_count = 0
        if dock is not None:
            fall_count = int(getattr(dock, "fallCountSpin", None).value() if getattr(dock, "fallCountSpin", None) else 2)
            stop_count = int(getattr(dock, "stopCountSpin", None).value() if getattr(dock, "stopCountSpin", None) else 0)

        # 确定锚点所在组的点位顺序
        anchor_point = self._find_point_in_node(self.active_node, anchor_id)
        if anchor_point is None:
            return self._field_to_scene(fx, fy)

        group_id = anchor_point.get("group_id")
        group_members = []
        if group_id is not None and int(group_id) < len(self.group_to_point):
            group_info = self.group_to_point[int(group_id)]
            group_members = [int(pid) for pid in group_info.get("point_ids", []) if int(pid) in self._selected_point_ids]

        if not group_members or len(group_members) < 2:
            # 无组或单点：仅移动锚点自身
            preview_points = []
            src_points = []
            for pid in self._selected_point_ids:
                # p_orig = self._interval_original_positions.get(int(pid))
                p_orig = self._find_point_in_node(self.active_node - 1, int(pid))
                if p_orig is None:
                    continue
                src_points.append({"id": int(pid), "x": p_orig['x'], "y": p_orig['y']})
                if int(pid) == int(anchor_id):
                    preview_points.append((p_orig['x'] + dx, p_orig['y'] + dy))
                else:
                    preview_points.append((p_orig['x'], p_orig['y']))
            self._draw_interval_preview(preview_points, src_points)
            return self._field_to_scene(fx, fy)

        # 找到锚点在组内的索引
        anchor_index = group_members.index(int(anchor_id))

        # 计算每个组内点的偏移量：相邻点落后 fall_count 拍
        preview_points = []
        src_points = []
        sum_beat = self._node_start_beat(self.active_node) - self._node_start_beat(self.active_node - 1)

        # 以锚点实际移动拍数为基准计算每拍位移量
        dx, dy = dx / sum_beat, dy / sum_beat

        for pid in self._selected_point_ids:
            pid = int(pid)
            p_orig = self._find_point_in_node(self.active_node - 1, pid)

            if pid not in group_members:
                # 不在同一组，保持原位
                src_points.append({"id": pid, "x": p_orig['x'], "y": p_orig['y']})
                preview_points.append((p_orig['x'], p_orig['y']))
                continue

            try:
                member_idx = group_members.index(pid)
            except ValueError:
                src_points.append({"id": pid, "x": p_orig['x'], "y": p_orig['y']})
                preview_points.append((p_orig['x'], p_orig['y']))
                continue

            # 距离锚点的索引偏移
            dist_from_anchor = abs(member_idx - anchor_index)

            # 与 _sample_point_from_node_path 的 interval 分支使用相同的拍数计算逻辑
            start_beat, end_beat = _calc_interval_beats(
                dist_from_anchor, sum_beat, fall_count, stop_count,
            )

            move_count = end_beat - start_beat if end_beat > start_beat else 0
            px = p_orig['x'] + dx * move_count
            py = p_orig['y'] + dy * move_count
            src_points.append({"id": pid, "x": p_orig['x'], "y": p_orig['y']})
            preview_points.append((px, py))

        self._draw_interval_preview(preview_points, src_points)
        return self._field_to_scene(fx, fy)

    def _confirm_interval_marching(self, had_draft: bool) -> bool:
        """确认间隔行进：将锚点移动量与间隔设置写入 node_paths。"""
        anchor_id = self._interval_anchor_id
        orig = self._find_point_in_node(self.active_node - 1, anchor_id)
        anchor_point = self._find_point_in_node(self.active_node, anchor_id)

        if anchor_point is None:
            self._clear_draft()
            self._clear_interval_helpers()
            self._pending_points = []
            if not had_draft:
                self.draftFinished.emit()
            self._render_points_for_active_node()
            self.drawingRematchStateChanged.emit()
            return False

        # 从拖拽位置读取锚点最终坐标（未写入 node_points）
        if self._interval_drag_position is not None:
            anchor_fx, anchor_fy = self._interval_drag_position
        else:
            anchor_fx, anchor_fy = float(anchor_point.get("x", 0.0)), float(anchor_point.get("y", 0.0))

        # 锚点移动量
        dx = anchor_fx - orig['x']
        dy = anchor_fy - orig['y']

        # 获取组成员
        group_id = anchor_point.get("group_id")
        members_union = list(self._selected_point_ids)
        if group_id is not None and int(group_id) < len(self.group_to_point):
            group_info = self.group_to_point[int(group_id)]
            members_union = [int(pid) for pid in group_info.get("point_ids", []) if int(pid) in self._selected_point_ids]
        else:
            members_union = [int(pid) for pid in self._selected_point_ids]

        # 获取 dock 中的 interval 设置
        parent = self.parent()
        dock = getattr(parent, "drawingControlDock", None)
        fall_count = 2
        stop_count = 0
        if dock is not None:
            fall_spin = getattr(dock, "fallCountSpin", None)
            stop_spin = getattr(dock, "stopCountSpin", None)
            if fall_spin is not None:
                fall_count = int(fall_spin.value())
            if stop_spin is not None:
                stop_count = int(stop_spin.value())

        # 先预计算各成员是否有运动节拍，过滤出活跃成员
        sum_beat = self._node_start_beat(self.active_node) - self._node_start_beat(self.active_node - 1)
        effect_range = sum_beat / (fall_count + stop_count) if (fall_count + stop_count) > 0 else 0
        active_members = []
        if effect_range == 0:
            active_members = members_union
        elif len(members_union) >= 2:
            for pid in members_union:
                try:
                    member_idx = members_union.index(pid)
                    anchor_idx = members_union.index(int(anchor_id))
                except ValueError:
                    continue
                dist_from_anchor = abs(member_idx - anchor_idx)

                # sum_beat = self._node_start_beat(self.active_node) - self._node_start_beat(self.active_node - 1)

                # start_beat, end_beat = _calc_interval_beats(
                #     dist_from_anchor, sum_beat, fall_count, stop_count,
                # )

                # 有实际运动节拍才视为活跃成员
                if dist_from_anchor < effect_range:
                    active_members.append(pid)

        # 存储路径（锚点原始位置到新位置），仅含活跃成员
        path = [(float(anchor_fx), float(anchor_fy))]

        self._upsert_node_path_entry(
            self.active_node,
            'interval',
            anchor_id,
            path,
            active_members,
            interval=(fall_count, stop_count),
        )

        # 应用活跃成员的各点最终位置
        # 计算锚点拍数基准（与预览 _on_interval_helper_moved 一致）
        anchor_idx = active_members.index(int(anchor_id))
        dx, dy = dx / sum_beat, dy / sum_beat

        for pid in active_members:
            pid = int(pid)
            p_orig = self._find_point_in_node(self.active_node - 1, pid)
            point = self._find_point_in_node(self.active_node, pid)
            if point is None:
                continue

            member_idx = active_members.index(pid)

            dist_from_anchor = abs(member_idx - anchor_idx)

            start_beat, end_beat = _calc_interval_beats(
                dist_from_anchor, sum_beat, fall_count, stop_count,
            )

            move_count = end_beat - start_beat
            point["x"] = p_orig['x'] + dx * move_count
            point["y"] = p_orig['y'] + dy * move_count

        self.sync_sampling_values_from_selection("间隔")
        self.reset_sampling_defaults("间隔")
        self._pending_points = []
        self._draft_reference_points = []
        self._reset_drawing_rematch_state(active=False)
        self.node_manual_edited[self.active_node] = True
        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
        self._clear_draft()
        self._clear_interval_helpers()
        if not had_draft:
            self.draftFinished.emit()
        self._render_points_for_active_node()
        self.drawingRematchStateChanged.emit()
        self.dataChanged.emit()
        return True

    def _draw_interval_preview(self, preview_points: list[tuple[float, float]], src_points: list[dict] | None = None):
        """绘制间隔行进的预览点位与连线。"""
        # 清除之前的预览
        for item in getattr(self, "_pending_preview_items", []):
            self.removeItem(item)
        self._pending_preview_items = []

        if not preview_points:
            return

        for px, py in preview_points:
            scene_pos = self._field_to_scene(px, py)
            r = 4.0
            dot = QGraphicsEllipseItem(
                scene_pos.x() - r,
                scene_pos.y() - r,
                r * 2,
                r * 2,
            )
            dot.setPen(QPen(QColor("#2980b9"), 1.4))
            dot.setBrush(QBrush(QColor(41, 128, 185, 120)))
            dot.setZValue(895)
            dot.setData(0, "interval_preview")
            self.addItem(dot)
            self._pending_preview_items.append(dot)
        # 绘制原始位置->预览位置的连线
        if src_points:
            self._pending_preview_items.extend(
                self._build_preview_line_items(list(preview_points), src_points, z=885)
            )

    def _refresh_interval_preview(self):
        """刷新预览。"""
        if self.active_tool != "间隔" or self._interval_anchor_id is None:
            return
        anchor_id = self._interval_anchor_id
        # 优先使用 _interval_drag_position（node_points 未写入拖拽位置）
        if self._interval_drag_position is not None:
            pos = self._field_to_scene(*self._interval_drag_position)
        else:
            anchor_point = self._find_point_in_node(self.active_node, anchor_id)
            if anchor_point is None:
                return
            pos = self._field_to_scene(float(anchor_point.get("x", 0.0)), float(anchor_point.get("y", 0.0)))
        self._on_interval_helper_moved(anchor_id, pos)

    # ———————————————————————————————————————— 分组 ———————————————————————————————————————
    def _update_temp_group_visuals(self):
        """绘制临时分组的连线与首尾 helper（仅首尾响应鼠标事件）。"""
        if self.active_tool != "分组":
            self._clear_temp_group_items()
            return
        # 先移除之前临时项目
        self._clear_temp_group_items()
        groups = self._temp_group_to_point
        grouped_point_ids = {int(pid) for group in groups for pid in group}
        # 绘制连线（使用已有函数）——只有在有临时组时绘制连线
        if groups:
            self._draw_temp_group_links(groups)

        # 为每组的首尾点添加 helper 圆（可点击区域），仅针对当前选中的点
        for idx, group in enumerate(groups):
            if not group:
                continue
            first_id = int(group[0])
            last_id = int(group[-1]) if len(group) > 1 else first_id
            for pid in (first_id, last_id):
                item = self._point_items_by_id.get(int(pid))
                if item is None:
                    continue
                pos = item.scenePos()
                helper_radius = self.helper_radius
                helper = QGraphicsEllipseItem(
                    pos.x() - helper_radius,
                    pos.y() - helper_radius,
                    helper_radius * 2,
                    helper_radius * 2,
                )
                helper.setPen(QPen(QColor("#000000"), 1.4))
                # 填充颜色：如果是当前临时组且与插入标记匹配，则填红
                is_current_group = (idx == self._temp_group_current_index)
                mark_head = self._temp_group_mark_head
                fill_red = False
                if is_current_group and group:
                    if mark_head and int(pid) == int(group[-1]):
                        fill_red = True
                    elif (not mark_head) and int(pid) == int(group[0]):
                        fill_red = True
                if fill_red:
                    helper.setBrush(QBrush(QColor("#ff4d4d")))
                else:
                    helper.setBrush(QBrush(QColor(0, 0, 0, 0)))
                helper.setZValue(240)
                helper.setData(0, "temp_group_helper")
                helper.setData(1, int(pid))
                # 兼容符号标记，供外部或导出检查使用
                helper.setData(2, "#sym:helper")
                self.addItem(helper)
                self._temp_group_helper_items.append(helper)

        # 为所有当前未归入任何组的点也添加 helper（标记为 #sym:helper）
        existing_helper_pids = {int(it.data(1)) for it in getattr(self, "_temp_group_helper_items", []) if it.data(1) is not None}
        for point in self.node_points[self.active_node]:
            pid = int(point.get("id", 0))
            if pid in grouped_point_ids:
                continue
            if pid in existing_helper_pids:
                continue
            if pid not in self._selected_point_ids:
                continue
            item = self._point_items_by_id.get(pid)
            if item is None:
                continue
            pos = item.scenePos()
            helper_radius = self.helper_radius
            helper = QGraphicsEllipseItem(
                pos.x() - helper_radius,
                pos.y() - helper_radius,
                helper_radius * 2,
                helper_radius * 2,
            )
            helper.setPen(QPen(QColor("#000000"), 1.4))
            helper.setBrush(QBrush(QColor(0, 0, 0, 0)))
            helper.setZValue(240)
            helper.setData(0, "temp_group_helper")
            helper.setData(1, pid)
            helper.setData(2, "#sym:helper")
            self.addItem(helper)
            self._temp_group_helper_items.append(helper)

    def start_temp_group_edit_from_selection(self):
        """基于当前选中点初始化临时分组：仅包含选中点本身，不扩张到原组其余点。"""
        selected = set(getattr(self, "_selected_point_ids", set()))
        if not selected:
            return
        # 保存原始快照
        selected_in_scene_order = [int(point.get("id", -1)) for point in self.node_points[self.active_node] if int(point.get("id", -1)) in selected]
        temp_groups: list[list[int]] = []
        grouped_selected_ids: set[int] = set()
        for group in self.group_to_point:
            group_selected = [int(point_id) for point_id in group.get("point_ids", []) if int(point_id) in selected]
            if group_selected:
                temp_groups.append(group_selected)
                grouped_selected_ids.update(group_selected)
        ungrouped_selected = [point_id for point_id in selected_in_scene_order if point_id not in grouped_selected_ids]
        if ungrouped_selected:
            temp_groups.append(ungrouped_selected)
        if not temp_groups:
            temp_groups = [selected_in_scene_order or sorted(int(x) for x in selected)]
        self._temp_group_to_point = temp_groups
        self._temp_group_current_index = 0
        # 重置首/尾标记为默认（tail 之后）
        self._temp_group_mark_head = True
        self._update_temp_group_visuals()
    
    def clear_temp_groups(self):
        """清空临时分组（由 dock 的重新分组按钮触发）。"""
        self._temp_group_to_point = [[]]
        self._temp_group_current_index = 0
        self._temp_group_mark_head = True
        self._clear_selection_rect()
        self._clear_temp_group_items()
        self._render_points_for_active_node()
        QTimer.singleShot(0, self._update_temp_group_visuals)

    def set_next_temp_group(self):
        """
        切换到下一临时组；若末尾则追加空组并切换到该组。
        逻辑：
            - 如果未分组的点个数 < 2，则在已有组中循环切换（不新增）。
            - 否则（未分组点数 >= 2）：
                - 若当前索引指向最后一组且该组非空，则新增空组并切换过去，同时重置标记。
                - 否则在已有组中循环切换。
        """
        # 获取当前未分组的点个数
        grouped = {int(pid) for group in self._temp_group_to_point for pid in group}
        unassigned_count = sum(1 for pid in self._selected_point_ids if pid not in grouped)

        # 当未分组点数不足2时，仅循环切换已有组
        if unassigned_count < 2:
            # 循环到下一组（至少存在一个组，否则需要提前初始化）
            self._temp_group_current_index = (self._temp_group_current_index + 1) % len(self._temp_group_to_point)
        else:
            # 未分组点数 >= 2
            total_groups = len(self._temp_group_to_point)
            current_group = self._temp_group_to_point[self._temp_group_current_index]

            # 判断是否为最后一组且当前组非空
            if self._temp_group_current_index == total_groups - 1 and current_group:
                # 新增一个空组
                self._temp_group_to_point.append([])
                # 重置标记为“tail 之后”的状态
                self._temp_group_mark_head = True
                # 切换到新组
                self._temp_group_current_index += 1
            else:
                # 循环切换到下一组
                self._temp_group_current_index = (self._temp_group_current_index + 1) % total_groups
        
        self._update_temp_group_visuals()

    def add_point_ids_to_current_temp_group(self, 
                                            src_group: list[int], # 需合并的点位 id 列表
                                            clicked_point_id: int = None): # 点击的点位 id
        """将给定点位（或组内点位）加入当前临时组。

        插入依据 `self._temp_group_mark_head`（默认视为 True）：
        - True 表示在 tail 之后（append），
        - False 表示在 head 之前（prepend）
        """
        dst_idx = self._temp_group_current_index
        dst_group = self._temp_group_to_point[dst_idx]
        dst_mark = self._temp_group_mark_head # True：tail后插入；False：head前插入
        origin_src_group = src_group
        
        if clicked_point_id == src_group[0]:
            src_mark = False    # 点击了 src 的首节点
        elif clicked_point_id == src_group[-1]:
            src_mark = True     # 点击了 src 的尾节点
        
        if dst_mark == src_mark:
            src_group = list(reversed(src_group))
            
        if dst_mark:
            self._temp_group_to_point[dst_idx].extend(src_group)
        else:
            self._temp_group_to_point[dst_idx] = src_group + dst_group

        src_idx = None
        for index, group in enumerate(self._temp_group_to_point):
            if group == origin_src_group:
                src_idx = index
                break
        if src_idx is not None and src_idx != dst_idx:
            self._temp_group_to_point.pop(src_idx)
            if src_idx < dst_idx:
                self._temp_group_current_index = dst_idx - 1 if len(src_group) > 1 else dst_idx

        self._update_temp_group_visuals()
        
    def confirm_temp_groups(self):
        """将临时分组写回到真实的 group_to_point 和 node_to_group 中。
        
        更新范围：从 self.active_node 开始，一直向后直到（但不包括）第一个手动编辑节点。
        """
        if not getattr(self, "_temp_group_to_point", None):
            return

        # ========== 1. 过滤临时分组 ==========
        filtered_temp_groups = []
        assigned_point_ids = set()
        for group in self._temp_group_to_point:
            normalized_group = []
            seen_in_group = set()
            for point_id in group:
                point_id = int(point_id)
                if point_id in seen_in_group or point_id in assigned_point_ids:
                    continue
                seen_in_group.add(point_id)
                normalized_group.append(point_id)
            if len(normalized_group) >= 2:
                filtered_temp_groups.append(normalized_group)
                assigned_point_ids.update(normalized_group)

        if not filtered_temp_groups:
            self.clear_temp_groups()
            self._render_points_for_active_node()
            return

        # ========== 2. 复用或新建分组（group_to_point） ==========
        existing_group_map = {
            tuple(int(pid) for pid in group.get("point_ids", [])): gid
            for gid, group in enumerate(self.group_to_point)
        }
        temp_group_to_group_id = {}
        for temp_group in filtered_temp_groups:
            key = tuple(temp_group)
            gid = existing_group_map.get(key)
            if gid is None:
                gid = len(self.group_to_point)
                self.group_to_point.append({
                    "point_ids": list(key),
                    "leader": True,
                })
                existing_group_map[key] = gid
            temp_group_to_group_id[key] = gid

        # ========== 3. 点 -> 新组ID 映射 ==========
        point_to_new_group = {}
        for temp_group in filtered_temp_groups:
            gid = temp_group_to_group_id[tuple(temp_group)]
            for pid in temp_group:
                point_to_new_group[int(pid)] = gid

        # ========== 4. 全局组数据迁移：保证每个点只在一个组中 ==========
        # 添加到新组
        for pid, new_gid in point_to_new_group.items():
            new_point_list = self.group_to_point[new_gid].get("point_ids", [])
            if pid not in new_point_list:
                new_point_list.append(pid)

        # ========== 5. 确定需要更新的节点范围 ==========
        # 确保 node_to_group 长度足够
        max_node_index = max(len(self.node_points) - 1, len(self.node_to_group) - 1)
        while len(self.node_to_group) <= max_node_index:
            self.node_to_group.append([])

        start_node = int(self.active_node)

        # 寻找第一个手动编辑节点（从 start_node+1 开始查找）
        first_manual_node = None
        for idx in range(start_node + 1, max_node_index + 1):
            if self.node_manual_edited[idx]:
                first_manual_node = idx
                break

        # 更新范围：从 start_node 到 end_node（不包含 end_node）
        if first_manual_node is not None:
            end_node = first_manual_node   # 不更新该手动节点
        else:
            end_node = max_node_index + 1  # 更新到最后一个节点

        # ========== 6. 执行节点数据更新（拆分旧组，而非合并） ==========
        for node_idx in range(start_node, end_node):

            node_points = self.node_points[node_idx]
            # 记录更新前的 group_id
            old_gid_by_pid = {}
            for point in node_points:
                pid = int(point.get("id", -1))
                old_gid = point.get("group_id")
                if old_gid is not None:
                    old_gid_by_pid[pid] = int(old_gid)

            # 第一步：应用临时分组的新组ID
            for pid, new_gid in point_to_new_group.items():
                for point in node_points:
                    if int(point.get("id", -1)) == pid:
                        point["group_id"] = new_gid
                        break

            # 第二步：收集所有受影响的旧组（即那些包含至少一个被临时分组修改的点的旧组）
            affected_old_groups = set()
            for pid in point_to_new_group:
                if pid in old_gid_by_pid:
                    affected_old_groups.add(old_gid_by_pid[pid])

            # 第三步：对于每个受影响的旧组，处理剩余的点
            # 记录需要新建的组（剩余点组成）: (剩余点列表) -> 新组ID
            new_remnant_group_map = {}  # tuple(sorted(remnant_pids)) -> new_gid

            for old_gid in affected_old_groups:
                # 收集该节点中所有原来属于这个旧组的点
                pids_in_old_group = [pid for pid, gid in old_gid_by_pid.items() if gid == old_gid]
                if not pids_in_old_group:
                    continue

                # 按照当前的 group_id 分组（更新后的）
                current_groups = {}  # gid -> list[pid]
                for pid in pids_in_old_group:
                    # 找到该点当前的 group_id
                    cur_gid = None
                    for point in node_points:
                        if int(point.get("id", -1)) == pid:
                            cur_gid = point.get("group_id")
                            if cur_gid is not None:
                                cur_gid = int(cur_gid)
                            break
                    if cur_gid is None:
                        cur_gid = None
                    current_groups.setdefault(cur_gid, []).append(pid)

                # 对于当前 group_id 等于 old_gid 的分组（即未被修改的剩余点）
                if old_gid in current_groups:
                    remnant_pids = current_groups[old_gid]
                    if len(remnant_pids) >= 2:
                        # 需要新建一个组
                        remnant_key = tuple(sorted(remnant_pids))
                        if remnant_key in new_remnant_group_map:
                            new_gid = new_remnant_group_map[remnant_key]
                        else:
                            # 检查全局是否已存在相同的点集
                            existing = None
                            for gid, group in enumerate(self.group_to_point):
                                if tuple(sorted(group.get("point_ids", []))) == remnant_key:
                                    existing = gid
                                    break
                            if existing is not None:
                                new_gid = existing
                            else:
                                new_gid = len(self.group_to_point)
                                self.group_to_point.append({
                                    "point_ids": list(remnant_key),
                                    "leader": True,
                                })
                            new_remnant_group_map[remnant_key] = new_gid
                        # 将剩余点的 group_id 更新为新组ID
                        for pid in remnant_pids:
                            for point in node_points:
                                if int(point.get("id", -1)) == pid:
                                    point["group_id"] = new_gid
                                    break
                    else:
                        # 剩余点数 < 2，无法成组，将它们的 group_id 设为 None
                        for pid in remnant_pids:
                            for point in node_points:
                                if int(point.get("id", -1)) == pid:
                                    point["group_id"] = None
                                    break
                # 对于其他分组（即已经变成临时分组ID的），它们已经在新组中了，无需额外操作

                # 注意：原来的 old_gid 不会被添加到 node_to_group 中（相当于被删除）

            # 第四步：重新构建 node_to_group[node_idx]（基于更新后的 group_id）
            group_ids_in_node = set()
            point_seen_in_node = set()
            for point in node_points:
                pid = int(point.get("id", -1))
                if pid in point_seen_in_node:
                    continue
                point_seen_in_node.add(pid)
                gid = point.get("group_id")
                if gid is None:
                    continue
                gid = int(gid)
                if 0 <= gid < len(self.group_to_point):
                    group_ids_in_node.add(gid)

            self.node_to_group[node_idx] = list(group_ids_in_node)

            # 第五步：同步更新全局 group_to_point（将新创建的剩余点组中的点加入，避免重复）
            for remnant_key, new_gid in new_remnant_group_map.items():
                current_list = self.group_to_point[new_gid].get("point_ids", [])
                for pid in remnant_key:
                    if pid not in current_list:
                        current_list.append(pid)
                        
        # ========== 7. 清理临时状态并刷新界面 ==========
        self.clear_temp_groups()
        self.clear_empty_group()    # 清理空组
        self.dataChanged.emit()
        self._render_points_for_active_node()

    def _refresh_selected_group_links(self):
        """根据当前选中点位重建组内连线，只连接每组中被选中的点。"""
        self._clear_selection_link_items()
        if not self._selected_point_ids:
            return

        # 连接同一组内被选中的点位，使用不透明线条。
        pen = QPen(QColor("#f39c12"), 4, Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)
        
        node_groups = self.node_to_group[self.active_node]
        if not node_groups:
            return

        for group_idx in node_groups:
            group_info = self.group_to_point[group_idx]
            if self.active_tool == "跟随":
                point_ids = self._follow_group_point_ids_for_group(group_info)
            else:
                point_ids = [int(point_id) for point_id in group_info.get("point_ids", [])]
            selected_in_group = [point_id for point_id in point_ids if point_id in self._selected_point_ids]
            if len(selected_in_group) < 2:
                continue

            previous_point_id = selected_in_group[0]
            for current_point_id in selected_in_group[1:]:
                previous_item = self._point_items_by_id.get(previous_point_id)
                current_item = self._point_items_by_id.get(current_point_id)
                if previous_item is not None and current_item is not None:
                    previous_pos = previous_item.scenePos()
                    current_pos = current_item.scenePos()
                    line_item = QGraphicsLineItem(
                        previous_pos.x(),
                        previous_pos.y(),
                        current_pos.x(),
                        current_pos.y(),
                    )
                    line_item.setPen(pen)
                    line_item.setZValue(150)
                    self.addItem(line_item)
                    self._selection_link_items.append(line_item)
                previous_point_id = current_point_id

    def _group_point_ids_for_point_id(self, point_id: int) -> list[int]:
        """获取指定点位所属组的全部点位 ID；若点位未归组则返回空列表。"""
        point = self._find_point_in_node(self.active_node, point_id)
        if point is None:
            return []

        group_value = point.get("group_id")
        if group_value is None:
            return []

        group_id = int(group_value)
        if group_id < 0 or group_id >= len(self.group_to_point):
            return []

        group_info = self.group_to_point[group_id]
        return [int(group_point_id) for group_point_id in group_info.get("point_ids", [])]

    def _temp_group_point_ids_for_point_id(self, point_id: int) -> list[int]:
        """获取指定点位在当前临时分组中的全部点位 ID；若不在临时组中则返回空列表。"""
        for group in getattr(self, "_temp_group_to_point", []) or []:
            if point_id in group:
                return group
        return []

    # ———————————————————————————————————————— 拖拽点位 ———————————————————————————————————————
    def _can_drag_performer_point(self) -> bool:
        """
        查看功能允许在任意拍位浏览
            但拖拽写回仅允许发生在“当前节点拍位”上。
            可避免在中间插值预览拍位误改真实节点点位。
        """
        if getattr(self, "_adjustment_active", False):
            return False
        return self.active_tool in {"框选", '选择'} and self._is_current_beat_editable()

    def _on_performer_point_moved(self, point_id: int, scene_pos: QPointF) -> QPointF:
        """预览拍位下禁止写回真实数据，只返回当前位置。"""
        if not self._is_current_beat_editable():
            return scene_pos

        point = self._find_point_in_node(self.active_node, point_id)
        if point is None:
            return scene_pos
        x, y = self._scene_to_field(scene_pos)
        x, y = self._snap_field_point(x, y)

        for other in self.node_points[self.active_node]:
            if int(other.get("id", -1)) == int(point_id):
                continue
            if abs(other["x"] - x) < 1e-9 and abs(other["y"] - y) < 1e-9:
                return self._field_to_scene(point["x"], point["y"])

        point["x"] = x
        point["y"] = y

        label = self._label_items_by_id.get(int(point_id))
        if label is not None:
            pos = self._field_to_scene(x, y)
            # 使用与创建时相同的参数计算偏移（角度以15°为单位）
            angle_deg = (int(self.label_pos) % 360)
            angle_rad = math.radians(angle_deg)
            dx = math.cos(angle_rad) * float(self.label_offset)
            dy = math.sin(angle_rad) * float(self.label_offset)
            br = label.boundingRect()
            label.setPos(pos.x() + dx - br.width() / 2.0, pos.y() + dy - br.height() / 2.0)

        if point_id in self._selected_point_ids:
            self._refresh_selected_group_links()
            if len(self._selected_point_ids) == 1:
                # 单点拖拽时补充“原始->当前位置”预览连线。
                self._selection_link_items.extend(self._build_preview_line_items([point]))

        return self._field_to_scene(x, y)

    def _on_performer_point_pressed(self, point_id: int | None = None):
        """点位拖拽开始（按下）：为撤销/重做记录“拖拽前”快照（会话开始）。"""
        if self.history is not None:
            self.history.begin("拖拽点位")

    def _on_performer_point_released(self, point_id: int | None = None, moved: bool = True):
        """预览拍位下禁止写回真实数据，直接返回；当前节点拍位上则标记节点为手动编辑过并触发后续自动调整。

        moved 表示拖拽过程中是否真正发生了移动：仅真实拖拽提交撤销步骤，原地点击则取消会话。
        """
        # 撤销/重做会话收尾：真实拖拽提交为一步，原地点击取消。
        if self.history is not None:
            if moved:
                self.history.commit()
            else:
                self.history.cancel()
        # 清理拖拽中附加到 selection_link 的预览连线。
        self._refresh_selected_group_links()
        if not self._is_current_beat_editable():
            return
        if not moved:
            return

        # 若拖拽过程中点位确实发生过移动，从当前节点的路径定义中清除该选中点位
        self.clear_selected_point_in_path(self.active_node)

        self.node_manual_edited[self.active_node] = True
        self._recalculate_following_auto_nodes(self.active_node)
        self.dataChanged.emit()

    def _clear_draft(self):
        """清空绘制草稿"""
        had_draft = bool(self._draft_tool_name or self._draft_reference_points)
        self._draft_tool_name = None
        self._draft_reference_points = []
        self._clear_draft_items()
        self._clear_pending_preview_items()
        if had_draft:
            self.draftFinished.emit()

    def _clear_draft_items(self):
        """清除当前草稿相关的所有图元"""
        for item in self._draft_preview_items + self._draft_handle_items:
            self.removeItem(item)
        self._draft_preview_items = []
        self._draft_handle_items = []

    def _clear_pending_preview_items(self):
        """清除待确认参考点的预览图元"""
        for item in self._pending_preview_items:
            self.removeItem(item)
        self._pending_preview_items = []

    def _clear_adjustment_items(self):
        """清除调整模式的参考框与手柄图元。"""
        if self._adjustment_frame_item is not None:
            self.removeItem(self._adjustment_frame_item)
            self._adjustment_frame_item = None
        for item in self._adjustment_handle_items:
            self.removeItem(item)
        self._adjustment_handle_items = []
        for item in getattr(self, "_adjustment_preview_line_items", []):
            self.removeItem(item)
        self._adjustment_preview_line_items = []

    def _adjustment_rotation_radians(self) -> float:
        """将角度值转换为弧度，供内部计算使用。"""
        return math.radians(float(self._adjustment_rotation))

    def _adjustment_rotation_pivot(self) -> tuple[float, float]:
        """调整旋转的中心点坐标，默认为调整参考框的中心。"""
        return (float(self._adjustment_center_handle.x()), float(self._adjustment_center_handle.y()))

    def begin_adjustment(self):
        """基于当前选中点位进入调整会话。"""
        if not self._selected_point_ids:
            self._reset_adjustment_state(reset_controls=False)
            return

        source_points = copy.deepcopy(self.node_points[self.active_node])
        self._adjustment_source_points = source_points

        selected_points = [point for point in source_points if int(point.get("id", -1)) in self._selected_point_ids]
        if not selected_points:
            self._reset_adjustment_state(reset_controls=False)
            return

        min_x = min(float(point["x"]) for point in selected_points)
        max_x = max(float(point["x"]) for point in selected_points)
        min_y = min(float(point["y"]) for point in selected_points)
        max_y = max(float(point["y"]) for point in selected_points)

        width = max(1e-6, max_x - min_x)
        height = max(1e-6, max_y - min_y)
        self._adjustment_center = QPointF((min_x + max_x) / 2.0, (min_y + max_y) / 2.0)
        self._adjustment_center_handle = QPointF(self._adjustment_center.x(), self._adjustment_center.y())
        self._adjustment_half_size = QPointF(width / 2.0, height / 2.0)
        self._adjustment_corners_local = [
            (-width / 2.0, -height / 2.0),
            (width / 2.0, -height / 2.0),
            (width / 2.0, height / 2.0),
            (-width / 2.0, height / 2.0),
        ]
        self._adjustment_preview_points = self._build_adjustment_preview_points()
        self._adjustment_active = True
        self._clear_adjustment_items()
        self._render_points_for_active_node()

    def set_adjustment_mode(self, mode_name: str):
        """设置调整模式：比例、伸展、倾斜、歪曲；切换模式时会重新计算预览点位并刷新显示。"""
        if mode_name not in {"比例", "伸展", "倾斜", "歪曲"}:
            return
        self._adjustment_mode = mode_name
        if self._adjustment_active:
            self._adjustment_preview_points = self._build_adjustment_preview_points()
            self._render_points_for_active_node()

    def set_adjustment_rotation(self, angle: float):
        """设置调整旋转角度（度）；切换角度时会重新计算预览点位并刷新显示。"""
        self._adjustment_rotation = float(angle)
        if self._adjustment_active:
            self._adjustment_preview_points = self._build_adjustment_preview_points()
            self._render_points_for_active_node()

    def refresh_adjustment_preview(self):
        """在调整会话中强制刷新预览点位并重绘，适用于外部参数变化（如调整框大小）后需要更新预览的场景。"""
        if not self._adjustment_active:
            return
        self._adjustment_preview_points = self._build_adjustment_preview_points()
        self._render_points_for_active_node()

    def confirm_current_adjustment(self):
        """将当前调整预览点位写回节点数据，并标记节点为手动编辑过以触发后续自动调整；如果未处于调整会话中则无操作。"""
        if not self._adjustment_active:
            return
        if not self._adjustment_preview_points:
            self._adjustment_preview_points = self._build_adjustment_preview_points()

        self.clear_selected_point_in_path(self.active_node)
        
        current_points = self.node_points[self.active_node]
        # 若存在选中点集合，则按索引匹配仅移动匹配到的原点位；否则保持旧逻辑全部替换
        if self._selected_point_ids:
            src_ordered = [p for p in self._adjustment_source_points if int(p.get("id", -1)) in self._selected_point_ids]
            dst_ordered = [p for p in self._adjustment_preview_points if int(p.get("id", -1)) in self._selected_point_ids]
            id_to_index = {int(p.get("id", -1)): idx for idx, p in enumerate(current_points)}
            match_count = min(len(src_ordered), len(dst_ordered))
            for i in range(match_count):
                sid = int(src_ordered[i].get("id", -1))
                dst = dst_ordered[i]
                if sid in id_to_index:
                    idx = id_to_index[sid]
                    current_points[idx]["x"] = float(dst.get("x", 0.0))
                    current_points[idx]["y"] = float(dst.get("y", 0.0))
            # 更新调整源快照为当前节点的最新状态
            self._adjustment_source_points = [dict(point) for point in current_points]
        else:
            current_points[:] = [
                {"id": int(point["id"]), "x": float(point["x"]), "y": float(point["y"]), **({"group_id": point.get("group_id")} if point.get("group_id") is not None else {})}
                for point in self._adjustment_preview_points
            ]
            self._adjustment_source_points = [dict(point) for point in self._adjustment_preview_points]
        self.node_manual_edited[self.active_node] = True
        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
        self._render_points_for_active_node()
        self.dataChanged.emit()

    def cancel_current_adjustment(self):
        """取消当前调整会话，重置预览点位为初始状态并刷新显示；如果未处于调整会话中则无操作。"""
        if not self._adjustment_active:
            self._reset_adjustment_state(reset_controls=True)
            return
        self._reset_adjustment_state(reset_controls=True)
        if self.active_tool == "调整" and self._selected_point_ids:
            self.begin_adjustment()
        self._render_points_for_active_node()

    def _build_adjustment_preview_points(self, reset_to_source: bool = False) -> list[dict]:
        """根据当前调整模式、旋转角度和参考框参数计算预览点位；如果 reset_to_source 为 True 则直接返回初始状态的点位快照。"""
        if not self._adjustment_source_points:
            return []

        selected_points = [point for point in self._adjustment_source_points if int(point.get("id", -1)) in self._selected_point_ids]
        if not selected_points:
            return [dict(point) for point in self._adjustment_source_points]

        if len(selected_points) == 1:
            center_x = float(self._adjustment_center.x())
            center_y = float(self._adjustment_center.y())
            preview_points = []
            selected_id = int(selected_points[0].get("id", -1))
            for point in self._adjustment_source_points:
                point_id = int(point.get("id", -1))
                if point_id == selected_id:
                    transformed = {"id": point_id, "x": center_x, "y": center_y}
                    if point.get("group_id") is not None:
                        transformed["group_id"] = point.get("group_id")
                    preview_points.append(transformed)
                else:
                    preview_points.append(dict(point))
            return preview_points

        if reset_to_source:
            return [dict(point) for point in self._adjustment_source_points]

        center = (float(self._adjustment_center.x()), float(self._adjustment_center.y()))
        angle = self._adjustment_rotation_radians()
        pivot = self._adjustment_rotation_pivot()
        local_corners = list(self._adjustment_corners_local)
        current_corners = []
        for x, y in local_corners:
            base_x = center[0] + x
            base_y = center[1] + y
            current_corners.append(_field_rotate_point((base_x, base_y), pivot, self._adjustment_rotation))

        min_x = min(float(point["x"]) for point in selected_points)
        max_x = max(float(point["x"]) for point in selected_points)
        min_y = min(float(point["y"]) for point in selected_points)
        max_y = max(float(point["y"]) for point in selected_points)
        width = max(1e-6, max_x - min_x)
        height = max(1e-6, max_y - min_y)

        preview_points = []
        for point in self._adjustment_source_points:
            point_id = int(point.get("id", -1))
            if point_id not in self._selected_point_ids:
                preview_points.append(dict(point))
                continue

            u = (float(point["x"]) - min_x) / width
            v = (float(point["y"]) - min_y) / height
            local_x, local_y = _bilinear_point(local_corners, u, v)
            base_x = center[0] + local_x
            base_y = center[1] + local_y
            world_x, world_y = _field_rotate_point((base_x, base_y), pivot, self._adjustment_rotation)
            transformed = {"id": point_id, "x": world_x, "y": world_y}
            if point.get("group_id") is not None:
                transformed["group_id"] = point.get("group_id")
            preview_points.append(transformed)
        return preview_points

    def _sync_adjustment_handle_positions(self):
        """根据当前调整参考框参数同步更新调整手柄的位置；在批量更新过程中会设置 _updating_adjustment_handles 标记以避免触发不必要的回调与重绘。"""
        if not self._adjustment_handle_items or not self._adjustment_active:
            return
        if len(self._adjustment_handle_items) != 5:
            return
        self._updating_adjustment_handles = True
        try:
            center = (float(self._adjustment_center.x()), float(self._adjustment_center.y()))
            pivot = self._adjustment_rotation_pivot()
            for handle, (lx, ly) in zip(self._adjustment_handle_items[:4], self._adjustment_corners_local):
                base_x = center[0] + lx
                base_y = center[1] + ly
                world_x, world_y = _field_rotate_point((base_x, base_y), pivot, self._adjustment_rotation)
                handle.setPos(self._field_to_scene(world_x, world_y))
            center_handle = self._adjustment_handle_items[4]
            center_handle.setPos(self._field_to_scene(float(self._adjustment_center_handle.x()), float(self._adjustment_center_handle.y())))
        finally:
            self._updating_adjustment_handles = False

    def _sync_adjustment_frame_item(self):
        """根据当前中心、旋转和局部角点更新调整框路径，避免拖拽时重建图元。"""
        if self._adjustment_frame_item is None:
            return
        center = (float(self._adjustment_center.x()), float(self._adjustment_center.y()))
        pivot = self._adjustment_rotation_pivot()
        corners = []
        for lx, ly in self._adjustment_corners_local:
            base_x = center[0] + lx
            base_y = center[1] + ly
            world_x, world_y = _field_rotate_point((base_x, base_y), pivot, self._adjustment_rotation)
            corners.append(self._field_to_scene(world_x, world_y))
        if len(corners) != 4:
            return
        path = QPainterPath()
        path.moveTo(corners[0])
        for point in corners[1:]:
            path.lineTo(point)
        path.closeSubpath()
        self._adjustment_frame_item.setPath(path)

    def _build_preview_line_items(self, dst_points: list, src_points: list[dict] = [], *, z: float = 200) -> list:
        """根据目标点位集构建原始->目标的连线图元。"""
        line_items = []
        if not dst_points:
            return line_items

        if isinstance(dst_points[0], dict):
            src_map = {
                int(point.get("id", -1)): (float(point.get("x", 0.0)), float(point.get("y", 0.0)))
                for point in src_points
            }
            for point in dst_points:
                point_id = int(point.get("id", -1))
                src = src_map.get(point_id)
                if src is None:
                    continue
                sx, sy = src
                dx = float(point.get("x", 0.0))
                dy = float(point.get("y", 0.0))
                if abs(sx - dx) <= 1e-12 and abs(sy - dy) <= 1e-12:
                    continue

                s_scene = self._field_to_scene(sx, sy)
                e_scene = self._field_to_scene(dx, dy)
                line_item = QGraphicsLineItem(s_scene.x(), s_scene.y(), e_scene.x(), e_scene.y())
                pen = QPen(QColor("#000000"), 1)
                pen.setCosmetic(True)
                line_item.setPen(pen)
                line_item.setZValue(z)
                self.addItem(line_item)
                line_items.append(line_item)
            return line_items

        match_count = min(len(src_points), len(dst_points))
        for i in range(match_count):
            src = src_points[i]
            dst = dst_points[i]
            sx, sy = float(src.get("x", 0.0)), float(src.get("y", 0.0))
            dx = float(dst[0])
            dy = float(dst[1])
            if abs(sx - dx) <= 1e-12 and abs(sy - dy) <= 1e-12:
                continue

            s_scene = self._field_to_scene(sx, sy)
            e_scene = self._field_to_scene(dx, dy)
            line_item = QGraphicsLineItem(s_scene.x(), s_scene.y(), e_scene.x(), e_scene.y())
            pen = QPen(QColor("#000000"), 1)
            pen.setCosmetic(True)
            line_item.setPen(pen)
            line_item.setZValue(z)
            self.addItem(line_item)
            line_items.append(line_item)

        return line_items

    def _sync_adjustment_preview_items(self):
        """将调整预览坐标增量同步到已存在点位/标签图元，减少拖拽卡顿。"""
        if not self._adjustment_preview_points:
            return
        if not self._point_items_by_id:
            self._render_points_for_active_node()
            return
        # 清理旧的原始->预览 线条
        for item in getattr(self, "_adjustment_preview_line_items", []):
            self.removeItem(item)
        self._adjustment_preview_line_items = []

        for point in self._adjustment_preview_points:
            point_id = int(point.get("id", -1))
            # 仅对选中的点进行绘制
            if point_id not in self._selected_point_ids:
                continue
            item = self._point_items_by_id.get(point_id)
            if item is None:
                continue
            pos = self._field_to_scene(float(point["x"]), float(point["y"]))
            item.setPos(pos)

            label = self._label_items_by_id.get(point_id)
            if label is None:
                continue
            angle_deg = (int(self.label_pos) % 360)
            angle_rad = math.radians(angle_deg)
            dx = math.cos(angle_rad) * float(self.label_offset)
            dy = math.sin(angle_rad) * float(self.label_offset)
            br = label.boundingRect()
            label.setPos(pos.x() + dx - br.width() / 2.0, pos.y() + dy - br.height() / 2.0)

        dst_ordered = [p for p in self._adjustment_preview_points if int(p.get("id", -1)) in self._selected_point_ids]
        self._adjustment_preview_line_items = self._build_preview_line_items(dst_ordered, self._adjustment_source_points)

    def _refresh_adjustment_drag_visuals(self):
        """拖拽中进行轻量刷新：更新预览点位、选中连线、调整框和句柄位置。"""
        self._sync_adjustment_preview_items()
        self._refresh_selected_group_links()
        self._sync_adjustment_frame_item()
        self._sync_adjustment_handle_positions()

    def _on_adjustment_handle_drag_started(self, index: int, scene_pos: QPointF, part: str | None = None):
        """记录拖拽起点快照，保证位移以拖拽前位置为参考。"""
        if not self._adjustment_active:
            return
        center = (float(self._adjustment_center.x()), float(self._adjustment_center.y()))
        start_field = self._scene_to_field(scene_pos)
        start_field = self._snap_field_point(*start_field)
        state = {
            "kind": "center" if index == 4 else "corner",
            "index": int(index),
            "part": part,
            "start_field": start_field,
            "start_center": center,
            "start_center_handle": (float(self._adjustment_center_handle.x()), float(self._adjustment_center_handle.y())),
            "start_corners_local": [tuple(c) for c in self._adjustment_corners_local],
            "start_corner_fields": [],
            "start_half_size": (
                max(1e-6, float(self._adjustment_half_size.x())),
                max(1e-6, float(self._adjustment_half_size.y())),
            ),
            "rotation": float(self._adjustment_rotation),
            "mode": self._adjustment_mode,
        }
        pivot = self._adjustment_rotation_pivot()
        for lx, ly in self._adjustment_corners_local:
            base_x = center[0] + lx
            base_y = center[1] + ly
            state["start_corner_fields"].append(_field_rotate_point((base_x, base_y), pivot, self._adjustment_rotation))
        if index >= 0 and index <= 3 and index < len(self._adjustment_corners_local):
            lx, ly = self._adjustment_corners_local[index]
            base_x = center[0] + lx
            base_y = center[1] + ly
            state["start_corner_field"] = _field_rotate_point((base_x, base_y), pivot, self._adjustment_rotation)
        self._adjustment_drag_state = state

    def _on_adjustment_handle_drag_finished(self, index: int, scene_pos: QPointF, part: str | None = None):
        """清理拖拽快照。"""
        self._adjustment_drag_state = None

    def _draw_adjustment_overlay(self):
        """在调整会话中绘制参考框与手柄；根据当前调整参数计算参考框四角的场景坐标并绘制框线图元，同时在四角和中心位置绘制可拖动的手柄图元；如果未处于调整会话中则不进行任何操作。"""
        if not self._adjustment_active:
            return

        self._clear_adjustment_items()
        center = (float(self._adjustment_center.x()), float(self._adjustment_center.y()))
        pivot = self._adjustment_rotation_pivot()
        corners = []
        for lx, ly in self._adjustment_corners_local:
            base_x = center[0] + lx
            base_y = center[1] + ly
            world_x, world_y = _field_rotate_point((base_x, base_y), pivot, self._adjustment_rotation)
            corners.append(self._field_to_scene(world_x, world_y))

        if len(corners) == 4:
            path = QPainterPath()
            path.moveTo(corners[0])
            for point in corners[1:]:
                path.lineTo(point)
            path.closeSubpath()
            frame_item = QGraphicsPathItem(path)
            frame_item.setPen(QPen(QColor(210, 84, 0, 180), 1.4, Qt.PenStyle.DashLine))
            frame_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            frame_item.setZValue(960)
            self.addItem(frame_item)
            self._adjustment_frame_item = frame_item

        self._updating_adjustment_handles = True
        try:
            for index, corner in enumerate(corners):
                handle = ReferenceHandleItem(
                    index = index,
                    center_scene_pos = corner,
                    moved_callback=self._on_adjustment_corner_moved,
                    drag_started_callback=self._on_adjustment_handle_drag_started,
                    drag_finished_callback=self._on_adjustment_handle_drag_finished,
                )
                handle.setBrush(QBrush(QColor(210, 84, 0, 40)))
                handle.setPen(QPen(QColor(210, 84, 0), 1.2))
                handle.set_size(ReferenceHandleItem.default_size)
                handle.setZValue(970)
                self.addItem(handle)
                self._adjustment_handle_items.append(handle)

            center_handle = MovementControlHandleItem(
                4,
                self._field_to_scene(float(self._adjustment_center_handle.x()), float(self._adjustment_center_handle.y())),
                outer_moved_callback=self._on_adjustment_center_moved,
                inner_moved_callback=self._on_adjustment_center_inner_moved,
                drag_started_callback=self._on_adjustment_handle_drag_started,
                drag_finished_callback=self._on_adjustment_handle_drag_finished,
            )
            center_handle.setBrush(QBrush(QColor(39, 174, 96, 70)))
            center_handle.setPen(QPen(QColor(39, 174, 96), 1.2))
            center_handle.set_size(MovementControlHandleItem.default_size)
            center_handle.set_inner_ratio(MovementControlHandleItem.default_inner_ratio)
            center_handle.setZValue(975)
            self.addItem(center_handle)
            self._adjustment_handle_items.append(center_handle)
        finally:
            self._updating_adjustment_handles = False

    def _on_adjustment_center_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        """调整中心点移动回调，根据新的场景坐标计算调整中心的场地坐标并更新预览点位；在批量更新过程中或调整未激活时会直接返回原始场景坐标以避免触发不必要的回调与重绘。"""
        if self._updating_adjustment_handles or not self._adjustment_active:
            return scene_pos
        field_pos = self._scene_to_field(scene_pos)
        field_pos = self._snap_field_point(*field_pos)
        state = self._adjustment_drag_state
        if state and state.get("kind") == "center" and int(state.get("index", -1)) == 4 and state.get("part") == "outer":
            sx, sy = state.get("start_field", field_pos)
            hx, hy = state.get("start_center_handle", (float(self._adjustment_center_handle.x()), float(self._adjustment_center_handle.y())))
            dx = field_pos[0] - sx
            dy = field_pos[1] - sy
            field_pos = self._snap_field_point(hx + dx, hy + dy)
        else:
            self._adjustment_drag_state = None

        self._adjustment_center_handle = QPointF(*field_pos)
        return self._field_to_scene(*field_pos)

    def _on_adjustment_center_inner_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        """内圈移动回调：移动选中点位并更新预览。

        - 圆心吸附格点（与外圈相同），
        - 只更新预览状态，不写回原始点位数据，确认时再统一提交。
        """
        if self._updating_adjustment_handles or not self._adjustment_active:
            return scene_pos
        new_field = self._scene_to_field(scene_pos)
        new_field = self._snap_field_point(*new_field)
        state = self._adjustment_drag_state

        if state and state.get("kind") == "center" and int(state.get("index", -1)) == 4 and state.get("part") == "inner":
            sx, sy = state.get("start_field", new_field)
            start_hx, start_hy = state.get("start_center_handle", (float(self._adjustment_center_handle.x()), float(self._adjustment_center_handle.y())))
            start_cx, start_cy = state.get("start_center", (float(self._adjustment_center.x()), float(self._adjustment_center.y())))
            dx = new_field[0] - sx
            dy = new_field[1] - sy
            new_handle = self._snap_field_point(start_hx + dx, start_hy + dy)
            delta_x = new_handle[0] - start_hx
            delta_y = new_handle[1] - start_hy
            new_center = (start_cx + delta_x, start_cy + delta_y)
        else:
            self._adjustment_drag_state = None
            current_handle = (float(self._adjustment_center_handle.x()), float(self._adjustment_center_handle.y()))
            current_center = (float(self._adjustment_center.x()), float(self._adjustment_center.y()))
            delta_x = new_field[0] - current_handle[0]
            delta_y = new_field[1] - current_handle[1]
            new_handle = new_field
            new_center = (current_center[0] + delta_x, current_center[1] + delta_y)

        old_center = (float(self._adjustment_center.x()), float(self._adjustment_center.y()))
        old_handle = (float(self._adjustment_center_handle.x()), float(self._adjustment_center_handle.y()))
        if (
            abs(new_center[0] - old_center[0]) <= 1e-12
            and abs(new_center[1] - old_center[1]) <= 1e-12
            and abs(new_handle[0] - old_handle[0]) <= 1e-12
            and abs(new_handle[1] - old_handle[1]) <= 1e-12
        ):
            return self._field_to_scene(*new_handle)

        self._adjustment_center = QPointF(*new_center)
        self._adjustment_center_handle = QPointF(*new_handle)
        self._adjustment_preview_points = self._build_adjustment_preview_points()
        self._refresh_adjustment_drag_visuals()
        return self._field_to_scene(*new_handle)

    def _on_adjustment_corner_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        """调整角点移动回调，根据新的场景坐标计算调整框的局部坐标并更新预览点位；在批量更新过程中、调整未激活或索引无效时会直接返回原始场景坐标以避免触发不必要的回调与重绘。"""
        if self._updating_adjustment_handles or not self._adjustment_active:
            return scene_pos
        if index < 0 or index > 3:
            return scene_pos

        center = (float(self._adjustment_center.x()), float(self._adjustment_center.y()))
        field_pos = self._scene_to_field(scene_pos)
        field_pos = self._snap_field_point(*field_pos)
        state = self._adjustment_drag_state
        if state and state.get("kind") == "corner" and int(state.get("index", -1)) == int(index):
            sx, sy = state.get("start_field", field_pos)
            corner_start = state.get("start_corner_field", field_pos)
            dx = field_pos[0] - sx
            dy = field_pos[1] - sy
            field_pos = self._snap_field_point(corner_start[0] + dx, corner_start[1] + dy)
        else:
            self._adjustment_drag_state = None

        pivot = self._adjustment_rotation_pivot()
        local_pos = _field_rotate_point(field_pos, pivot, -self._adjustment_rotation)
        lx = local_pos[0] - center[0]
        ly = local_pos[1] - center[1]
        state = self._adjustment_drag_state
        if state and state.get("kind") == "corner" and int(state.get("index", -1)) == int(index):
            base_hw, base_hh = state.get("start_half_size", (max(1e-6, float(self._adjustment_half_size.x())), max(1e-6, float(self._adjustment_half_size.y()))))
            base_corners_local = [tuple(c) for c in state.get("start_corners_local", self._adjustment_corners_local)]
        else:
            base_hw = max(1e-6, float(self._adjustment_half_size.x()))
            base_hh = max(1e-6, float(self._adjustment_half_size.y()))
            base_corners_local = [tuple(c) for c in self._adjustment_corners_local]

        if self._adjustment_mode == "比例":
            scale = max(abs(lx) / base_hw, abs(ly) / base_hh, 0.1)
            hw = base_hw * scale
            hh = base_hh * scale
            self._adjustment_corners_local = [
                (-hw, -hh),
                (hw, -hh),
                (hw, hh),
                (-hw, hh),
            ]
        elif self._adjustment_mode == "伸展":
            shift_pressed = bool(QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier)
            if shift_pressed and state and state.get("kind") == "corner" and int(state.get("index", -1)) == int(index):
                start_corner_fields = state.get("start_corner_fields", [])
                opposite_index = (index + 2) % 4
                if len(start_corner_fields) > opposite_index:
                    fixed_field = start_corner_fields[opposite_index]
                    center_field = ((field_pos[0] + fixed_field[0]) / 2.0, (field_pos[1] + fixed_field[1]) / 2.0)
                    fixed_local = _field_rotate_point(fixed_field, center_field, -self._adjustment_rotation)
                    dragged_local = _field_rotate_point(field_pos, center_field, -self._adjustment_rotation)
                    half_x = max(1e-6, abs(dragged_local[0] - fixed_local[0]) / 2.0)
                    half_y = max(1e-6, abs(dragged_local[1] - fixed_local[1]) / 2.0)
                    self._adjustment_center = QPointF(*center_field)
                    self._adjustment_half_size = QPointF(half_x, half_y)
                    self._adjustment_corners_local = [
                        (-half_x, -half_y),
                        (half_x, -half_y),
                        (half_x, half_y),
                        (-half_x, half_y),
                    ]
                else:
                    hw = max(1e-6, abs(lx))
                    hh = max(1e-6, abs(ly))
                    self._adjustment_corners_local = [
                        (-hw, -hh),
                        (hw, -hh),
                        (hw, hh),
                        (-hw, hh),
                    ]
            else:
                hw = max(1e-6, abs(lx))
                hh = max(1e-6, abs(ly))
                self._adjustment_corners_local = [
                    (-hw, -hh),
                    (hw, -hh),
                    (hw, hh),
                    (-hw, hh),
                ]
        elif self._adjustment_mode == "倾斜":
            if state and state.get("kind") == "corner" and int(state.get("index", -1)) == int(index):
                start_corner_fields = [tuple(point) for point in state.get("start_corner_fields", [])]
            else:
                angle = self._adjustment_rotation_radians()
                start_corner_fields = []
                for corner_lx, corner_ly in base_corners_local:
                    corner_rx, corner_ry = _rotate_vector(corner_lx, corner_ly, angle)
                    start_corner_fields.append((center[0] + corner_rx, center[1] + corner_ry))

            if len(start_corner_fields) != 4:
                return scene_pos

            moved_index = int(index) % 4
            clockwise_index = (moved_index + 1) % 4
            drag_start_field = start_corner_fields[moved_index]
            drag_dx = field_pos[0] - drag_start_field[0]
            drag_dy = field_pos[1] - drag_start_field[1]

            updated_corner_fields = [tuple(point) for point in start_corner_fields]
            updated_corner_fields[moved_index] = tuple(field_pos)
            next_start_x, next_start_y = start_corner_fields[clockwise_index]
            updated_corner_fields[clockwise_index] = self._snap_field_point(next_start_x + drag_dx, next_start_y + drag_dy)

            center_field = (
                sum(point[0] for point in updated_corner_fields) / 4.0,
                sum(point[1] for point in updated_corner_fields) / 4.0,
            )
            updated_corners_local = []
            for corner_field in updated_corner_fields:
                local_corner = _field_rotate_point(corner_field, center_field, -self._adjustment_rotation)
                updated_corners_local.append((local_corner[0] - center_field[0], local_corner[1] - center_field[1]))

            local_xs = [corner[0] for corner in updated_corners_local]
            local_ys = [corner[1] for corner in updated_corners_local]
            self._adjustment_center = QPointF(*center_field)
            self._adjustment_half_size = QPointF(
                max(1e-6, (max(local_xs) - min(local_xs)) / 2.0),
                max(1e-6, (max(local_ys) - min(local_ys)) / 2.0),
            )
            self._adjustment_corners_local = updated_corners_local
        else:
            self._adjustment_corners_local = list(base_corners_local)
            self._adjustment_corners_local[index] = (lx, ly)

        self._adjustment_preview_points = self._build_adjustment_preview_points()
        self._refresh_adjustment_drag_visuals()
        return self._field_to_scene(*field_pos)

    def _clear_draft_preview_items(self):
        """仅清除草稿预览图元，保留可拖动参考点。"""
        for item in self._draft_preview_items:
            self.removeItem(item)
        self._draft_preview_items = []

    def _sync_draft_handle_positions(self):
        """把已有拖拽手柄的位置同步到当前参考点坐标。"""
        if len(self._draft_handle_items) != len(self._draft_reference_points):
            return
        self._updating_draft_handles = True
        skip_first = self.active_tool in {"路径", '跟随'}
        for handle, (x, y) in zip(self._draft_handle_items[1 if skip_first else 0:], self._draft_reference_points[1 if skip_first else 0:]):
            handle.setPos(self._field_to_scene(x, y))
        self._updating_draft_handles = False

    def _sync_pending_handle_positions(self):
        """把已有待确认参考点手柄同步到当前参考点坐标。"""
        if len(self._draft_handle_items) != len(self._pending_points):
            return
        self._updating_draft_handles = True
        for handle, (x, y) in zip(self._draft_handle_items, self._pending_points):
            handle.setPos(self._field_to_scene(x, y))
        self._updating_draft_handles = False

    def _refresh_reference_overlay_for_active_tool(self):
        """重建当前参考点相关图元，避免拖动后残留旧图元。"""
        if self._adjustment_active:
            self._clear_adjustment_items()
            self._draw_adjustment_overlay()
            return

        if self._draft_tool_name:
            self._clear_draft_preview_items()
            self._sync_draft_handle_positions()
            self._draw_draft_preview()
            return

        if self.active_tool == "曲线/折线" and self._pending_points:
            self._clear_pending_preview_items()
            self._sync_pending_handle_positions()
            self._draw_pending_reference_preview()
            return

        self._render_points_for_active_node()

    def _pending_reference_graphic_item(self):
        """构建未确认阶段的实时参考线图元（当前用于曲线/折线工具）。"""
        if self.active_tool != "曲线/折线" or len(self._pending_points) < 2:
            return None

        refs = self._pending_points
        pen = QPen(QColor(210, 84, 0, 170), 1.3, Qt.PenStyle.DashLine)

        if getattr(self, '_curve_mode', 'polyline') == 'curve':
            path = QPainterPath()
            start = self._field_to_scene(*refs[0])
            path.moveTo(start)
            n = len(refs)
            for i in range(n - 1):
                p0 = refs[i - 1] if i - 1 >= 0 else refs[i]
                p1 = refs[i]
                p2 = refs[i + 1]
                p3 = refs[i + 2] if i + 2 < n else refs[i + 1]

                p0s = self._field_to_scene(*p0)
                p1s = self._field_to_scene(*p1)
                p2s = self._field_to_scene(*p2)
                p3s = self._field_to_scene(*p3)

                c1x = p1s.x() + (p2s.x() - p0s.x()) / 6.0
                c1y = p1s.y() + (p2s.y() - p0s.y()) / 6.0
                c2x = p2s.x() - (p3s.x() - p1s.x()) / 6.0
                c2y = p2s.y() - (p3s.y() - p1s.y()) / 6.0

                path.cubicTo(QPointF(c1x, c1y), QPointF(c2x, c2y), self._field_to_scene(*p2))
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            return item

        path = QPainterPath()
        path.moveTo(self._field_to_scene(*refs[0]))
        for x, y in refs[1:]:
            path.lineTo(self._field_to_scene(x, y))
        item = QGraphicsPathItem(path)
        item.setPen(pen)
        return item

    def _draw_pending_reference_preview(self):
        """绘制未确认阶段的参考线预览（当前用于曲线/折线工具）。"""
        self._clear_pending_preview_items()
        item = self._pending_reference_graphic_item()
        if item is not None:
            item.setZValue(890)
            self.addItem(item)
            self._pending_preview_items.append(item)

        if self.active_tool == "文本" and len(self._textbox_pending_points) == 1 and self._textbox_hover_scene_pos is not None:
            # 绘制文本框预览
            start_scene = self._field_to_scene(*self._textbox_pending_points[0])
            preview_rect = QRectF(start_scene, self._textbox_hover_scene_pos).normalized()
            if preview_rect.width() > 1e-6 and preview_rect.height() > 1e-6:
                textbox_pen = QPen(QColor(210, 84, 0, 170), 1.3, Qt.PenStyle.DashLine)
                textbox_item = QGraphicsRectItem(preview_rect)
                textbox_item.setPen(textbox_pen)
                textbox_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
                textbox_item.setZValue(890)
                self.addItem(textbox_item)
                self._pending_preview_items.append(textbox_item)

        # 未确认阶段同样显示参考线与预览点位。
        if self.active_tool == "曲线/折线" and len(self._pending_points) >= 2:
            preview_points = self._generate_performer_points("曲线/折线", self._pending_points)
            rematch_snapshot = self._drawing_rematch_snapshot()
            if rematch_snapshot["active"]:
                dots = self._render_preview_points_for_drawing_rematch(preview_points)
            else:
                dots = self.render_preview_points(preview_points)
            for d in dots:
                self._pending_preview_items.append(d)

        # 路径工具：显示路径线（可选择折线或平滑曲线），并绘制路径点用于预览；路径不依赖点位个数/间距设置
        if self.active_tool in {"路径", "跟随"} and len(self._pending_points) >= 2:
            pts = list(self._pending_points)
            if getattr(self, '_curve_mode', 'polyline') == 'curve':
                pts_path = _build_dense_curve_points(pts, float(self.field_info.grid_step))
            else:
                pts_path = pts
            if pts_path:
                pen = QPen(QColor(210, 84, 0, 170), 1.3, Qt.PenStyle.DashLine)
                path = QPainterPath()
                path.moveTo(self._field_to_scene(*pts_path[0]))
                for x, y in pts_path[1:]:
                    path.lineTo(self._field_to_scene(x, y))
                path_item = QGraphicsPathItem(path)
                path_item.setPen(pen)
                path_item.setZValue(890)
                self.addItem(path_item)
                self._pending_preview_items.append(path_item)
                # 绘制路径点的预览小圆点
                dots = self.render_preview_points(pts_path)
                for d in dots:
                    self._pending_preview_items.append(d)
                # 如果存在选中点，则为选中点生成按锚点到路径最后一点的整体平移预览（不写回数据）

                src_points = [self._find_point_in_node(self.active_node - 1, int(pid)) for pid in self._selected_point_ids]
                if src_points and src_points[0] is not None:
                    base_x = float(src_points[0].get("x", 0.0))
                    base_y = float(src_points[0].get("y", 0.0))
                    last_px, last_py = pts_path[-1]
                    tx = float(last_px) - float(base_x)
                    ty = float(last_py) - float(base_y)
                    preview_points = []
                    for p in src_points:
                        if p is None:
                            preview_points.append((0.0, 0.0))
                        else:
                            ox = float(p.get("x", 0.0))
                            oy = float(p.get("y", 0.0))
                            preview_points.append((ox + tx, oy + ty))
                    # 使用与 render_preview_points 相同的渲染风格绘制选中点的平移预览
                    moved_dots = self.render_preview_points(preview_points, pen_color="#2980b9", brush_color=(41, 128, 185, 120), z=895)
                    for d in moved_dots:
                        self._pending_preview_items.append(d)

    def _update_textbox_hover_preview(self, scene_pos: QPointF):
        """更新文本框第一参考点后的鼠标吸附位置，并重绘预览矩形。"""
        if self.active_tool != "文本" or len(self._textbox_pending_points) != 1:
            return
        x, y = self._scene_to_field(scene_pos)
        x, y = self._snap_field_point(x, y)
        snapped_scene_pos = self._field_to_scene(x, y)
        if self._textbox_hover_scene_pos is not None:
            same_x = abs(self._textbox_hover_scene_pos.x() - snapped_scene_pos.x()) <= 1e-9
            same_y = abs(self._textbox_hover_scene_pos.y() - snapped_scene_pos.y()) <= 1e-9
            if same_x and same_y:
                return
        self._textbox_hover_scene_pos = snapped_scene_pos
        self._clear_pending_preview_items()
        self._draw_pending_reference_preview()

    def _sample_curve_points_with_count(self, points: list[tuple[float, float]], point_count: int) -> list[tuple[float, float]]:
        """基于 Catmull-Rom 样条生成平滑曲线，并按目标点数重新采样。"""
        dense = _build_dense_curve_points(points, float(self.field_info.grid_step))
        if len(dense) < 2:
            return dense[:]

        return _sample_polyline_points_with_count(dense, point_count)

    def set_curve_mode(self, mode: str):
        """设置曲线绘制模式：'polyline' 或 'curve'。"""
        if mode not in ('polyline', 'curve'):
            return
        self._curve_mode = mode
        # 仅在草稿态下即时重绘，避免打断 pending 参考点的显示状态。
        if self._draft_tool_name:
            self._clear_draft_preview_items()
            self._draw_draft_overlay()
        else:
            self._draw_pending_reference_preview()
        self.update()

    def _sample_polygon_perimeter_points(self, center: tuple[float, float], radius_point: tuple[float, float], spacing: float) -> list[tuple[float, float]]:
        """多边形绘制点位预览"""
        vertices = _make_polygon_points(center, radius_point, self.polygon_side_count("多边形"))
        if not vertices:
            return []
        points = _sample_closed_polyline_points_with_spacing(vertices, spacing)
        return points

    def _sample_polygon_perimeter_points_with_count(self, center: tuple[float, float], radius_point: tuple[float, float], point_count: int) -> list[tuple[float, float]]:
        """按点位个数采样多边形周长点位"""
        vertices = _make_polygon_points(center, radius_point, self.polygon_side_count("多边形"))
        if not vertices:
            return []
        return _sample_closed_polyline_points_with_count(vertices, point_count)

    def _generate_performer_points(self, tool_name: str, refs: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """根据当前草稿工具和参考点生成最终的执行点位列表（field 坐标）。"""
        spacing = max(1e-9, float(self.field_info.grid_step) * 2.0)
        # 支持路径绘制工具——返回原始参考点或按曲线模式平滑后的点（不使用间距/点数设置）
        if tool_name in {"路径", "跟随"}:
            is_curve = getattr(self, '_curve_mode', 'polyline') == 'curve'
            if is_curve:
                dense = _build_dense_curve_points(refs, float(self.field_info.grid_step))
                return dense if dense else []
            return list(refs)
        if tool_name == "点" and refs:
            return refs
        if tool_name in self._sampling_tools and len(refs) >= 2:
            state = self._sampling_state(tool_name)
            line_spacing = max(1e-9, float(self.field_info.grid_step) * float(state["spacing_steps"]))
            point_count = max(1, int(state["point_count"]))

            if tool_name == "线段":
                # 统一线段为折线/多段线的采样逻辑：将两点视为一段折线，复用折线/曲线采样函数
                is_curve = False
                # 与曲线/折线分支保持一致的优先级：手动间距+手动点数 -> 手动点数 -> 手动间距 -> 自动间距
                if state.get("spacing_manual", False) and state.get("point_count_manual", False):
                    return _sample_polyline_points_with_count_and_spacing(refs, point_count, line_spacing)
                if state.get("spacing_manual", False):
                    return _sample_polyline_points(refs, line_spacing)
                if state.get("point_count_manual", False):
                    return _sample_polyline_points_with_count(refs, point_count)
                return _sample_polyline_points(refs, line_spacing)
            elif tool_name == "弧":
                if state.get("point_count_manual", False) and state.get("spacing_manual", False):
                    return _sample_arc_points_with_count_and_spacing(refs[0], refs[2], refs[1], point_count, line_spacing)
                if state.get("point_count_manual", False):
                    return _sample_arc_points_with_count(refs[0], refs[2], refs[1], point_count)
                return _sample_arc_points(refs[0], refs[2], refs[1], line_spacing)
            elif tool_name == "圆":
                if state["point_count_manual"]:
                    return _sample_circle_points_with_count(refs[0], refs[1], point_count)
                return _sample_circle_points(refs[0], refs[1], line_spacing)
            elif tool_name == "多边形":
                if state["point_count_manual"]:
                    return self._sample_polygon_perimeter_points_with_count(refs[0], refs[1], point_count)
                return self._sample_polygon_perimeter_points(refs[0], refs[1], line_spacing)
            elif tool_name == "曲线/折线" and len(refs) >= 2:
                is_curve = getattr(self, '_curve_mode', 'polyline') == 'curve'
                if state["spacing_manual"] and state["point_count_manual"]:
                    if is_curve:
                        dense_curve = _build_dense_curve_points(refs, line_spacing)
                        return _sample_polyline_points_with_count_and_spacing(dense_curve, point_count, line_spacing)
                    return _sample_polyline_points_with_count_and_spacing(refs, point_count, line_spacing)
                if state["spacing_manual"]:
                    if is_curve:
                        return _sample_curve_points(refs, line_spacing)
                    return _sample_polyline_points(refs, line_spacing)
                if state["point_count_manual"]:
                    if is_curve:
                        return self._sample_curve_points_with_count(refs, point_count)
                    return _sample_polyline_points_with_count(refs, point_count)
                if is_curve:
                    return _sample_curve_points(refs, line_spacing)
                return _sample_polyline_points(refs, line_spacing)
            elif tool_name == "填充四边形" and len(refs) >= 3:
                state = self._sampling_state(tool_name)
                base_spacing = max(1e-9, float(self.field_info.grid_step) * float(state.get("spacing_steps", 2.0)))
                shift_spacing = max(1e-9, float(self.field_info.grid_step) * float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0))))
                base_point_count = int(state.get("point_count", 1))
                shift_point_count = int(state.get("point_count_shift", 1))
                return _sample_rectangle_fill_points_with_counts(refs[0], refs[1], refs[2], base_spacing, shift_spacing, base_point_count, shift_point_count)
        return []

    def render_preview_points(self, preview_points: list[tuple[float, float]], *, pen_color: str = "#d35400", brush_color: tuple = (243, 156, 18, 90), z: float = 900) -> list:
        """渲染接口：在场景上为给定的 field 单位点位创建预览小圆点图元并返回创建的图元列表（不修改外部列表）。"""
        items = []
        for x, y in preview_points:
            pos = self._field_to_scene(x, y)
            item = QGraphicsEllipseItem(pos.x() - 3.5, pos.y() - 3.5, 7.0, 7.0)
            item.setPen(QPen(QColor(pen_color), 1))
            item.setBrush(QBrush(QColor(*brush_color)))
            item.setZValue(z)
            self.addItem(item)
            items.append(item)
        
        # 若存在已选点集，按索引匹配原点位->新点位并绘制连线以保持连贯性
        if self._selected_point_ids and self.active_tool not in {"路径", '跟随'}:
            current_points = self.node_points[self.active_node]
            src_ordered = [p for p in current_points if int(p.get("id", -1)) in self._selected_point_ids]
            items.extend(self._build_preview_line_items(list(preview_points), src_ordered, z=z - 10))
        
        return items

    def _render_preview_points_for_drawing_rematch(self, preview_points: list[tuple[float, float]], *, z: float = 900) -> list:
        """在重匹配流程下渲染预览点和已确认的匹配连线。"""
        snapshot = self._drawing_rematch_snapshot()
        items = []
        committed_indexes = set(snapshot.get("committed_preview_indexes", set()))
        current_index = snapshot.get("current_preview_index")

        for index, (x, y) in enumerate(preview_points):
            pos = self._field_to_scene(x, y)
            item = QGraphicsEllipseItem(pos.x() - 3.5, pos.y() - 3.5, 7.0, 7.0)
            if snapshot["active"] and current_index is not None and int(index) == int(current_index):
                item.setPen(QPen(QColor("#c0392b"), 1.2))
                item.setBrush(QBrush(QColor("#e74c3c")))
            elif int(index) in committed_indexes:
                item.setPen(QPen(QColor("#27ae60"), 1.2))
                item.setBrush(QBrush(QColor(39, 174, 96, 140)))
            else:
                item.setPen(QPen(QColor("#d35400"), 1))
                item.setBrush(QBrush(QColor(243, 156, 18, 90)))
            item.setZValue(z)
            self.addItem(item)
            items.append(item)

        dst_ordered = []
        for point_id, preview_index in sorted(snapshot.get("point_to_preview", {}).items(), key=lambda item: int(item[1])):
            idx = int(preview_index)
            if idx < 0 or idx >= len(preview_points):
                continue
            dx, dy = preview_points[idx]
            dst_ordered.append({"id": int(point_id), "x": dx, "y": dy})
        items.extend(self._build_preview_line_items(dst_ordered, self.node_points[self.active_node], z=z - 10))

        return items

    def _reference_graphic_item(self):
        """根据当前草稿工具和参考点生成草稿参考图形的 QGraphicsItem（field 坐标转换为 scene 坐标）。仅用于草稿预览显示，不参与最终点位计算。"""
        if not self._draft_tool_name or self._draft_tool_name == "点" or not self._draft_reference_points:
            return None

        pen = QPen(QColor(210, 84, 0, 170), 1.3, Qt.PenStyle.DashLine)
        refs = self._draft_reference_points

        if self._draft_tool_name == "线段" and len(refs) >= 2:
            p1 = self._field_to_scene(*refs[0])
            p2 = self._field_to_scene(*refs[1])
            item = QGraphicsLineItem(p1.x(), p1.y(), p2.x(), p2.y())
            item.setPen(pen)
            return item

        if self._draft_tool_name == "曲线/折线" and len(refs) >= 2:
            # 根据当前模式选择参考图形：折线或平滑曲线
            if getattr(self, '_curve_mode', 'polyline') == 'curve':
                # 构造 Catmull-Rom -> Bezier 的平滑路径用于草稿参考
                pts = refs
                path = QPainterPath()
                start = self._field_to_scene(*pts[0])
                path.moveTo(start)
                n = len(pts)
                for i in range(n - 1):
                    p0 = pts[i - 1] if i - 1 >= 0 else pts[i]
                    p1 = pts[i]
                    p2 = pts[i + 1]
                    p3 = pts[i + 2] if i + 2 < n else pts[i + 1]

                    p0s = self._field_to_scene(*p0)
                    p1s = self._field_to_scene(*p1)
                    p2s = self._field_to_scene(*p2)
                    p3s = self._field_to_scene(*p3)

                    c1x = p1s.x() + (p2s.x() - p0s.x()) / 6.0
                    c1y = p1s.y() + (p2s.y() - p0s.y()) / 6.0
                    c2x = p2s.x() - (p3s.x() - p1s.x()) / 6.0
                    c2y = p2s.y() - (p3s.y() - p1s.y()) / 6.0

                    path.cubicTo(QPointF(c1x, c1y), QPointF(c2x, c2y), self._field_to_scene(*p2))

                item = QGraphicsPathItem(path)
                item.setPen(pen)
                return item
            else:
                path = QPainterPath()
                start = self._field_to_scene(*refs[0])
                path.moveTo(start)
                for x, y in refs[1:]:
                    path.lineTo(self._field_to_scene(x, y))
                item = QGraphicsPathItem(path)
                item.setPen(pen)
                return item

        if self._draft_tool_name == "弧" and len(refs) >= 3:
            start_scene = self._field_to_scene(*refs[0])
            end_scene = self._field_to_scene(*refs[1])
            through_scene = self._field_to_scene(*refs[2])

            path = _arc_path_from_three_points(
                (start_scene.x(), start_scene.y()),
                (through_scene.x(), through_scene.y()),
                (end_scene.x(), end_scene.y()),
            )

            center = _circumcenter(
                (start_scene.x(), start_scene.y()),
                (through_scene.x(), through_scene.y()),
                (end_scene.x(), end_scene.y()),
            )
            if center is not None:
                cx, cy = center
                radius = math.hypot(start_scene.x() - cx, start_scene.y() - cy)
                if radius > 1e-9:
                    # 草稿参考层额外显示参考圆和圆心十字。
                    path.addEllipse(QRectF(cx - radius, cy - radius, radius * 2, radius * 2))
                    marker = 4.0
                    path.moveTo(cx - marker, cy)
                    path.lineTo(cx + marker, cy)
                    path.moveTo(cx, cy - marker)
                    path.lineTo(cx, cy + marker)

            item = QGraphicsPathItem(path)
            item.setPen(pen)
            return item

        if self._draft_tool_name == "填充四边形" and len(refs) >= 3:
            return None

        if self._draft_tool_name == "圆" and len(refs) >= 2:
            center = self._field_to_scene(*refs[0])
            radius = _distance(refs[0], refs[1]) * float(self.field_info.scale)
            item = QGraphicsEllipseItem(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            item.setPen(pen)
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            return item

        if self._draft_tool_name == "多边形" and len(refs) >= 2:
            center = self._field_to_scene(*refs[0])
            radius = _distance(refs[0], refs[1]) * float(self.field_info.scale)
            item = QGraphicsEllipseItem(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            item.setPen(pen)
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            return item

        return None

    def _start_draft(self, tool_name: str, refs: list[tuple[float, float]]):
        """进入草稿确认阶段，等待控制台确认或取消。"""
        self._draft_tool_name = tool_name
        self._draft_reference_points = list(refs)
        self._reset_drawing_rematch_state(active=False)
        self._clear_pending_preview_items()
        if tool_name in self._sampling_tools:
            self._sync_sampling_auto_values_from_draft(tool_name)
        self._render_points_for_active_node()
        self.draftStarted.emit(tool_name)
        self.drawingRematchStateChanged.emit()

    def _on_reference_handle_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        """草稿参考点被移动时的回调，用于更新参考点位置和草稿预览图形。返回更新后的 scene_pos（可能被吸附）。"""
        if self._updating_draft_handles:
            return scene_pos
        if index < 0 or index >= len(self._draft_reference_points):
            return scene_pos
        # 路径/跟随工具的首个参考点是固定锚点，不允许拖动。
        if self._draft_tool_name in {"路径", "跟随"} and index == 0:
            return self._field_to_scene(*self._draft_reference_points[0])
        x, y = self._scene_to_field(scene_pos)
        x, y = self._snap_field_point(x, y)
        snapped_scene_pos = self._field_to_scene(x, y)
        self._draft_reference_points[index] = (x, y)
        if self._draft_tool_name in {"路径", "跟随"}:
            # 路径工具后续新增参考点依赖 _pending_points，需同步更新避免回退到旧坐标。
            self._pending_points[index] = (x, y)
        if self._draft_tool_name in self._sampling_tools:
            self._sync_sampling_auto_values_from_draft(self._draft_tool_name)
        QTimer.singleShot(0, self._refresh_reference_overlay_for_active_tool)
        self.drawingRematchStateChanged.emit()
        return snapped_scene_pos

    def clear_selected_point_in_path(self, node_idx: int):
        """清空 path 内的选中点位（仅限当前节点）"""
        if node_idx not in self.node_paths.keys():
            return
        
        new_paths = []
        for path_info in self.node_paths[node_idx]:
            members = path_info['members']
            # 不在 selected_point_ids 中的点位才保留在原 path 中
            new_member = [id for id in members if id not in self._selected_point_ids]
            if new_member:
                if len(new_member) != len(members):
                    # 成员不一致时，需要更新路径信息
                    path_info['members'] = new_member   # 更新成员列表
                    path_type = path_info['type']
                    if path_type == 'interval': # 间隔行进单独计算
                        if path_info['anchor_id'] not in new_member:
                            old_anchor = self._find_point_in_node(node_idx - 1, path_info['anchor_id'])
                            path_info['anchor_id'] = new_member[0]
                            new_anchor = self._find_point_in_node(node_idx - 1, path_info['anchor_id'])
                            dx = new_anchor['x'] - old_anchor['x']
                            dy = new_anchor['y'] - old_anchor['y']
                            path_info['path'] = [(px + dx, py + dy) for px, py in path_info['path']]
                            
                    elif path_type != 'rotate': # rotate 类型不需要更新 anchor_id
                        # 参考 _get_anchor 的查找规则：从 new_member 中按组排序选择 anchor
                        cur_node_points = self.node_points[node_idx]
                        active_groups = list({cur_node_points[id]['group_id'] for id in new_member})
                        if active_groups:
                            min_gid = min(active_groups)
                            min_group = self.group_to_point[min_gid]
                            ordered_ids = self._follow_group_point_ids_for_group(min_group)
                            new_anchor_id = next(
                                (pid for pid in ordered_ids if pid in new_member),
                                new_member[0],
                            )
                        else:
                            new_anchor_id = sorted(new_member)[0]
                        old_anchor_id = path_info['anchor_id']
                        path_info['anchor_id'] = new_anchor_id
                        # path 中的每个点位加上原 anchor 到现 anchor 的向量（基于上一节点位置）
                        old_anchor = self._find_point_in_node(node_idx - 1, old_anchor_id)
                        new_anchor = self._find_point_in_node(node_idx - 1, new_anchor_id)
                        dx = new_anchor['x'] - old_anchor['x']
                        dy = new_anchor['y'] - old_anchor['y']
                        path_info['path'] = [(px + dx, py + dy) for px, py in path_info['path']]
                            
                # 有剩余就保留，当不一致时才修改
                new_paths.append(path_info)
        if new_paths:
            self.node_paths[node_idx] = new_paths
        else:
            self.node_paths.pop(node_idx, None)

    def confirm_current_drawing(self):
        """确认当前草稿并写入当前节点点位。"""
        # 箭头工具单独处理
        if self.active_tool == "箭头":
            return self.confirm_current_arrow()

        tool_name = self._draft_tool_name
        refs = list(self._draft_reference_points)
        had_draft = bool(self._draft_tool_name or self._draft_reference_points)

        # 曲线/折线可直接用 pending 参考点确认。
        if (not tool_name or not refs) and self.active_tool == "曲线/折线" and len(self._pending_points) >= 2:
            tool_name = "曲线/折线"
            refs = list(self._pending_points)

        if (not tool_name or not refs) and self.active_tool != "间隔":
            self._clear_draft()
            self._pending_points = []
            if not had_draft:
                self.draftFinished.emit()
            self._render_points_for_active_node()
            self.drawingRematchStateChanged.emit()
            return False
        
        generated = self._generate_performer_points(tool_name, refs)    # 生成最终点位列表（field 坐标）
        current_points = self.node_points[self.active_node]  # 当前节点的点位列表

        # 如果有选中点，则按索引匹配移动已存在的点；多余的生成点不新增
        if self._selected_point_ids:
            self.clear_selected_point_in_path(self.active_node)
                
            if tool_name == "路径":
                # 路径模式：以第一个选中点为锚，按路径最后一点生成预览点位并写回 node_points。
                selected_ids = self._selected_point_ids
                if generated:
                    path_points = list(generated)
                    # 获取选中点对应的group，选取group_id最小的[0]，作为锚点
                    anchor_id = self._get_anchor()
                    # anchor_point = self._find_previous_point_by_id(anchor_id)
                    anchor_point = self._find_point_in_node(self.active_node - 1, anchor_id)
                    if anchor_point is not None and path_points:
                        base_x = float(anchor_point.get("x", 0.0))
                        base_y = float(anchor_point.get("y", 0.0))
                        # 以第一个选中点为锚，整体平移到路径的最后一点位置
                        last_px, last_py = path_points[-1]
                        tx = float(last_px) - float(base_x)
                        ty = float(last_py) - float(base_y)
                        preview_points = []
                        selected_points = []
                        for pid in selected_ids:
                            # point = point_by_id.get(int(pid))
                            point = self._find_point_in_node(self.active_node, int(pid))
                            if point is None:
                                continue
                            selected_points.append(point)
                            # 选中点当前位置优先基于上一拍位计算，保持与锚点逻辑一致。
                            previous_point = self._find_point_in_node(self.active_node - 1, int(pid))
                            source_point = previous_point if previous_point is not None else point
                            new_x = float(source_point.get("x", 0.0)) + tx
                            new_y = float(source_point.get("y", 0.0)) + ty
                            preview_points.append({
                                "id": int(pid),
                                "x": float(new_x),
                                "y": float(new_y),
                                "group_id": point.get("group_id"),
                            })
                        for preview in preview_points:
                            pid = int(preview.get("id", -1))
                            # point = point_by_id.get(pid)
                            point = self._find_point_in_node(self.active_node, pid)
                            if point is None:
                                continue
                            point["x"] = float(preview["x"])
                            point["y"] = float(preview["y"])
                            
                        # 记录路径信息：只保存锚点ID、路径点和成员点ID，成员偏移在插值时根据当前节点现算。
                        # path 不保存前一张图位置（[0] 由插值时经 _find_point_in_node 动态补齐）。
                        self._upsert_node_path_entry(
                            node_index=self.active_node,
                            path_type='forward',
                            anchor_id=anchor_id,
                            path=[[float(px), float(py)] for px, py in path_points[1:]],
                            members=[int(p.get("id", -1)) for p in selected_points],
                        )
                        self.sync_sampling_values_from_selection(tool_name)
                        self.reset_sampling_defaults(tool_name)
                        self._pending_points = []
                        self._draft_reference_points = []
                        self._reset_drawing_rematch_state(active=False)
                        self.node_manual_edited[self.active_node] = True
                        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
                        self._clear_draft()
                        if not had_draft:
                            self.draftFinished.emit()
                        self._render_points_for_active_node()
                        self.drawingRematchStateChanged.emit()
                        self.dataChanged.emit()
                        return True
                    
            elif tool_name == "跟随":
                # 跟随模式：以第一个选中 leader 为锚，绘制 leader 路径，记录 leaders 列表与所属组成员
                selected_ids = self._selected_point_ids
                if generated:
                    path_points = list(generated)
                    anchor_id = self._get_anchor()
                    # anchor_point = self._find_previous_point_by_id(anchor_id)
                    anchor_point = self._find_point_in_node(self.active_node - 1, anchor_id)
                    if anchor_point is not None and path_points:
                        # 汇总各组成员，并把当前 leader 端点写入 leaders 列表。
                        members_union = []
                        leaders_union = []
                        for lid in selected_ids:
                            if lid in members_union:
                                # 跳过已处理过的点位，避免重复添加同组成员
                                continue
                            # leader_point = self._find_previous_point_by_id(lid)
                            leader_point = self._find_point_in_node(self.active_node - 1, lid)
                            if leader_point.get("group_id") is None:
                                continue
                            found_group = self.group_to_point[leader_point["group_id"]]
                            if found_group is not None:
                                ordered_group = self._follow_group_point_ids_for_group(found_group)
                                for pid in ordered_group:
                                    if int(pid) not in members_union:
                                        members_union.append(int(pid))
                                leader_id = int(ordered_group[0]) if ordered_group else lid
                                if leader_id not in leaders_union:
                                    leaders_union.append(leader_id)
                                    # break
                            if found_group is None:
                                if lid not in members_union:
                                    members_union.append(lid)
                                if lid not in leaders_union:
                                    leaders_union.append(lid)

                        # 保存 follow 路径定义（需先注册，后续 _sample_point_from_node_path 依赖此数据）。
                        # path 不保存前一张图位置（[0] 由插值时经 _find_point_in_node 动态补齐）。
                        self._upsert_node_path_entry(
                            self.active_node,
                            'follow',
                            anchor_id,
                            path_points[1:],
                            members_union,
                            leaders=leaders_union,
                        )

                        # 按 _sample_point_from_node_path 计算各点路径终点位置（progress=1.0）
                        for pid in selected_ids:
                            sampled = self._sample_point_from_node_path(self.active_node, int(pid), 1.0)
                            if sampled is None:
                                continue
                            point = self._find_point_in_node(self.active_node, int(pid))
                            if point is None:
                                continue
                            point["x"] = float(sampled[0])
                            point["y"] = float(sampled[1])
                        self.sync_sampling_values_from_selection(tool_name)
                        self.reset_sampling_defaults(tool_name)
                        self._pending_points = []
                        self._draft_reference_points = []
                        self._reset_drawing_rematch_state(active=False)
                        self.node_manual_edited[self.active_node] = True
                        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
                        self._clear_draft()
                        if not had_draft:
                            self.draftFinished.emit()
                        self._render_points_for_active_node()
                        self.drawingRematchStateChanged.emit()
                        self.dataChanged.emit()
                        return True
            
            elif self.active_tool == "间隔" and self._interval_anchor_id is not None:
                return self._confirm_interval_marching(had_draft)

            rematch_snapshot = self._drawing_rematch_snapshot()
            id_to_index = {int(p.get("id", -1)): idx for idx, p in enumerate(current_points)}
            if rematch_snapshot["active"]:
                # 允许在未全部匹配的情况下确认：只将已有匹配关系的预览点写回对应原点，
                # 未匹配的原点保持原位置，未匹配的预览点直接舍弃（不新增）。
                for point_id in rematch_snapshot["selected_ids"]:
                    preview_index = rematch_snapshot["point_to_preview"].get(int(point_id))
                    if preview_index is None:
                        continue
                    preview_index = int(preview_index)
                    if preview_index < 0 or preview_index >= len(generated):
                        continue
                    idx = id_to_index.get(int(point_id))
                    if idx is None:
                        continue
                    dx, dy = generated[preview_index]
                    current_points[idx]["x"] = float(dx)
                    current_points[idx]["y"] = float(dy)
            else:
                # 源点按当前节点中的顺序筛选出被选中的点
                src_ordered = [p for p in current_points if int(p.get("id", -1)) in self._selected_point_ids]
                dst_ordered = [p for p in generated]
                match_count = min(len(src_ordered), len(dst_ordered))
                for i in range(match_count):
                    sid = int(src_ordered[i].get("id", -1))
                    dx, dy = dst_ordered[i]
                    if sid in id_to_index:
                        idx = id_to_index[sid]
                        current_points[idx]["x"] = float(dx)
                        current_points[idx]["y"] = float(dy)
            
            self.sync_sampling_values_from_selection(tool_name)
        else:
            new_point_ids = []
            group_id = len(self.group_to_point)
            for x, y in generated:
                if self._position_occupied(x, y):
                    continue
                point_id = self._next_point_id
                point = {"id": point_id, "x": x, "y": y}
                if group_id is not None:
                    point["group_id"] = group_id
                current_points.append(point)
                self._next_point_id += 1
                new_point_ids.append(point_id)
                # 初始化标签数据：serial=point_id, prefix=""
                self.point_lable.append({"prefix": "", "serial": point_id + 1})

            if new_point_ids:
                # 添加到分组中
                self.node_to_group[self.active_node].append(group_id)
                if self.active_node + 1 < len(self.node_to_group):
                    for idx in range(len(self.node_to_group))[self.active_node + 1:]:
                        if self.node_manual_edited[idx]:
                            break
                        self.node_to_group[idx].append(group_id)
                self.group_to_point.append({
                    "point_ids": new_point_ids, # 组内点位 ID 列表
                    "leader": True,  # leader 点位为正向第一个
                })
            self.reset_sampling_defaults(tool_name)

        self._pending_points = []
        self._draft_reference_points = []
        self._reset_drawing_rematch_state(active=False)
        self.node_manual_edited[self.active_node] = True
        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
        self._clear_draft()
        if not had_draft:
            self.draftFinished.emit()
        self._render_points_for_active_node()
        self.drawingRematchStateChanged.emit()
        self.dataChanged.emit()
        return True

    def cancel_current_drawing(self):
        """取消当前草稿，不写入点位。"""
        # 箭头工具单独处理
        if self.active_tool == "箭头":
            self.cancel_current_arrow()
            return

        # 间隔行进：清理锚点状态和 helper
        if self.active_tool == "间隔":
            self._clear_interval_helpers()
            self._render_points_for_active_node()
            self.drawingRematchStateChanged.emit()
            return

        # 取消绘制时：对所有采样工具恢复默认参数
        tools_to_reset = set()
        if self._draft_tool_name in self._sampling_tools:
            tools_to_reset.add(self._draft_tool_name)
        if self.active_tool in self._sampling_tools:
            tools_to_reset.add(self.active_tool)
        for t in tools_to_reset:
            if self._selected_point_ids:
                self.sync_sampling_values_from_selection(t)
            else:
                self.reset_sampling_defaults(t)
        self._pending_points = []
        self._reset_drawing_rematch_state(active=False)
        self._clear_draft()
        self.draftFinished.emit()
        self._render_points_for_active_node()
        self.drawingRematchStateChanged.emit()

    def _field_to_scene(self, x: float, y: float) -> QPointF:
        """将 field 坐标转换为 scene 坐标用于显示。"""
        s = self.field_info
        return QPointF(x * s.scale + s.offset.x(), y * s.scale + s.offset.y())

    def _scene_to_field(self, scene_pos: QPointF) -> tuple[float, float]:
        """将 scene 坐标转换为 field 坐标用于计算。"""
        s = self.field_info
        scale = s.scale if abs(s.scale) > 1e-9 else 1.0
        x = (scene_pos.x() - s.offset.x()) / scale
        y = (scene_pos.y() - s.offset.y()) / scale
        return x, y

    def _snap_field_point(self, x: float, y: float) -> tuple[float, float]:
        """将 field 坐标吸附到网格点。"""
        step = max(1e-9, float(self.field_info.grid_step))
        return (round(x / step) * step, round(y / step) * step)

    def _sampling_state(self, tool_name: str) -> dict:
        """获取指定工具的采样状态字典，包含当前的点数与间隔设置以及自动/手动状态。"""
        if tool_name not in self._sampling_tools:
            tool_name = "线段"
        if tool_name not in self._sampling_settings:
            self._sampling_settings[tool_name] = dict(self._sampling_defaults)
        state = self._sampling_settings[tool_name]
        _enforce_sampling_auto_rule(tool_name, state)
        return state

    def sampling_shift_point_count(self, tool_name: str) -> int:
        """获取填充四边形第二方向（P0-P2）的点位个数设置。"""
        state = self._sampling_state(tool_name)
        return int(state.get("point_count_shift", 1))

    def sampling_settings(self, tool_name: str) -> tuple[int, float]:
        """获取指定工具的采样点位个数与采样间距。"""
        state = self._sampling_state(tool_name)
        return int(state.get("point_count", 1)), float(state.get("spacing_steps", 2.0))

    def polygon_side_count(self, tool_name: str) -> int:
        """获取多边形工具的边数设置。"""
        state = self._sampling_state(tool_name)
        return max(2, int(state.get("polygon_sides", 6)))

    def is_sampling_point_count_auto(self, tool_name: str) -> bool:
        """获取指定工具的采样点位个数设置是否为自动。"""
        return not bool(self._sampling_state(tool_name)["point_count_manual"])

    def is_sampling_spacing_auto(self, tool_name: str) -> bool:
        """获取指定工具的采样间距是否为自动。"""
        return not bool(self._sampling_state(tool_name)["spacing_manual"])

    def is_sampling_point_count_shift_auto(self, tool_name: str) -> bool:
        """获取填充四边形第二方向（P0-P2）的点位个数设置是否为自动。"""
        return not bool(self._sampling_state(tool_name).get("point_count_shift_manual", False))

    def _emit_sampling_point_count_changed(self, tool_name: str, point_count: int):
        """发出采样点位个数改变的信号。"""
        point_count = max(1, int(point_count))
        self.samplingPointCountChanged.emit(tool_name, point_count)

    def _emit_sampling_shift_point_count_changed(self, tool_name: str, point_count: int):
        """发出填充四边形第二方向（P0-P2）采样点位个数改变的信号。"""
        point_count = max(1, int(point_count))
        self.samplingShiftPointCountChanged.emit(tool_name, point_count)

    def _emit_sampling_spacing_changed(self, tool_name: str, spacing_steps: float):
        """发出采样间距改变的信号。spacing_steps 是 field 网格单位的倍数。"""
        spacing_steps = max(0.001, float(spacing_steps))
        self.samplingSpacingChanged.emit(tool_name, spacing_steps)

    def _sampling_length_for_tool(self, tool_name: str, refs: list[tuple[float, float]]) -> float:
        if tool_name == "线段" and len(refs) >= 2:
            return _distance(refs[0], refs[1])
        if tool_name == "曲线/折线" and len(refs) >= 2:
            total = 0.0
            for idx in range(len(refs) - 1):
                total += _distance(refs[idx], refs[idx + 1])
            return total
        if tool_name == "弧" and len(refs) >= 3:
            center = _circumcenter(refs[0], refs[2], refs[1])
            if center is None:
                return _distance(refs[0], refs[2]) + _distance(refs[2], refs[1])
            cx, cy = center
            radius = math.hypot(refs[0][0] - cx, refs[0][1] - cy)
            if radius <= 1e-9:
                return 0.0

            start_angle = math.atan2(refs[0][1] - cy, refs[0][0] - cx)
            through_angle = math.atan2(refs[2][1] - cy, refs[2][0] - cx)
            end_angle = math.atan2(refs[1][1] - cy, refs[1][0] - cx)

            def norm(a):
                while a < 0:
                    a += 2.0 * math.pi
                while a >= 2.0 * math.pi:
                    a -= 2.0 * math.pi
                return a

            s = norm(start_angle)
            m = norm(through_angle)
            e = norm(end_angle)
            tau = 2.0 * math.pi
            ccw_se = (e - s) % tau
            ccw_sm = (m - s) % tau
            use_ccw = ccw_sm <= ccw_se
            if use_ccw:
                total_delta = ccw_se
            else:
                total_delta = -((s - e) % tau)
            return abs(total_delta) * radius
        if tool_name == "圆" and len(refs) >= 2:
            radius = _distance(refs[0], refs[1])
            return 2.0 * math.pi * radius
        if tool_name == "多边形" and len(refs) >= 2:
            vertices = _make_polygon_points(refs[0], refs[1], self.polygon_side_count(tool_name))
            if not vertices:
                return 0.0
            total = 0.0
            loop = vertices + [vertices[0]]
            for idx in range(len(loop) - 1):
                total += _distance(loop[idx], loop[idx + 1])
            return total
        if tool_name == "填充四边形":
            # 基线方向长度（P0-P1）用于自动计算 P0-P1 方向的点位个数/间隔
            if len(refs) >= 2:
                return _distance(refs[0], refs[1])
            return 0.0
        return 0.0

    def _sampling_auto_point_count_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> int:
        state = self._sampling_state(tool_name)
        spacing = max(1e-9, float(self.field_info.grid_step) * float(state["spacing_steps"]))
        length = self._sampling_length_for_tool(tool_name, refs)
        if length <= 1e-9:
            return max(1, int(state["point_count"]))
        # 原实现：对圆/多边形使用向下取整 floor，会导致与按点数采样产生末尾点位差异。
        # 改为使用四舍五入，使 spacing->point_count 与 point_count->spacing 更可逆，末尾点位一致性更好。
        if tool_name in {"圆", "多边形"}:
            return max(1, int(round(length / spacing)))
        return max(1, int(length // spacing) + 1)

    def _sampling_auto_point_count_shift_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> int:
        """计算填充四边形第二方向（P0-P2）的自动点数。"""
        # 默认复用基线 spacing 来估算，除非额外逻辑需要。
        state = self._sampling_state(tool_name)
        spacing_shift = max(1e-9, float(self.field_info.grid_step) * float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0))))
        # P0-P2 长度为 shift_len
        if tool_name != "填充四边形" or len(refs) < 3:
            return max(1, int(state.get("point_count_shift", 1)))
        ax, ay = refs[0]
        cx, cy = refs[2]
        shift_len = math.hypot(cx - ax, cy - ay)
        if shift_len <= 1e-9:
            return max(1, int(state.get("point_count_shift", 1)))
        return max(1, int(shift_len // spacing_shift) + 1)

    def _sampling_auto_spacing_steps_shift_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> float:
        """计算填充四边形第二方向（P0-P2）的自动间隔步数。"""
        state = self._sampling_state(tool_name)
        length = 0.0
        if tool_name == "填充四边形" and len(refs) == 3:
            ax, ay = refs[0]
            cx, cy = refs[2]
            length = math.hypot(cx - ax, cy - ay)
        point_count = max(1, int(state.get("point_count_shift", 1)))
        if length <= 1e-9 or point_count <= 1:
            return max(0.001, float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0))))
        return max(0.001, float(length / (point_count - 1) / float(self.field_info.grid_step)))

    def _sampling_auto_spacing_steps_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> float:
        """计算指定工具在当前参考点下的自动间距步数（field 网格单位的倍数）。根据工具类型和自动规则不同，可能基于长度与点数的关系进行计算。对于填充四边形，如果行方向（P0-P1）为自动间距，则独立计算列方向（P0-P2）的自动间距。"""
        state = self._sampling_state(tool_name)
        length = self._sampling_length_for_tool(tool_name, refs)
        point_count = max(1, int(state["point_count"]))
        if length <= 1e-9:
            return max(0.001, float(state["spacing_steps"]))
        if tool_name in {"圆", "多边形"}:
            if point_count <= 0:
                return max(0.001, float(state["spacing_steps"]))
            return max(0.001, float(length / point_count / float(self.field_info.grid_step)))
        if point_count <= 1:
            return max(0.001, float(state["spacing_steps"]))
        return max(0.001, float(length / (point_count - 1) / float(self.field_info.grid_step)))

    def _sync_sampling_auto_values_from_draft(self, tool_name: str):
        """根据当前草稿参考点和工具，自动计算并同步采样工具的自动点数与间距设置。仅在对应设置为自动时才会更新。"""
        if tool_name not in self._sampling_tools:
            return
        
        # 计算自动值时优先使用草稿参考点；
        #   如果草稿参考点不足以计算（如线段少于2点），
        #   则退回使用 pending 参考点（如鼠标点击位置等）进行计算，
        #   以保证在草稿输入过程中自动值能够及时响应用户操作。
        refs = self._draft_reference_points
        if len(refs) < 2 and self.active_tool == tool_name:
            refs = self._pending_points

        state = self._sampling_state(tool_name)
        # 自动适配点位个数
        if not state["point_count_manual"]:
            point_count = self._sampling_auto_point_count_for_refs(tool_name, refs)
            if point_count != state["point_count"]:
                state["point_count"] = point_count
            self._emit_sampling_point_count_changed(tool_name, point_count)
        
        # 自动适配间距
        if not state["spacing_manual"] and state["point_count_manual"]:
            spacing_steps = self._sampling_auto_spacing_steps_for_refs(tool_name, refs)
            if abs(spacing_steps - float(state["spacing_steps"])) > 1e-9:
                state["spacing_steps"] = spacing_steps
            self._emit_sampling_spacing_changed(tool_name, spacing_steps)

        # 对于填充四边形，若行方向未手动设置，则同步为基线的自动值
        if tool_name == "填充四边形":
            # 同步自动点数（P0-P2）
            if not state.get("point_count_shift_manual", False):
                pc_shift = self._sampling_auto_point_count_shift_for_refs(tool_name, refs)
                if pc_shift != int(state.get("point_count_shift", pc_shift)):
                    state["point_count_shift"] = pc_shift
                self.samplingShiftPointCountChanged.emit(tool_name, pc_shift)

            # 若行方向 spacing 未手动设置，则根据 P0-P2 方向长度与点位个数独立自动计算
            if not state.get("spacing_shift_manual", False) and state.get("point_count_shift_manual", False):
                spacing_shift = self._sampling_auto_spacing_steps_shift_for_refs(tool_name, refs)
                if abs(spacing_shift - float(state.get("spacing_steps_shift", spacing_shift))) > 1e-9:
                    state["spacing_steps_shift"] = spacing_shift
                self._emit_sampling_shift_spacing_changed(tool_name, spacing_shift)

    def sync_sampling_values_from_selection(self, tool_name: str) -> bool:
        """根据当前选中点位数量同步采样参数。"""
        if tool_name not in self._sampling_tools:
            return False
        if not self._selected_point_ids:
            return False

        selected_count = max(1, len(self._selected_point_ids))
        if tool_name == "填充四边形":
            selected_count = max(1, math.ceil(math.sqrt(selected_count)))
        state = self._sampling_state(tool_name)
        changed = False

        # 同步点位个数
        if int(state.get("point_count", 1)) != selected_count:
            state["point_count"] = selected_count
            changed = True
        if tool_name == "填充四边形" and int(state.get("point_count_shift", 1)) != selected_count:
            state["point_count_shift"] = selected_count
            changed = True
        
        # 点位个数设置切换到手动模式
        if not state.get("point_count_manual", False):
            state["point_count_manual"] = True
            changed = True
        if tool_name == "填充四边形" and not state.get("point_count_shift_manual", False):
            state["point_count_shift_manual"] = True
            changed = True
        
        # 点位间距设置切换到自动模式
        if state.get("spacing_manual", True):
            state["spacing_manual"] = False
            changed = True
        if tool_name == "填充四边形" and state.get("spacing_shift_manual", True):
            state["spacing_shift_manual"] = False
            changed = True

        if changed:
            self._emit_sampling_point_count_changed(tool_name, selected_count)
            if tool_name == "填充四边形":
                self._emit_sampling_shift_point_count_changed(tool_name, selected_count)
        return changed

    def _emit_sampling_shift_spacing_changed(self, tool_name: str, spacing_steps: float):
        """发出填充四边形第二方向（P0-P2）采样间距改变的信号。spacing_steps 是 field 网格单位的倍数。"""
        spacing_steps = max(0.001, float(spacing_steps))
        self.samplingShiftSpacingChanged.emit(tool_name, spacing_steps)

    def set_sampling_point_count(self, tool_name: str, point_count: int):
        """设置指定工具的采样点位个数，并切换到手动模式。point_count 会被自动修正为至少 1。"""
        state = self._sampling_state(tool_name)
        state["point_count"] = max(1, int(point_count))
        state["point_count_manual"] = True
        self._refresh_draft_preview_for_active_tool()

    def set_sampling_point_count_shift(self, tool_name: str, point_count: int):
        """设置填充四边形第二方向（P0-P2）的采样点位个数，并切换到手动模式。point_count 会被自动修正为至少 1。"""
        state = self._sampling_state(tool_name)
        state["point_count_shift"] = max(1, int(point_count))
        state["point_count_shift_manual"] = True
        self._refresh_draft_preview_for_active_tool()
        self._emit_sampling_shift_point_count_changed(tool_name, int(point_count))

    def set_sampling_point_count_auto_enabled(self, tool_name: str, enabled: bool):
        """设置指定工具的采样点位个数自动启用或禁用。启用自动时会根据当前草稿参考点自动计算点数；禁用自动会保持当前点数不变并切换到手动模式。"""
        state = self._sampling_state(tool_name)
        state["point_count_manual"] = not bool(enabled)
        _enforce_sampling_auto_rule(
            tool_name,
            state,
            changed="point_count_auto" if enabled else "point_count_manual",
        )
        if enabled:
            self._sync_sampling_auto_values_from_draft(tool_name)
        self._refresh_draft_preview_for_active_tool()

    def set_sampling_point_count_shift_auto_enabled(self, tool_name: str, enabled: bool):
        """设置填充四边形第二方向（P0-P2）的采样点位个数自动启用或禁用。启用自动时会根据当前草稿参考点自动计算点数；禁用自动会保持当前点数不变并切换到手动模式。"""
        state = self._sampling_state(tool_name)
        state["point_count_shift_manual"] = not bool(enabled)
        if enabled:
            self._sync_sampling_auto_values_from_draft(tool_name)   # 设置第一方向
            _enforce_sampling_shift_auto_rule(state, changed="point_count_shift_auto") # 设置第二方向
        self._refresh_draft_preview_for_active_tool()

    def set_sampling_spacing(self, tool_name: str, spacing_steps: float):
        """设置指定工具的采样间距，并切换到手动模式。spacing_steps 是 field 网格单位的倍数，会被自动修正为至少 0.001。"""
        state = self._sampling_state(tool_name)
        state["spacing_steps"] = max(0.001, float(spacing_steps))
        state["spacing_manual"] = True
        self._sync_sampling_auto_values_from_draft(tool_name)
        self._refresh_draft_preview_for_active_tool()

    def set_sampling_spacing_auto_enabled(self, tool_name: str, enabled: bool):
        """设置指定工具的采样间距自动启用或禁用。启用自动时会根据当前草稿参考点自动计算间距；禁用自动会保持当前间距不变并切换到手动模式。"""
        state = self._sampling_state(tool_name)
        state["spacing_manual"] = not bool(enabled)
        _enforce_sampling_auto_rule(
            tool_name,
            state,
            changed="spacing_auto" if enabled else "spacing_manual",
        )
        if enabled:
            self._sync_sampling_auto_values_from_draft(tool_name)
        self._refresh_draft_preview_for_active_tool()

    def sampling_shift_spacing(self, tool_name: str) -> float:
        """获取填充四边形第二方向（P0-P2）的采样间距设置。spacing_steps 是 field 网格单位的倍数。"""
        state = self._sampling_state(tool_name)
        return float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0)))

    def is_sampling_shift_auto(self, tool_name: str) -> bool:
        """获取填充四边形第二方向（P0-P2）的采样间距设置是否为自动。"""
        return not bool(self._sampling_state(tool_name).get("spacing_shift_manual", False))

    def set_sampling_spacing_shift(self, tool_name: str, spacing_steps: float):
        """设置填充四边形第二方向（P0-P2）的采样间距，并切换到手动模式。spacing_steps 是 field 网格单位的倍数，会被自动修正为至少 0.001。"""
        state = self._sampling_state(tool_name)
        state["spacing_steps_shift"] = max(0.001, float(spacing_steps))
        state["spacing_shift_manual"] = True
        self._refresh_draft_preview_for_active_tool()

    def set_sampling_shift_auto_enabled(self, tool_name: str, enabled: bool):
        """设置填充四边形第二方向（P0-P2）的采样间距自动启用或禁用。启用自动时会根据当前草稿参考点自动计算间距；禁用自动会保持当前间距不变并切换到手动模式。"""
        state = self._sampling_state(tool_name)
        state["spacing_shift_manual"] = not bool(enabled)
        if enabled:
            self._sync_sampling_auto_values_from_draft(tool_name)   # 设置第一方向
            _enforce_sampling_shift_auto_rule(state, changed="spacing_shift_auto") # 设置第二方向
        self._refresh_draft_preview_for_active_tool()

    def set_polygon_side_count(self, tool_name: str, side_count: int):
        """设置多边形工具的边数，并切换到手动模式。side_count 会被自动修正为至少 2。"""
        state = self._sampling_state(tool_name)
        state["polygon_sides"] = max(2, int(side_count))
        self._sync_sampling_auto_values_from_draft(tool_name)
        self._refresh_draft_preview_for_active_tool()

    def reset_sampling_defaults(self, tool_name: str):
        """重置指定工具的采样设置为默认值：点位个数自动（自动计算点数），间距设为默认 2 步并由用户手动控制。对于填充四边形，第二方向（P0-P2）的点位个数和间距也会一并切换到默认设置。此方法通常在确认草稿后调用，以恢复默认行为。"""
        state = self._sampling_state(tool_name)
        # 默认行为：点位个数自动（自动计算点数），间距设为默认 2 步并由用户手动控制
        state["point_count_manual"] = False
        state["spacing_steps"] = 2.0
        state["spacing_manual"] = True
        self._emit_sampling_point_count_changed(tool_name, 1)
        self._emit_sampling_spacing_changed(tool_name, 2.0)
        # 若为填充四边形，第二方向也默认手动 2 步间隔
        if tool_name == "填充四边形":
            state['point_count_shift_manual'] = False
            state["spacing_steps_shift"] = 2.0
            state["spacing_shift_manual"] = True
            self._emit_sampling_shift_point_count_changed(tool_name, 1)
            self._emit_sampling_shift_spacing_changed(tool_name, 2.0)

    def _refresh_draft_preview_for_active_tool(self):
        """根据当前活动工具和草稿状态，刷新草稿预览的显示。对于采样工具，如果当前草稿工具是采样工具，则同步自动设置并重绘草稿叠加层；如果当前活动工具是采样工具且存在待定参考点，则清除草稿项并重绘待定参考点的预览。此方法通常在相关设置改变或草稿状态更新时调用，以确保草稿预览与当前设置和状态保持一致。"""
        if self._draft_tool_name in self._sampling_tools:
            self._sync_sampling_auto_values_from_draft(self._draft_tool_name)
            self._draw_draft_overlay()
            self.update()
            return

        if self.active_tool in self._sampling_tools and self._pending_points:
            # 原逻辑仅重绘预览，未先同步自动值。
            self._sync_sampling_auto_values_from_draft(self.active_tool)
            self._clear_draft_items()
            self._draw_pending_reference_preview()
            self._draw_pending_reference_points()
            self.update()

    def _draw_draft_overlay(self):
        self._clear_draft_items()   # 清除之前的草稿预览项和参考点项
        self._draw_draft_preview()  # 根据当前草稿工具和参考点绘制新的草稿预览项
        self._draw_draft_handles()  # 根据当前草稿参考点绘制新的参考点项（可交互的控制点）

    def _draw_draft_preview(self):
        """根据当前草稿工具和参考点，绘制草稿预览项。对于点工具，仅绘制参考点；对于其他工具，根据参考点生成预览点并绘制。此方法会先检查当前是否有有效的草稿工具和参考点，如果没有则直接返回。对于有效的草稿状态，会先绘制一个基于参考点的预览项（如果适用），然后根据工具类型生成相应的预览点并绘制为小圆点。所有草稿预览项都会被添加到场景中，并且会被记录在 _draft_preview_items 列表中，以便后续清除或更新。"""
        if not self._draft_tool_name or not self._draft_reference_points:
            return

        reference_item = self._reference_graphic_item()
        if reference_item is not None:
            reference_item.setZValue(890)
            self.addItem(reference_item)
            self._draft_preview_items.append(reference_item)

        if self._draft_tool_name == "路径" and len(self._draft_reference_points) >= 2:
            refs = list(self._draft_reference_points)
            if getattr(self, '_curve_mode', 'polyline') == 'curve':
                refs_path = _build_dense_curve_points(refs, float(self.field_info.grid_step))
            else:
                refs_path = refs
            if refs_path:
                pen = QPen(QColor(210, 84, 0, 170), 1.3, Qt.PenStyle.DashLine)
                path = QPainterPath()
                path.moveTo(self._field_to_scene(*refs_path[0]))
                for x, y in refs_path[1:]:
                    path.lineTo(self._field_to_scene(x, y))
                path_item = QGraphicsPathItem(path)
                path_item.setPen(pen)
                path_item.setZValue(890)
                self.addItem(path_item)
                self._draft_preview_items.append(path_item)

                anchor = self._find_point_in_node(self.active_node - 1, int(self._get_anchor()))
                src_points = [self._find_point_in_node(self.active_node - 1, int(pid)) for pid in self._selected_point_ids]
                if src_points and anchor is not None:
                    base_x = float(anchor.get("x", 0.0))
                    base_y = float(anchor.get("y", 0.0))
                    last_px, last_py = refs_path[-1]
                    tx = float(last_px) - float(base_x)
                    ty = float(last_py) - float(base_y)
                    preview_points = []
                    for point in src_points:
                        if point is None:
                            continue
                        preview_points.append((float(point.get("x", 0.0)) + tx, float(point.get("y", 0.0)) + ty))
                    moved_dots = self.render_preview_points(preview_points, pen_color="#2980b9", brush_color=(41, 128, 185, 120), z=895)
                    for dot in moved_dots:
                        self._draft_preview_items.append(dot)
            return
        
        if self._draft_tool_name == "跟随" and len(self._draft_reference_points) >= 2:
            refs = list(self._draft_reference_points)
            if getattr(self, '_curve_mode', 'polyline') == 'curve':
                refs_path = _build_dense_curve_points(refs, float(self.field_info.grid_step))
            else:
                refs_path = refs
            if refs_path:
                pen = QPen(QColor(210, 84, 0, 170), 1.3, Qt.PenStyle.DashLine)
                path = QPainterPath()
                path.moveTo(self._field_to_scene(*refs_path[0]))
                for x, y in refs_path[1:]:
                    path.lineTo(self._field_to_scene(x, y))
                path_item = QGraphicsPathItem(path)
                path_item.setPen(pen)
                path_item.setZValue(890)
                self.addItem(path_item)
                self._draft_preview_items.append(path_item)

                selected_ids = self._selected_point_ids

                total_length = 0.0
                for index in range(len(refs_path) - 1):
                    x1, y1 = refs_path[index]
                    x2, y2 = refs_path[index + 1]
                    total_length += math.hypot(x2 - x1, y2 - y1)

                progress = 1.0
                preview_points = []
                for pid in selected_ids:
                    point = self._find_point_in_node(self.active_node, int(pid))
                    if point is None:
                        continue

                    group_members = self._follow_group_point_ids_for_point_id(int(pid))
                    if not group_members:
                        source_point = self._find_point_in_node(self.active_node - 1, int(pid)) or point
                        leader_sample = sample_on_polyline(refs_path, total_length)
                        if leader_sample is None:
                            continue
                        offset = (
                            float(source_point.get("x", 0.0)) - float(point.get("x", 0.0)),
                            float(source_point.get("y", 0.0)) - float(point.get("y", 0.0)),
                        )
                        preview_points.append((float(leader_sample[0]) + offset[0], float(leader_sample[1]) + offset[1]))
                        continue

                    try:
                        member_index = group_members.index(int(pid))
                    except ValueError:
                        source_point = self._find_point_in_node(self.active_node - 1, int(pid)) or point
                        leader_sample = sample_on_polyline(refs_path, total_length)
                        if leader_sample is None:
                            continue
                        offset = (
                            float(source_point.get("x", 0.0)) - float(point.get("x", 0.0)),
                            float(source_point.get("y", 0.0)) - float(point.get("y", 0.0)),
                        )
                        preview_points.append((float(leader_sample[0]) + offset[0], float(leader_sample[1]) + offset[1]))
                        continue

                    if member_index == 0:
                        anchor_id = self._get_anchor()
                        # 仅 anchor 沿绝对路径行进
                        if int(pid) == int(anchor_id):
                            pos = sample_on_polyline(refs_path, total_length)
                            if pos is not None:
                                preview_points.append(pos)
                        else:
                            # 其余组 leader 相对于 anchor 行进
                            anchor_orig = self._find_point_in_node(self.active_node - 1, int(anchor_id))
                            member_orig = self._find_point_in_node(self.active_node - 1, int(pid))
                            if anchor_orig is not None and member_orig is not None:
                                offset_x = float(member_orig.get("x", 0.0)) - float(anchor_orig.get("x", 0.0))
                                offset_y = float(member_orig.get("y", 0.0)) - float(anchor_orig.get("y", 0.0))
                                anchor_pos = sample_on_polyline(refs_path, total_length)
                                if anchor_pos is not None:
                                    preview_points.append((float(anchor_pos[0]) + offset_x, float(anchor_pos[1]) + offset_y))
                            else:
                                pos = sample_on_polyline(refs_path, total_length)
                                if pos is not None:
                                    preview_points.append(pos)
                        continue

                    forward_points = []
                    for group_index in range(member_index, -1, -1):
                        member_pid = int(group_members[group_index])
                        orig = self._find_point_in_node(self.active_node - 1, member_pid) or self._find_point_in_node(self.active_node, member_pid)
                        if orig is None:
                            forward_points = []
                            break
                        forward_points.append((float(orig.get("x", 0.0)), float(orig.get("y", 0.0))))

                    if not forward_points:
                        source_point = self._find_point_in_node(self.active_node - 1, int(pid)) or point
                        leader_sample = sample_on_polyline(refs_path, total_length)
                        if leader_sample is None:
                            continue
                        offset = (
                            float(source_point.get("x", 0.0)) - float(point.get("x", 0.0)),
                            float(source_point.get("y", 0.0)) - float(point.get("y", 0.0)),
                        )
                        preview_points.append((float(leader_sample[0]) + offset[0], float(leader_sample[1]) + offset[1]))
                        continue

                    front_length = 0.0
                    for group_index in range(len(forward_points) - 1):
                        ax, ay = forward_points[group_index]
                        bx, by = forward_points[group_index + 1]
                        front_length += math.hypot(bx - ax, by - ay)

                    # 非 anchor 组的跟随点应沿该组 leader 的相对路径行进
                    anchor_id = self._get_anchor()
                    leader_is_anchor = int(group_members[0]) == int(anchor_id)
                    if not leader_is_anchor:
                        anchor_orig2 = self._find_point_in_node(self.active_node - 1, int(anchor_id))
                        leader_orig2 = self._find_point_in_node(self.active_node - 1, int(group_members[0]))
                        if anchor_orig2 is not None and leader_orig2 is not None:
                            loff_x = float(leader_orig2.get("x", 0.0)) - float(anchor_orig2.get("x", 0.0))
                            loff_y = float(leader_orig2.get("y", 0.0)) - float(anchor_orig2.get("y", 0.0))
                            effective_path = [(float(px) + loff_x, float(py) + loff_y) for px, py in refs_path]
                        else:
                            effective_path = refs_path
                    else:
                        effective_path = refs_path

                    combined_path = forward_points + [(float(px), float(py)) for px, py in effective_path]
                    sample_dist = progress * total_length
                    if sample_dist > front_length + total_length:
                        sample_dist = front_length + total_length

                    result_pos = sample_on_polyline(combined_path, sample_dist)
                    if result_pos is None:
                        continue
                    preview_points.append(result_pos)

                if preview_points:
                    moved_dots = self.render_preview_points(preview_points, pen_color="#2980b9", brush_color=(41, 128, 185, 120), z=895)
                    for dot in moved_dots:
                        self._draft_preview_items.append(dot)
            return

        preview_points = self._generate_performer_points(self._draft_tool_name, self._draft_reference_points)
        if preview_points:
            rematch_snapshot = self._drawing_rematch_snapshot()
            if rematch_snapshot["active"]:
                items = self._render_preview_points_for_drawing_rematch(preview_points)
            else:
                items = self.render_preview_points(preview_points)
            for it in items:
                self._draft_preview_items.append(it)

    def _draw_draft_handles(self):
        """根据当前草稿参考点，绘制可交互的参考点控制项。每个参考点都会对应一个 ReferenceHandleItem，用户可以通过拖动这些控制项来调整参考点的位置。此方法会先检查当前是否有草稿参考点，如果没有则直接返回。对于每个草稿参考点，会创建一个 ReferenceHandleItem，并将其添加到场景中，同时记录在 _draft_handle_items 列表中，以便后续清除或更新。ReferenceHandleItem 会绑定一个回调函数，当用户拖动控制项时会调用该函数来更新对应的参考点坐标，并根据需要同步相关的自动设置和刷新预览。"""
        if not self._draft_reference_points:
            return

        self._updating_draft_handles = True
        for index, (x, y) in enumerate(self._draft_reference_points):
            handle = ReferenceHandleItem(
                index = index,
                center_scene_pos = self._field_to_scene(x, y),
                moved_callback = self._on_reference_handle_moved,
            )
            self.addItem(handle)
            self._draft_handle_items.append(handle)
        self._updating_draft_handles = False

    def _draw_pending_reference_points(self):
        """根据当前待定参考点，绘制可交互的参考点控制项。每个待定参考点都会对应一个 ReferenceHandleItem，用户可以通过拖动这些控制项来调整参考点的位置。此方法会先检查当前是否有待定参考点，如果没有则直接返回。对于每个待定参考点，会创建一个 ReferenceHandleItem，并将其添加到场景中，同时记录在 _draft_handle_items 列表中，以便后续清除或更新。ReferenceHandleItem 会绑定一个回调函数，当用户拖动控制项时会调用该函数来更新对应的参考点坐标，并根据需要同步相关的自动设置和刷新预览。"""
        if not self._pending_points:
            return
        self._updating_draft_handles = True
        for index, (x, y) in enumerate(self._pending_points):
            if self.active_tool in {"路径", "跟随"} and index == 0:
                # 路径的第一个参考点是固定锚点，不允许拖动。
                fixed = QGraphicsEllipseItem(-4.0, -4.0, 8.0, 8.0)
                fixed.setPen(QPen(QColor("#d35400"), 1.2))
                fixed.setBrush(QBrush(QColor(211, 84, 0, 80)))
                fixed.setPos(self._field_to_scene(x, y))
                fixed.setZValue(1000)
                self.addItem(fixed)
                self._draft_handle_items.append(fixed)
                continue
            handle = ReferenceHandleItem(
                index=index,
                center_scene_pos=self._field_to_scene(x, y),
                moved_callback=self._on_pending_reference_handle_moved,
            )
            self.addItem(handle)
            self._draft_handle_items.append(handle)
        self._updating_draft_handles = False

    def _on_pending_reference_handle_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        """
        当用户拖动待定参考点的控制项时，更新对应的参考点坐标，并根据需要同步相关的自动设置和刷新预览。
        此回调函数会被 ReferenceHandleItem 调用，传入被拖动控制项的索引和新的场景坐标。
        函数会先检查当前是否正在更新草稿控制项，如果是则直接返回新的场景坐标而不进行任何处理。
        然后会检查索引是否有效，如果无效也直接返回新的场景坐标。
        对于有效的索引，会将新的场景坐标转换为字段坐标，并进行吸附处理，然后更新对应的待定参考点坐标。
        根据当前活动工具，如果是线段工具则同步线段工具的自动设置；
            如果是曲线/折线工具则同步采样工具的自动设置。
        最后会使用 QTimer.singleShot 来延迟刷新当前活动工具的参考叠加层，以确保界面及时更新。
        函数返回最终调整后的场景坐标，以便 ReferenceHandleItem 更新控制项的位置。
        """
        if self._updating_draft_handles:
            return scene_pos
        if self.active_tool in {"路径", "跟随"} and index == 0:
            # 路径首点固定，不允许拖动。
            return self._field_to_scene(*self._pending_points[0]) if self._pending_points else scene_pos
        if index < 0 or index >= len(self._pending_points):
            return scene_pos
        x, y = self._scene_to_field(scene_pos)
        x, y = self._snap_field_point(x, y)
        self._pending_points[index] = (x, y)
        if self.active_tool in self._sampling_tools:
            self._sync_sampling_auto_values_from_draft(self.active_tool)
        # 拖拽进行中仅刷新待确认参考线预览，避免重建 handle 导致拖拽中失焦。
        self._clear_pending_preview_items()
        self._draw_pending_reference_preview()
        self.update()
        self.drawingRematchStateChanged.emit()
        return self._field_to_scene(x, y)

    def _handle_draw_tool(self, tool_name: str, field_point: tuple[float, float]):
        # 非单点工具进入草稿态后，仅允许拖拽现有参考点，不再响应新增点击。
        if tool_name not in {"点", "路径", "跟随"} and self._draft_tool_name and self._draft_reference_points:
            return

        if tool_name == "点":
            if self._draft_tool_name != "点":
                self._draft_tool_name = "点"
                self._draft_reference_points = [field_point]
                self.draftStarted.emit("点")
            else:
                _append_unique_reference_point(self._draft_reference_points, field_point)
            self.drawingRematchStateChanged.emit()
            self._draw_draft_overlay()
            return

        if tool_name in {"路径", "跟随"}:
            # 路径工具：第一个参考点固定为锚点，后续点击仅记录轨迹点。
            if not self._pending_points:
                anchor_id = self._get_anchor()
                if anchor_id is not None:
                    anchor_point = self._find_point_in_node(self.active_node - 1, int(anchor_id))
                    if anchor_point is not None:
                        self._pending_points.append((float(anchor_point["x"]), float(anchor_point["y"])))
            _append_unique_reference_point(self._pending_points, field_point)
            if len(self._pending_points) >= 2:
                self._draft_tool_name = tool_name
                self._draft_reference_points = list(self._pending_points)
                self.draftStarted.emit(tool_name)
                self._draw_draft_overlay()
            else:
                self._draft_tool_name = None
                self._draft_reference_points = []
                self.draftFinished.emit()
            self.drawingRematchStateChanged.emit()
            return

        _append_unique_reference_point(self._pending_points, field_point)
        if tool_name == "曲线/折线":
            self._sync_sampling_auto_values_from_draft("曲线/折线")
            # 取消右键确认：参考点>=2 时即可通过绘制控制台确认。
            if len(self._pending_points) >= 2:
                self.draftStarted.emit("曲线/折线")
            else:
                self.draftFinished.emit()
            self.drawingRematchStateChanged.emit()
            return

        required_points = {
            "点": 1,
            "线段": 2,
            "弧": 3,
            "填充四边形": 3,
            "圆": 2,
            "多边形": 2,
        }.get(tool_name, 0)
        if required_points and len(self._pending_points) >= required_points:
            refs = self._pending_points[:required_points]
            self._pending_points = []
            self._start_draft(tool_name, refs)
        elif required_points:
            self.draftFinished.emit()
        self.drawingRematchStateChanged.emit()

    def _is_drawing_tool(self) -> bool:
        return self.active_tool in {"点", "线段", "弧", "曲线/折线", "填充四边形", "圆", "多边形", "路径", "跟随"}

    def _render_points_for_active_node(self):
        """重绘当前节点与前一节点的点位叠加效果。"""
        self._clear_overlay_items()
        self.ensure_node_exists(self.active_node)

        # 预览逻辑
        node_at_beat = self._node_index_at_beat(self.preview_beat)
        if node_at_beat is not None:
            # 拍位正好在某节点起始拍，直接显示该节点。
            preview_node = node_at_beat
            if preview_node > 0:
                prev_points = self.node_points[preview_node - 1]
                for point in prev_points:
                    self._draw_point_item(point, pre_view=True, draw_label=False)
            current_points = self._points_for_node_render(preview_node)
        else:
            # 拍位位于两节点之间，显示左节点为 pre_view，当前层显示线性插值结果。
            segment = self._segment_for_beat(self.preview_beat)
            if segment is not None:
                # 在拍位位于两节点之间时显示插值预览，且仅显示左节点的点位为 pre_view。
                left, right = segment
                prev_points = self.node_points[left]
                for point in prev_points:
                    self._draw_point_item(point, pre_view=True, draw_label=False)
                current_points = self._interpolate_points_at_beat(left, right, self.preview_beat)
            else:
                if self.active_node > 0:
                    prev_points = self.node_points[self.active_node - 1]
                    for point in prev_points:
                        self._draw_point_item(point, pre_view=True, draw_label=False)
                current_points = self._points_for_node_render(self.active_node)

        for point in current_points:
            self._draw_point_item(point, pre_view=False, draw_label=True)

        self._draw_textbox_items()
        if self.active_tool == "文本":
            self._rebuild_textbox_handles()

        if self._adjustment_active:
            self._draw_adjustment_overlay()
            self._refresh_adjustment_drag_visuals()
            return

        if self._draft_tool_name:
            self._draw_draft_overlay()
        else:
            self._clear_draft_items()
            self._draw_pending_reference_preview()
            self._draw_pending_reference_points()
        if self.active_tool == "间隔":
            self._draw_interval_helpers()
            if self._interval_anchor_id is not None and self._interval_drag_position is not None:
                # 将锚点的 PerformerPointItem 移到拖拽位置（node_points 未修改）
                anchor_item = self._point_items_by_id.get(self._interval_anchor_id)
                if anchor_item is not None:
                    anchor_item.setPos(self._field_to_scene(*self._interval_drag_position))
                # 直接刷新预览（_clear_overlay_items 已清空旧预览图元）
                self._refresh_interval_preview()
        if self.active_tool == "旋转":
            self._draw_rotate_helpers()
            self._refresh_rotate_preview()
        if self.active_tool == "箭头":
            self._draw_arrow_items()
            if self._arrow_pending_points:
                self._draw_arrow_draft_preview()
        else:
            # 非箭头模式下，直接绘制 node_arrows 中已确认的箭头
            self._clear_arrow_items()
            arrows = self.node_arrows.get(self.active_node, [])
            for idx, entry in enumerate(arrows):
                pts = entry.get('points', [])
                if not pts:
                    continue
                scene_pts = [(self._field_to_scene(x, y).x(), self._field_to_scene(x, y).y()) for x, y in pts]
                arrow_item = ArrowItem(
                    arrow_index=idx,
                    arrow_type=entry.get('type', 'line'),
                    points=scene_pts,
                    style=entry.get('style', {}),
                    is_current=False,
                )
                arrow_item.set_mouse_interactive(False)
                self.addItem(arrow_item)
                self._arrow_items.append(arrow_item)
        # 若存在临时分组信息，则绘制其连线与首尾 helper
        if getattr(self, "_temp_group_to_point", None):
            QTimer.singleShot(0, self._update_temp_group_visuals)
        # "跟随"/"路径"/"间隔"：将选中点位视觉重置到上一张图位置
        if self.active_tool in {"跟随", "路径", "间隔"} and self._selected_point_ids and self.active_node > 0:
            self._reset_selected_points_to_prev_visual()
        # 跟随工具的 helper 需在预览点位移动后绘制，以保证 helper 位置与预览点位一致
        if self.active_tool == "跟随":
            self._draw_follow_group_helpers()
            self.update()

    def delete_selected_points(self):
        """删除当前选中的点位：在所有节点中移除对应点位 ID，重排剩余点位 ID 并同步 group_to_point 与 _next_point_id。"""
        to_delete = set(int(i) for i in getattr(self, "_selected_point_ids", set()))
        if not to_delete:
            return

        # 收集所有剩余点位 ID（跨所有节点），按旧 ID 升序排序以确定新 ID 分配顺序
        remaining_ids = sorted({int(p["id"]) for pts in self.node_points for p in pts if int(p["id"]) not in to_delete})

        # 生成 old->new 映射（point_id 从 0 开始）
        id_map = {old: new for new, old in enumerate(remaining_ids, start=0)}

        # 重新构建每个节点的点位列表，移除被删点并重写 ID
        for node_idx in range(len(self.node_points)):
            new_points = []
            for p in self.node_points[node_idx]:
                old_id = int(p.get("id", -1))
                if old_id in to_delete:
                    continue
                new_id = id_map.get(old_id)
                if new_id is None:
                    continue
                # 更新 id，同时保留坐标与 group_id
                new_p = {"id": new_id, "x": p["x"], "y": p["y"]}
                if p.get("group_id") is not None:
                    new_p["group_id"] = p.get("group_id")
                new_points.append(new_p)
            self.node_points[node_idx] = new_points

        # 更新分组信息：移除被删的点位并将其余 point_ids 映射为新 ID
        for group in self.group_to_point:
            old_list = [int(pid) for pid in group["point_ids"]]
            new_list = [id_map[pid] for pid in old_list if pid not in to_delete and pid in id_map]
            group["point_ids"] = new_list

        # 更新 node_paths：移除与删除点位相关的路径定义，并重映射剩余点位 ID
        for node_idx in list(self.node_paths.keys()):
            self.clear_selected_point_in_path(node_idx)

        # 更新自增计数器
        self._next_point_id = len(self.node_points[0])

        # 更新点位标签数据（point_lable 以 point_id 为下标）
        if self.point_lable:
            new_point_lable = []
            # 按 prefix 分组收集标签
            prefix_groups = {}
            for old_id, new_id in sorted(id_map.items()):
                while len(new_point_lable) <= new_id:
                    new_point_lable.append(None)
                old_idx = old_id
                if 0 <= old_idx < len(self.point_lable) and self.point_lable[old_idx] is not None:
                    label = dict(self.point_lable[old_idx])
                    prefix = label.get("prefix", "")
                    prefix_groups.setdefault(prefix, []).append((new_id, label))
            # 在每个 prefix 组内按 new_id 顺序重新分配 serial
            for entries in prefix_groups.values():
                entries.sort(key=lambda e: e[0])
                for idx, (new_id, label) in enumerate(entries):
                    label["serial"] = idx + 1
                    new_point_lable[new_id] = label
            self.point_lable = new_point_lable

        # 若删除后所有节点的点位列表均为空，则将 node_manual_edited 全部置为 False
        if all(len(pts) == 0 for pts in self.node_points):
            self.node_manual_edited = [False] * len(self.node_points)

        # 清除当前选中集合并刷新显示与后续自动计算
        self._selected_point_ids = set()
        self.clear_empty_group()
        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
        self._render_points_for_active_node()
        self.dataChanged.emit()

    def restore_selected_points_to_prev(self):
        """将当前选中的点位恢复到前一节点对应点位的位置。

        - 仅在 active_node > 0 时可用。
        - 对每个被选中的点，将 x,y 恢复到前一节点对应的值，并同步后续所有未修改节点的对应点位。
        - 若所有点位均与前一节点一致，则将 node_manual_edited[current_node] 置为 False。（即为未修改过）
        """
        if not getattr(self, "_selected_point_ids", None):
            return
        if int(getattr(self, "active_node", 0)) <= 0:
            return

        current_points = self.node_points[self.active_node]
        for p in current_points:
            pid = int(p.get("id", -1))
            if pid in self._selected_point_ids:
                # p["x"] = prev_points[pid][0]
                # p["y"] = prev_points[pid][1]
                prev_point = self._find_point_in_node(self.active_node - 1, pid)
                p["x"] = prev_point['x']
                p["y"] = prev_point['y']

        # 从 active_node 的 node_paths 中移除与选中点位相关的路径定义
        self.clear_selected_point_in_path(self.active_node)

        self.node_manual_edited[self.active_node] = True
        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=False)
        self.dataChanged.emit()

        # 若所有点位均与前一节点一致，则标记为未修改
        all_match = True
        for p in self.node_points[self.active_node]:
            pid = int(p.get("id", -1))
            prev_point = self._find_point_in_node(self.active_node - 1, pid)
            if abs(float(p.get("x", 0.0)) - float(prev_point['x'])) > 1e-9 or abs(float(p.get("y", 0.0)) - float(prev_point['y'])) > 1e-9:
                all_match = False
                break

        if all_match:
            self.node_manual_edited[self.active_node] = False

        self._render_points_for_active_node()

    def _draw_point_item(self, point: dict, pre_view: bool, draw_label: bool):
        """在场景中绘制一个点位项。根据 point 字典中的信息创建一个 PerformerPointItem，并将其添加到场景中。
        pre_view 参数用于确定该点位是否为预览状态，预览状态的点位通常会使用半透明的颜色来区分于正式绘制的点位。
        draw_label 参数用于确定是否在点位旁边绘制一个标签，标签显示点位的 ID 以便识别。
        此方法会先计算点位在场景中的位置，然后根据 pre_view 参数创建相应样式的 PerformerPointItem，并将其添加到场景中。
        同时，如果 draw_label 为 True，还会创建一个 QGraphicsSimpleTextItem 来显示点位的 ID，并将其添加到场景中。
        所有创建的项都会被记录在相应的列表和字典中，以便后续管理和更新。"""
        pos = self._field_to_scene(point["x"], point["y"])
        # radius = 5.0

        if pre_view:
            # 绘制上一张图的点位
            item = QGraphicsEllipseItem(pos.x() - self.pre_point_radius, pos.y() - self.pre_point_radius, self.pre_point_radius * 2, self.pre_point_radius * 2)
            item.setPen(QPen(Qt.PenStyle.NoPen))
            item.setBrush(QBrush(self.pre_point_color))
            self._previous_items.append(item)
        else:
            # 绘制当前图的点位
            item = PerformerPointItem(
                point_id=point["id"],
                center_scene_pos=pos,
                moved_callback=self._on_performer_point_moved,
                released_callback=self._on_performer_point_released,
                can_drag_callback=self._can_drag_performer_point,
                pressed_callback=self._on_performer_point_pressed,
                selected=point["id"] in self._selected_point_ids,
            )
            self._current_items.append(item)
            self._point_items_by_id[int(point["id"])] = item

            rematch_snapshot = self._drawing_rematch_snapshot()
            if (
                rematch_snapshot["active"]
                and int(point["id"]) in rematch_snapshot["selected_ids"]
            ):
                helper_radius = self.helper_radius
                helper = QGraphicsEllipseItem(
                    pos.x() - helper_radius,
                    pos.y() - helper_radius,
                    helper_radius * 2,
                    helper_radius * 2,
                )
                point_id = int(point["id"])
                if point_id == rematch_snapshot.get("candidate_point_id"):
                    helper_pen = QPen(QColor("#2980b9"), 1.8)
                elif point_id in rematch_snapshot.get("matched_ids", set()):
                    helper_pen = QPen(QColor("#27ae60"), 1.6)
                else:
                    helper_pen = QPen(QColor("#7f8c8d"), 1.4)
                helper.setPen(helper_pen)
                # 使用透明填充而不是 NoBrush，这样圆内部也会被视为可点击区域
                helper.setBrush(QBrush(QColor(0, 0, 0, 0)))
                helper.setZValue(900)
                helper.setData(0, "drawing_rematch_helper")
                helper.setData(1, point_id)
                self.addItem(helper)
                self._rematch_helper_items.append(helper)
        self.addItem(item)

        if draw_label:
            # 绘制标签，使用场景参数控制字体大小、偏移与角度
            label = QGraphicsSimpleTextItem(self._get_point_label_text(point["id"]))
            # 字体大小
            font = QFont()
            font.setPointSize(int(self.label_size))
            label.setFont(font)
            label.setBrush(QBrush(self.label_color))
            # 计算相对于点位的偏移（角度以 15° 为单位）并使标签中心位于该偏移点
            angle_deg = (int(self.label_pos) % 360)
            angle_rad = math.radians(angle_deg)
            dx = math.cos(angle_rad) * float(self.label_offset)
            dy = math.sin(angle_rad) * float(self.label_offset)
            br = label.boundingRect()
            label.setPos(pos.x() + dx - br.width() / 2.0, pos.y() + dy - br.height() / 2.0)
            self.addItem(label)
            self._label_items.append(label)
            self._label_items_by_id[int(point["id"])] = label

    def _position_occupied(self, x: float, y: float) -> bool:
        """判断当前图是否已有同位置点位。"""
        for point in self.node_points[self.active_node]:
            if abs(point["x"] - x) < 1e-9 and abs(point["y"] - y) < 1e-9:
                return True
        return False

    def _scene_item_under_cursor(self, scene_pos: QPointF):
        """根据场景坐标获取当前鼠标下的图元项。此方法会调用 QGraphicsScene 的 itemAt 方法，传入鼠标的场景坐标和当前视图的变换矩阵，以获取位于该位置的图元项。由于可能存在多个视图，此方法会优先使用第一个视图进行坐标转换。如果没有任何视图可用，则返回 None。"""
        views = self.views()
        if not views:
            return None
        return self.itemAt(scene_pos, views[0].transform())

    def mousePressEvent(self, event):
        """绘图模式下拦截鼠标：左键采样点。"""
        if event.button() == Qt.MouseButton.LeftButton:
            item = self._scene_item_under_cursor(event.scenePos())
            if self.active_tool == "文本":
                if not self._is_current_beat_editable():
                    event.accept()
                    return
                item_type = item.data(0) if item is not None and hasattr(item, "data") else None
                item_id = item.data(1) if item is not None and hasattr(item, "data") else None
                if isinstance(item, ReferenceHandleItem):
                    super().mousePressEvent(event)
                    return
                if isinstance(item, TextBoxItem) or item_type == "textbox" or item_type == "textbox_proxy":
                    textbox_id = None
                    if isinstance(item, TextBoxItem):
                        textbox_id = int(item.textbox_id)
                    elif item_id is not None:
                        textbox_id = int(item_id)
                    if textbox_id is not None:
                        self._textbox_pending_points = []
                        self._set_selected_textbox_id(textbox_id, refresh=False)
                    super().mousePressEvent(event)
                    textbox_item = self._textbox_items_by_id.get(textbox_id) if textbox_id is not None else None
                    if textbox_item is not None:
                        textbox_item.focus_editor()
                    return

                x, y = self._scene_to_field(event.scenePos())
                x, y = self._snap_field_point(x, y)
                self._textbox_pending_points.append((x, y))
                self._set_selected_textbox_id(None)
                if len(self._textbox_pending_points) >= 2:
                    p1 = self._textbox_pending_points[0]
                    p2 = self._textbox_pending_points[1]
                    textbox = {
                        "id": int(self._next_textbox_id),
                        "x1": float(p1[0]),
                        "y1": float(p1[1]),
                        "x2": float(p2[0]),
                        "y2": float(p2[1]),
                        "text": "",
                        "font_size": int(self._textbox_font_size),
                    }
                    self._next_textbox_id += 1
                    self._textbox_preview.append(textbox)
                    self._textbox_pending_points = []
                    self._set_selected_textbox_id(int(textbox["id"]), refresh=False)
                    self._render_points_for_active_node()
                    textbox_item = self._textbox_items_by_id.get(int(textbox["id"]))
                    if textbox_item is not None:
                        textbox_item.focus_editor()
                event.accept()
                return

            if self.active_tool == "箭头":
                if not self._is_current_beat_editable():
                    event.accept()
                    return
                if isinstance(item, ReferenceHandleItem):
                    super().mousePressEvent(event)
                    return
                if isinstance(item, ArrowItem):
                    # ArrowItem 处理自己的 click
                    super().mousePressEvent(event)
                    return
                # 点击空白区域：向当前箭头添加参考点。
                entry = self._current_arrow_entry()
                if entry is None:
                    # 无当前箭头，新建一个（沿用控制台中的类型/样式设置）
                    dock = getattr(self.parent(), "drawingControlDock", None)
                    type_map = {'折线': 'line', '曲线': 'curve', '圆': 'circle'}
                    arrow_type = 'line'
                    if dock is not None:
                        type_text = dock.arrowTypeCombo.currentText()
                        arrow_type = type_map.get(type_text, 'line')
                    self._arrow_editing_index = len(self._arrow_preview)
                    self._arrow_preview.append({
                        'type': arrow_type,
                        'points': [],
                        'style': {
                            'forward': dock.arrowForwardCheck.isChecked() if dock else True,
                            'backward': dock.arrowBackwardCheck.isChecked() if dock else False,
                            'mid': dock.arrowMidCheck.isChecked() if dock else False,
                        },
                    })
                    entry = self._arrow_preview[self._arrow_editing_index]

                x, y = self._scene_to_field(event.scenePos())
                x, y = self._snap_field_point(x, y)

                # 若当前编辑箭头已有确认点位，则直接追加到 entry['points'] 并刷新
                if entry is not None and entry.get('points'):
                    entry['points'].append((float(x), float(y)))
                    if entry.get('type') == 'circle':
                        entry['points'] = entry['points'][:2]
                else:
                    self._arrow_pending_points.append((float(x), float(y)))
                    if entry is not None and entry.get('type') == 'circle':
                        self._arrow_pending_points = self._arrow_pending_points[:2]

                self._render_points_for_active_node()
                self._sync_arrow_dock_state()
                event.accept()
                return

            if self.active_tool == "调整":
                if isinstance(item, (ReferenceHandleItem, MovementControlHandleItem)):
                    super().mousePressEvent(event)
                else:
                    event.accept()
                return

            if isinstance(item, (ReferenceHandleItem, MovementControlHandleItem)):
                super().mousePressEvent(event)
                return

            # 间隔行进工具：点击 helper 圆圈启动拖拽
            if self.active_tool == "间隔" and item is not None and item.data(0) == "interval_helper":
                point_id = int(item.data(1))
                self._on_interval_drag_started(point_id, event.scenePos())
                self._interval_dragging = True
                event.accept()
                return

            # 旋转工具：点击旋转中心 helper 启动拖拽
            if self.active_tool == "旋转" and item is not None and item.data(0) == "rotate_helper":
                self._rotate_dragging = True
                event.accept()
                return

            rematch_snapshot = self._drawing_rematch_snapshot()
            clicked_point_id = None
            if isinstance(item, PerformerPointItem):
                clicked_point_id = int(item.point_id)
            elif item is not None and item.data(0) in ("drawing_rematch_helper", "temp_group_helper"):
                helper_point_id = item.data(1)
                if helper_point_id is not None:
                    clicked_point_id = int(helper_point_id)

            if rematch_snapshot["active"] and self._is_drawing_tool() and clicked_point_id is not None:
                # 点击时先将该点设置为当前预览的候选匹配，若设置成功则立即确认匹配并前进。
                if self.drawing_match_set_candidate(clicked_point_id):
                    # 自动确认当前候选匹配（等同于用户点击“Keep”按钮），然后阻止事件继续传播。
                    self.drawing_match_keep()
                    event.accept()
                    return
            if rematch_snapshot["active"] and self._is_drawing_tool():
                event.accept()
                return

            if self.active_tool == "跟随" and item is not None and item.data(0) == "follow_group_helper":
                group_id = item.data(1)
                if group_id is not None and self._toggle_follow_group_leader(int(group_id)):
                    # 若锚点（第一个选中点）在切换的组内，同步更新草稿路径起点为新 leader 上一节点位置
                    selected_ids = self._selected_point_ids
                    anchor_id = self._get_anchor()
                    anchor_point = self._find_point_in_node(self.active_node, anchor_id)
                    point_group_id = int(anchor_point["group_id"])
                    if not self._draft_reference_points and not self._pending_points:
                        group_info = self.group_to_point[point_group_id]
                        ordered_ids = self._follow_group_point_ids_for_group(group_info)
                        new_anchor_id = int(ordered_ids[0])
                        prev_point = self._find_point_in_node(self.active_node - 1, new_anchor_id)
                        new_pos = (float(prev_point["x"]), float(prev_point["y"]))
                        self._draft_reference_points[0] = new_pos
                        self._pending_points[0] = new_pos
                    self._render_points_for_active_node()
                    self.drawingRematchStateChanged.emit()
                event.accept()
                return

            # 分组工具交互：单击或框选用于向当前临时分组添加点
            if self.active_tool == "分组":
                # 若点击了点或 helper，则把该点所属组或点本身加入当前临时组
                if clicked_point_id is not None:
                    cur_grp = self._temp_group_to_point[self._temp_group_current_index]
                    if clicked_point_id in cur_grp:
                        # 若点击的点位在当前临时组内，则切换首/尾插入标记
                        self._temp_group_mark_head = not self._temp_group_mark_head
                    else:
                        # 否则进行组合并
                        temp_group_point_ids = self._temp_group_point_ids_for_point_id(clicked_point_id)
                        if temp_group_point_ids:
                            self.add_point_ids_to_current_temp_group(temp_group_point_ids, clicked_point_id)
                        else:
                            self.add_point_ids_to_current_temp_group([clicked_point_id], clicked_point_id)
                        event.accept()
                    self._render_points_for_active_node()
                    return

            # 非单点草稿态：禁止新增参考点点击，仅保留手柄拖拽。
            # 对于“路径”工具允许在草稿态继续添加参考点（轨迹追加）。
            if self._is_drawing_tool() and self._draft_tool_name and self._draft_tool_name not in {"点", "路径", "跟随"}:
                event.accept()
                return

            modifiers = event.modifiers()
            if self.active_tool in {"框选", "选择"} and isinstance(item, PerformerPointItem):
                # 框选时，对选中的单一点位进行拖拽修改位置。
                selected_ids = set(self._selected_point_ids)
                if self.active_tool == "选择":
                    if (modifiers & Qt.KeyboardModifier.ShiftModifier):
                        group_point_ids = self._group_point_ids_for_point_id(item.point_id)
                        for group_point_id in group_point_ids:
                            if group_point_id in selected_ids:
                                selected_ids.discard(group_point_id)
                            else:
                                selected_ids.add(group_point_id)
                    elif (modifiers & Qt.KeyboardModifier.ControlModifier):
                        if item.point_id in selected_ids:
                            selected_ids.discard(item.point_id)
                        else:
                            selected_ids.add(item.point_id)
                    else:
                        selected_ids = set(self._group_point_ids_for_point_id(item.point_id))
                else:
                    # 框选操作
                    selected_ids = {item.point_id}
                if (modifiers & Qt.KeyboardModifier.ControlModifier) and self.active_tool == "框选":
                    self._selected_point_ids.update(selected_ids)
                else:
                    self._selected_point_ids = selected_ids
                self._refresh_point_selection_visuals()
                self._clear_selection_rect()
                super().mousePressEvent(event)
                return

            if self.active_tool in {"框选", "选择"}:
                # 点击框选工具下的空白区域：进入框选状态，记录起始场景坐标，清空当前选择并刷新视觉效果。
                self._selection_start_position = QPointF(event.scenePos())
                self._selection_current_position = QPointF(event.scenePos())
                if not ((modifiers & Qt.KeyboardModifier.ControlModifier) and self.active_tool == "框选"):
                    self._selected_point_ids.clear()
                self._refresh_point_selection_visuals()
                self._update_selection_rect_item()
                event.accept()
                return

        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing_tool():
            # 绘图时，点击生成“参考点”，参考点始终吸附到格线；
            # 自动生成的点位仅在确认后写入。
            if not self._is_current_beat_editable():
                event.accept()
                return

            x, y = self._scene_to_field(event.scenePos())
            x, y = self._snap_field_point(x, y)

            self._handle_draw_tool(self.active_tool, (x, y))
            self._render_points_for_active_node()

            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        """绘图模式下拦截鼠标：左键拖动更新框选区域。"""
        if event.buttons() & Qt.MouseButton.LeftButton and self._selection_start_position is not None:
            if self.active_tool in {"框选", "选择"}:
                self._selection_current_position = QPointF(event.scenePos())
                self._update_selection_rect_item()
                # 实时更新被框选的点并刷新视觉反馈
                scene_rect = QRectF(self._selection_start_position, self._selection_current_position).normalized()
                self._select_points_in_scene_rect(scene_rect, self.active_tool, event)
                event.accept()
                return

        # 间隔行进工具拖拽中
        if self._interval_dragging and self._interval_anchor_id is not None:
            self._on_interval_helper_moved(self._interval_anchor_id, event.scenePos())
            event.accept()
            return

        # 旋转工具拖拽中
        if self._rotate_dragging:
            self._on_rotate_center_moved(event.scenePos())
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """绘图模式下拦截鼠标：左键释放完成框选。"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.active_tool in {"框选", "选择"} and self._selection_start_position is not None:
                self._selection_current_position = QPointF(event.scenePos())
                scene_rect = QRectF(self._selection_start_position, self._selection_current_position).normalized()
                self._select_points_in_scene_rect(scene_rect, self.active_tool, event)
                self._clear_selection_rect()
                event.accept()
                return

            # 间隔行进工具拖拽释放
            if self._interval_dragging:
                self._interval_dragging = False
                event.accept()
                return

            # 旋转工具拖拽释放
            if self._rotate_dragging:
                self._rotate_dragging = False
                event.accept()
                return

        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        super().keyPressEvent(event)