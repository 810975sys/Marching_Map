# scheme_scene.py
"""
自定义场地场景，负责网格与场地的绘制。
"""
from PyQt6.QtWidgets import QGraphicsScene
from PyQt6.QtCore import QRectF, Qt
from field_settings import FieldSettings, GridRenderer

class SchemeScene(QGraphicsScene):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.field_settings = FieldSettings(self)
        self.grid_renderer = GridRenderer(self.field_settings)
        self.field_settings.changed.connect(self.update)

    def drawBackground(self, painter, rect):
        self.grid_renderer.draw_background_grid(painter, rect)
        self.grid_renderer.draw_field_lines(painter)
        self.grid_renderer.draw_field_labels(painter)

    # def auto_scale_to_viewport(self, view_size, margin=20):
    #     """
    #     根据视图像素尺寸自动调整scale，使场地完整显示。
    #     :param view_size: QSize 或 (width, height) 元组
    #     :param margin: 边距像素
    #     """
    #     w = self.field_settings.field_width
    #     h = self.field_settings.field_height
    #     if hasattr(view_size, 'width') and hasattr(view_size, 'height'):
    #         width = view_size.width()
    #         height = view_size.height()
    #     else:
    #         width, height = view_size
    #     scale_x = (width - margin * 2) / w
    #     scale_y = (height - margin * 2) / h
    #     scale = min(scale_x, scale_y)
    #     self.field_settings.set_scale(scale)
    #     self.update()

