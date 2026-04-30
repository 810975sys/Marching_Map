# field_settings.py
"""
场地与网格模块
- FieldSettings: 存储网格和场地参数
- GridRenderer: 根据设置绘制网格和数字
"""
from PyQt6.QtCore import QObject, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPen, QFont, QPainter

SCALE_MIN = 10
SCALE_MAX = 100
ZOOM_PERCENT_FACTOR = 5
ZOOM_PERCENT_MIN = SCALE_MIN * ZOOM_PERCENT_FACTOR
ZOOM_PERCENT_MAX = SCALE_MAX * ZOOM_PERCENT_FACTOR

class FieldSettings(QObject):
    """场地参数模型。

    负责统一存储网格、场地尺寸、坐标显示与缩放偏移，
    并通过 `changed` 信号通知视图重绘。
    """

    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        # 网格参数
        self.bg_grid_color = QColor(128, 255, 255)  # 背景网格颜色
        self.bg_grid_width = 1  # 背景网格线宽
        self.field_line_color = QColor(128, 128, 128)  # 行进场地经纬线颜色
        self.field_line_width = 2  # 行进场地经纬线线宽
        self.bold_interval = 8  # 每8条经纬线绘制一条场地线

        # 场地参数
        self.field_width = 40   # 场地长度（米）
        self.field_height = 30  # 场地宽度（米）
        self.scale = 22         # 显示缩放比例（像素/米）
        self.offset = QPointF(0, 0) # 画布偏移量（像素）
        self.unit = 5           # 相邻场地格线间距（米）
        self.grid_step = self.unit/self.bold_interval    # 网格绘制间距（米）
        
        # 坐标参数
        self.label_abs = True   # 坐标显示绝对值（True）还是相对值（False）
        self.label_zoom = 1    # 坐标字体大小（pt）（与缩放值共同决定字体实际像素大小）
        
        self.top_display = (True, 0)    # 上侧 横坐标显示 (是否显示，是否翻转)
        self.bottom_display = (True, 0) # 下侧 横坐标显示
        self.label_y_offset = -15       # 上下侧 横坐标偏移量，调整坐标距离边线的距离，单位像素
        self.label_y_cnt = 4            # 上下侧 横坐标显示数量（单侧，从0开始计数，另一边对称）
        self.label_y_zero_index = 4     # 从左起第几条场地线为0线（纵向）
        
        self.left_display = (True, 0)   # 左侧 纵坐标显示
        self.right_display = (True, 0)  # 右侧 纵坐标显示
        self.label_x_offset = -5        # 左右侧 纵坐标偏移量，调整坐标距离边线的距离，单位像素
        self.label_x_cnt = 3            # 左右侧 纵坐标显示数量（单侧，从0开始计数，另一边对称）
        self.label_x_zero_index = 3     # 从上起第几条场地线为0线（横向）
        self.label_y_zero_step = self.label_y_zero_index * self.bold_interval
        self.label_x_zero_step = self.label_x_zero_index * self.bold_interval

    @staticmethod
    def _parse_color(value, fallback: QColor) -> QColor:
        """把字符串颜色值解析为 `QColor`，失败则回退到默认值。"""
        if isinstance(value, str):
            color = QColor(value)
            if color.isValid():
                return color
        return QColor(fallback)

    @staticmethod
    def _parse_display_tuple(value, fallback: tuple[bool, int]) -> tuple[bool, int]:
        """解析四侧显示配置：(是否显示, 是否翻转)。"""
        if isinstance(value, (list, tuple)) and len(value) >= 2:
            return (bool(value[0]), int(bool(value[1])))
        if isinstance(value, bool):
            return (value, fallback[1])
        return fallback

    def _emit_changed(self):
        """统一触发配置变更信号。"""
        self.changed.emit()

    def _clamp_zero_step(self, step: int, limit: int) -> int:
        return max(0, min(limit, int(step)))

    def _zero_step_limit_x(self) -> int:
        return int(round(self.field_width / self.grid_step))

    def _zero_step_limit_y(self) -> int:
        return int(round(self.field_height / self.grid_step))

    @staticmethod
    def format_value(value: float) -> str:
        if abs(value - round(value)) < 1e-6:
            return str(int(round(value)))
        return f"{value:.3f}".rstrip("0").rstrip(".")

    @property
    def field_rect(self):
        # 动态计算当前场地矩形（米）
        w, h = self.field_width, self.field_height
        return QRectF(-w/2, -h/2, w, h)

    def to_dict(self) -> dict:
        """序列化为可持久化字典。"""
        return {
            "bg_grid_color": self.bg_grid_color.name(),
            "bg_grid_width": self.bg_grid_width,
            "field_line_color": self.field_line_color.name(),
            "field_line_width": self.field_line_width,
            "bold_interval": self.bold_interval,
            "field_width": self.field_width,
            "field_height": self.field_height,
            "label_abs": self.label_abs,
            "label_zoom": self.label_zoom,
            "top_display": [bool(self.top_display[0]), int(bool(self.top_display[1]))],
            "bottom_display": [bool(self.bottom_display[0]), int(bool(self.bottom_display[1]))],
            "left_display": [bool(self.left_display[0]), int(bool(self.left_display[1]))],
            "right_display": [bool(self.right_display[0]), int(bool(self.right_display[1]))],
            "label_y_offset": self.label_y_offset,
            "label_x_offset": self.label_x_offset,
            "label_y_cnt": self.label_y_cnt,
            "label_x_cnt": self.label_x_cnt,
            "label_y_zero_step": self.label_y_zero_step,
            "label_x_zero_step": self.label_x_zero_step,
        }

    def load_from_dict(self, data: dict):
        """从持久化字典恢复参数，并进行必要的边界修正。"""
        if not isinstance(data, dict):
            raise ValueError("场地设置文件格式无效")

        self.bg_grid_color = self._parse_color(data.get("bg_grid_color"), self.bg_grid_color)
        self.bg_grid_width = max(1, int(data.get("bg_grid_width", self.bg_grid_width)))
        self.field_line_color = self._parse_color(data.get("field_line_color"), self.field_line_color)
        self.field_line_width = max(1, int(data.get("field_line_width", self.field_line_width)))

        bold_interval = int(data.get("bold_interval", self.bold_interval))
        self.bold_interval = max(1, bold_interval)
        self.grid_step = self.unit / self.bold_interval

        field_width = int(data.get("field_width", self.field_width))
        field_height = int(data.get("field_height", self.field_height))
        self.field_width = max(5, int(round(field_width / 5)) * 5)
        self.field_height = max(5, int(round(field_height / 5)) * 5)

        self.label_abs = bool(data.get("label_abs", self.label_abs))
        self.label_zoom = max(0.1, float(data.get("label_zoom", self.label_zoom)))

        self.top_display = self._parse_display_tuple(data.get("top_display"), self.top_display)
        self.bottom_display = self._parse_display_tuple(data.get("bottom_display"), self.bottom_display)
        self.left_display = self._parse_display_tuple(data.get("left_display"), self.left_display)
        self.right_display = self._parse_display_tuple(data.get("right_display"), self.right_display)

        self.label_y_offset = int(data.get("label_y_offset", self.label_y_offset))
        self.label_x_offset = int(data.get("label_x_offset", self.label_x_offset))
        self.label_y_cnt = max(0, int(data.get("label_y_cnt", self.label_y_cnt)))
        self.label_x_cnt = max(0, int(data.get("label_x_cnt", self.label_x_cnt)))

        self.label_y_zero_step = self._clamp_zero_step(
            int(data.get("label_y_zero_step", self.label_y_zero_step)),
            self._zero_step_limit_x(),
        )
        self.label_x_zero_step = self._clamp_zero_step(
            int(data.get("label_x_zero_step", self.label_x_zero_step)),
            self._zero_step_limit_y(),
        )
        self.label_y_zero_index = self.label_y_zero_step / self.bold_interval
        self.label_x_zero_index = self.label_x_zero_step / self.bold_interval

        self._emit_changed()

    def set_field_size(self, width: int, height: int):
        """设置场地长宽（按 5 米网格对齐）。"""
        self.field_width = max(5, int(round(width / 5)) * 5)
        self.field_height = max(5, int(round(height / 5)) * 5)
        self.label_y_zero_step = self._clamp_zero_step(self.label_y_zero_step, self._zero_step_limit_x())
        self.label_x_zero_step = self._clamp_zero_step(self.label_x_zero_step, self._zero_step_limit_y())
        self._emit_changed()

    def set_center(self, x: float, y: float):
        self.center = QPointF(x, y)

    def set_scale(self, scale: float):
        """设置缩放比例（受全局最小/最大值约束）。"""
        self.scale = max(SCALE_MIN, min(SCALE_MAX, scale))
        self._emit_changed()

    def set_offset(self, x: float, y: float):
        """设置画布偏移（像素）。"""
        self.offset = QPointF(x, y)
        self._emit_changed()

    def set_grid_step(self, step: float):
        self.grid_step = step
        self._emit_changed()

    # 视觉参数接口
    def set_bg_grid_color(self, color: QColor):
        self.bg_grid_color = color
        self._emit_changed()

    def set_bg_grid_width(self, width: int):
        self.bg_grid_width = width
        self._emit_changed()

    def set_field_line_color(self, color: QColor):
        self.field_line_color = color
        self._emit_changed()

    def set_field_line_width(self, width: int):
        self.field_line_width = width
        self._emit_changed()

    def set_bold_interval(self, interval: int):
        self.bold_interval = interval
        self.grid_step = self.unit / self.bold_interval
        self.label_y_zero_step = self._clamp_zero_step(self.label_y_zero_step, self._zero_step_limit_x())
        self.label_x_zero_step = self._clamp_zero_step(self.label_x_zero_step, self._zero_step_limit_y())
        self._emit_changed()

    def set_label_abs(self, enabled: bool):
        self.label_abs = enabled
        self._emit_changed()

    def set_label_zoom(self, zoom: float):
        self.label_zoom = max(0.1, float(zoom))
        self._emit_changed()

    def set_display_flags(self, top: bool, bottom: bool, left: bool, right: bool):
        self.top_display = (top, self.top_display[1])
        self.bottom_display = (bottom, self.bottom_display[1])
        self.left_display = (left, self.left_display[1])
        self.right_display = (right, self.right_display[1])
        self._emit_changed()

    def set_label_offsets(self, y_offset: int, x_offset: int):
        self.label_y_offset = int(y_offset)
        self.label_x_offset = int(x_offset)
        self._emit_changed()

    def set_label_counts(self, y_count: int, x_count: int):
        self.label_y_cnt = max(0, int(y_count))
        self.label_x_cnt = max(0, int(x_count))
        self._emit_changed()

    def set_label_y_zero_step(self, step: int):
        self.label_y_zero_step = self._clamp_zero_step(step, self._zero_step_limit_x())
        self.label_y_zero_index = self.label_y_zero_step / self.bold_interval
        self._emit_changed()

    def set_label_x_zero_step(self, step: int):
        self.label_x_zero_step = self._clamp_zero_step(step, self._zero_step_limit_y())
        self.label_x_zero_index = self.label_x_zero_step / self.bold_interval
        self._emit_changed()
    
