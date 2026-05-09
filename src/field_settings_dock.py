"""场地设置侧边面板。

主要职责：
1. 将 `FieldInfo` 的关键参数映射到可编辑控件。
2. 在用户修改控件时回写到 `FieldInfo`。
3. 在 `FieldInfo.changed` 触发时刷新 UI，保持双向同步。
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QColorDialog,
    QCheckBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from field_info import FieldInfo, format_value


class FieldSettingsDock(QDockWidget):
    """场地参数编辑面板（Dock 形式）。"""

    def __init__(self, parent=None):
        super().__init__("场地设置-修改", parent)
        self.setObjectName("fieldSettingsDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable    # 可关闭
            # | QDockWidget.DockWidgetFeature.DockWidgetMovable # 可移动
        )
        self.setMinimumWidth(360)

        # `_updating=True` 时说明正在程序化刷新控件，需屏蔽回写，避免循环触发。
        self._scene = None      # 绑定的场景对象，提供设置数据来源和回写接口。
        self._field = None   # 当前绑定的 `FieldInfo` 对象，直接从场景获取；仅在 `refresh_from_settings` 中更新值。
        self._updating = False  # 标志位：正在刷新控件时为 True，避免回写干扰；用户交互时为 False，允许回写生效。

        self.content = QWidget(self)    # 面板容器，所有控件都放在这里；外层是一个 `QScrollArea`，以支持小屏幕时滚动查看。
        self.rootLayout = QVBoxLayout(self.content) # 布局容器，垂直排列所有分区，底部有弹性空间。
        self.rootLayout.setContentsMargins(8, 8, 8, 8)
        self.rootLayout.setSpacing(10)

        self._build_ui()

        scroll = QScrollArea(self)  # 外层滚动区域，包裹内容容器；当内容过高时显示滚动条。
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)  # 去掉滚动区域的边框，使界面更简洁。
        scroll.setWidget(self.content)  # 设置滚动区域的内容容器为 `content`，所有控件都放在 `content` 中。
        self.setWidget(scroll)

    def _build_ui(self):
        """组装面板分区：网格、坐标显示、0线位置。"""
        self._build_grid_group()
        self._build_field_group()
        self._build_coordinate_group()
        self.rootLayout.addStretch(1)

    def bind_scene(self, scene):
        """绑定场景对象
        响应场地变化信号。"""
        self._scene = scene
        self._field = scene.field_info
        self._field.changed.connect(self.refresh_from_settings)
        self.refresh_from_settings()

    def _build_grid_group(self):
        """构建网格与场地尺寸相关控件。"""
        group = QGroupBox("网格与场地", self.content)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.bgColorButton = QPushButton("选择", group)
        self.bgColorButton.clicked.connect(self._choose_bg_color)
        form.addRow("背景网格颜色", self.bgColorButton)

        self.bgWidthSpin = QSpinBox(group)
        self.bgWidthSpin.setRange(1, 10)
        self.bgWidthSpin.setSingleStep(1)
        self.bgWidthSpin.valueChanged.connect(lambda value: self._apply("set_bg_grid_width", value))
        form.addRow("背景网格线宽", self.bgWidthSpin)

        self.fieldColorButton = QPushButton("选择", group)
        self.fieldColorButton.clicked.connect(self._choose_field_color)
        form.addRow("行进场地颜色", self.fieldColorButton)

        self.fieldWidthSpin = QSpinBox(group)
        self.fieldWidthSpin.setRange(1, 20)
        self.fieldWidthSpin.setSingleStep(1)
        self.fieldWidthSpin.valueChanged.connect(lambda value: self._apply("set_field_line_width", value))
        form.addRow("行进场地线宽", self.fieldWidthSpin)

        self.fieldLengthSpin = QSpinBox(group)
        self.fieldLengthSpin.setRange(5, 1000)
        self.fieldLengthSpin.setSingleStep(5)
        self.fieldLengthSpin.valueChanged.connect(self._apply_field_size)
        form.addRow("场地长度", self.fieldLengthSpin)

        self.fieldHeightSpin = QSpinBox(group)
        self.fieldHeightSpin.setRange(5, 1000)
        self.fieldHeightSpin.setSingleStep(5)
        self.fieldHeightSpin.valueChanged.connect(self._apply_field_size)
        form.addRow("场地宽度", self.fieldHeightSpin)

        self.rootLayout.addWidget(group)

    def _build_field_group(self):
        """构建坐标显示相关控件。"""
        group = QGroupBox("坐标显示", self.content)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.labelAbsCheck = QCheckBox("显示绝对值", group)
        self.labelAbsCheck.toggled.connect(lambda checked: self._apply("set_label_abs", checked))
        form.addRow("坐标正负", self.labelAbsCheck)

        self.labelZoomSpin = QDoubleSpinBox(group)
        self.labelZoomSpin.setRange(0.1, 10.0)
        self.labelZoomSpin.setSingleStep(0.1)
        self.labelZoomSpin.setDecimals(2)
        self.labelZoomSpin.valueChanged.connect(lambda value: self._apply("set_label_zoom", value))
        form.addRow("坐标字体大小", self.labelZoomSpin)

        display_row = QWidget(group)
        # display_layout3 = QVBoxLayout(display_row)
        display_layout = QHBoxLayout(display_row)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(8)
        # display_layout2 = QHBoxLayout(display_row)
        
        self.top_label_display = QSpinBox(display_row)
        self.bottom_label_display = QSpinBox(display_row)
        self.left_label_display = QSpinBox(display_row)
        self.right_label_display = QSpinBox(display_row)
        for checkbox in (
            self.top_label_display,
            self.bottom_label_display,
            self.left_label_display,
            self.right_label_display,
        ):
            checkbox.setRange(-1, 360)
            checkbox.setSingleStep(1)
            checkbox.valueChanged.connect(self._apply_display_flags)
            display_layout.addWidget(checkbox)
        display_layout.addStretch(1)  # 让四个开关靠左排列，右侧留空
        form.addRow("坐标角度", display_row)

        self.yOffsetSpin = QSpinBox(group)
        self.yOffsetSpin.setRange(-200, 200)
        self.yOffsetSpin.setSingleStep(1)
        self.yOffsetSpin.valueChanged.connect(self._apply_label_offsets)
        form.addRow("上下偏移量", self.yOffsetSpin)

        self.xOffsetSpin = QSpinBox(group)
        self.xOffsetSpin.setRange(-200, 200)
        self.xOffsetSpin.setSingleStep(1)
        self.xOffsetSpin.valueChanged.connect(self._apply_label_offsets)
        form.addRow("左右偏移量", self.xOffsetSpin)

        self.yCountSpin = QSpinBox(group)
        self.yCountSpin.setRange(0, 50)
        self.yCountSpin.setSingleStep(1)
        self.yCountSpin.valueChanged.connect(self._apply_label_counts)
        form.addRow("横坐标数量", self.yCountSpin)

        self.xCountSpin = QSpinBox(group)
        self.xCountSpin.setRange(0, 50)
        self.xCountSpin.setSingleStep(1)
        self.xCountSpin.valueChanged.connect(self._apply_label_counts)
        form.addRow("纵坐标数量", self.xCountSpin)

        self.rootLayout.addWidget(group)

    def _build_coordinate_group(self):
        """构建 0 线滑块控制区。"""
        group = QGroupBox("0线位置", self.content)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(10)

        self.zeroYSummary = QLabel(group)
        self.zeroYSlider = QSlider(Qt.Orientation.Horizontal, group)
        self.zeroYSlider.setTracking(True)
        self.zeroYSlider.valueChanged.connect(self._on_zero_y_changed)
        self.zeroYHint = QLabel("按 Shift 吸附到场地经纬线", group)
        self.zeroYHint.setStyleSheet("color: #666666;")

        self.zeroXSummary = QLabel(group)
        self.zeroXSlider = QSlider(Qt.Orientation.Horizontal, group)
        self.zeroXSlider.setTracking(True)
        self.zeroXSlider.valueChanged.connect(self._on_zero_x_changed)
        self.zeroXHint = QLabel("按 Shift 吸附到场地经纬线", group)
        self.zeroXHint.setStyleSheet("color: #666666;")

        layout.addWidget(QLabel("纵向 0 线（左右方向）", group))
        layout.addWidget(self.zeroYSlider)
        layout.addWidget(self.zeroYSummary)
        layout.addWidget(self.zeroYHint)
        layout.addSpacing(4)
        layout.addWidget(QLabel("横向 0 线（上下方向）", group))
        layout.addWidget(self.zeroXSlider)
        layout.addWidget(self.zeroXSummary)
        layout.addWidget(self.zeroXHint)

        self.rootLayout.addWidget(group)

    def _apply(self, method_name, value):
        """通用回写入口：根据方法名把值写入 `FieldInfo`。"""
        if self._field is None or self._updating:
            return
        getattr(self._field, method_name)(value)

    def _apply_field_size(self):
        """同步场地长宽。"""
        if self._field is None or self._updating:
            return
        self._field.set_field_size(self.fieldLengthSpin.value(), self.fieldHeightSpin.value())

    def _apply_display_flags(self):
        """同步四侧坐标开关。"""
        if self._field is None or self._updating:
            return
        self._field.set_label_display(
            self.top_label_display.value(),
            self.bottom_label_display.value(),
            self.left_label_display.value(),
            self.right_label_display.value(),
        )

    def _apply_label_offsets(self):
        """同步四侧坐标偏移。"""
        if self._field is None or self._updating:
            return
        self._field.set_label_offsets(self.yOffsetSpin.value(), self.xOffsetSpin.value())

    def _apply_label_counts(self):
        """同步四侧坐标数量。"""
        if self._field is None or self._updating:
            return
        self._field.set_label_counts(self.yCountSpin.value(), self.xCountSpin.value())

    def _choose_bg_color(self):
        """选择背景网格颜色。"""
        if self._field is None or self._updating:
            return
        color = QColorDialog.getColor(self._field.bg_grid_color, self, "选择背景网格颜色")
        if color.isValid():
            self._field.set_bg_grid_color(color)

    def _choose_field_color(self):
        """选择场地经纬线颜色。"""
        if self._field is None or self._updating:
            return
        color = QColorDialog.getColor(self._field.field_line_color, self, "选择行进场地颜色")
        if color.isValid():
            self._field.set_field_line_color(color)

    def _apply_color_button_style(self, button: QPushButton, color: QColor):
        """根据颜色亮度设置按钮前景色，保证可读性。"""
        brightness = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
        text_color = "#000000" if brightness > 160 else "#ffffff"
        button.setText(color.name().upper())
        button.setStyleSheet(
            f"background-color: {color.name()}; color: {text_color}; border: 1px solid #666666; padding: 4px 10px;"
        )

    def refresh_from_settings(self):
        """从 `FieldInfo` 拉取数据并刷新全部控件。"""
        if self._field is None:
            return
        s = self._field
        self._updating = True

        self._apply_color_button_style(self.bgColorButton, s.bg_grid_color)
        self._apply_color_button_style(self.fieldColorButton, s.field_line_color)

        self.bgWidthSpin.setValue(s.bg_grid_width)
        self.fieldWidthSpin.setValue(s.field_line_width)

        self.fieldLengthSpin.setValue(s.field_width)
        self.fieldHeightSpin.setValue(s.field_height)

        self.labelAbsCheck.setChecked(s.label_abs)
        self.labelZoomSpin.setValue(s.label_zoom)

        self.top_label_display.setValue(s.top_display)
        self.bottom_label_display.setValue(s.bottom_display)
        self.left_label_display.setValue(s.left_display)
        self.right_label_display.setValue(s.right_display)

        self.yOffsetSpin.setValue(s.label_y_offset)
        self.xOffsetSpin.setValue(s.label_x_offset)
        self.yCountSpin.setValue(s.label_y_cnt)
        self.xCountSpin.setValue(s.label_x_cnt)

        self.zeroYSlider.setRange(0, s._zero_step_limit_x())
        self.zeroXSlider.setRange(0, s._zero_step_limit_y())
        self.zeroYSlider.setSingleStep(1)
        self.zeroXSlider.setSingleStep(1)
        self.zeroYSlider.setPageStep(s.bold_interval)
        self.zeroXSlider.setPageStep(s.bold_interval)
        self.zeroYSlider.setValue(s.label_y_zero_step)
        self.zeroXSlider.setValue(s.label_x_zero_step)

        self.zeroYSummary.setText(
            f"当前位置：{format_value(s.label_y_zero_step * s.grid_step)}m"
        )
        self.zeroXSummary.setText(
            f"当前位置：{format_value(s.label_x_zero_step * s.grid_step)}m"
        )

        self._updating = False

    def _update_zero_summary(self):
        """更新 0 线当前位置文本（米）。"""
        if self._field is None:
            return
        s = self._field
        self.zeroYSummary.setText(
            f"当前位置：{format_value(self.zeroYSlider.value() * s.grid_step)}m"
        )
        self.zeroXSummary.setText(
            f"当前位置：{format_value(self.zeroXSlider.value() * s.grid_step)}m"
        )

    def _on_zero_y_changed(self, value):
        """处理纵向 0 线滑块：按住 Shift 时吸附粗线。"""
        if self._field is None or self._updating:
            return
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            value = round(value / self._field.bold_interval) * self._field.bold_interval
            self.zeroYSlider.blockSignals(True)
            self.zeroYSlider.setValue(value)
            self.zeroYSlider.blockSignals(False)
        self._field.set_label_y_zero_step(value)
        self._update_zero_summary()

    def _on_zero_x_changed(self, value):
        """处理横向 0 线滑块：按住 Shift 时吸附粗线。"""
        if self._field is None or self._updating:
            return
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            value = round(value / self._field.bold_interval) * self._field.bold_interval
            self.zeroXSlider.blockSignals(True)
            self.zeroXSlider.setValue(value)
            self.zeroXSlider.blockSignals(False)
        self._field.set_label_x_zero_step(value)
        self._update_zero_summary()
