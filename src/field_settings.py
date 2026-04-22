# field_settings.py
"""
场地与网格模块
- FieldSettings: 存储网格和场地参数
- GridRenderer: 根据设置绘制网格和数字
"""
from PyQt6.QtCore import QObject, QPointF, QRectF
from PyQt6.QtGui import QColor, QPen, QFont, QPainter
from PyQt6.QtWidgets import QGraphicsScene

SCALE_MIN = 10
SCALE_MAX = 100
ZOOM_PERCENT_FACTOR = 5
ZOOM_PERCENT_MIN = SCALE_MIN * ZOOM_PERCENT_FACTOR
ZOOM_PERCENT_MAX = SCALE_MAX * ZOOM_PERCENT_FACTOR

class FieldSettings:
    def __init__(self):
        # 网格参数
        self.bg_grid_color = QColor(128, 255, 255)  # 背景网格颜色
        self.bg_grid_width = 1  # 背景网格线宽
        self.field_line_color = QColor(128, 128, 128)  # 行进场地经纬线颜色
        self.field_line_width = 2  # 行进场地经纬线线宽
        self.bold_interval = 8  # 每8条经纬线绘制一条场地线

        # 场地参数
        self.field_width = 40   # 场地宽度（米）
        self.field_height = 30  # 场地高度（米）
        self.scale = 22         # 显示缩放比例（像素/米）
        self.offset = QPointF(0, 0) # 画布偏移量（像素）
        self.unit = 5           # 相邻场地格线间距（米）
        self.interval = 8       # 场地线加粗间隔（格数），每8条经纬线加粗一条场地线
        self.grid_step = self.unit/self.interval    # 网格绘制间距（米）
        
        # 坐标参数
        self.label_abs = True   # 坐标显示绝对值（True）还是相对值（False）
        self.label_zoom = 1    # 坐标字体大小（pt）（与缩放值共同决定字体实际像素大小）
        
        self.top_display = (True, 0)    # 上侧坐标显示 (是否显示，是否翻转)
        self.bottom_display = (True, 0) # 下侧坐标显示
        self.label_y_offset = -15       # 上下坐标偏移量，调整坐标距离边线的距离，单位像素
        self.label_y_cnt = 4            # 上下坐标显示数量（单侧，从0开始计数，另一边对称）
        self.label_y_zero_index = 4     # 从左起第几条场地线为0线（纵向）
        
        self.left_display = (True, 0)   # 左侧坐标显示
        self.right_display = (True, 0)  # 右侧坐标显示
        self.label_x_offset = -5        # 左右坐标偏移量，调整坐标距离边线的距离，单位像素
        self.label_x_cnt = 4            # 左右坐标显示数量（单侧，从0开始计数，另一边对称）
        self.label_x_zero_index = 3     # 从上起第几条场地线为0线（横向）

    @property
    def field_rect(self):
        # 动态计算当前场地矩形（米）
        w, h = self.field_width, self.field_height
        return QRectF(-w/2, -h/2, w, h)

    def set_field_size(self, width: int, height: int):
        self.field_width = width
        self.field_height = height

    def set_center(self, x: float, y: float):
        self.center = QPointF(x, y)

    def set_scale(self, scale: float):
        self.scale = max(SCALE_MIN, min(SCALE_MAX, scale))

    def set_offset(self, x: float, y: float):
        self.offset = QPointF(x, y)

    def set_grid_step(self, step: float):
        self.grid_step = step

    # 视觉参数接口
    def set_bg_grid_color(self, color: QColor):
        self.bg_grid_color = color

    def set_bg_grid_width(self, width: int):
        self.bg_grid_width = width

    def set_field_line_color(self, color: QColor):
        self.field_line_color = color

    def set_field_line_width(self, width: int):
        self.field_line_width = width

    def set_bold_interval(self, interval: int):
        self.bold_interval = interval

    def set_label_orientation(self, top_normal: bool, left_normal: bool, bottom_rotated: bool, right_rotated: bool):
        self.top_label_normal = top_normal
        self.left_label_normal = left_normal
        self.bottom_label_rotated = bottom_rotated
        self.right_label_rotated = right_rotated

class GridRenderer:
    def __init__(self, field_settings: FieldSettings):
        self.settings = field_settings

    @staticmethod
    def _crisp_pixel(value: float, pen_width: float) -> float:
        """将轴对齐线条吸附到更稳定的像素位置。"""
        if int(round(pen_width)) & 1 == 1:
            return round(value) + 0.5
        return round(value)

    def draw_background_grid(self, painter: QPainter, scene_rect: QRectF):
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
        zero_x = s.field_rect.left() + s.label_y_zero_index * s.bold_interval * s.grid_step
        for k in range(s.label_y_cnt + 1):
            for sign in (-1, 1):
                x = zero_x + sign * k * s.bold_interval * s.grid_step
                if x < s.field_rect.left() - 1e-6 or x > s.field_rect.right() + 1e-6:
                    continue
                x_draw = x * s.scale + offset_x
                y_top = s.field_rect.top()*s.scale + label_y_offset + offset_y
                y_bottom = s.field_rect.bottom()*s.scale - label_y_offset + offset_y
                label_num = sign * k * s.unit
                if s.label_abs:
                    label = str(abs(label_num))
                else:
                    label = str(label_num)
                text_width = metrics.horizontalAdvance(label)
                text_height = metrics.height()
                ascent = metrics.ascent()
                descent = metrics.descent()
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
        zero_y = s.field_rect.top() + s.label_x_zero_index * s.bold_interval * s.grid_step
        for k in range(s.label_x_cnt + 1):
            for sign in (-1, 1):
                y = zero_y + sign * k * s.bold_interval * s.grid_step
                if y < s.field_rect.top() - 1e-6 or y > s.field_rect.bottom() + 1e-6:
                    continue
                y_draw = y * s.scale + offset_y
                x_left = s.field_rect.left()*s.scale + s.label_x_offset + offset_x
                x_right = s.field_rect.right()*s.scale - s.label_x_offset + offset_x
                label_num = sign * k * s.unit
                if s.label_abs:
                    text = str(abs(label_num))
                else:
                    text = str(label_num)
                text_width = metrics.horizontalAdvance(text)
                text_height = metrics.height()
                ascent = metrics.ascent()
                descent = metrics.descent()
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
