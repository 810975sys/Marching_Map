from PyQt6.QtCore import QPointF, QRectF
from PyQt6.QtGui import QFont, QPainter, QPen
from field_info import FieldInfo, format_value

def _crisp_pixel(value: float, pen_width: float) -> float:
    """将轴对齐线条吸附到更稳定的像素位置。"""
    if int(round(pen_width)) & 1 == 1:
        return round(value) + 0.5
    return round(value)

class GridRenderer:
    """网格绘制器：根据 `FieldInfo` 绘制背景网格、粗线与坐标标签。"""

    def __init__(self, field_info: FieldInfo):
        self.field_info = field_info

    def draw_background_grid(self, painter: QPainter, scene_rect: QRectF):
        """绘制细网格背景。"""
        s = self.field_info
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
            x_draw = _crisp_pixel(x, s.bg_grid_width)
            painter.drawLine(QPointF(x_draw, top), QPointF(x_draw, bottom))
            x += step
        # 横向网格线
        y0 = field_top_px
        y = y0 + ((top - y0) // step) * step
        if y < top:
            y += step
        while y <= bottom:
            y_draw = _crisp_pixel(y, s.bg_grid_width)
            painter.drawLine(QPointF(left, y_draw), QPointF(right, y_draw))
            y += step
        painter.restore()

    def draw_field_lines(self, painter: QPainter):
        """绘制场地粗经纬线。"""
        s = self.field_info
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
                x_draw = _crisp_pixel(x * s.scale + offset_x, s.field_line_width)
                y_top = _crisp_pixel(s.field_rect.top() * s.scale + offset_y, 1)
                y_bottom = _crisp_pixel(s.field_rect.bottom() * s.scale + offset_y, 1)
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
                y_draw = _crisp_pixel(y * s.scale + offset_y, s.field_line_width)
                x_left = _crisp_pixel(s.field_rect.left() * s.scale + offset_x, 1)
                x_right = _crisp_pixel(s.field_rect.right() * s.scale + offset_x, 1)
                painter.drawLine(QPointF(x_left, y_draw), QPointF(x_right, y_draw))
            y += s.grid_step
            idx += 1
        painter.restore()

    def draw_field_labels(self, painter: QPainter):
        """绘制四侧坐标标签。"""
        s = self.field_info
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
                    label = format_value(abs(label_num))
                else:
                    label = format_value(label_num)
                text_width = metrics.horizontalAdvance(label)
                text_height = metrics.height()
                ascent = metrics.ascent()
                # descent = metrics.descent()  # 未参与计算，保留注释便于后续排版调整。
                # 上侧
                if s.top_display != -1:
                    painter.save()
                    painter.translate(x_draw, y_top)
                    painter.rotate(s.top_display)  # 根据显示模式旋转文本
                    painter.drawText(QPointF(-text_width/2, ascent - text_height/2), label)
                    painter.restore()
                # 下侧
                if s.bottom_display != -1:
                    painter.save()
                    painter.translate(x_draw, y_bottom)
                    painter.rotate(s.bottom_display)  # 根据显示模式旋转文本
                    painter.drawText(QPointF(-text_width/2, ascent - text_height/2), label)
                    painter.restore()

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
                    text = format_value(abs(label_num))
                else:
                    text = format_value(label_num)
                text_width = metrics.horizontalAdvance(text)
                text_height = metrics.height()
                ascent = metrics.ascent()
                # descent = metrics.descent()  # 未参与计算，保留注释便于后续排版调整。
                # 左侧
                if s.left_display != -1:
                    painter.save()
                    painter.translate(x_left, y_draw)
                    painter.rotate(s.left_display)  # 根据显示模式旋转文本
                    painter.drawText(QPointF(-text_width, ascent - text_height/2), text)
                    painter.restore()
                # 右侧
                if s.right_display != -1:
                    painter.save()
                    painter.translate(x_right, y_draw)
                    painter.rotate(s.right_display)  # 根据显示模式旋转文本
                    painter.drawText(QPointF(0, ascent - text_height/2), text)
                    painter.restore()
        painter.restore()
