"""
绘制方案图
"""
import math
from pathlib import Path

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
from field_info import FieldInfo, ZOOM_PERCENT_FACTOR
from field_renderer import GridRenderer
from scene_items import PerformerPointItem, ReferenceHandleItem, MovementControlHandleItem, TextBoxItem
from scheme_scene_data import SchemeSceneData
from draw_utils import (
    _distance,
    # _dedupe_points,
    # _sample_line_points_with_count,
    _sample_polyline_points,
    _sample_polyline_points_with_count,
    _sample_polyline_points_with_count_and_spacing,
    _sample_curve_points,
    _build_dense_curve_points,
    _sample_closed_polyline_points_with_spacing,
    _sample_closed_polyline_points_with_count,
    _make_polygon_points,
    # _circle_from_two_points,
    # _rectangle_from_three_points,
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
    # lineSegmentPointCountChanged = pyqtSignal(int)  # 线段工具采样点位数量
    # lineSegmentSpacingChanged = pyqtSignal(float)   # 线段工具采样间距
    
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
        
        self.setup_scene_data()     # 初始化场景数据结构
        self._draft_tool_name = None    # 当前正在使用的绘图工具名称，None表示无草稿状态；非None表示草稿状态，值为对应工具名称。
        self._draft_reference_points = []   # 当前绘图草稿的参考点坐标列表
        self._draft_preview_items = []      # 当前绘图草稿的预览图元列表
        self._pending_preview_items = []    # 当前未确认阶段的参考线预览图元列表（如曲线/折线工具在输入至少2个点位后的实时预览）
        self._draft_handle_items = []       # 当前绘图草稿的可拖动参考点图元列表（如曲线/折线工具在输入至少2个点位后的可调整参考点）
        self._pending_points = []   # 当前工具操作中尚未提交的数据点位列表，如绘制中的线段或多边形顶点等
        
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

        # 固定为启动时的初始场景大小，避免新增图元导致 sceneRect 自动变化。
        initial_field_rect = self.field_info.field_rect
        # initial_scale = float(self.field_info.scale)
        # width_px = float(initial_field_rect.width()) * initial_scale
        # height_px = float(initial_field_rect.height()) * initial_scale
        # margin = max(width_px, height_px) * 0.5 + 200.0
        self.setSceneRect(initial_field_rect)
        
        
        # 上一点位的绘制参数（用于预览上一节点的点位）
        self.pre_point_radius = 2.0
        self.pre_point_color = QColor("#444444")  # alpha 值控制透明度（0-255，值越大越不透明）
        
        # 点位label绘制参数
        self.label_color = QColor("#000000")
        self.label_size = 12    # label 字体大小
        self.label_offset = 15  # label 相对于点位的距离
        self.label_pos = 6     # label 相对于点位的角度 以15°为单位，上限为24（360°），默认12（120° 下侧）
        
        #点位修改的参数
        self.helper_radius = 12

        self.export_ratio = 3.0

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

    def load_confirmed_state(self, data: dict, node_count: int | None = None):
        """恢复已确认的方案图数据，并清理当前编辑中的临时状态。"""
        self.load_confirmed_state_data(data, node_count=node_count)
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
        self._clear_overlay_items()

    def load_confirmed_state_data(self, data: dict, node_count: int | None = None):
        """仅恢复数据层状态，不重绘场景。"""
        super().load_confirmed_state(data, node_count=node_count)

    def _copy_textboxes_for_node(self, node_index: int) -> list[dict]:
        return [dict(tb) for tb in self.node_textboxes.get(int(node_index), [])]

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

    # def _selected_textbox_item(self):
    #     selected = self._selected_preview_textbox()
    #     if selected is None:
    #         return None
    #     return self._textbox_items_by_id.get(int(selected.get("id", -1)))

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
        self._textbox_preview = self._copy_textboxes_for_node(self.active_node)
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
        self._textbox_preview = self._copy_textboxes_for_node(self.active_node)
        self._textbox_pending_points = []
        self._set_selected_textbox_id(None)
        self._render_points_for_active_node()

    def _ordered_selected_point_ids_for_drawing(self) -> list[int]:
        """按当前节点顺序返回被选中的点位 ID。"""
        if not self._selected_point_ids:
            return []
        return [
            int(point.get("id", -1))
            for point in self.node_points.get(self.active_node, [])
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

    # def get_drawing_rematch_status(self) -> dict:
    #     """提供给主窗口的绘图重匹配状态快照。"""
    #     return self._drawing_rematch_snapshot()

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

    # def _pdf_export_font_scale_factor(self, export_scale: float) -> float:
    #     """把导出字号换算到页面导出坐标系。"""
    #     base_scale = 22.0
    #     return max(0.1, float(export_scale) / base_scale)

    def _pdf_export_content_padding(self, export_scale: float) -> tuple[float, float, float]:
        """计算 PDF 内容区留白（水平、上、下），下侧留白约为上侧的两倍。

        返回 (horizontal_padding, top_padding, bottom_padding)。
        """
        font_px = float(self.field_info.label_zoom) * export_scale
        offset_px = max(float(abs(self.field_info.label_x_offset)) + font_px,
                        float(abs(self.field_info.label_y_offset)) + font_px)

        # 保持原先对水平留白的保护规则
        horizontal_padding = max(128.0, offset_px * 5.0)

        # 设定上/下不对称：上侧取较小的基准，下侧约为上侧的两倍并至少保持与旧逻辑相同的下限
        top_padding = max(64.0, offset_px * 3.0)
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
        export_grid_renderer.draw_field_labels(painter)

    def _add_pdf_export_point_items(self, scene: QGraphicsScene, point: dict, export_scale: float, export_offset: QPointF):
        """向临时导出场景添加一个点位及其标签。"""
        field_x = float(point.get("x", 0.0))
        field_y = float(point.get("y", 0.0))
        pos = QPointF(field_x * export_scale + float(export_offset.x()), field_y * export_scale + float(export_offset.y()))
        # font_scale = self._pdf_export_font_scale_factor(export_scale)
        font_scale = export_scale
        size_scale = font_scale

        # point_item = PerformerPointItem()
        dot_radius = 5.0 * self.export_ratio
        dot = QGraphicsEllipseItem(pos.x() - dot_radius, pos.y() - dot_radius, dot_radius * 2.0, dot_radius * 2.0)
        dot.setPen(QPen(Qt.PenStyle.NoPen))
        dot.setBrush(QBrush(QColor("#2aa6ff")))
        dot.setZValue(960)
        scene.addItem(dot)

        label = QGraphicsSimpleTextItem(str(int(point.get("id", 0))))
        font = QFont()
        font.setPointSizeF(float(self.label_size * self.export_ratio))
        label.setFont(font)
        label.setBrush(QBrush(self.label_color))
        angle_deg = (int(self.label_pos) % 24) * 15
        angle_rad = math.radians(angle_deg)
        dx = math.cos(angle_rad) * float(self.label_offset) * self.export_ratio
        dy = math.sin(angle_rad) * float(self.label_offset) * self.export_ratio
        br = label.boundingRect()
        label.setPos(pos.x() + dx - br.width() / 2.0, pos.y() + dy - br.height() / 2.0)
        label.setZValue(965)
        scene.addItem(label)

    def _add_pdf_export_textbox_items(self, scene: QGraphicsScene, textbox: dict, export_scale: float, export_offset: QPointF):
        """向临时导出场景添加一个文本框。"""
        from scene_items import TextBoxItem
        # font_scale = self._pdf_export_font_scale_factor(export_scale)
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

    def _build_pdf_export_scene(self, node_index: int, page_cnt: int, export_scale: float, export_offset: QPointF) -> QGraphicsScene:
        """为单个方案图节点构建临时导出场景。"""
        export_scene = QGraphicsScene()
        # node_index = node_index
        # if node_index > 0:
        for point in self.node_points.get(node_index, []):
            pos = QPointF(float(point.get("x", 0.0)) * export_scale + float(export_offset.x()), float(point.get("y", 0.0)) * export_scale + float(export_offset.y()))
            # pre_dot_radius = 2.0 * self._pdf_export_font_scale_factor(export_scale)
            pre_dot_radius = self.pre_point_radius * self.export_ratio
            pre_dot = QGraphicsEllipseItem(pos.x() - pre_dot_radius, pos.y() - pre_dot_radius, pre_dot_radius * 2.0, pre_dot_radius * 2.0)
            pre_dot.setPen(QPen(Qt.PenStyle.NoPen))
            pre_dot.setBrush(QBrush(self.pre_point_color))
            pre_dot.setZValue(950)
            export_scene.addItem(pre_dot)
        for point in self.node_points.get(node_index, []):
            self._add_pdf_export_point_items(export_scene, point, export_scale, export_offset)
        for textbox in self.node_textboxes.get(node_index, []):
            self._add_pdf_export_textbox_items(export_scene, textbox, export_scale, export_offset)
        return export_scene

    def export_pdf(self, file_path: str | Path, cnt_per_page: list[int] | None = None):
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

        # indexes = list(range(len(self.node_points))) if node_indexes is None else [max(0, int(idx)) for idx in node_indexes]
        # if not indexes:
        #     indexes = [0]

        painter = QPainter(writer)
        try:
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

        finally:
            painter.end()

    def _clear_overlay_items(self):
        """清除当前所有点位与标签图元，准备重建。"""
        for item in self._current_items + self._previous_items + self._label_items + self._selection_link_items + self._rematch_helper_items + self._textbox_items + self._textbox_handle_items:
            self.removeItem(item)
        self._current_items = []
        self._previous_items = []
        self._label_items = []
        self._selection_link_items = []
        self._rematch_helper_items = []
        self._textbox_items = []
        self._textbox_items_by_id = {}
        self._textbox_handle_items = []
        self._point_items_by_id = {}
        self._label_items_by_id = {}

    def set_active_tool(self, tool_name: str):
        """切换当前工具并清空临时草稿。"""
        # if self.active_tool == "调整" and tool_name != "调整" and self._adjustment_active:
        #     self._reset_adjustment_state(reset_controls=True)

        previous_tool = self.active_tool
        if previous_tool == "文本" and tool_name != "文本":
            self._exit_textbox_mode()

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
        self._render_points_for_active_node()   # 刷新点位显示
        if tool_name == "调整" and self._selected_point_ids:
            self.begin_adjustment()
        self.drawingRematchStateChanged.emit()

    def set_active_node(self, node_index: int):
        """切换当前时间轴节点并刷新显示。"""
        if self.active_tool == "调整" and self._adjustment_active:
            self._reset_adjustment_state(reset_controls=True)

        self.active_node = max(0, int(node_index))  # 确保节点索引非负
        self.ensure_node_exists(self.active_node)   # 确保目标节点存在，若不存在则初始化
        self._pending_points = []   # 清空草稿点位
        self._reset_drawing_rematch_state(active=False)
        self._selected_point_ids.clear()
        self._clear_selection_rect()
        self._clear_draft()
        if self.active_tool == "文本":
            self._enter_textbox_mode()
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
        for point in self.node_points.get(self.active_node, []):
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

    def _refresh_selected_group_links(self):
        """根据当前选中点位重建组内连线，只连接每组中被选中的点。"""
        self._clear_selection_link_items()
        if not self._selected_point_ids:
            return

        # 连接同一组内被选中的点位，使用不透明线条。
        pen = QPen(QColor("#f39c12"), 2, Qt.PenStyle.SolidLine)
        pen.setCosmetic(True)

        for group_info in self.group_to_point:
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

    def _find_point_by_id(self, point_id: int) -> dict | None:
        """根据点位ID查找当前节点中的点位数据字典"""
        for point in self.node_points.get(self.active_node, []):
            if int(point.get("id", -1)) == int(point_id):
                return point
        return None

    def _group_point_ids_for_point_id(self, point_id: int) -> list[int]:
        """获取指定点位所属组的全部点位 ID；若点位未归组则返回空列表。"""
        point = self._find_point_by_id(point_id)
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

        point = self._find_point_by_id(point_id)
        if point is None:
            return scene_pos
        x, y = self._scene_to_field(scene_pos)
        x, y = self._snap_field_point(x, y)

        for other in self.node_points.get(self.active_node, []):
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
            angle_deg = (int(self.label_pos) % 24) * 15
            angle_rad = math.radians(angle_deg)
            dx = math.cos(angle_rad) * float(self.label_offset)
            dy = math.sin(angle_rad) * float(self.label_offset)
            br = label.boundingRect()
            label.setPos(pos.x() + dx - br.width() / 2.0, pos.y() + dy - br.height() / 2.0)

        if int(point_id) in self._selected_point_ids:
            self._refresh_selected_group_links()
            if len(self._selected_point_ids) == 1:
                # 单点拖拽时补充“原始->当前位置”预览连线。
                self._selection_link_items.extend(self._build_preview_line_items([point]))

        return self._field_to_scene(x, y)

    def _on_performer_point_released(self, point_id: int | None = None):
        """预览拍位下禁止写回真实数据，直接返回；当前节点拍位上则标记节点为手动编辑过并触发后续自动调整。"""
        # 清理拖拽中附加到 selection_link 的预览连线。
        self._refresh_selected_group_links()
        if not self._is_current_beat_editable():
            return
        self._mark_node_manual(self.active_node)
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

        source_points = [
            {"id": int(point["id"]), "x": float(point["x"]), "y": float(point["y"]), **({"group_id": point.get("group_id")} if point.get("group_id") is not None else {})}
            for point in self.node_points.get(self.active_node, [])
        ]
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

        current_points = self.node_points.setdefault(self.active_node, [])
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
        self._mark_node_manual(self.active_node)
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

    def _build_preview_line_items(self, dst_points: list, src_points: list[dict] | None = None, *, z: float = 200) -> list:
        """根据目标点位集构建原始->目标的连线图元。"""
        line_items = []
        if not dst_points:
            return line_items

        prev_points = self.node_points.get(self.active_node - 1, [])
        source_points = prev_points if prev_points else (src_points or [])
        if not source_points:
            return line_items

        if isinstance(dst_points[0], dict):
            src_map = {
                int(point.get("id", -1)): (float(point.get("x", 0.0)), float(point.get("y", 0.0)))
                for point in source_points
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

        match_count = min(len(source_points), len(dst_points))
        for i in range(match_count):
            src = source_points[i]
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
            angle_deg = (int(self.label_pos) % 24) * 15
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
                handle.set_size(12.0)
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
            center_handle.set_size(32.0)
            center_handle.set_inner_ratio(0.45)
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
        try:
            for handle, (x, y) in zip(self._draft_handle_items, self._draft_reference_points):
                handle.setPos(self._field_to_scene(x, y))
        finally:
            self._updating_draft_handles = False

    def _sync_pending_handle_positions(self):
        """把已有待确认参考点手柄同步到当前参考点坐标。"""
        if len(self._draft_handle_items) != len(self._pending_points):
            return
        self._updating_draft_handles = True
        try:
            for handle, (x, y) in zip(self._draft_handle_items, self._pending_points):
                handle.setPos(self._field_to_scene(x, y))
        finally:
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

        # if self.active_tool == "文本" and len(self._textbox_pending_points) == 1:
        #     self._clear_pending_preview_items()
        #     self._sync_pending_handle_positions()
        #     self._draw_pending_reference_preview()
        #     self._draw_pending_reference_points()
        #     return

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

        # 未确认阶段同样显示按默认“两步间隔”采样的表演者预览点位。
        if self.active_tool == "曲线/折线" and len(self._pending_points) >= 2:
            preview_points = self._generate_performer_points("曲线/折线", self._pending_points)
            rematch_snapshot = self._drawing_rematch_snapshot()
            if rematch_snapshot["active"]:
                dots = self._render_preview_points_for_drawing_rematch(preview_points)
            else:
                dots = self.render_preview_points(preview_points)
            for d in dots:
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
        if tool_name == "点" and refs:
            # return _dedupe_points(refs)
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
                    # return _dedupe_points(_sample_polyline_points_with_count_and_spacing(refs, point_count, line_spacing))
                if state.get("spacing_manual", False):
                    return _sample_polyline_points(refs, line_spacing)
                    # return _dedupe_points(_sample_polyline_points(refs, line_spacing))
                if state.get("point_count_manual", False):
                    return _sample_polyline_points_with_count(refs, point_count)
                    # return _dedupe_points(_sample_polyline_points_with_count(refs, point_count))
                return _sample_polyline_points(refs, line_spacing)
                # return _dedupe_points(_sample_polyline_points(refs, line_spacing))
            elif tool_name == "弧":
                if state.get("point_count_manual", False) and state.get("spacing_manual", False):
                    return _sample_arc_points_with_count_and_spacing(refs[0], refs[2], refs[1], point_count, line_spacing)
                    # return _dedupe_points(_sample_arc_points_with_count_and_spacing(refs[0], refs[2], refs[1], point_count, line_spacing))
                if state.get("point_count_manual", False):
                    return _sample_arc_points_with_count(refs[0], refs[2], refs[1], point_count)
                    # return _dedupe_points(_sample_arc_points_with_count(refs[0], refs[2], refs[1], point_count))
                return _sample_arc_points(refs[0], refs[2], refs[1], line_spacing)
                # return _dedupe_points(_sample_arc_points(refs[0], refs[2], refs[1], line_spacing))
            elif tool_name == "圆":
                if state["point_count_manual"]:
                    return _sample_circle_points_with_count(refs[0], refs[1], point_count)
                    # return _dedupe_points(_sample_circle_points_with_count(refs[0], refs[1], point_count))
                return _sample_circle_points(refs[0], refs[1], line_spacing)
                # return _dedupe_points(_sample_circle_points(refs[0], refs[1], line_spacing))
            elif tool_name == "多边形":
                if state["point_count_manual"]:
                    return self._sample_polygon_perimeter_points_with_count(refs[0], refs[1], point_count)
                    # return _dedupe_points(self._sample_polygon_perimeter_points_with_count(refs[0], refs[1], point_count))
                return self._sample_polygon_perimeter_points(refs[0], refs[1], line_spacing)
                # return _dedupe_points(self._sample_polygon_perimeter_points(refs[0], refs[1], line_spacing))
            elif tool_name == "曲线/折线" and len(refs) >= 2:
                is_curve = getattr(self, '_curve_mode', 'polyline') == 'curve'
                if state["spacing_manual"] and state["point_count_manual"]:
                    if is_curve:
                        # dense_curve = _sample_curve_points(refs, line_spacing)
                        dense_curve = _build_dense_curve_points(refs, line_spacing)
                        return _sample_polyline_points_with_count_and_spacing(dense_curve, point_count, line_spacing)
                        # return _dedupe_points(_sample_polyline_points_with_count_and_spacing(dense_curve, point_count, line_spacing))
                    return _sample_polyline_points_with_count_and_spacing(refs, point_count, line_spacing)
                    # return _dedupe_points(_sample_polyline_points_with_count_and_spacing(refs, point_count, line_spacing))
                if state["spacing_manual"]:
                    if is_curve:
                        return _sample_curve_points(refs, line_spacing)
                        # return _dedupe_points(_sample_curve_points(refs, line_spacing))
                    return _sample_polyline_points(refs, line_spacing)
                    # return _dedupe_points(_sample_polyline_points(refs, line_spacing))
                if state["point_count_manual"]:
                    if is_curve:
                        return self._sample_curve_points_with_count(refs, point_count)
                        # return _dedupe_points(self._sample_curve_points_with_count(refs, point_count))
                    return _sample_polyline_points_with_count(refs, point_count)
                    # return _dedupe_points(_sample_polyline_points_with_count(refs, point_count))
                if is_curve:
                    return _sample_curve_points(refs, line_spacing)
                    # return _dedupe_points(_sample_curve_points(refs, line_spacing))
                return _sample_polyline_points(refs, line_spacing)
                # return _dedupe_points(_sample_polyline_points(refs, line_spacing))
            elif tool_name == "填充四边形" and len(refs) >= 3:
                state = self._sampling_state(tool_name)
                base_spacing = max(1e-9, float(self.field_info.grid_step) * float(state.get("spacing_steps", 2.0)))
                shift_spacing = max(1e-9, float(self.field_info.grid_step) * float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0))))
                base_point_count = int(state.get("point_count", 1))
                shift_point_count = int(state.get("point_count_shift", 1))
                return _sample_rectangle_fill_points_with_counts(refs[0], refs[1], refs[2], base_spacing, shift_spacing, base_point_count, shift_point_count)
                # return _dedupe_points(_sample_rectangle_fill_points_with_counts(refs[0], refs[1], refs[2], base_spacing, shift_spacing, base_point_count, shift_point_count))
        return []

    # def _generate_performer_points(self, tool_name: str, refs: list[tuple[float, float]]) -> list[tuple[float, float]]:
    #     """纯计算接口：根据工具与参考点计算返回 field 单位的预览点位列表（不创建任何 QGraphicsItem）。"""
    #     return self._generate_performer_points(tool_name, refs)

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
        if getattr(self, "_selected_point_ids", None):
            current_points = self.node_points.get(self.active_node, [])
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

        point_map = {
            int(point.get("id", -1)): point
            for point in self.node_points.get(self.active_node, [])
        }
        dst_ordered = []
        for point_id, preview_index in sorted(snapshot.get("point_to_preview", {}).items(), key=lambda item: int(item[1])):
            idx = int(preview_index)
            if idx < 0 or idx >= len(preview_points):
                continue
            dx, dy = preview_points[idx]
            dst_ordered.append({"id": int(point_id), "x": dx, "y": dy})
        items.extend(self._build_preview_line_items(dst_ordered, list(point_map.values()), z=z - 10))

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
        # if tool_name == "线段":
        #     self._sync_line_segment_auto_values_from_draft()
        self._render_points_for_active_node()
        self.draftStarted.emit(tool_name)
        self.drawingRematchStateChanged.emit()

    def _on_reference_handle_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        """草稿参考点被移动时的回调，用于更新参考点位置和草稿预览图形。返回更新后的 scene_pos（可能被吸附）。"""
        if self._updating_draft_handles:
            return scene_pos
        if index < 0 or index >= len(self._draft_reference_points):
            return scene_pos
        x, y = self._scene_to_field(scene_pos)
        x, y = self._snap_field_point(x, y)
        snapped_scene_pos = self._field_to_scene(x, y)
        self._draft_reference_points[index] = (x, y)
        # if self._draft_tool_name == "线段":
        #     self._sync_line_segment_auto_values_from_draft()
        if self._draft_tool_name in self._sampling_tools:
            self._sync_sampling_auto_values_from_draft(self._draft_tool_name)
        QTimer.singleShot(0, self._refresh_reference_overlay_for_active_tool)
        self.drawingRematchStateChanged.emit()
        return snapped_scene_pos

    def confirm_current_drawing(self):
        """确认当前草稿并写入当前节点点位。"""
        tool_name = self._draft_tool_name
        refs = list(self._draft_reference_points)
        had_draft = bool(self._draft_tool_name or self._draft_reference_points)

        # 曲线/折线可直接用 pending 参考点确认。
        if (not tool_name or not refs) and self.active_tool == "曲线/折线" and len(self._pending_points) >= 2:
            tool_name = "曲线/折线"
            refs = list(self._pending_points)

        if not tool_name or not refs:
            self._clear_draft()
            self._pending_points = []
            if not had_draft:
                self.draftFinished.emit()
            self._render_points_for_active_node()
            self.drawingRematchStateChanged.emit()
            return False
        
        generated = self._generate_performer_points(tool_name, refs)    # 生成最终点位列表（field 坐标）
        current_points = self.node_points.setdefault(self.active_node, [])  # 当前节点的点位列表

        # 如果有选中点，则按索引匹配移动已存在的点；多余的生成点不新增
        if getattr(self, "_selected_point_ids", None):
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

            if new_point_ids:
                # 添加到分组中
                self.node_to_group[self.active_node].add(group_id)
                self.group_to_point.append({
                    "point_ids": new_point_ids, # 组内点位 ID 列表
                    "leader": True,  # leader 点位为正向第一个
                })

        self._pending_points = []
        self._draft_reference_points = []
        self._reset_drawing_rematch_state(active=False)
        self._mark_node_manual(self.active_node)
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
        # if tool_name in {"圆", "多边形"}:
        #     return max(1, int(length // spacing))
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

    # def _sampling_shift_length_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> float:
    #     """计算填充四边形第二方向（P0-P2）的长度。"""
    #     if tool_name != "填充四边形" or len(refs) < 3:
    #         return 0.0
    #     ax, ay = refs[0]
    #     cx, cy = refs[2]
    #     return math.hypot(cx - ax, cy - ay)

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
        # state["point_count"] = 1
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
            # self._clear_draft_items()
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
            handle = ReferenceHandleItem(
                index = index,
                center_scene_pos = self._field_to_scene(x, y),
                moved_callback = self._on_pending_reference_handle_moved,
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
        if tool_name != "点" and self._draft_tool_name and self._draft_reference_points:
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
        return self.active_tool in {"点", "线段", "弧", "曲线/折线", "填充四边形", "圆", "多边形"}

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
                prev_points = self.node_points.get(preview_node - 1, [])
                for point in prev_points:
                    self._draw_point_item(point, pre_view=True, draw_label=False)
            current_points = self._points_for_node_render(preview_node)
        else:
            # 拍位位于两节点之间，显示左节点为 pre_view，当前层显示线性插值结果。
            segment = self._segment_for_beat(self.preview_beat)
            if segment is not None:
                # 在拍位位于两节点之间时显示插值预览，且仅显示左节点的点位为 pre_view。
                left, right = segment
                prev_points = self.node_points.get(left, [])
                for point in prev_points:
                    self._draw_point_item(point, pre_view=True, draw_label=False)
                current_points = self._interpolate_points_at_beat(left, right, self.preview_beat)
            else:
                if self.active_node > 0:
                    prev_points = self.node_points.get(self.active_node - 1, [])
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


    def delete_selected_points(self):
        """删除当前选中的点位：在所有节点中移除对应点位 ID，重排剩余点位 ID 并同步 group_to_point 与 _next_point_id。"""
        to_delete = set(int(i) for i in getattr(self, "_selected_point_ids", set()))
        if not to_delete:
            return

        # 收集所有剩余点位 ID（跨所有节点），按旧 ID 升序排序以确定新 ID 分配顺序
        remaining_ids = sorted({int(p["id"]) for pts in self.node_points.values() for p in pts if int(p["id"]) not in to_delete})

        # 生成 old->new 映射
        id_map = {old: new for new, old in enumerate(remaining_ids, start=1)}

        # 重新构建每个节点的点位列表，移除被删点并重写 ID
        for node_idx in list(self.node_points.keys()):
            new_points = []
            for p in self.node_points.get(node_idx, []):
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
            old_list = [int(pid) for pid in group.get("point_ids", [])]
            new_list = [id_map[pid] for pid in old_list if pid not in to_delete and pid in id_map]
            group["point_ids"] = new_list

        # 更新自增计数器
        max_id = max(id_map.values()) if id_map else 0
        self._next_point_id = max_id + 1

        # 清除当前选中集合并刷新显示与后续自动计算
        self._selected_point_ids = set()
        self._mark_node_manual(self.active_node)
        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
        self._render_points_for_active_node()
        self.dataChanged.emit()

    def restore_selected_points_to_prev(self):
        """将当前选中的点位恢复到前一节点对应点位的位置。

        - 仅在 active_node > 0 时可用。
        - 对每个被选中的点，如果前一节点存在相同 id 的点位，则将 x,y 恢复到前一节点的值。
        - 如果实际发生了任何变更，则标记当前节点为手动编辑并触发后续自动计算；
          否则将 node_manual_edited[current_node] 置为 False。
        """
        if not getattr(self, "_selected_point_ids", None):
            return
        if int(getattr(self, "active_node", 0)) <= 0:
            return

        prev_points = {int(p.get("id", -1)): (float(p.get("x", 0.0)), float(p.get("y", 0.0)))
                       for p in self.node_points.get(self.active_node - 1, [])}
        if not prev_points:
            return

        current_points = self.node_points.get(self.active_node, [])
        changed = False
        for p in current_points:
            pid = int(p.get("id", -1))
            if pid in self._selected_point_ids and pid in prev_points:
                px, py = prev_points[pid]
                if abs(float(p.get("x", 0.0)) - px) > 1e-9 or abs(float(p.get("y", 0.0)) - py) > 1e-9:
                    p["x"] = px
                    p["y"] = py
                    changed = True

        if changed:
            self._mark_node_manual(self.active_node)
            self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
            self.dataChanged.emit()
        else:
            # 若没有实际变更，则认为当前节点未被手动编辑过
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
            # item.setPen(QPen(self.pre_point_color, 1))
            item.setBrush(QBrush(self.pre_point_color))
            # item.setPen(QPen(QColor(60, 60, 60, 110), 1))
            # item.setBrush(QBrush(QColor(80, 80, 80, 70)))
            self._previous_items.append(item)
        else:
            # 绘制当前图的点位
            item = PerformerPointItem(
                point_id=point["id"],
                center_scene_pos=pos,
                moved_callback=self._on_performer_point_moved,
                released_callback=self._on_performer_point_released,
                can_drag_callback=self._can_drag_performer_point,
                selected=point["id"] in self._selected_point_ids,
                # size=self.dot_radius * 2,
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
                helper.setZValue(230)
                helper.setData(0, "drawing_rematch_helper")
                helper.setData(1, point_id)
                self.addItem(helper)
                self._rematch_helper_items.append(helper)
        self.addItem(item)

        if draw_label:
            # 绘制标签，使用场景参数控制字体大小、偏移与角度
            label = QGraphicsSimpleTextItem(str(point["id"]))
            # 字体大小
            font = QFont()
            font.setPointSize(int(self.label_size))
            label.setFont(font)
            label.setBrush(QBrush(self.label_color))
            # 计算相对于点位的偏移（角度以 15° 为单位）并使标签中心位于该偏移点
            angle_deg = (int(self.label_pos) % 24) * 15
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
        for point in self.node_points.get(self.active_node, []):
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

            if self.active_tool == "调整":
                if isinstance(item, (ReferenceHandleItem, MovementControlHandleItem)):
                    super().mousePressEvent(event)
                else:
                    event.accept()
                return

            if isinstance(item, (ReferenceHandleItem, MovementControlHandleItem)):
                super().mousePressEvent(event)
                return

            rematch_snapshot = self._drawing_rematch_snapshot()
            clicked_point_id = None
            if isinstance(item, PerformerPointItem):
                clicked_point_id = int(item.point_id)
            elif item is not None and item.data(0) == "drawing_rematch_helper":
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

            # 非单点草稿态：禁止新增参考点点击，仅保留手柄拖拽。
            if self._is_drawing_tool() and self._draft_tool_name and self._draft_tool_name != "点":
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
        # 旧版尝试直接在 scene.mouseMoveEvent 中刷新文本框预览；
        # 当视图未开启 mouse tracking 时，无按键移动不会稳定触发这里。
        # if self.active_tool == "文本" and len(self._textbox_pending_points) == 1:
        #     x, y = self._scene_to_field(event.scenePos())
        #     x, y = self._snap_field_point(x, y)
        #     self._textbox_hover_scene_pos = self._field_to_scene(x, y)
        #     self._refresh_reference_overlay_for_active_tool()

        if event.buttons() & Qt.MouseButton.LeftButton and self._selection_start_position is not None:
            if self.active_tool in {"框选", "选择"}:
                self._selection_current_position = QPointF(event.scenePos())
                self._update_selection_rect_item()
                # 实时更新被框选的点并刷新视觉反馈
                scene_rect = QRectF(self._selection_start_position, self._selection_current_position).normalized()
                self._select_points_in_scene_rect(scene_rect, self.active_tool, event)
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

        super().mouseReleaseEvent(event)

    def keyPressEvent(self, event):
        super().keyPressEvent(event)

