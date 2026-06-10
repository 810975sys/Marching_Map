"""
独立的几何与采样辅助函数，均为无状态（不依赖 self）的实现。
"""
import math
from typing import List, Tuple
from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QPainterPath

def _distance(p1: tuple[float, float], p2: tuple[float, float]) -> float:
    return math.hypot(p2[0] - p1[0], p2[1] - p1[1])

# def _dedupe_points(points: List[tuple[float, float]]) -> List[tuple[float, float]]:
#     """根据坐标值去重，避免重复点位导致的图元重叠与性能问题。"""
#     unique: List[tuple[float, float]] = []
#     seen = set()
#     for x, y in points:
#         key = (round(x, 6), round(y, 6))
#         if key in seen:
#             continue
#         seen.add(key)
#         unique.append((x, y))
#     return unique

def _sample_line_points_with_count(p1: tuple[float, float], p2: tuple[float, float], spacing: float, point_count: int) -> List[tuple[float, float]]:
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

def _sample_polyline_points(points: List[tuple[float, float]], spacing: float) -> List[tuple[float, float]]:
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

def _sample_polyline_points_with_count(points: List[tuple[float, float]], point_count: int) -> List[tuple[float, float]]:
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

def _sample_polyline_points_with_count_and_spacing(points: List[tuple[float, float]], point_count: int, spacing: float) -> List[tuple[float, float]]:
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

def _sample_curve_points(points: List[tuple[float, float]], spacing: float) -> List[tuple[float, float]]:
    """基于 Catmull-Rom 样条生成平滑曲线并按 spacing 重新等距采样（返回 field 坐标点）。"""
    dense = _build_dense_curve_points(points, spacing)
    if len(dense) < 2:
        return dense[:]
    return _sample_polyline_points(dense, spacing)

def _build_dense_curve_points(points: List[tuple[float, float]], spacing_hint: float) -> List[tuple[float, float]]:
    """基于 Catmull-Rom 样条生成密集曲线点（返回 field 坐标点）。"""
    if len(points) < 2:
        return points[:]
    dense: List[tuple[float, float]] = []
    n = len(points)
    for i in range(n - 1):
        p0 = points[i - 1] if i - 1 >= 0 else points[i]
        p1 = points[i]
        p2 = points[i + 1]
        p3 = points[i + 2] if i + 2 < n else points[i + 1]

        seg_len = max(1e-9, _distance(p1, p2))
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

def _sample_closed_polyline_points_with_spacing(points: List[tuple[float, float]], spacing: float) -> List[tuple[float, float]]:
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

def _sample_closed_polyline_points_with_count(points: List[tuple[float, float]], point_count: int) -> List[tuple[float, float]]:
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

