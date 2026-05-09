"""
绘制方案图
"""
import math

from PyQt6.QtWidgets import (
    QGraphicsEllipseItem,
    QGraphicsLineItem,
    QGraphicsPathItem,
    QGraphicsPolygonItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
)
from PyQt6.QtCore import QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF, QFont
from field_info import FieldInfo
from field_renderer import GridRenderer
from scene_items import PerformerPointItem, ReferenceHandleItem
from scheme_scene_data import SchemeSceneData

def _distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    """计算两点之间的欧几里得距离。"""
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

class SchemeScene(SchemeSceneData, QGraphicsScene):
    """主绘图场景：管理节点点位、图形草稿与渲染。"""
    # 通知主窗口更新“绘制控制台”状态，替代阻塞式弹窗。
    draftStarted = pyqtSignal(str)  # 工具名称
    draftFinished = pyqtSignal()    # 无参数，表示草稿结束（确认或取消）
    selectedPointsChanged = pyqtSignal(int) # 当前选中点位数量
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
        self.setup_scene_data()     # 初始化场景数据结构
        self._draft_tool_name = None    # 当前正在使用的绘图工具名称，None表示无草稿状态；非None表示草稿状态，值为对应工具名称。
        self._draft_reference_points = []   # 当前绘图草稿的参考点坐标列表
        self._draft_preview_items = []      # 当前绘图草稿的预览图元列表
        self._pending_preview_items = []    # 当前未确认阶段的参考线预览图元列表（如曲线/折线工具在输入至少2个点位后的实时预览）
        self._draft_handle_items = []       # 当前绘图草稿的可拖动参考点图元列表（如曲线/折线工具在输入至少2个点位后的可调整参考点）
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
        self._point_items_by_id = {}    # 当前显示的点位图元字典，key为点位ID，value为对应的 PerformerPointItem 图元；用于快速定位与更新特定点位的图元。
        self._label_items_by_id = {}    # 当前显示的标签图元字典，key为点位ID，value为对应的 QGraphicsSimpleTextItem 图元；用于快速定位与更新特定点位的标签图元。

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

    def _on_field_settings_changed(self):
        """场地配置变化后刷新场景绘制。"""
        self._render_points_for_active_node()
        self.update()

    def drawBackground(self, painter, rect):
        """场景背景绘制入口。"""
        self.grid_renderer.draw_background_grid(painter, rect)
        self.grid_renderer.draw_field_lines(painter)
        self.grid_renderer.draw_field_labels(painter)

    def _clear_overlay_items(self):
        """清除当前所有点位与标签图元，准备重建。"""
        for item in self._current_items + self._previous_items + self._label_items + self._selection_link_items:
            self.removeItem(item)
        self._current_items = []
        self._previous_items = []
        self._label_items = []
        self._selection_link_items = []
        self._point_items_by_id = {}
        self._label_items_by_id = {}

    def set_active_tool(self, tool_name: str):
        """切换当前工具并清空临时草稿。"""
        self.active_tool = tool_name
        self._pending_points = []   # 清空草稿点位
        self._selected_point_ids.clear()    # 清空选中点位
        self._clear_selection_rect()    # 清除框选工具的选区矩形和相关状态
        self._clear_draft()             # 清除绘图工具的草稿图形
        self._render_points_for_active_node()   # 切换工具后刷新显示，确保界面状态与工具一致

    def set_active_node(self, node_index: int):
        """切换当前时间轴节点并刷新显示。"""
        self.active_node = max(0, int(node_index))  # 确保节点索引非负
        self.ensure_node_exists(self.active_node)   # 确保目标节点存在，若不存在则初始化
        self._pending_points = []   # 清空草稿点位
        self._selected_point_ids.clear()
        self._clear_selection_rect()
        self._clear_draft()
        self._render_points_for_active_node()

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

    def _select_points_in_scene_rect(self, scene_rect: QRectF, tool_name: str):
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

        self._selected_point_ids = selected_ids
        self._refresh_point_selection_visuals()

    def _refresh_point_selection_visuals(self):
        """刷新当前点位图元的选中状态视觉效果，并发出选中点位数量变化信号。"""
        for point_id, item in self._point_items_by_id.items():
            item.set_selected_visual(point_id in self._selected_point_ids)
        self._refresh_selected_group_links()
        self.selectedPointsChanged.emit(len(self._selected_point_ids))

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

        # 连接同一组内被选中的点位，使用不透明绿色线条。
        pen = QPen(QColor("#f39c12"), 3, Qt.PenStyle.SolidLine)
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
                    line_item.setZValue(180)
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

        return self._field_to_scene(x, y)

    def _on_performer_point_released(self, point_id: int | None = None):
        """预览拍位下禁止写回真实数据，直接返回；当前节点拍位上则标记节点为手动编辑过并触发后续自动调整。"""
        if not self._is_current_beat_editable():
            return
        self._mark_node_manual(self.active_node)
        self._recalculate_following_auto_nodes(self.active_node)

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

        # 未确认阶段同样显示按默认“两步间隔”采样的表演者预览点位。
        if self.active_tool == "曲线/折线" and len(self._pending_points) >= 2:
            preview_points = self._generate_performer_points("曲线/折线", self._pending_points)
            for x, y in preview_points:
                pos = self._field_to_scene(x, y)
                dot = QGraphicsEllipseItem(pos.x() - 3.5, pos.y() - 3.5, 7.0, 7.0)
                dot.setPen(QPen(QColor("#d35400"), 1))
                dot.setBrush(QBrush(QColor(243, 156, 18, 90)))
                dot.setZValue(900)
                self.addItem(dot)
                self._pending_preview_items.append(dot)

    def _dedupe_points(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """根据坐标值去重，避免重复点位导致的图元重叠与性能问题。"""
        unique = []
        seen = set()
        for x, y in points:
            key = (round(x, 6), round(y, 6))
            if key in seen:
                continue
            seen.add(key)
            unique.append((x, y))
        return unique

    def _sample_line_points_with_count(self, p1: tuple[float, float], p2: tuple[float, float], spacing: float, point_count: int) -> list[tuple[float, float]]:
        """在线段上以固定间距和点位数量采样点位，包含起点但不包含终点；当点位数量过少时优先保证间距。"""
        count = max(1, int(point_count))
        dist = _distance(p1, p2)
        if dist <= 1e-9:
            return [p1]
        ux = (p2[0] - p1[0]) / dist
        uy = (p2[1] - p1[1]) / dist
        return [(
            p1[0] + ux * spacing * index,
            p1[1] + uy * spacing * index,
        ) for index in range(count)]

    def _sample_polyline_points(self, points: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
        """在线段上以固定间距采样点位，包含起点但不包含终点。"""
        if len(points) < 2:
            return points[:]
        sampled = [points[0]]
        next_target = spacing
        traveled = 0.0
        for idx in range(len(points) - 1):
            start = points[idx]
            end = points[idx + 1]
            segment_length = _distance(start, end)
            if segment_length <= 1e-9:
                continue
            while next_target <= traveled + segment_length + 1e-9:
                distance_on_segment = next_target - traveled
                t = distance_on_segment / segment_length
                sampled.append((
                    start[0] + (end[0] - start[0]) * t,
                    start[1] + (end[1] - start[1]) * t,
                ))
                next_target += spacing
            traveled += segment_length
        return sampled

    def _sample_polyline_points_with_count(self, points: list[tuple[float, float]], point_count: int) -> list[tuple[float, float]]:
        """在线段上以固定间距和点位数量采样点位，包含起点但不包含终点；当点位数量过少时优先保证间距。"""
        if len(points) < 2:
            return points[:]
        count = max(1, int(point_count))
        if count == 1:
            return [points[0]]

        segment_lengths = []
        total_length = 0.0
        for idx in range(len(points) - 1):
            seg_len = _distance(points[idx], points[idx + 1])
            segment_lengths.append(seg_len)
            total_length += seg_len
        if total_length <= 1e-9:
            return [points[0]]

        step = total_length / (count - 1)
        sampled = [points[0]]
        next_target = step
        traveled = 0.0
        for idx, seg_len in enumerate(segment_lengths):
            start = points[idx]
            end = points[idx + 1]
            if seg_len <= 1e-9:
                traveled += seg_len
                continue
            while next_target <= traveled + seg_len + 1e-9 and len(sampled) < count - 1:
                distance_on_segment = next_target - traveled
                t = distance_on_segment / seg_len
                sampled.append((
                    start[0] + (end[0] - start[0]) * t,
                    start[1] + (end[1] - start[1]) * t,
                ))
                next_target += step
            traveled += seg_len

        if len(sampled) < count:
            sampled.append(points[-1])
        return sampled[:count]

    def _sample_polyline_points_with_count_and_spacing(self, points: list[tuple[float, float]], point_count: int, spacing: float) -> list[tuple[float, float]]:
        """在线段上以固定间距和点位数量采样点位，包含起点但不包含终点；当点位数量过少时优先保证间距；当点位数量过多时优先保证数量。"""
        if len(points) < 2:
            return points[:]

        count = max(1, int(point_count))
        if count == 1:
            return [points[0]]

        segment_lengths = []
        total_length = 0.0
        for idx in range(len(points) - 1):
            seg_len = _distance(points[idx], points[idx + 1])
            segment_lengths.append(seg_len)
            total_length += seg_len

        if total_length <= 1e-9:
            return [points[0]]

        last_dx = points[-1][0] - points[-2][0]
        last_dy = points[-1][1] - points[-2][1]
        last_len = math.hypot(last_dx, last_dy)
        if last_len <= 1e-9:
            last_unit_x = 0.0
            last_unit_y = 0.0
        else:
            last_unit_x = last_dx / last_len
            last_unit_y = last_dy / last_len

        sampled = []
        traveled = 0.0
        segment_index = 0
        for index in range(count):
            target = spacing * index
            while segment_index < len(segment_lengths) and target > traveled + segment_lengths[segment_index] + 1e-9:
                traveled += segment_lengths[segment_index]
                segment_index += 1

            if segment_index >= len(segment_lengths):
                extra = target - total_length
                sampled.append((
                    points[-1][0] + last_unit_x * extra,
                    points[-1][1] + last_unit_y * extra,
                ))
                continue

            seg_len = segment_lengths[segment_index]
            if seg_len <= 1e-9:
                sampled.append(points[segment_index])
                continue

            start = points[segment_index]
            end = points[segment_index + 1]
            distance_on_segment = target - traveled
            t = max(0.0, min(1.0, distance_on_segment / seg_len))
            sampled.append((
                start[0] + (end[0] - start[0]) * t,
                start[1] + (end[1] - start[1]) * t,
            ))

        return sampled

    def _sample_curve_points(self, points: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
        """基于 Catmull-Rom 样条生成平滑曲线并按 spacing 重新等距采样（返回 field 坐标点）。"""
        dense = self._build_dense_curve_points(points, spacing)
        if len(dense) < 2:
            return dense[:]

        # 将密集曲线点按 spacing 等距重采样（复用折线采样实现）
        return self._sample_polyline_points(dense, spacing)

    def _build_dense_curve_points(self, points: list[tuple[float, float]], spacing_hint: float) -> list[tuple[float, float]]:
        """生成 Catmull-Rom 曲线的密集折线点，为不同采样策略提供统一输入。"""
        if len(points) < 2:
            return points[:]

        dense = []
        n = len(points)
        for i in range(n - 1):
            p0 = points[i - 1] if i - 1 >= 0 else points[i]
            p1 = points[i]
            p2 = points[i + 1]
            p3 = points[i + 2] if i + 2 < n else points[i + 1]

            seg_len = max(1e-9, _distance(p1, p2))
            # 根据段长度和采样间隔决定密集采样步数
            steps = max(6, int(seg_len / max(1e-9, spacing_hint * 0.25)))
            for s in range(steps):
                t = s / steps
                t2 = t * t
                t3 = t2 * t
                x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
                y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
                dense.append((x, y))
        dense.append(points[-1])
        return dense

    def _sample_curve_points_with_count(self, points: list[tuple[float, float]], point_count: int) -> list[tuple[float, float]]:
        """基于 Catmull-Rom 样条生成平滑曲线，并按目标点数重新采样。"""
        dense = self._build_dense_curve_points(points, float(self.field_info.grid_step))
        if len(dense) < 2:
            return dense[:]

        return self._sample_polyline_points_with_count(dense, point_count)

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

    def _sample_circle_points(self, center: tuple[float, float], radius_point: tuple[float, float], spacing: float) -> list[tuple[float, float]]:
        """圆绘制点位预览"""
        cx, cy, radius = self._circle_from_two_points(center, radius_point)
        if radius <= 1e-9:
            return [center]
        circumference = 2.0 * math.pi * radius
        # 从第二个参考点开始，沿逆时针方向按固定弧长步进生成点位。
        # 若末尾剩余弧长不足 spacing，则不生成接近起点的最后一个点，避免尾段过短。
        # 原实现（向下取整）：
        # point_count = int(circumference // max(1e-9, spacing))
        # 改为四舍五入以与按点数采样的生成规则保持一致性
        point_count = max(1, int(round(circumference / max(1e-9, spacing))))
        if point_count <= 0:
            return [radius_point]

        start_angle = math.atan2(radius_point[1] - cy, radius_point[0] - cx)
        points = []
        for index in range(point_count):
            arc_length = spacing * index
            angle = start_angle - arc_length / radius
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        return points

    def _sample_circle_points_with_count(self, center: tuple[float, float], radius_point: tuple[float, float], point_count: int) -> list[tuple[float, float]]:
        """圆绘制点位预览（按点位数量采样）"""
        cx, cy, radius = self._circle_from_two_points(center, radius_point)
        if radius <= 1e-9:
            return [center]
        count = max(1, int(point_count))
        if count == 1:
            return [radius_point]

        start_angle = math.atan2(radius_point[1] - cy, radius_point[0] - cx)
        points = []
        for index in range(count):
            angle = start_angle - 2.0 * math.pi * index / count
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        return points

    def _sample_arc_points(self, start: tuple[float, float], through: tuple[float, float], end: tuple[float, float], spacing: float) -> list[tuple[float, float]]:
        """弧绘制点位预览，基于三点确定的圆弧生成点位。"""
        center = self._circumcenter(start, through, end)
        if center is None:
            # 退化为折线时，按整段折线连续等距采样（只保证起点落点）。
            return self._sample_polyline_points([start, through, end], spacing)

        cx, cy = center
        radius = math.hypot(start[0] - cx, start[1] - cy)
        if radius <= 1e-9:
            return [start, end]

        start_angle = math.atan2(start[1] - cy, start[0] - cx)
        through_angle = math.atan2(through[1] - cy, through[0] - cx)
        end_angle = math.atan2(end[1] - cy, end[0] - cx)

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

        # 判定第三点属于 start->end 的 CCW 弧，还是 CW 弧。
        ccw_se = (e - s) % tau
        ccw_sm = (m - s) % tau
        use_ccw = ccw_sm <= ccw_se

        # 仅采样包含第三参考点的那段弧，并拆成两段确保必经 through。
        if use_ccw:
            d1 = ccw_sm
            d2 = ccw_se - ccw_sm
        else:
            cw_sm = (s - m) % tau
            cw_se = (s - e) % tau
            d1 = -cw_sm
            d2 = -(cw_se - cw_sm)

        total_delta = d1 + d2
        total_len = abs(total_delta) * radius
        count = int(total_len // spacing)
        points = []
        for i in range(count + 1):
            distance = spacing * i
            angle = s + (distance / radius) * (1.0 if total_delta >= 0 else -1.0)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        return points

    def _sample_arc_points_with_count(self, start: tuple[float, float], through: tuple[float, float], end: tuple[float, float], point_count: int) -> list[tuple[float, float]]:
        """弧绘制点位预览，基于三点确定的圆弧生成点位（按点位数量采样）。"""
        center = self._circumcenter(start, through, end)
        if center is None:
            count = max(1, int(point_count))
            if count == 1:
                return [start]
            total_length = _distance(start, through) + _distance(through, end)
            spacing = max(1e-9, total_length / (count - 1))
            return self._sample_polyline_points([start, through, end], spacing)

        cx, cy = center
        radius = math.hypot(start[0] - cx, start[1] - cy)
        if radius <= 1e-9:
            return [start, end]

        start_angle = math.atan2(start[1] - cy, start[0] - cx)
        through_angle = math.atan2(through[1] - cy, through[0] - cx)
        end_angle = math.atan2(end[1] - cy, end[0] - cx)

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

        count = max(1, int(point_count))
        if count == 1:
            return [start]

        points = []
        for i in range(count):
            distance = abs(total_delta) * radius * i / (count - 1)
            angle = s + (distance / radius) * (1.0 if total_delta >= 0 else -1.0)
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        return points

    def _sample_arc_points_with_count_and_spacing(self, start: tuple[float, float], through: tuple[float, float], end: tuple[float, float], point_count: int, spacing: float) -> list[tuple[float, float]]:
        """按起点开始、固定间隔和固定个数采样弧：
        - 从 start 出发，每隔 spacing 放一个点，直到达到 point_count。
        - 若弧长不足以放下所有点，超出部分沿终点处切线方向延申。
        返回 field 单位坐标点列表。
        """
        count = max(1, int(point_count))
        spacing = max(1e-9, float(spacing))

        center = self._circumcenter(start, through, end)
        if center is None:
            # 退化为折线：重用折线按个数与间隔采样的实现
            return self._sample_polyline_points_with_count_and_spacing([start, through, end], count, spacing)

        cx, cy = center
        radius = math.hypot(start[0] - cx, start[1] - cy)
        if radius <= 1e-9:
            return [start]

        start_angle = math.atan2(start[1] - cy, start[0] - cx)
        through_angle = math.atan2(through[1] - cy, through[0] - cx)
        end_angle = math.atan2(end[1] - cy, end[0] - cx)

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
            if ccw_se >= 0:
                total_delta = ccw_se
            else:
                total_delta = -( (s - e) % tau )
        else:
            # clockwise negative delta
            total_delta = -((s - e) % tau)

        total_len = abs(total_delta) * radius

        points: list[tuple[float, float]] = []
        # 方向标记：角度增大为正
        sign = 1.0 if total_delta >= 0 else -1.0

        # 计算单位切向量（沿着角度变化的方向）在终点处，用于延申
        ux_t = -math.sin(end_angle)
        uy_t = math.cos(end_angle)
        unit_tangent_x = sign * ux_t
        unit_tangent_y = sign * uy_t

        for i in range(count):
            target_dist = spacing * i
            if target_dist <= total_len + 1e-9:
                angle = s + (target_dist / radius) * sign
                points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
            else:
                extra = target_dist - total_len
                # 起点为弧终点位置
                arc_end_x = cx + radius * math.cos(e)
                arc_end_y = cy + radius * math.sin(e)
                points.append((arc_end_x + unit_tangent_x * extra, arc_end_y + unit_tangent_y * extra))

        return points

    def _sample_rectangle_fill_points_with_counts(self, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], spacing_base: float, spacing_shift: float, base_point_count: int, shift_point_count: int) -> list[tuple[float, float]]:
        """按两个方向的点位个数与间隔采样填充四边形点位。"""
        ax, ay = a
        bx, by = b
        cx, cy = c
        base_dx, base_dy = bx - ax, by - ay
        shift_dx, shift_dy = cx - ax, cy - ay
        base_len = math.hypot(base_dx, base_dy)
        shift_len = math.hypot(shift_dx, shift_dy)
        if base_len <= 1e-9 or shift_len <= 1e-9:
            return [a, b, c]

        base_unit_x = base_dx / base_len
        base_unit_y = base_dy / base_len
        shift_unit_x = shift_dx / shift_len
        shift_unit_y = shift_dy / shift_len

        base_point_count = max(1, int(base_point_count))
        shift_point_count = max(1, int(shift_point_count))

        base_line = self._sample_line_points_with_count(a, b, spacing_base, base_point_count)
        if not base_line:
            base_line = [a]

        points = []
        for shift_index in range(shift_point_count):
            shift_distance = spacing_shift * shift_index
            row = [(
                px + shift_unit_x * shift_distance,
                py + shift_unit_y * shift_distance,
            ) for px, py in base_line]
            points.extend(row)

        return points or [a, b, c]

    def _sample_polygon_perimeter_points(self, center: tuple[float, float], radius_point: tuple[float, float], spacing: float) -> list[tuple[float, float]]:
        """多边形绘制点位预览"""
        vertices = self._make_polygon_points(center, radius_point, self._polygon_side_count("多边形"))
        if not vertices:
            return []
        points = self._sample_closed_polyline_points_with_spacing(vertices, spacing)
        return points

    def _sample_closed_polyline_points_with_spacing(self, points: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
        """按固定间距采样闭合折线：包含起点，不包含回到起点的闭合末点。"""
        if len(points) < 2:
            return points[:]

        spacing = max(1e-9, float(spacing))
        loop = points + [points[0]]
        segment_lengths = []
        total_length = 0.0
        for idx in range(len(loop) - 1):
            seg_len = _distance(loop[idx], loop[idx + 1])
            segment_lengths.append(seg_len)
            total_length += seg_len

        if total_length <= 1e-9:
            return [points[0]]

        # 原实现（向下取整）会在间距换算成点数时产生末尾差异：
        # count = int(total_length // spacing)
        # 改为四舍五入以与按点数采样保持一致
        count = max(1, int(round(total_length / spacing)))
        if count <= 0:
            return [points[0]]

        sampled = [loop[0]]
        traveled = 0.0
        segment_index = 0
        for index in range(1, count):
            target = spacing * index
            while segment_index < len(segment_lengths) and target > traveled + segment_lengths[segment_index] + 1e-9:
                traveled += segment_lengths[segment_index]
                segment_index += 1

            if segment_index >= len(segment_lengths):
                break

            seg_len = segment_lengths[segment_index]
            if seg_len <= 1e-9:
                continue

            start = loop[segment_index]
            end = loop[segment_index + 1]
            distance_on_segment = target - traveled
            t = max(0.0, min(1.0, distance_on_segment / seg_len))
            sampled.append((
                start[0] + (end[0] - start[0]) * t,
                start[1] + (end[1] - start[1]) * t,
            ))

        return sampled

    def _sample_closed_polyline_points_with_count(self, points: list[tuple[float, float]], point_count: int) -> list[tuple[float, float]]:
        """按点位个数采样闭合折线点位"""
        if len(points) < 2:
            return points[:]
        count = max(1, int(point_count))
        if count == 1:
            return [points[0]]

        loop = points + [points[0]]
        total_length = 0.0
        segment_lengths = []
        for idx in range(len(loop) - 1):
            seg_len = _distance(loop[idx], loop[idx + 1])
            segment_lengths.append(seg_len)
            total_length += seg_len
        if total_length <= 1e-9:
            return [points[0]]

        step = total_length / count
        sampled = [loop[0]]
        next_target = step
        traveled = 0.0
        for idx, seg_len in enumerate(segment_lengths):
            start = loop[idx]
            end = loop[idx + 1]
            if seg_len <= 1e-9:
                traveled += seg_len
                continue
            while next_target <= traveled + seg_len + 1e-9 and len(sampled) < count:
                distance_on_segment = next_target - traveled
                t = distance_on_segment / seg_len
                sampled.append((
                    start[0] + (end[0] - start[0]) * t,
                    start[1] + (end[1] - start[1]) * t,
                ))
                next_target += step
            traveled += seg_len
        return sampled[:count]

    def _sample_polygon_perimeter_points_with_count(self, center: tuple[float, float], radius_point: tuple[float, float], point_count: int) -> list[tuple[float, float]]:
        """按点位个数采样多边形周长点位"""
        vertices = self._make_polygon_points(center, radius_point, self._polygon_side_count("多边形"))
        if not vertices:
            return []
        return self._sample_closed_polyline_points_with_count(vertices, point_count)

    def _generate_performer_points(self, tool_name: str, refs: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """根据当前草稿工具和参考点生成最终的执行点位列表（field 坐标）。"""
        spacing = max(1e-9, float(self.field_info.grid_step) * 2.0)
        if tool_name == "点" and refs:
            return self._dedupe_points(refs)
        if tool_name in self._sampling_tools and len(refs) >= 2:
            state = self._sampling_state(tool_name)
            line_spacing = max(1e-9, float(self.field_info.grid_step) * float(state["spacing_steps"]))
            point_count = max(1, int(state["point_count"]))

            if tool_name == "线段":
                # 统一线段为折线/多段线的采样逻辑：将两点视为一段折线，复用折线/曲线采样函数
                is_curve = False
                # 与曲线/折线分支保持一致的优先级：手动间距+手动点数 -> 手动点数 -> 手动间距 -> 自动间距
                if state.get("spacing_manual", False) and state.get("point_count_manual", False):
                    return self._dedupe_points(self._sample_polyline_points_with_count_and_spacing(refs, point_count, line_spacing))
                if state.get("spacing_manual", False):
                    return self._dedupe_points(self._sample_polyline_points(refs, line_spacing))
                if state.get("point_count_manual", False):
                    return self._dedupe_points(self._sample_polyline_points_with_count(refs, point_count))
                return self._dedupe_points(self._sample_polyline_points(refs, line_spacing))
            elif tool_name == "弧":
                if state.get("point_count_manual", False) and state.get("spacing_manual", False):
                    return self._dedupe_points(self._sample_arc_points_with_count_and_spacing(refs[0], refs[2], refs[1], point_count, line_spacing))
                if state.get("point_count_manual", False):
                    return self._dedupe_points(self._sample_arc_points_with_count(refs[0], refs[2], refs[1], point_count))
                # return self._dedupe_points(self._sample_arc_points(refs[0], refs[2], refs[1], spacing))
                return self._dedupe_points(self._sample_arc_points(refs[0], refs[2], refs[1], line_spacing))
            elif tool_name == "圆":
                if state["point_count_manual"]:
                    return self._dedupe_points(self._sample_circle_points_with_count(refs[0], refs[1], point_count))
                return self._dedupe_points(self._sample_circle_points(refs[0], refs[1], line_spacing))
            elif tool_name == "多边形":
                if state["point_count_manual"]:
                    return self._dedupe_points(self._sample_polygon_perimeter_points_with_count(refs[0], refs[1], point_count))
                return self._dedupe_points(self._sample_polygon_perimeter_points(refs[0], refs[1], line_spacing))
        # if tool_name == "弧" and len(refs) >= 3:
        #     # 弧工具参考点语义：端点1、端点2、弧上一点。
        #     return self._dedupe_points(self._sample_arc_points(refs[0], refs[2], refs[1], spacing))
            elif tool_name == "曲线/折线" and len(refs) >= 2:
                is_curve = getattr(self, '_curve_mode', 'polyline') == 'curve'
                if state["spacing_manual"] and state["point_count_manual"]:
                    if is_curve:
                        # dense_curve = self._sample_curve_points(refs, line_spacing)
                        dense_curve = self._build_dense_curve_points(refs, line_spacing)
                        return self._dedupe_points(self._sample_polyline_points_with_count_and_spacing(dense_curve, point_count, line_spacing))
                    return self._dedupe_points(self._sample_polyline_points_with_count_and_spacing(refs, point_count, line_spacing))
                if state["spacing_manual"]:
                    if is_curve:
                        return self._dedupe_points(self._sample_curve_points(refs, line_spacing))
                    return self._dedupe_points(self._sample_polyline_points(refs, line_spacing))
                if state["point_count_manual"]:
                    if is_curve:
                        return self._dedupe_points(self._sample_curve_points_with_count(refs, point_count))
                    return self._dedupe_points(self._sample_polyline_points_with_count(refs, point_count))
                if is_curve:
                    return self._dedupe_points(self._sample_curve_points(refs, line_spacing))
                return self._dedupe_points(self._sample_polyline_points(refs, line_spacing))
            elif tool_name == "填充四边形" and len(refs) >= 3:
                state = self._sampling_state(tool_name)
                base_spacing = max(1e-9, float(self.field_info.grid_step) * float(state.get("spacing_steps", 2.0)))
                shift_spacing = max(1e-9, float(self.field_info.grid_step) * float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0))))
                base_point_count = int(state.get("point_count", 1))
                shift_point_count = int(state.get("point_count_shift", 1))
                return self._dedupe_points(
                    self._sample_rectangle_fill_points_with_counts(
                        refs[0],
                        refs[1],
                        refs[2],
                        base_spacing,
                        shift_spacing,
                        base_point_count,
                        shift_point_count,
                    )
                )
        return []

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

            path = self._arc_path_from_three_points(
                (start_scene.x(), start_scene.y()),
                (through_scene.x(), through_scene.y()),
                (end_scene.x(), end_scene.y()),
            )

            center = self._circumcenter(
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
        self._clear_pending_preview_items()
        if tool_name in self._sampling_tools:
            self._sync_sampling_auto_values_from_draft(tool_name)
        # if tool_name == "线段":
        #     self._sync_line_segment_auto_values_from_draft()
        self._render_points_for_active_node()
        self.draftStarted.emit(tool_name)

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
            return
        
        generated = self._generate_performer_points(tool_name, refs)    # 生成最终点位列表（field 坐标）
        current_points = self.node_points.setdefault(self.active_node, [])  # 当前节点的点位列表
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

        # 确认后丢弃参考点缓存，下一次绘制重新输入。
        self.reset_sampling_defaults(tool_name)
        self._pending_points = []
        self._draft_reference_points = []
        self._mark_node_manual(self.active_node)
        self._recalculate_following_auto_nodes(self.active_node, include_manual_nodes=True)
        self._clear_draft()
        if not had_draft:
            self.draftFinished.emit()
        self._render_points_for_active_node()

    def cancel_current_drawing(self):
        """取消当前草稿，不写入点位。"""
        # 取消绘制时：对所有采样工具恢复默认参数
        tools_to_reset = set()
        if self._draft_tool_name in self._sampling_tools:
            tools_to_reset.add(self._draft_tool_name)
        if self.active_tool in self._sampling_tools:
            tools_to_reset.add(self.active_tool)
        for t in tools_to_reset:
            self.reset_sampling_defaults(t)
        self._pending_points = []
        self._clear_draft()
        self.draftFinished.emit()
        self._render_points_for_active_node()

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
        self._enforce_sampling_auto_rule(tool_name, state)
        return state

    def _enforce_sampling_auto_rule(self, tool_name: str | None, state: dict, changed: str | None = None):
        """个数与间隔不允许同时为自动：只允许都手动或仅一项自动。
        同时保证至少有一项为自动（即不可全部手动）：当两项都为手动时，默认开启点数自动。
        """
        point_auto = not bool(state.get("point_count_manual", False))
        spacing_auto = not bool(state.get("spacing_manual", False))
        # 若两项同时为自动，则根据最近变更优先保留被手动的那一项
        if point_auto and spacing_auto:
            if changed == "point_count_auto":
                state["spacing_manual"] = True
                return
            if changed == "spacing_auto":
                state["point_count_manual"] = True
                return
            # 兜底：保留点数自动，间距手动
            state["spacing_manual"] = True
            return

        # 仅对圆与多边形,若两项同时为手动（即都不是自动），默认启用点数自动以保证至少有一项自动适配；
        # 对其他图形保持用户手动设置不变，避免影响现有行为。
        if not point_auto and not spacing_auto:
            tname = tool_name or ""
            if tname in ("圆", "多边形"):
                # 圆/多边形回退策略：当用户把其中一项切到“手动”导致两项都手动时，交换另一项为自动。
                if changed == "point_count_manual":
                    state["spacing_manual"] = False
                    return
                if changed == "spacing_manual":
                    state["point_count_manual"] = False
                    return
                # 兜底：来源未知时默认保留“点数自动”。
                state["point_count_manual"] = False
            return

    def _enforce_sampling_shift_auto_rule(self, state: dict, changed: str | None = None):
        """填充四边形第二方向（P0-P2）也不允许“点数自动+间隔自动”同时开启。"""
        point_auto = not bool(state.get("point_count_shift_manual", False))
        spacing_auto = not bool(state.get("spacing_shift_manual", False))
        if not (point_auto and spacing_auto):
            # 两项不同时为自动，无需调整
            return

        if changed == "point_count_shift_auto":
            state["spacing_shift_manual"] = True
            return
        if changed == "spacing_shift_auto":
            state["point_count_shift_manual"] = True
            return
        # 兜底：保留“点数自动”，把“间隔”落为手动。
        state["spacing_shift_manual"] = True

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

    def _polygon_side_count(self, tool_name: str) -> int:
        """获取多边形工具的边数设置的内部方法，保证返回值至少为 2。"""
        return self.polygon_side_count(tool_name)

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
        # if tool_name == "线段":
        #     self.lineSegmentPointCountChanged.emit(point_count)

    def _emit_sampling_shift_point_count_changed(self, tool_name: str, point_count: int):
        """发出填充四边形第二方向（P0-P2）采样点位个数改变的信号。"""
        point_count = max(1, int(point_count))
        self.samplingShiftPointCountChanged.emit(tool_name, point_count)
        # no special-case for line segments

    def _emit_sampling_spacing_changed(self, tool_name: str, spacing_steps: float):
        """发出采样间距改变的信号。spacing_steps 是 field 网格单位的倍数。"""
        spacing_steps = max(0.001, float(spacing_steps))
        self.samplingSpacingChanged.emit(tool_name, spacing_steps)
        # if tool_name == "线段":
        #     self.lineSegmentSpacingChanged.emit(spacing_steps)

    def _sampling_length_for_tool(self, tool_name: str, refs: list[tuple[float, float]]) -> float:
        if tool_name == "线段" and len(refs) >= 2:
            return _distance(refs[0], refs[1])
        if tool_name == "曲线/折线" and len(refs) >= 2:
            total = 0.0
            for idx in range(len(refs) - 1):
                total += _distance(refs[idx], refs[idx + 1])
            return total
        if tool_name == "弧" and len(refs) >= 3:
            center = self._circumcenter(refs[0], refs[2], refs[1])
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
            vertices = self._make_polygon_points(refs[0], refs[1], self._polygon_side_count(tool_name))
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

    def _sampling_shift_length_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> float:
        """计算填充四边形第二方向（P0-P2）的长度。"""
        if tool_name != "填充四边形" or len(refs) < 3:
            return 0.0
        ax, ay = refs[0]
        cx, cy = refs[2]
        return math.hypot(cx - ax, cy - ay)

    def _sampling_auto_spacing_steps_shift_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> float:
        """计算填充四边形第二方向（P0-P2）的自动间隔步数。"""
        state = self._sampling_state(tool_name)
        length = self._sampling_shift_length_for_refs(tool_name, refs)
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
        self._enforce_sampling_auto_rule(
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
            self._enforce_sampling_shift_auto_rule(state, changed="point_count_shift_auto") # 设置第二方向
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
        self._enforce_sampling_auto_rule(
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
            self._enforce_sampling_shift_auto_rule(state, changed="spacing_shift_auto") # 设置第二方向
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

    def _make_polygon_points(self, center: tuple[float, float], radius_point: tuple[float, float], sides: int) -> list[tuple[float, float]]:
        """根据中心点、半径点和边数，计算正多边形的顶点坐标。中心点和半径点定义了多边形的大小和初始方向，边数决定了多边形的形状。返回一个包含所有顶点坐标的列表。如果半径过小（小于等于 1e-9），则返回一个空列表；如果边数不足 2，则自动修正为至少 2。"""
        cx, cy = center
        rx, ry = radius_point
        radius = math.hypot(rx - cx, ry - cy)
        if radius <= 1e-9:
            return []
        count = max(2, int(sides))
        start_angle = math.atan2(ry - cy, rx - cx)
        points = []
        for index in range(count):
            angle = start_angle + 2 * math.pi * index / count
            points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
        return points

    def _circle_from_two_points(self, center: tuple[float, float], radius_point: tuple[float, float]) -> tuple[float, float, float]:
        """根据中心点和半径点，计算圆的参数（中心坐标和半径）。中心点定义了圆心的位置，半径点定义了圆的大小。返回一个包含圆心坐标和半径的元组。如果半径过小（小于等于 1e-9），则半径会被修正为 0。"""
        cx, cy = center
        rx, ry = radius_point
        radius = math.hypot(rx - cx, ry - cy)
        return cx, cy, radius

    def _rectangle_from_three_points(self, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> list[tuple[float, float]]:
        """根据三个点计算矩形的顶点坐标。返回一个包含所有顶点坐标的列表。"""
        ax, ay = a
        bx, by = b
        cx, cy = c
        dx = bx + (cx - ax)
        dy = by + (cy - ay)
        return [a, b, (dx, dy), c]

    def _circumcenter(self, p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float]) -> tuple[float, float] | None:
        """计算三角形的外心坐标。外心是三角形三个顶点的垂直平分线的交点，也是通过这三个点的圆的圆心。返回一个包含外心坐标的元组，如果三个点共线则返回 None。"""
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        d = 2 * (x1 * (y2 - y3) + x2 * (y3 - y1) + x3 * (y1 - y2))
        if abs(d) < 1e-9:
            return None
        ux = ((x1 * x1 + y1 * y1) * (y2 - y3) + (x2 * x2 + y2 * y2) * (y3 - y1) + (x3 * x3 + y3 * y3) * (y1 - y2)) / d
        uy = ((x1 * x1 + y1 * y1) * (x3 - x2) + (x2 * x2 + y2 * y2) * (x1 - x3) + (x3 * x3 + y3 * y3) * (x2 - x1)) / d
        return ux, uy

    def _arc_path_from_three_points(self, start: tuple[float, float], through: tuple[float, float], end: tuple[float, float]) -> QPainterPath:
        """根据起点、过渡点和终点，计算通过这三个点的圆弧路径。首先计算三点的外心作为圆心，然后根据圆心和起点计算半径，最后根据起点、过渡点和终点计算起始角度、过渡角度和结束角度，并确定弧线的方向（顺时针或逆时针）。返回一个 QPainterPath 对象表示该圆弧路径。如果三点共线，则返回一条连接起点、过渡点和终点的折线路径。"""
        center = self._circumcenter(start, through, end)
        path = QPainterPath()
        path.moveTo(QPointF(*start))
        if center is None:
            path.lineTo(QPointF(*through))
            path.lineTo(QPointF(*end))
            return path

        cx, cy = center
        radius = math.hypot(start[0] - cx, start[1] - cy)
        if radius <= 1e-9:
            path.lineTo(QPointF(*end))
            return path

        start_angle = math.degrees(math.atan2(start[1] - cy, start[0] - cx))
        through_angle = math.degrees(math.atan2(through[1] - cy, through[0] - cx))
        end_angle = math.degrees(math.atan2(end[1] - cy, end[0] - cx))

        def normalize(angle: float) -> float:
            while angle < 0:
                angle += 360
            while angle >= 360:
                angle -= 360
            return angle

        start_angle_n = normalize(start_angle)
        through_angle_n = normalize(through_angle)
        end_angle_n = normalize(end_angle)

        clockwise = False
        if start_angle_n <= end_angle_n:
            clockwise = not (start_angle_n < through_angle_n < end_angle_n)
        else:
            clockwise = start_angle_n < through_angle_n or through_angle_n < end_angle_n

        span = end_angle_n - start_angle_n
        if clockwise and span > 0:
            span -= 360
        if not clockwise and span < 0:
            span += 360

        rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        path.arcMoveTo(rect, start_angle)
        path.arcTo(rect, start_angle, span)
        return path

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

        if self._draft_tool_name != "点":
            preview_points = self._generate_performer_points(self._draft_tool_name, self._draft_reference_points)
            for x, y in preview_points:
                pos = self._field_to_scene(x, y)
                item = QGraphicsEllipseItem(pos.x() - 3.5, pos.y() - 3.5, 7.0, 7.0)
                item.setPen(QPen(QColor("#d35400"), 1))
                item.setBrush(QBrush(QColor(243, 156, 18, 90)))
                item.setZValue(900)
                self.addItem(item)
                self._draft_preview_items.append(item)

    def _draw_draft_handles(self):
        """根据当前草稿参考点，绘制可交互的参考点控制项。每个参考点都会对应一个 ReferenceHandleItem，用户可以通过拖动这些控制项来调整参考点的位置。此方法会先检查当前是否有草稿参考点，如果没有则直接返回。对于每个草稿参考点，会创建一个 ReferenceHandleItem，并将其添加到场景中，同时记录在 _draft_handle_items 列表中，以便后续清除或更新。ReferenceHandleItem 会绑定一个回调函数，当用户拖动控制项时会调用该函数来更新对应的参考点坐标，并根据需要同步相关的自动设置和刷新预览。"""
        if not self._draft_reference_points:
            return

        self._updating_draft_handles = True
        for index, (x, y) in enumerate(self._draft_reference_points):
            handle = ReferenceHandleItem(
                index,
                self._field_to_scene(x, y),
                self._on_reference_handle_moved,
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
                index,
                self._field_to_scene(x, y),
                self._on_pending_reference_handle_moved,
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
        QTimer.singleShot(0, self._refresh_reference_overlay_for_active_tool)
        return self._field_to_scene(x, y)

    @staticmethod
    def _append_unique_reference_point(target: list[tuple[float, float]], field_point: tuple[float, float]) -> bool:
        x, y = field_point
        for px, py in target:
            if abs(px - x) < 1e-9 and abs(py - y) < 1e-9:
                return False
        target.append(field_point)
        return True

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
                self._append_unique_reference_point(self._draft_reference_points, field_point)
            self._draw_draft_overlay()
            return

        self._append_unique_reference_point(self._pending_points, field_point)
        if tool_name == "曲线/折线":
            self._sync_sampling_auto_values_from_draft("曲线/折线")
            # 取消右键确认：参考点>=2 时即可通过绘制控制台确认。
            if len(self._pending_points) >= 2:
                self.draftStarted.emit("曲线/折线")
            else:
                self.draftFinished.emit()
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
            current_points = self.node_points.get(preview_node, [])
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
                current_points = self.node_points.get(self.active_node, [])

        for point in current_points:
            self._draw_point_item(point, pre_view=False, draw_label=True)

        if self._draft_tool_name:
            self._draw_draft_overlay()
        else:
            self._clear_draft_items()
            self._draw_pending_reference_preview()
            self._draw_pending_reference_points()

        self._refresh_selected_group_links()

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
        self.addItem(item)

        if draw_label:
            # 绘制标签，使用场景参数控制字体大小、偏移与角度
            label = QGraphicsSimpleTextItem(str(point["id"]))
            # 字体大小
            font = QFont()
            try:
                font.setPointSize(int(self.label_size))
            except Exception:
                pass
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
            if isinstance(item, ReferenceHandleItem):
                super().mousePressEvent(event)
                return

            # 非单点草稿态：禁止新增参考点点击，仅保留手柄拖拽。
            if self._is_drawing_tool() and self._draft_tool_name and self._draft_tool_name != "点":
                event.accept()
                return

            if self.active_tool in {"框选", "选择"} and isinstance(item, PerformerPointItem):
                # 框选时，对选中的单一点位进行拖拽修改位置。
                selected_ids = set(self._selected_point_ids)
                modifiers = event.modifiers()
                if self.active_tool == "选择":
                    if (modifiers & Qt.KeyboardModifier.ShiftModifier):
                        group_point_ids = self._group_point_ids_for_point_id(item.point_id)
                        for group_point_id in group_point_ids:
                            if group_point_id in selected_ids:
                                selected_ids.discard(group_point_id)
                            else:
                                selected_ids.add(group_point_id)
                    elif (modifiers & Qt.KeyboardModifier.ControlModifier):
                        selected_ids.add(item.point_id)
                    else:
                        selected_ids = set(self._group_point_ids_for_point_id(item.point_id))
                else:
                    # 框选操作
                    selected_ids = {item.point_id}
                self._selected_point_ids = selected_ids
                self._refresh_point_selection_visuals()
                self._clear_selection_rect()
                super().mousePressEvent(event)
                return

            if self.active_tool in {"框选", "选择"}:
                # 点击框选工具下的空白区域：进入框选状态，记录起始场景坐标，清空当前选择并刷新视觉效果。
                self._selection_start_position = QPointF(event.scenePos())
                self._selection_current_position = QPointF(event.scenePos())
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
                self._select_points_in_scene_rect(scene_rect, self.active_tool)
                event.accept()
                return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        """绘图模式下拦截鼠标：左键释放完成框选。"""
        if event.button() == Qt.MouseButton.LeftButton:
            if self.active_tool in {"框选", "选择"} and self._selection_start_position is not None:
                self._selection_current_position = QPointF(event.scenePos())
                scene_rect = QRectF(self._selection_start_position, self._selection_current_position).normalized()
                self._select_points_in_scene_rect(scene_rect, self.active_tool)
                self._clear_selection_rect()
                event.accept()
                return

        super().mouseReleaseEvent(event)

