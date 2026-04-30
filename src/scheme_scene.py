# scheme_scene.py
"""
自定义场地场景，负责网格与场地的绘制。
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
from PyQt6.QtGui import QBrush, QColor, QPainterPath, QPen, QPolygonF
from field_settings import FieldSettings, GridRenderer
from scene_items import PerformerPointItem, ReferenceHandleItem
from scheme_scene_data import SchemeSceneDataMixin


class SchemeScene(SchemeSceneDataMixin, QGraphicsScene):
    """主绘图场景：管理节点点位、图形草稿与渲染。"""

    # 通知主窗口更新“绘制控制台”状态，替代阻塞式弹窗。
    draftStarted = pyqtSignal(str)
    draftFinished = pyqtSignal()
    selectedPointsChanged = pyqtSignal(int)
    lineSegmentPointCountChanged = pyqtSignal(int)
    lineSegmentSpacingChanged = pyqtSignal(float)
    samplingPointCountChanged = pyqtSignal(str, int)
    samplingSpacingChanged = pyqtSignal(str, float)
    samplingShiftSpacingChanged = pyqtSignal(str, float)
    samplingShiftPointCountChanged = pyqtSignal(str, int)

    _single_click_tools = {"点", "线段", "弧", "填充四边形", "圆", "多边形"}

    def __init__(self, parent=None):
        super().__init__(parent)
        # 场地参数与网格绘制器。
        self.field_settings = FieldSettings(self)
        self.grid_renderer = GridRenderer(self.field_settings)
        self.field_settings.changed.connect(self._on_field_settings_changed)
        self._current_items = []
        self._previous_items = []
        self._label_items = []
        self.setup_scene_data()
        self._draft_tool_name = None
        self._draft_reference_points = []
        self._draft_preview_items = []
        self._pending_preview_items = []
        self._draft_handle_items = []
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
        self._updating_draft_handles = False
        self._selection_rect_item = None
        self._selection_start_scene = None
        self._selection_current_scene = None
        self._point_items_by_id = {}
        self._label_items_by_id = {}

        # 固定为启动时的初始场景大小，避免新增图元导致 sceneRect 自动变化。
        initial_field_rect = self.field_settings.field_rect
        # initial_scale = float(self.field_settings.scale)
        # width_px = float(initial_field_rect.width()) * initial_scale
        # height_px = float(initial_field_rect.height()) * initial_scale
        # margin = max(width_px, height_px) * 0.5 + 200.0
        self.setSceneRect(initial_field_rect)

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
        for item in self._current_items + self._previous_items + self._label_items:
            self.removeItem(item)
        self._current_items = []
        self._previous_items = []
        self._label_items = []
        self._point_items_by_id = {}
        self._label_items_by_id = {}


    def _clear_selection_rect(self):
        if self._selection_rect_item is not None:
            self.removeItem(self._selection_rect_item)
            self._selection_rect_item = None
        self._selection_start_scene = None
        self._selection_current_scene = None

    def _update_selection_rect_item(self):
        if self._selection_start_scene is None or self._selection_current_scene is None:
            return
        rect = QRectF(self._selection_start_scene, self._selection_current_scene).normalized()
        if self._selection_rect_item is None:
            self._selection_rect_item = QGraphicsRectItem(rect)
            self._selection_rect_item.setPen(QPen(QColor("#d35400"), 1.2, Qt.PenStyle.DashLine))
            self._selection_rect_item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            self._selection_rect_item.setZValue(980)
            self.addItem(self._selection_rect_item)
        else:
            self._selection_rect_item.setRect(rect)

    def _select_points_in_scene_rect(self, scene_rect: QRectF):
        if scene_rect.width() <= 1e-6 and scene_rect.height() <= 1e-6:
            return
        selected_ids = set()
        for point in self.node_points.get(self.active_node, []):
            pos = self._field_to_scene(point["x"], point["y"])
            if scene_rect.contains(pos):
                selected_ids.add(int(point["id"]))
        self._selected_point_ids = selected_ids
        self._refresh_point_selection_visuals()

    def _refresh_point_selection_visuals(self):
        for point_id, item in self._point_items_by_id.items():
            item.set_selected_visual(point_id in self._selected_point_ids)
        self.selectedPointsChanged.emit(len(self._selected_point_ids))

    def _find_point_by_id(self, point_id: int) -> dict | None:
        for point in self.node_points.get(self.active_node, []):
            if int(point.get("id", -1)) == int(point_id):
                return point
        return None

    def _can_drag_performer_point(self) -> bool:
        # 查看功能允许在任意拍位浏览；但拖拽写回仅允许发生在“当前节点拍位”上。
        # 这样可避免在中间插值预览拍位误改真实节点点位。
        return self.active_tool == "框选" and self._is_current_beat_editable()

    def _on_performer_point_moved(self, point_id: int, scene_pos: QPointF) -> QPointF:
        # 预览拍位下禁止写回真实数据，只返回当前位置。
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
            label.setPos(pos.x() + 6, pos.y() - 14)

        return self._field_to_scene(x, y)

    def _on_performer_point_released(self, point_id: int):
        # _ = point_id  # 仅为占位消警告，当前无实际用途。
        if not self._is_current_beat_editable():
            return
        self._mark_node_manual(self.active_node)
        self._recalculate_following_auto_nodes(self.active_node)

    def _clear_draft(self):
        had_draft = bool(self._draft_tool_name or self._draft_reference_points)
        self._draft_tool_name = None
        self._draft_reference_points = []
        self._clear_draft_items()
        self._clear_pending_preview_items()
        if had_draft:
            self.draftFinished.emit()

    def _clear_draft_items(self):
        for item in self._draft_preview_items + self._draft_handle_items:
            self.removeItem(item)
        self._draft_preview_items = []
        self._draft_handle_items = []

    def _clear_pending_preview_items(self):
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

    # def _two_step_spacing(self) -> float:
    #     return max(1e-9, float(self.field_settings.grid_step) * 2.0)

    def _dedupe_points(self, points: list[tuple[float, float]]) -> list[tuple[float, float]]:
        unique = []
        seen = set()
        for x, y in points:
            key = (round(x, 6), round(y, 6))
            if key in seen:
                continue
            seen.add(key)
            unique.append((x, y))
        return unique

    @staticmethod
    def _distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
        return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

    def _sample_line_points(self, p1: tuple[float, float], p2: tuple[float, float], spacing: float) -> list[tuple[float, float]]:
        dist = self._distance(p1, p2)
        if dist <= 1e-9:
            return [p1]
        steps = int(dist // spacing)
        ux = (p2[0] - p1[0]) / dist
        uy = (p2[1] - p1[1]) / dist
        points = []
        for index in range(steps + 1):
            distance = spacing * index
            points.append((p1[0] + ux * distance, p1[1] + uy * distance))
        return points

    def _sample_line_points_with_count(self, p1: tuple[float, float], p2: tuple[float, float], spacing: float, point_count: int) -> list[tuple[float, float]]:
        count = max(1, int(point_count))
        dist = self._distance(p1, p2)
        if dist <= 1e-9:
            return [p1]
        ux = (p2[0] - p1[0]) / dist
        uy = (p2[1] - p1[1]) / dist
        return [(
            p1[0] + ux * spacing * index,
            p1[1] + uy * spacing * index,
        ) for index in range(count)]

    def _sample_polyline_points(self, points: list[tuple[float, float]], spacing: float) -> list[tuple[float, float]]:
        if len(points) < 2:
            return points[:]
        sampled = [points[0]]
        next_target = spacing
        traveled = 0.0
        for idx in range(len(points) - 1):
            start = points[idx]
            end = points[idx + 1]
            segment_length = self._distance(start, end)
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
        if len(points) < 2:
            return points[:]
        count = max(1, int(point_count))
        if count == 1:
            return [points[0]]

        segment_lengths = []
        total_length = 0.0
        for idx in range(len(points) - 1):
            seg_len = self._distance(points[idx], points[idx + 1])
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
        if len(points) < 2:
            return points[:]

        count = max(1, int(point_count))
        if count == 1:
            return [points[0]]

        segment_lengths = []
        total_length = 0.0
        for idx in range(len(points) - 1):
            seg_len = self._distance(points[idx], points[idx + 1])
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
        if len(points) < 2:
            return points[:]

        dense = []
        n = len(points)
        for i in range(n - 1):
            p0 = points[i - 1] if i - 1 >= 0 else points[i]
            p1 = points[i]
            p2 = points[i + 1]
            p3 = points[i + 2] if i + 2 < n else points[i + 1]

            seg_len = max(1e-9, self._distance(p1, p2))
            # 根据段长度和采样间隔决定密集采样步数
            steps = max(6, int(seg_len / max(1e-9, spacing * 0.25)))
            for s in range(steps):
                t = s / steps
                t2 = t * t
                t3 = t2 * t
                x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
                y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
                dense.append((x, y))
        dense.append(points[-1])

        # 将密集曲线点按 spacing 等距重采样（复用折线采样实现）
        return self._sample_polyline_points(dense, spacing)

    def _sample_curve_points_with_count(self, points: list[tuple[float, float]], point_count: int) -> list[tuple[float, float]]:
        """基于 Catmull-Rom 样条生成平滑曲线，并按目标点数重新采样。"""
        if len(points) < 2:
            return points[:]

        dense = []
        n = len(points)
        for i in range(n - 1):
            p0 = points[i - 1] if i - 1 >= 0 else points[i]
            p1 = points[i]
            p2 = points[i + 1]
            p3 = points[i + 2] if i + 2 < n else points[i + 1]

            seg_len = max(1e-9, self._distance(p1, p2))
            steps = max(6, int(seg_len / max(1e-9, float(self.field_settings.grid_step) * 0.25)))
            for s in range(steps):
                t = s / steps
                t2 = t * t
                t3 = t2 * t
                x = 0.5 * ((2 * p1[0]) + (-p0[0] + p2[0]) * t + (2 * p0[0] - 5 * p1[0] + 4 * p2[0] - p3[0]) * t2 + (-p0[0] + 3 * p1[0] - 3 * p2[0] + p3[0]) * t3)
                y = 0.5 * ((2 * p1[1]) + (-p0[1] + p2[1]) * t + (2 * p0[1] - 5 * p1[1] + 4 * p2[1] - p3[1]) * t2 + (-p0[1] + 3 * p1[1] - 3 * p2[1] + p3[1]) * t3)
                dense.append((x, y))
        dense.append(points[-1])

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
        cx, cy, radius = self._circle_from_two_points(center, radius_point)
        if radius <= 1e-9:
            return [center]
        circumference = 2.0 * math.pi * radius
        # 从第二个参考点开始，沿逆时针方向按固定弧长步进生成点位。
        # 若末尾剩余弧长不足 spacing，则不生成接近起点的最后一个点，避免尾段过短。
        point_count = int(circumference // max(1e-9, spacing))
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
        center = self._circumcenter(start, through, end)
        if center is None:
            count = max(1, int(point_count))
            if count == 1:
                return [start]
            total_length = self._distance(start, through) + self._distance(through, end)
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

    def _sample_rectangle_fill_points(self, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], spacing: float) -> list[tuple[float, float]]:
        ax, ay = a
        bx, by = b
        cx, cy = c
        base_dx, base_dy = bx - ax, by - ay
        shift_dx, shift_dy = cx - ax, cy - ay
        base_len = math.hypot(base_dx, base_dy)
        shift_len = math.hypot(shift_dx, shift_dy)
        if base_len <= 1e-9 or shift_len <= 1e-9:
            return [a, b, c]

        # 此处的间距用于基线方向；若提供则缩进部分可以使用不同的间距。
        base_step_count = int(base_len // spacing)
        shift_step_count = int(shift_len // spacing)

        base_unit_x = base_dx / base_len
        base_unit_y = base_dy / base_len
        shift_unit_x = shift_dx / shift_len
        shift_unit_y = shift_dy / shift_len

        base_line = [(
            ax + base_unit_x * spacing * index,
            ay + base_unit_y * spacing * index,
        ) for index in range(base_step_count + 1)]

        points = []
        for shift_index in range(shift_step_count + 1):
            shift_distance = spacing * shift_index
            if shift_distance > shift_len + 1e-9:
                break
            row = [(
                px + shift_unit_x * shift_distance,
                py + shift_unit_y * shift_distance,
            ) for px, py in base_line]
            points.extend(row)

        return points or [a, b, c]

    # def _sample_rectangle_fill_points_two_spacing(self, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], spacing_base: float, spacing_shift: float) -> list[tuple[float, float]]:
    #     """按两个方向不同间隔采样填充四边形点位（field 单位）。"""
    #     ax, ay = a
    #     bx, by = b
    #     cx, cy = c
    #     base_dx, base_dy = bx - ax, by - ay
    #     shift_dx, shift_dy = cx - ax, cy - ay
    #     base_len = math.hypot(base_dx, base_dy)
    #     shift_len = math.hypot(shift_dx, shift_dy)
    #     if base_len <= 1e-9 or shift_len <= 1e-9:
    #         return [a, b, c]

    #     base_unit_x = base_dx / base_len
    #     base_unit_y = base_dy / base_len
    #     shift_unit_x = shift_dx / shift_len
    #     shift_unit_y = shift_dy / shift_len

    #     base_step_count = int(base_len // spacing_base)
    #     shift_step_count = int(shift_len // spacing_shift)

    #     base_line = [(
    #         ax + base_unit_x * spacing_base * index,
    #         ay + base_unit_y * spacing_base * index,
    #     ) for index in range(base_step_count + 1)]

    #     points = []
    #     for shift_index in range(shift_step_count + 1):
    #         shift_distance = spacing_shift * shift_index
    #         if shift_distance > shift_len + 1e-9:
    #             break
    #         row = [(
    #             px + shift_unit_x * shift_distance,
    #             py + shift_unit_y * shift_distance,
    #         ) for px, py in base_line]
    #         points.extend(row)

    #     return points or [a, b, c]

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
        vertices = self._make_polygon_points(center, radius_point, self._polygon_side_count("多边形"))
        if not vertices:
            return []
        points = self._sample_polyline_points(vertices + [vertices[0]], spacing)
        return points

    def _sample_closed_polyline_points_with_count(self, points: list[tuple[float, float]], point_count: int) -> list[tuple[float, float]]:
        if len(points) < 2:
            return points[:]
        count = max(1, int(point_count))
        if count == 1:
            return [points[0]]

        loop = points + [points[0]]
        total_length = 0.0
        segment_lengths = []
        for idx in range(len(loop) - 1):
            seg_len = self._distance(loop[idx], loop[idx + 1])
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
        vertices = self._make_polygon_points(center, radius_point, self._polygon_side_count("多边形"))
        if not vertices:
            return []
        return self._sample_closed_polyline_points_with_count(vertices, point_count)

    def _generate_performer_points(self, tool_name: str, refs: list[tuple[float, float]]) -> list[tuple[float, float]]:
        spacing = max(1e-9, float(self.field_settings.grid_step) * 2.0)
        if tool_name == "点" and refs:
            return self._dedupe_points(refs)
        if tool_name in self._sampling_tools and len(refs) >= 2:
            state = self._sampling_state(tool_name)
            line_spacing = max(1e-9, float(self.field_settings.grid_step) * float(state["spacing_steps"]))
            point_count = max(1, int(state["point_count"]))

            if tool_name == "线段":
                return self._dedupe_points(self._sample_line_points_with_count(refs[0], refs[1], line_spacing, point_count))
            if tool_name == "弧":
                if state.get("point_count_manual", False) and state.get("spacing_manual", False):
                    return self._dedupe_points(self._sample_arc_points_with_count_and_spacing(refs[0], refs[2], refs[1], point_count, line_spacing))
                if state.get("point_count_manual", False):
                    return self._dedupe_points(self._sample_arc_points_with_count(refs[0], refs[2], refs[1], point_count))
                return self._dedupe_points(self._sample_arc_points(refs[0], refs[2], refs[1], line_spacing))
            if tool_name == "圆":
                if state["point_count_manual"]:
                    return self._dedupe_points(self._sample_circle_points_with_count(refs[0], refs[1], point_count))
                return self._dedupe_points(self._sample_circle_points(refs[0], refs[1], line_spacing))
            if tool_name == "多边形":
                if state["point_count_manual"]:
                    return self._dedupe_points(self._sample_polygon_perimeter_points_with_count(refs[0], refs[1], point_count))
                return self._dedupe_points(self._sample_polygon_perimeter_points(refs[0], refs[1], line_spacing))
        if tool_name == "弧" and len(refs) >= 3:
            # 弧工具参考点语义：端点1、端点2、弧上一点。
            return self._dedupe_points(self._sample_arc_points(refs[0], refs[2], refs[1], spacing))
        if tool_name == "曲线/折线" and len(refs) >= 2:
            is_curve = getattr(self, '_curve_mode', 'polyline') == 'curve'
            if state["spacing_manual"] and state["point_count_manual"]:
                if is_curve:
                    dense_curve = self._sample_curve_points(refs, line_spacing)
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
        if tool_name == "填充四边形" and len(refs) >= 3:
            state = self._sampling_state(tool_name)
            base_spacing = max(1e-9, float(self.field_settings.grid_step) * float(state.get("spacing_steps", 2.0)))
            shift_spacing = max(1e-9, float(self.field_settings.grid_step) * float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0))))
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
            radius = self._distance(refs[0], refs[1]) * float(self.field_settings.scale)
            item = QGraphicsEllipseItem(center.x() - radius, center.y() - radius, radius * 2, radius * 2)
            item.setPen(pen)
            item.setBrush(QBrush(Qt.BrushStyle.NoBrush))
            return item

        if self._draft_tool_name == "多边形" and len(refs) >= 2:
            center = self._field_to_scene(*refs[0])
            radius = self._distance(refs[0], refs[1]) * float(self.field_settings.scale)
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
        if tool_name == "线段":
            self._sync_line_segment_auto_values_from_draft()
        self._render_points_for_active_node()
        self.draftStarted.emit(tool_name)

    def _on_reference_handle_moved(self, index: int, scene_pos: QPointF) -> QPointF:
        if self._updating_draft_handles:
            return scene_pos
        if index < 0 or index >= len(self._draft_reference_points):
            return scene_pos
        x, y = self._scene_to_field(scene_pos)
        x, y = self._snap_field_point(x, y)
        snapped_scene_pos = self._field_to_scene(x, y)
        self._draft_reference_points[index] = (x, y)
        if self._draft_tool_name == "线段":
            self._sync_line_segment_auto_values_from_draft()
        if self._draft_tool_name in self._sampling_tools:
            self._sync_sampling_auto_values_from_draft(self._draft_tool_name)
        QTimer.singleShot(0, self._refresh_reference_overlay_for_active_tool)
        return snapped_scene_pos

    def confirm_current_drawing(self):
        """确认当前草稿并写入当前节点点位。"""
        tool_name = self._draft_tool_name
        refs = list(self._draft_reference_points)
        had_draft = bool(self._draft_tool_name or self._draft_reference_points)

        # 曲线/折线可直接用 pending 参考点确认（无需右键进入 draft）。
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

        generated = self._generate_performer_points(tool_name, refs)
        current_points = self.node_points.setdefault(self.active_node, [])
        new_point_ids = []
        group_id = None
        if tool_name == "点":
            group_id = self._next_group_id
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

        if group_id is not None and new_point_ids:
            self.point_groups.append({
                "id": group_id,
                "node": self.active_node,
                "tool": tool_name,
                "point_ids": new_point_ids,
                "leader_id": new_point_ids[0],
            })
            self._next_group_id += 1

        if tool_name == "曲线/折线":
            self.reset_sampling_defaults(tool_name)
        elif tool_name in self._sampling_tools:
            self.reset_sampling_auto(tool_name)

        # 确认后丢弃参考点缓存，下一次绘制重新输入。
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
            if t == "曲线/折线":
                self.reset_sampling_defaults(t)
            else:
                self.reset_sampling_auto(t)
        self._pending_points = []
        self._clear_draft()
        self.draftFinished.emit()
        self._render_points_for_active_node()

    def _field_to_scene(self, x: float, y: float) -> QPointF:
        s = self.field_settings
        return QPointF(x * s.scale + s.offset.x(), y * s.scale + s.offset.y())

    def _scene_to_field(self, scene_pos: QPointF) -> tuple[float, float]:
        s = self.field_settings
        scale = s.scale if abs(s.scale) > 1e-9 else 1.0
        x = (scene_pos.x() - s.offset.x()) / scale
        y = (scene_pos.y() - s.offset.y()) / scale
        return x, y

    def _snap_field_point(self, x: float, y: float) -> tuple[float, float]:
        step = max(1e-9, float(self.field_settings.grid_step))
        return (round(x / step) * step, round(y / step) * step)

    def _sampling_state(self, tool_name: str) -> dict:
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

        # 若两项同时为手动（即都不是自动），仅对圆与多边形默认启用点数自动以保证至少有一项自动适配；
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
            return

        if changed == "point_count_shift_auto":
            state["spacing_shift_manual"] = True
            return
        if changed == "spacing_shift_auto":
            state["point_count_shift_manual"] = True
            return
        # 兜底：保留“点数自动”，把“间隔”落为手动。
        state["spacing_shift_manual"] = True

    def sampling_settings(self, tool_name: str) -> tuple[int, float]:
        state = self._sampling_state(tool_name)
        return int(state["point_count"]), float(state["spacing_steps"])

    def sampling_shift_point_count(self, tool_name: str) -> int:
        state = self._sampling_state(tool_name)
        return int(state.get("point_count_shift", 1))

    def polygon_side_count(self, tool_name: str) -> int:
        state = self._sampling_state(tool_name)
        return max(2, int(state.get("polygon_sides", 6)))

    def _polygon_side_count(self, tool_name: str) -> int:
        return self.polygon_side_count(tool_name)

    def is_sampling_point_count_auto(self, tool_name: str) -> bool:
        return not bool(self._sampling_state(tool_name)["point_count_manual"])

    def is_sampling_spacing_auto(self, tool_name: str) -> bool:
        return not bool(self._sampling_state(tool_name)["spacing_manual"])

    def is_sampling_point_count_shift_auto(self, tool_name: str) -> bool:
        return not bool(self._sampling_state(tool_name).get("point_count_shift_manual", False))

    def line_segment_settings(self) -> tuple[int, float]:
        return self.sampling_settings("线段")

    def is_line_segment_point_count_auto(self) -> bool:
        return self.is_sampling_point_count_auto("线段")

    def is_line_segment_spacing_auto(self) -> bool:
        return self.is_sampling_spacing_auto("线段")

    @property
    def _line_segment_point_count(self):
        return int(self._sampling_state("线段")["point_count"])

    @_line_segment_point_count.setter
    def _line_segment_point_count(self, value):
        self._sampling_state("线段")["point_count"] = max(1, int(value))

    @property
    def _line_segment_point_count_manual(self):
        return bool(self._sampling_state("线段")["point_count_manual"])

    @_line_segment_point_count_manual.setter
    def _line_segment_point_count_manual(self, value):
        self._sampling_state("线段")["point_count_manual"] = bool(value)

    @property
    def _line_segment_spacing_steps(self):
        return float(self._sampling_state("线段")["spacing_steps"])

    @_line_segment_spacing_steps.setter
    def _line_segment_spacing_steps(self, value):
        self._sampling_state("线段")["spacing_steps"] = max(0.001, float(value))

    @property
    def _line_segment_spacing_manual(self):
        return bool(self._sampling_state("线段")["spacing_manual"])

    @_line_segment_spacing_manual.setter
    def _line_segment_spacing_manual(self, value):
        self._sampling_state("线段")["spacing_manual"] = bool(value)

    def _emit_sampling_point_count_changed(self, tool_name: str, point_count: int):
        point_count = max(1, int(point_count))
        self.samplingPointCountChanged.emit(tool_name, point_count)
        if tool_name == "线段":
            self.lineSegmentPointCountChanged.emit(point_count)

    def _emit_sampling_shift_point_count_changed(self, tool_name: str, point_count: int):
        point_count = max(1, int(point_count))
        self.samplingShiftPointCountChanged.emit(tool_name, point_count)
        # no special-case for line segments

    def _emit_sampling_spacing_changed(self, tool_name: str, spacing_steps: float):
        spacing_steps = max(0.001, float(spacing_steps))
        self.samplingSpacingChanged.emit(tool_name, spacing_steps)
        if tool_name == "线段":
            self.lineSegmentSpacingChanged.emit(spacing_steps)

    def _sampling_length_for_tool(self, tool_name: str, refs: list[tuple[float, float]]) -> float:
        if tool_name == "线段" and len(refs) >= 2:
            return self._distance(refs[0], refs[1])
        if tool_name == "曲线/折线" and len(refs) >= 2:
            total = 0.0
            for idx in range(len(refs) - 1):
                total += self._distance(refs[idx], refs[idx + 1])
            return total
        if tool_name == "弧" and len(refs) >= 3:
            center = self._circumcenter(refs[0], refs[2], refs[1])
            if center is None:
                return self._distance(refs[0], refs[2]) + self._distance(refs[2], refs[1])
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
            radius = self._distance(refs[0], refs[1])
            return 2.0 * math.pi * radius
        if tool_name == "多边形" and len(refs) >= 2:
            vertices = self._make_polygon_points(refs[0], refs[1], self._polygon_side_count(tool_name))
            if not vertices:
                return 0.0
            total = 0.0
            loop = vertices + [vertices[0]]
            for idx in range(len(loop) - 1):
                total += self._distance(loop[idx], loop[idx + 1])
            return total
        if tool_name == "填充四边形":
            # 基线方向长度（P0-P1）用于自动计算 P0-P1 方向的点位个数/间隔
            if len(refs) >= 2:
                return self._distance(refs[0], refs[1])
            return 0.0
        return 0.0

    def _sampling_auto_point_count_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> int:
        state = self._sampling_state(tool_name)
        spacing = max(1e-9, float(self.field_settings.grid_step) * float(state["spacing_steps"]))
        length = self._sampling_length_for_tool(tool_name, refs)
        if length <= 1e-9:
            return max(1, int(state["point_count"]))
        if tool_name == "圆" or tool_name == "多边形":
            return max(1, int(length // spacing))
        return max(1, int(length // spacing) + 1)

    def _sampling_auto_point_count_shift_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> int:
        """计算填充四边形第二方向（P0-P2）的自动点数。"""
        # 默认复用基线 spacing 来估算，除非额外逻辑需要。
        state = self._sampling_state(tool_name)
        spacing_shift = max(1e-9, float(self.field_settings.grid_step) * float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0))))
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
        return max(0.001, float(length / (point_count - 1) / float(self.field_settings.grid_step)))

    def _sampling_auto_spacing_steps_for_refs(self, tool_name: str, refs: list[tuple[float, float]]) -> float:
        state = self._sampling_state(tool_name)
        length = self._sampling_length_for_tool(tool_name, refs)
        point_count = max(1, int(state["point_count"]))
        if length <= 1e-9:
            return max(0.001, float(state["spacing_steps"]))
        if tool_name == "圆" or tool_name == "多边形":
            if point_count <= 0:
                return max(0.001, float(state["spacing_steps"]))
            return max(0.001, float(length / point_count / float(self.field_settings.grid_step)))
        if point_count <= 1:
            return max(0.001, float(state["spacing_steps"]))
        return max(0.001, float(length / (point_count - 1) / float(self.field_settings.grid_step)))

    def _sync_sampling_auto_values_from_draft(self, tool_name: str):
        if tool_name not in self._sampling_tools:
            return

        refs = self._draft_reference_points
        if len(refs) < 2 and self.active_tool == tool_name:
            refs = self._pending_points

        state = self._sampling_state(tool_name)
        if not state["point_count_manual"]:
            point_count = self._sampling_auto_point_count_for_refs(tool_name, refs)
            if point_count != state["point_count"]:
                state["point_count"] = point_count
            self._emit_sampling_point_count_changed(tool_name, point_count)
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
        spacing_steps = max(0.001, float(spacing_steps))
        self.samplingShiftSpacingChanged.emit(tool_name, spacing_steps)

    def _sampling_point_count_manual(self, tool_name: str) -> bool:
        return bool(self._sampling_state(tool_name)["point_count_manual"])

    def _sampling_spacing_manual(self, tool_name: str) -> bool:
        return bool(self._sampling_state(tool_name)["spacing_manual"])

    def set_sampling_point_count(self, tool_name: str, point_count: int):
        state = self._sampling_state(tool_name)
        state["point_count"] = max(1, int(point_count))
        state["point_count_manual"] = True
        self._refresh_draft_preview_for_active_tool()

    def set_sampling_point_count_shift(self, tool_name: str, point_count: int):
        state = self._sampling_state(tool_name)
        state["point_count_shift"] = max(1, int(point_count))
        state["point_count_shift_manual"] = True
        self._refresh_draft_preview_for_active_tool()
        self._emit_sampling_shift_point_count_changed(tool_name, int(point_count))

    def set_sampling_point_count_auto_enabled(self, tool_name: str, enabled: bool):
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
        state = self._sampling_state(tool_name)
        state["point_count_shift_manual"] = not bool(enabled)
        if enabled:
            self._enforce_sampling_shift_auto_rule(state, changed="point_count_shift_auto")
        if enabled:
            self._sync_sampling_auto_values_from_draft(tool_name)
        self._refresh_draft_preview_for_active_tool()

    def set_sampling_spacing(self, tool_name: str, spacing_steps: float):
        state = self._sampling_state(tool_name)
        state["spacing_steps"] = max(0.001, float(spacing_steps))
        state["spacing_manual"] = True
        self._sync_sampling_auto_values_from_draft(tool_name)
        self._refresh_draft_preview_for_active_tool()

    def set_sampling_spacing_auto_enabled(self, tool_name: str, enabled: bool):
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
        state = self._sampling_state(tool_name)
        return float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0)))

    def is_sampling_shift_auto(self, tool_name: str) -> bool:
        return not bool(self._sampling_state(tool_name).get("spacing_shift_manual", False))

    def set_sampling_spacing_shift(self, tool_name: str, spacing_steps: float):
        state = self._sampling_state(tool_name)
        state["spacing_steps_shift"] = max(0.001, float(spacing_steps))
        state["spacing_shift_manual"] = True
        self._refresh_draft_preview_for_active_tool()

    def set_sampling_shift_auto_enabled(self, tool_name: str, enabled: bool):
        state = self._sampling_state(tool_name)
        state["spacing_shift_manual"] = not bool(enabled)
        if enabled:
            self._enforce_sampling_shift_auto_rule(state, changed="spacing_shift_auto")
        if enabled:
            self._sync_sampling_auto_values_from_draft(tool_name)
        self._refresh_draft_preview_for_active_tool()

    def set_polygon_side_count(self, tool_name: str, side_count: int):
        state = self._sampling_state(tool_name)
        state["polygon_sides"] = max(2, int(side_count))
        self._sync_sampling_auto_values_from_draft(tool_name)
        self._refresh_draft_preview_for_active_tool()

    def reset_sampling_auto(self, tool_name: str):
        state = self._sampling_state(tool_name)
        # 点位个数自动开启，间距自动关闭并恢复为默认 2 步间隔
        state["point_count_manual"] = False
        state["spacing_manual"] = True
        state["spacing_steps"] = 2.0
        # 对于填充四边形，第二方向也设置为手动默认值
        if tool_name == "填充四边形":
            state["spacing_shift_manual"] = True
            state["spacing_steps_shift"] = float(state.get("spacing_steps", 2.0))
        # 同步并通知 UI 当前的自动/手动状态与默认值
        self._emit_sampling_point_count_changed(tool_name, int(state.get("point_count", 1)))
        self._emit_sampling_spacing_changed(tool_name, float(state.get("spacing_steps", 2.0)))
        if tool_name == "填充四边形":
            self._emit_sampling_shift_spacing_changed(tool_name, float(state.get("spacing_steps_shift", state.get("spacing_steps", 2.0))))

    def reset_sampling_defaults(self, tool_name: str):
        state = self._sampling_state(tool_name)
        state["point_count"] = 1
        # 默认行为：点位个数自动（自动计算点数），间距设为默认 2 步并由用户手动控制
        state["point_count_manual"] = False
        state["spacing_steps"] = 2.0
        state["spacing_manual"] = True
        # 若为填充四边形，第二方向也默认手动 2 步间隔
        if tool_name == "填充四边形":
            state["spacing_steps_shift"] = 2.0
            state["spacing_shift_manual"] = True
        self._emit_sampling_point_count_changed(tool_name, 1)
        self._emit_sampling_spacing_changed(tool_name, 2.0)
        if tool_name == "填充四边形":
            self._emit_sampling_shift_spacing_changed(tool_name, 2.0)

    def _line_segment_auto_point_count(self) -> int:
        refs = self._draft_reference_points
        if len(refs) < 2 and self.active_tool == "线段":
            refs = self._pending_points
        if len(refs) < 2:
            return max(1, int(self._line_segment_point_count))
        spacing = max(1e-9, float(self.field_settings.grid_step) * float(self._line_segment_spacing_steps))
        distance = self._distance(refs[0], refs[1])
        if distance <= 1e-9:
            return 1
        return max(1, int(distance // spacing) + 1)

    def _line_segment_auto_spacing_steps(self) -> float:
        refs = self._draft_reference_points
        if len(refs) < 2 and self.active_tool == "线段":
            refs = self._pending_points
        if len(refs) < 2:
            return max(0.001, float(self._line_segment_spacing_steps))

        distance = self._distance(refs[0], refs[1])
        if distance <= 1e-9:
            return max(0.001, float(self._line_segment_spacing_steps))

        if self._line_segment_point_count_manual:
            count = max(1, int(self._line_segment_point_count))
            if count <= 1:
                return max(0.001, float(self._line_segment_spacing_steps))
            spacing_steps = distance / (float(self.field_settings.grid_step) * float(count - 1))
            return max(0.001, float(spacing_steps))

        return max(0.001, float(self._line_segment_spacing_steps))

    def _sync_line_segment_auto_values_from_draft(self):
        if self._draft_tool_name != "线段" and self.active_tool != "线段":
            return

        if not self._line_segment_point_count_manual:
            point_count = self._line_segment_auto_point_count()
            if point_count != self._line_segment_point_count:
                self._line_segment_point_count = point_count
            self.lineSegmentPointCountChanged.emit(point_count)

        if not self._line_segment_spacing_manual and self._line_segment_point_count_manual:
            spacing_steps = self._line_segment_auto_spacing_steps()
            if abs(spacing_steps - self._line_segment_spacing_steps) > 1e-9:
                self._line_segment_spacing_steps = spacing_steps
            self.lineSegmentSpacingChanged.emit(spacing_steps)

    def _sync_line_segment_point_count_from_draft(self):
        self._sync_line_segment_auto_values_from_draft()

    def _refresh_draft_preview_for_active_tool(self):
        if self._draft_tool_name in self._sampling_tools:
            self._sync_sampling_auto_values_from_draft(self._draft_tool_name)
            self._draw_draft_overlay()
            self.update()
            return

        if self.active_tool in self._sampling_tools and self._pending_points:
            self._clear_draft_items()
            self._draw_pending_reference_preview()
            self._draw_pending_reference_points()
            self.update()

    def set_line_segment_point_count(self, point_limit: int):
        self._line_segment_point_count = max(1, int(point_limit))
        self._line_segment_point_count_manual = True
        self._refresh_draft_preview_for_active_tool()

    def set_line_segment_point_count_auto_enabled(self, enabled: bool):
        self._line_segment_point_count_manual = not bool(enabled)
        if enabled:
            self._sync_line_segment_auto_values_from_draft()
        self._refresh_draft_preview_for_active_tool()

    def set_line_segment_spacing(self, spacing: float):
        self._line_segment_spacing_steps = max(0.001, float(spacing))
        self._line_segment_spacing_manual = True
        self._sync_line_segment_point_count_from_draft()
        self._refresh_draft_preview_for_active_tool()

    def set_line_segment_spacing_auto_enabled(self, enabled: bool):
        self._line_segment_spacing_manual = not bool(enabled)
        if enabled:
            if self._line_segment_point_count_manual:
                self._sync_line_segment_auto_values_from_draft()
            else:
                self._line_segment_spacing_steps = 2.0
                self._sync_line_segment_auto_values_from_draft()
        self._refresh_draft_preview_for_active_tool()

    def reset_line_segment_point_count_auto(self):
        self._line_segment_point_count_manual = False
        self._sync_line_segment_point_count_from_draft()

    def _shape_color(self, ghost: bool) -> tuple[QPen, QBrush]:
        if ghost:
            pen = QPen(QColor(60, 60, 60, 120), 1)
            brush = QBrush(QColor(90, 90, 90, 35))
        else:
            pen = QPen(QColor("#1f5e9c"), 1.5)
            brush = QBrush(QColor(255, 255, 255, 12))
        return pen, brush

    def _make_polygon_points(self, center: tuple[float, float], radius_point: tuple[float, float], sides: int) -> list[tuple[float, float]]:
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
        cx, cy = center
        rx, ry = radius_point
        radius = math.hypot(rx - cx, ry - cy)
        return cx, cy, radius

    def _rectangle_from_three_points(self, a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> list[tuple[float, float]]:
        ax, ay = a
        bx, by = b
        cx, cy = c
        dx = bx + (cx - ax)
        dy = by + (cy - ay)
        return [a, b, (dx, dy), c]

    def _circumcenter(self, p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float]) -> tuple[float, float] | None:
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

    def _shape_to_item(self, shape: dict, ghost: bool):
        pen, brush = self._shape_color(ghost)
        shape_type = shape.get("type")

        if shape_type == "line":
            p1 = self._field_to_scene(*shape["points"][0])
            p2 = self._field_to_scene(*shape["points"][1])
            item = QGraphicsLineItem(p1.x(), p1.y(), p2.x(), p2.y())
            item.setPen(pen)
            return item

        if shape_type == "circle":
            cx, cy = self._field_to_scene(*shape["center"])
            radius = float(shape["radius"]) * float(self.field_settings.scale)
            item = QGraphicsEllipseItem(cx.x() - radius, cy.y() - radius, radius * 2, radius * 2)
            item.setPen(pen)
            item.setBrush(brush)
            return item

        if shape_type in {"rect", "polygon"}:
            polygon = QPolygonF([
                self._field_to_scene(x, y)
                for x, y in shape["points"]
            ])
            item = QGraphicsPolygonItem(polygon)
            item.setPen(pen)
            item.setBrush(brush)
            return item

        if shape_type in {"polyline", "arc"}:
            path = QPainterPath()
            if shape_type == "polyline":
                points = shape["points"]
                if points:
                    start = self._field_to_scene(*points[0])
                    path.moveTo(start)
                    for x, y in points[1:]:
                        path.lineTo(self._field_to_scene(x, y))
            else:
                scene_points = [self._field_to_scene(x, y) for x, y in shape["points"]]
                path = self._arc_path_from_three_points(
                    (scene_points[0].x(), scene_points[0].y()),
                    (scene_points[1].x(), scene_points[1].y()),
                    (scene_points[2].x(), scene_points[2].y()),
                )
            item = QGraphicsPathItem(path)
            item.setPen(pen)
            return item

        return None

    def _draw_shape(self, shape: dict, ghost: bool):
        item = self._shape_to_item(shape, ghost)
        if item is None:
            return
        self.addItem(item)
        target_list = self._previous_items if ghost else self._current_items
        target_list.append(item)

    def _draw_preview_points(self):
        if not self._pending_points:
            return

        preview_pen = QPen(QColor("#d35400"), 1, Qt.PenStyle.DashLine)
        preview_item = None

        scene_pending = [self._field_to_scene(x, y) for x, y in self._pending_points]

        if self.active_tool == "线段" and len(scene_pending) >= 1:
            p1 = scene_pending[0]
            p2 = scene_pending[-1]
            preview_item = QGraphicsLineItem(p1.x(), p1.y(), p2.x(), p2.y())
            preview_item.setPen(preview_pen)
        elif self.active_tool == "圆" and len(self._pending_points) >= 1:
            cx, cy = scene_pending[0].x(), scene_pending[0].y()
            rx, ry = scene_pending[-1].x(), scene_pending[-1].y()
            radius = math.hypot(rx - cx, ry - cy)
            preview_item = QGraphicsEllipseItem(cx - radius, cy - radius, radius * 2, radius * 2)
            preview_item.setPen(preview_pen)
            preview_item.setBrush(QBrush(QColor(255, 165, 0, 30)))
        elif self.active_tool == "填充四边形" and len(self._pending_points) >= 2:
            points = self._rectangle_from_three_points(self._pending_points[0], self._pending_points[1], self._pending_points[-1])
            if len(points) == 4:
                polygon = QPolygonF([self._field_to_scene(x, y) for x, y in points])
                preview_item = QGraphicsPolygonItem(polygon)
                preview_item.setPen(preview_pen)
                preview_item.setBrush(QBrush(QColor(255, 165, 0, 30)))
        elif self.active_tool == "多边形" and len(self._pending_points) >= 2:
            points = self._make_polygon_points(self._pending_points[0], self._pending_points[-1], self._polygon_side_count("多边形"))
            if points:
                polygon = QPolygonF([self._field_to_scene(x, y) for x, y in points])
                preview_item = QGraphicsPolygonItem(polygon)
                preview_item.setPen(preview_pen)
                preview_item.setBrush(QBrush(QColor(255, 165, 0, 30)))
        elif self.active_tool == "弧" and len(self._pending_points) >= 2:
            if len(self._pending_points) >= 3:
                start_scene = self._field_to_scene(*self._pending_points[0])
                end_scene = self._field_to_scene(*self._pending_points[1])
                through_scene = self._field_to_scene(*self._pending_points[2])
                path = self._arc_path_from_three_points(
                    (start_scene.x(), start_scene.y()),
                    (through_scene.x(), through_scene.y()),
                    (end_scene.x(), end_scene.y()),
                )
            else:
                path = QPainterPath()
                path.moveTo(scene_pending[0])
                path.lineTo(scene_pending[-1])
            preview_item = QGraphicsPathItem(path)
            preview_item.setPen(preview_pen)
        elif self.active_tool == "曲线/折线" and len(self._pending_points) >= 2:
            if getattr(self, '_curve_mode', 'polyline') == 'curve':
                path = QPainterPath()
                path.moveTo(scene_pending[0])
                n = len(scene_pending)
                for i in range(n - 1):
                    p0 = scene_pending[i - 1] if i - 1 >= 0 else scene_pending[i]
                    p1 = scene_pending[i]
                    p2 = scene_pending[i + 1]
                    p3 = scene_pending[i + 2] if i + 2 < n else scene_pending[i + 1]

                    c1x = p1.x() + (p2.x() - p0.x()) / 6.0
                    c1y = p1.y() + (p2.y() - p0.y()) / 6.0
                    c2x = p2.x() - (p3.x() - p1.x()) / 6.0
                    c2y = p2.y() - (p3.y() - p1.y()) / 6.0

                    path.cubicTo(QPointF(c1x, c1y), QPointF(c2x, c2y), p2)
                preview_item = QGraphicsPathItem(path)
                preview_item.setPen(preview_pen)
            else:
                path = QPainterPath()
                path.moveTo(scene_pending[0])
                for point in scene_pending[1:]:
                    path.lineTo(point)
                preview_item = QGraphicsPathItem(path)
                preview_item.setPen(preview_pen)

        if preview_item is not None:
            self.addItem(preview_item)
            self._current_items.append(preview_item)

        for point in scene_pending:
            x = point.x()
            y = point.y()
            dot = QGraphicsEllipseItem(x - 3, y - 3, 6, 6)
            dot.setPen(QPen(QColor("#d35400"), 1))
            dot.setBrush(QBrush(QColor(255, 165, 0, 30)))
            self.addItem(dot)
            self._current_items.append(dot)

    def _draw_draft_overlay(self):
        self._clear_draft_items()
        self._draw_draft_preview()
        self._draw_draft_handles()

    def _draw_draft_preview(self):
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
        if self._updating_draft_handles:
            return scene_pos
        if index < 0 or index >= len(self._pending_points):
            return scene_pos
        x, y = self._scene_to_field(scene_pos)
        x, y = self._snap_field_point(x, y)
        self._pending_points[index] = (x, y)
        if self.active_tool == "线段":
            self._sync_line_segment_auto_values_from_draft()
        if self.active_tool == "曲线/折线":
            self._sync_sampling_auto_values_from_draft("曲线/折线")
        QTimer.singleShot(0, self._refresh_reference_overlay_for_active_tool)
        return self._field_to_scene(x, y)

    # def _ensure_point_draft(self):
    #     """确保点工具始终保持连续草稿态。"""
    #     # 历史方法：当前流程由 _handle_draw_tool 管理草稿态，无调用方。
    #     if self._draft_tool_name != "点":
    #         self._draft_tool_name = "点"
    #         self._draft_reference_points = []
    #         self.draftStarted.emit("点")

    # def _finalize_pending_shape(self):
    #     # 历史方法：当前右键进入草稿确认，不再直接写入 node_shapes。
    #     points = list(self._pending_points)
    #     if self.active_tool == "曲线/折线":
    #         if len(points) >= 2:
    #             self.node_shapes[self.active_node].append({"type": "polyline", "points": points})
    #     self._pending_points = []
    #     self._render_points_for_active_node()

    # def _add_shape_from_points(self, tool_name: str, points: list[tuple[float, float]]):
    #     # 历史方法：当前由点位生成流程统一处理，无调用方。
    #     if tool_name == "线段" and len(points) >= 2:
    #         self.node_shapes[self.active_node].append({"type": "line", "points": [points[0], points[1]]})
    #     elif tool_name == "弧" and len(points) >= 3:
    #         self.node_shapes[self.active_node].append({"type": "arc", "points": [points[0], points[1], points[2]]})
    #     elif tool_name == "填充四边形" and len(points) >= 3:
    #         polygon = self._rectangle_from_three_points(points[0], points[1], points[2])
    #         self.node_shapes[self.active_node].append({"type": "rect", "points": polygon})
    #     elif tool_name == "圆" and len(points) >= 2:
    #         center = points[0]
    #         radius_point = points[1]
    #         cx, cy, radius = self._circle_from_two_points(center, radius_point)
    #         self.node_shapes[self.active_node].append({"type": "circle", "center": (cx, cy), "radius": radius})
    #     elif tool_name == "多边形" and len(points) >= 2:
    #         polygon = self._make_polygon_points(points[0], points[1], 6)
    #         if polygon:
    #             self.node_shapes[self.active_node].append({"type": "polygon", "points": polygon})

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

        # 预览逻辑：
        # 1) 若拍位正好在某节点起始拍，直接显示该节点。
        # 2) 若拍位位于两节点之间，显示左节点为 ghost，当前层显示线性插值结果。
        node_at_beat = self._node_index_at_beat(self.preview_beat)
        if node_at_beat is not None:
            preview_node = node_at_beat
            if preview_node > 0:
                prev_points = self.node_points.get(preview_node - 1, [])
                for point in prev_points:
                    self._draw_point_item(point, ghost=True, draw_label=False)
            current_points = self.node_points.get(preview_node, [])
        else:
            segment = self._segment_for_beat(self.preview_beat)
            if segment is not None:
                left, right = segment
                prev_points = self.node_points.get(left, [])
                for point in prev_points:
                    self._draw_point_item(point, ghost=True, draw_label=False)
                current_points = self._interpolate_points_at_beat(left, right, self.preview_beat)
            else:
                if self.active_node > 0:
                    prev_points = self.node_points.get(self.active_node - 1, [])
                    for point in prev_points:
                        self._draw_point_item(point, ghost=True, draw_label=False)
                current_points = self.node_points.get(self.active_node, [])

        for point in current_points:
            self._draw_point_item(point, ghost=False, draw_label=True)

        if self._draft_tool_name:
            self._draw_draft_overlay()
        else:
            self._clear_draft_items()
            self._draw_pending_reference_preview()
            self._draw_pending_reference_points()

    def _draw_point_item(self, point: dict, ghost: bool, draw_label: bool):
        pos = self._field_to_scene(point["x"], point["y"])
        radius = 5.0

        if ghost:
            item = QGraphicsEllipseItem(pos.x() - radius, pos.y() - radius, radius * 2, radius * 2)
            item.setPen(QPen(QColor(60, 60, 60, 110), 1))
            item.setBrush(QBrush(QColor(80, 80, 80, 70)))
            self._previous_items.append(item)
        else:
            item = PerformerPointItem(
                point_id=point["id"],
                center_scene_pos=pos,
                moved_callback=self._on_performer_point_moved,
                released_callback=self._on_performer_point_released,
                can_drag_callback=self._can_drag_performer_point,
                selected=point["id"] in self._selected_point_ids,
                size=radius * 2,
            )
            self._current_items.append(item)
            self._point_items_by_id[int(point["id"])] = item
        self.addItem(item)

        if draw_label:
            label = QGraphicsSimpleTextItem(str(point["id"]))
            label.setBrush(QBrush(QColor("#1f1f1f")))
            label.setPos(pos.x() + 6, pos.y() - 14)
            self.addItem(label)
            self._label_items.append(label)
            self._label_items_by_id[int(point["id"])] = label

    def _position_occupied(self, x: float, y: float) -> bool:
        """判断当前图是否已有同位置点位。"""
        for point in self.node_points.get(self.active_node, []):
            if abs(point["x"] - x) < 1e-9 and abs(point["y"] - y) < 1e-9:
                return True
        return False

    # def _snap_scene_point(self, scene_pos: QPointF) -> QPointF:
    #     """把场景坐标吸附到最近网格交点。"""
    #     # 历史辅助方法：当前直接调用 _scene_to_field + _snap_field_point 组合，无调用方。
    #     x, y = self._scene_to_field(scene_pos)
    #     x, y = self._snap_field_point(x, y)
    #     return self._field_to_scene(x, y)

    def _scene_item_under_cursor(self, scene_pos: QPointF):
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

            if self.active_tool == "框选" and isinstance(item, PerformerPointItem):
                self._selected_point_ids = {item.point_id}
                self._refresh_point_selection_visuals()
                self._clear_selection_rect()
                super().mousePressEvent(event)
                return

            if self.active_tool == "框选":
                self._selection_start_scene = QPointF(event.scenePos())
                self._selection_current_scene = QPointF(event.scenePos())
                self._selected_point_ids.clear()
                self._refresh_point_selection_visuals()
                self._update_selection_rect_item()
                event.accept()
                return

        if event.button() == Qt.MouseButton.LeftButton and self._is_drawing_tool():
            # 绘图点击生成的是“参考点”，参考点始终吸附到格线；
            # 自动生成的点位仅在确认后写入，不在这里二次吸附。
            # if not self._is_current_beat_editable():
            #     event.accept()
            #     return

            x, y = self._scene_to_field(event.scenePos())
            x, y = self._snap_field_point(x, y)

            self._handle_draw_tool(self.active_tool, (x, y))
            self._render_points_for_active_node()

            event.accept()
            return

        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.active_tool == "框选" and self._selection_start_scene is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self._selection_current_scene = QPointF(event.scenePos())
            self._update_selection_rect_item()
            event.accept()
            return

        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.active_tool == "框选":
            if self._selection_start_scene is not None:
                self._selection_current_scene = QPointF(event.scenePos())
                scene_rect = QRectF(self._selection_start_scene, self._selection_current_scene).normalized()
                self._select_points_in_scene_rect(scene_rect)
                self._clear_selection_rect()
                event.accept()
                return

        super().mouseReleaseEvent(event)