class GridRenderer:
    """网格绘制器：根据 `FieldSettings` 绘制背景网格、粗线与坐标标签。"""

    def __init__(self, field_settings: FieldSettings):
        self.settings = field_settings

    @staticmethod
    def _crisp_pixel(value: float, pen_width: float) -> float:
        """将轴对齐线条吸附到更稳定的像素位置。"""
        if int(round(pen_width)) & 1 == 1:
            return round(value) + 0.5
        return round(value)

    def draw_background_grid(self, painter: QPainter, scene_rect: QRectF):
        """绘制细网格背景。"""
        s = self.settings
        painter.save()
        pen = QPen(s.bg_grid_color, s.bg_grid_width)
        pen.setCosmetic(True)
        painter.setPen(pen)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        step = s.grid_step * s.scale
        offset_x = s.offset.x()
        offset_y = s.offset.y()
        # 以场地左上角为基准，计算第一个纵向/横向网格线的像素位置
        field_left_px = s.field_rect.left() * s.scale + offset_x
        field_top_px = s.field_rect.top() * s.scale + offset_y
        left = scene_rect.left()
        right = scene_rect.right()
        top = scene_rect.top()
        bottom = scene_rect.bottom()
        # 纵向网格线
        x0 = field_left_px
        # 找到第一个>=left的网格线
        x = x0 + ((left - x0) // step) * step
        if x < left:
            x += step
        while x <= right:
            x_draw = self._crisp_pixel(x, s.bg_grid_width)
            painter.drawLine(QPointF(x_draw, top), QPointF(x_draw, bottom))
            x += step
        # 横向网格线
        y0 = field_top_px
        y = y0 + ((top - y0) // step) * step
        if y < top:
            y += step
        while y <= bottom:
            y_draw = self._crisp_pixel(y, s.bg_grid_width)
            painter.drawLine(QPointF(left, y_draw), QPointF(right, y_draw))
            y += step
        painter.restore()

    def draw_field_lines(self, painter: QPainter):
        """绘制场地粗经纬线。"""
        s = self.settings
        painter.save()
        offset_x = s.offset.x()
        offset_y = s.offset.y()
        # 纵向经线
        x = s.field_rect.left()
        right = s.field_rect.right()
        idx = 0
        while x <= right + 1e-6:
            if idx % s.bold_interval == 0:
                pen = QPen(s.field_line_color, s.field_line_width)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                x_draw = self._crisp_pixel(x * s.scale + offset_x, s.field_line_width)
                y_top = self._crisp_pixel(s.field_rect.top() * s.scale + offset_y, 1)
                y_bottom = self._crisp_pixel(s.field_rect.bottom() * s.scale + offset_y, 1)
                painter.drawLine(QPointF(x_draw, y_top), QPointF(x_draw, y_bottom))
            x += s.grid_step
            idx += 1
        # 横向纬线
        y = s.field_rect.top()
        bottom = s.field_rect.bottom()
        idx = 0
        while y <= bottom + 1e-6:
            if idx % s.bold_interval == 0:
                pen = QPen(s.field_line_color, s.field_line_width)
                pen.setCosmetic(True)
                painter.setPen(pen)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)
                y_draw = self._crisp_pixel(y * s.scale + offset_y, s.field_line_width)
                x_left = self._crisp_pixel(s.field_rect.left() * s.scale + offset_x, 1)
                x_right = self._crisp_pixel(s.field_rect.right() * s.scale + offset_x, 1)
                painter.drawLine(QPointF(x_left, y_draw), QPointF(x_right, y_draw))
            y += s.grid_step
            idx += 1
        painter.restore()

    def draw_field_labels(self, painter: QPainter):
        """绘制四侧坐标标签。"""
        s = self.settings
        painter.save()
        font = QFont()
        font.setPointSize(round(s.label_zoom * s.scale))  # 字体大小随缩放调整
        painter.setFont(font)
        # 只在粗线（场地经纬线）处显示坐标数字，且数字中心与线对齐
        metrics = painter.fontMetrics()
        offset_x = s.offset.x()
        offset_y = s.offset.y()
        # label_y_offset 随 scale 适配，基准scale=18
        base_offset = s.label_y_offset
        offset_scale = s.scale / 18 if s.scale > 0 else 1
        label_y_offset = base_offset * offset_scale
        # 上下数字（纵向粗线），0线可指定
        zero_x = s.field_rect.left() + s.label_y_zero_step * s.grid_step
        for k in range(s.label_y_cnt + 1):
            for sign in (-1, 1):
                x = zero_x + sign * k * s.bold_interval * s.grid_step
                if x < s.field_rect.left() - 1e-6 or x > s.field_rect.right() + 1e-6:
                    continue
                x_draw = x * s.scale + offset_x
                y_top = s.field_rect.top()*s.scale + label_y_offset + offset_y
                y_bottom = s.field_rect.bottom()*s.scale - label_y_offset + offset_y
                label_num = x - zero_x
                if s.label_abs:
                    label = FieldSettings.format_value(abs(label_num))
                else:
                    label = FieldSettings.format_value(label_num)
                text_width = metrics.horizontalAdvance(label)
                text_height = metrics.height()
                ascent = metrics.ascent()
                # descent = metrics.descent()  # 未参与计算，保留注释便于后续排版调整。
                # 上侧
                if s.top_display[0]:
                    if s.top_display[1]:  # 翻转
                        painter.save()
                        painter.translate(x_draw, y_top)
                        painter.rotate(180)
                        painter.drawText(QPointF(-text_width/2, ascent - text_height/2), label)
                        painter.restore()
                    else:
                        painter.drawText(QPointF(x_draw - text_width/2, y_top + ascent - text_height/2), label)
                # 下侧
                if s.bottom_display[0]:
                    if s.bottom_display[1]:  # 翻转
                        painter.save()
                        painter.translate(x_draw, y_bottom)
                        painter.rotate(180)
                        painter.drawText(QPointF(-text_width/2, ascent - text_height/2), label)
                        painter.restore()
                    else:
                        painter.drawText(QPointF(x_draw - text_width/2, y_bottom + ascent - text_height/2), label)

        # 左右数字（横向粗线），0线可指定
        zero_y = s.field_rect.top() + s.label_x_zero_step * s.grid_step
        for k in range(s.label_x_cnt + 1):
            for sign in (-1, 1):
                y = zero_y + sign * k * s.bold_interval * s.grid_step
                if y < s.field_rect.top() - 1e-6 or y > s.field_rect.bottom() + 1e-6:
                    continue
                y_draw = y * s.scale + offset_y
                x_left = s.field_rect.left()*s.scale + s.label_x_offset + offset_x
                x_right = s.field_rect.right()*s.scale - s.label_x_offset + offset_x
                label_num = y - zero_y
                if s.label_abs:
                    text = FieldSettings.format_value(abs(label_num))
                else:
                    text = FieldSettings.format_value(label_num)
                text_width = metrics.horizontalAdvance(text)
                text_height = metrics.height()
                ascent = metrics.ascent()
                # descent = metrics.descent()  # 未参与计算，保留注释便于后续排版调整。
                # 左侧
                if s.left_display[0]:
                    if s.left_display[1]:  # 翻转
                        painter.save()
                        painter.translate(x_left, y_draw)
                        painter.rotate(180)
                        painter.drawText(QPointF(-text_width, ascent - text_height/2), text)
                        painter.restore()
                    else:
                        painter.drawText(QPointF(x_left - text_width, y_draw + ascent - text_height/2), text)
                # 右侧
                if s.right_display[0]:
                    if s.right_display[1]:  # 翻转
                        painter.save()
                        painter.translate(x_right, y_draw)
                        painter.rotate(180)
                        painter.drawText(QPointF(0, ascent - text_height/2), text)
                        painter.restore()
                    else:
                        painter.drawText(QPointF(x_right, y_draw + ascent - text_height/2), text)
        painter.restore()

    @staticmethod
    def snap_to_grid(pos: QPointF, field_settings: FieldSettings) -> QPointF:
        # 吸附网格点（offset不影响吸附，保持原有逻辑）
        step = field_settings.grid_step * field_settings.scale
        x = round(pos.x() / step) * step
        y = round(pos.y() / step) * step
        return QPointF(x, y)