def _make_polygon_points(center: tuple[float, float], radius_point: tuple[float, float], sides: int) -> List[tuple[float, float]]:
    """根据中心点、半径点和边数，计算正多边形的顶点坐标。中心点和半径点定义了多边形的大小和初始方向，边数决定了多边形的形状。返回一个包含所有顶点坐标的列表。如果半径过小（小于等于 1e-9），则返回一个空列表；如果边数不足 2，则自动修正为至少 2。"""
    cx, cy = center
    rx, ry = radius_point
    radius = math.hypot(rx - cx, ry - cy)
    if radius <= 1e-9:
        return []
    count = max(2, int(sides))
    start_angle = math.atan2(ry - cy, rx - cx)
    points: List[tuple[float, float]] = []
    for index in range(count):
        angle = start_angle + 2 * math.pi * index / count
        points.append((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return points

def _circle_from_two_points(center: tuple[float, float], radius_point: tuple[float, float]) -> tuple[float, float, float]:
    """根据中心点和半径点，计算圆的参数（中心坐标和半径）。中心点定义了圆心的位置，半径点定义了圆的大小。返回一个包含圆心坐标和半径的元组。如果半径过小（小于等于 1e-9），则半径会被修正为 0。"""
    cx, cy = center
    rx, ry = radius_point
    radius = math.hypot(rx - cx, ry - cy)
    return cx, cy, radius

# def _rectangle_from_three_points(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float]) -> List[tuple[float, float]]:
#     """根据三个点的坐标，计算矩形的四个顶点坐标。"""
#     ax, ay = a
#     bx, by = b
#     cx, cy = c
#     dx = bx + (cx - ax)
#     dy = by + (cy - ay)
#     return [a, b, (dx, dy), c]

def _circumcenter(p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float]) -> tuple[float, float] | None:
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

def _arc_path_from_three_points(start: tuple[float, float], through: tuple[float, float], end: tuple[float, float]) -> QPainterPath:
    """根据起点、过渡点和终点，计算通过这三个点的圆弧路径。首先计算三点的外心作为圆心，然后根据圆心和起点计算半径，最后根据起点、过渡点和终点计算起始角度、过渡角度和结束角度，并确定弧线的方向（顺时针或逆时针）。返回一个 QPainterPath 对象表示该圆弧路径。如果三点共线，则返回一条连接起点、过渡点和终点的折线路径。"""
    center = _circumcenter(start, through, end)
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

def _sample_circle_points(center: tuple[float, float], radius_point: tuple[float, float], spacing: float) -> list[tuple[float, float]]:
    """圆绘制点位预览"""
    cx, cy, radius = _circle_from_two_points(center, radius_point)
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

def _sample_circle_points_with_count(center: tuple[float, float], radius_point: tuple[float, float], point_count: int) -> list[tuple[float, float]]:
    """圆绘制点位预览（按点位数量采样）"""
    cx, cy, radius = _circle_from_two_points(center, radius_point)
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

def _sample_arc_points(start: tuple[float, float], through: tuple[float, float], end: tuple[float, float], spacing: float) -> list[tuple[float, float]]:
    """弧绘制点位预览，基于三点确定的圆弧生成点位。"""
    center = _circumcenter(start, through, end)
    if center is None:
        # 退化为折线时，按整段折线连续等距采样（只保证起点落点）。
        return _sample_polyline_points([start, through, end], spacing)

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

def _sample_arc_points_with_count(start: tuple[float, float], through: tuple[float, float], end: tuple[float, float], point_count: int) -> list[tuple[float, float]]:
    """弧绘制点位预览，基于三点确定的圆弧生成点位（按点位数量采样）。"""
    center = _circumcenter(start, through, end)
    if center is None:
        count = max(1, int(point_count))
        if count == 1:
            return [start]
        total_length = _distance(start, through) + _distance(through, end)
        spacing = max(1e-9, total_length / (count - 1))
        return _sample_polyline_points([start, through, end], spacing)

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

def _sample_arc_points_with_count_and_spacing(start: tuple[float, float], through: tuple[float, float], end: tuple[float, float], point_count: int, spacing: float) -> list[tuple[float, float]]:
    """按起点开始、固定间隔和固定个数采样弧：
    - 从 start 出发，每隔 spacing 放一个点，直到达到 point_count。
    - 若弧长不足以放下所有点，超出部分沿终点处切线方向延申。
    返回 field 单位坐标点列表。
    """
    count = max(1, int(point_count))
    spacing = max(1e-9, float(spacing))

    center = _circumcenter(start, through, end)
    if center is None:
        # 退化为折线：重用折线按个数与间隔采样的实现
        return _sample_polyline_points_with_count_and_spacing([start, through, end], count, spacing)

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

def _sample_rectangle_fill_points_with_counts(a: tuple[float, float], b: tuple[float, float], c: tuple[float, float], spacing_base: float, spacing_shift: float, base_point_count: int, shift_point_count: int) -> list[tuple[float, float]]:
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

    base_line = _sample_line_points_with_count(a, b, spacing_base, base_point_count)
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


def _enforce_sampling_auto_rule(tool_name: str | None, state: dict, changed: str | None = None):
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

def _enforce_sampling_shift_auto_rule(state: dict, changed: str | None = None):
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


def _append_unique_reference_point(target: list[tuple[float, float]], field_point: tuple[float, float]) -> bool:
    x, y = field_point
    for px, py in target:
        if abs(px - x) < 1e-9 and abs(py - y) < 1e-9:
            return False
    target.append(field_point)
    return True

def _bilinear_point(corners: list[tuple[float, float]], u: float, v: float) -> tuple[float, float]:
    c0, c1, c2, c3 = corners
    x = (
        c0[0] * (1.0 - u) * (1.0 - v)
        + c1[0] * u * (1.0 - v)
        + c2[0] * u * v
        + c3[0] * (1.0 - u) * v
    )
    y = (
        c0[1] * (1.0 - u) * (1.0 - v)
        + c1[1] * u * (1.0 - v)
        + c2[1] * u * v
        + c3[1] * (1.0 - u) * v
    )
    return x, y

def _rotate_vector(x: float, y: float, angle_radians: float) -> tuple[float, float]:
    cos_a = math.cos(angle_radians)
    sin_a = math.sin(angle_radians)
    return x * cos_a - y * sin_a, x * sin_a + y * cos_a

def _field_rotate_point(point: tuple[float, float], center: tuple[float, float], angle_degrees: float) -> tuple[float, float]:
    """以指定中心点和角度旋转一个场地坐标点，返回旋转后的坐标。"""
    dx = point[0] - center[0]
    dy = point[1] - center[1]
    rx, ry = _rotate_vector(dx, dy, math.radians(float(angle_degrees)))
    return center[0] + rx, center[1] + ry

def sample_on_polyline(points, distance):
    """沿折线按距离采样"""
    if not points:
        return None
    if distance <= 0.0:
        return (float(points[0][0]), float(points[0][1]))
    cum_len = 0.0
    for i in range(len(points) - 1):
        x1, y1 = points[i]
        x2, y2 = points[i + 1]
        seg_len = math.hypot(x2 - x1, y2 - y1)
        if distance <= cum_len + seg_len + 1e-12:
            t = (distance - cum_len) / seg_len if seg_len > 0 else 0.0
            x = x1 + t * (x2 - x1)
            y = y1 + t * (y2 - y1)
            return (float(x), float(y))
        cum_len += seg_len
    # 超出总长则返回终点
    return (float(points[-1][0]), float(points[-1][1]))
