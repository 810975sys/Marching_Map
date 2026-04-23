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

from field_settings import FieldSettings


class FieldSettingsDock(QDockWidget):
    def __init__(self, parent=None):
        super().__init__("场地设置-修改", parent)
        self.setObjectName("fieldSettingsDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
        )
        self.setMinimumWidth(360)

        self._scene = None
        self._settings = None
        self._updating = False

        self.content = QWidget(self)
        self.rootLayout = QVBoxLayout(self.content)
        self.rootLayout.setContentsMargins(8, 8, 8, 8)
        self.rootLayout.setSpacing(10)

        self._build_ui()

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self.content)
        self.setWidget(scroll)

    def bind_scene(self, scene):
        self._scene = scene
        self._settings = scene.field_settings
        self._settings.changed.connect(self.refresh_from_settings)
        self.refresh_from_settings()

    def _build_ui(self):
        self._build_grid_group()
        self._build_field_group()
        self._build_coordinate_group()
        self.rootLayout.addStretch(1)

    def _build_grid_group(self):
        group = QGroupBox("网格与场地", self.content)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        self.bgColorButton = QPushButton("选择", group)
        self.bgColorButton.clicked.connect(self._choose_bg_color)
        form.addRow("背景网格颜色", self.bgColorButton)

        self.bgWidthSpin = QSpinBox(group)
        self.bgWidthSpin.setRange(1, 20)
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
        display_layout = QHBoxLayout(display_row)
        display_layout.setContentsMargins(0, 0, 0, 0)
        display_layout.setSpacing(8)
        self.topDisplayCheck = QCheckBox("上", display_row)
        self.bottomDisplayCheck = QCheckBox("下", display_row)
        self.leftDisplayCheck = QCheckBox("左", display_row)
        self.rightDisplayCheck = QCheckBox("右", display_row)
        for checkbox in (
            self.topDisplayCheck,
            self.bottomDisplayCheck,
            self.leftDisplayCheck,
            self.rightDisplayCheck,
        ):
            checkbox.toggled.connect(self._apply_display_flags)
            display_layout.addWidget(checkbox)
        display_layout.addStretch(1)
        form.addRow("四侧显示", display_row)

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
        form.addRow("上下显示数量", self.yCountSpin)

        self.xCountSpin = QSpinBox(group)
        self.xCountSpin.setRange(0, 50)
        self.xCountSpin.setSingleStep(1)
        self.xCountSpin.valueChanged.connect(self._apply_label_counts)
        form.addRow("左右显示数量", self.xCountSpin)

        self.rootLayout.addWidget(group)

    def _build_coordinate_group(self):
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
        if self._settings is None or self._updating:
            return
        getattr(self._settings, method_name)(value)

    def _apply_field_size(self):
        if self._settings is None or self._updating:
            return
        self._settings.set_field_size(self.fieldLengthSpin.value(), self.fieldHeightSpin.value())

    def _apply_display_flags(self):
        if self._settings is None or self._updating:
            return
        self._settings.set_display_flags(
            self.topDisplayCheck.isChecked(),
            self.bottomDisplayCheck.isChecked(),
            self.leftDisplayCheck.isChecked(),
            self.rightDisplayCheck.isChecked(),
        )

    def _apply_label_offsets(self):
        if self._settings is None or self._updating:
            return
        self._settings.set_label_offsets(self.yOffsetSpin.value(), self.xOffsetSpin.value())

    def _apply_label_counts(self):
        if self._settings is None or self._updating:
            return
        self._settings.set_label_counts(self.yCountSpin.value(), self.xCountSpin.value())

    def _choose_bg_color(self):
        if self._settings is None or self._updating:
            return
        color = QColorDialog.getColor(self._settings.bg_grid_color, self, "选择背景网格颜色")
        if color.isValid():
            self._settings.set_bg_grid_color(color)

    def _choose_field_color(self):
        if self._settings is None or self._updating:
            return
        color = QColorDialog.getColor(self._settings.field_line_color, self, "选择行进场地颜色")
        if color.isValid():
            self._settings.set_field_line_color(color)

    @staticmethod
    def _contrast_text_color(color: QColor) -> str:
        brightness = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
        return "#000000" if brightness > 160 else "#ffffff"

    def _apply_color_button_style(self, button: QPushButton, color: QColor):
        text_color = self._contrast_text_color(color)
        button.setText(color.name().upper())
        button.setStyleSheet(
            f"background-color: {color.name()}; color: {text_color}; border: 1px solid #666666; padding: 4px 10px;"
        )

    def refresh_from_settings(self):
        if self._settings is None:
            return
        s = self._settings
        self._updating = True

        self._apply_color_button_style(self.bgColorButton, s.bg_grid_color)
        self._apply_color_button_style(self.fieldColorButton, s.field_line_color)

        self.bgWidthSpin.setValue(s.bg_grid_width)
        self.fieldWidthSpin.setValue(s.field_line_width)

        self.fieldLengthSpin.setValue(s.field_width)
        self.fieldHeightSpin.setValue(s.field_height)

        self.labelAbsCheck.setChecked(s.label_abs)
        self.labelZoomSpin.setValue(s.label_zoom)

        self.topDisplayCheck.setChecked(s.top_display[0])
        self.bottomDisplayCheck.setChecked(s.bottom_display[0])
        self.leftDisplayCheck.setChecked(s.left_display[0])
        self.rightDisplayCheck.setChecked(s.right_display[0])

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
            f"当前位置：{FieldSettings.format_value(s.label_y_zero_step * s.grid_step)}m"
        )
        self.zeroXSummary.setText(
            f"当前位置：{FieldSettings.format_value(s.label_x_zero_step * s.grid_step)}m"
        )

        self._updating = False

    def _update_zero_summary(self):
        if self._settings is None:
            return
        s = self._settings
        self.zeroYSummary.setText(
            f"当前位置：{FieldSettings.format_value(self.zeroYSlider.value() * s.grid_step)}m"
        )
        self.zeroXSummary.setText(
            f"当前位置：{FieldSettings.format_value(self.zeroXSlider.value() * s.grid_step)}m"
        )

    def _on_zero_y_changed(self, value):
        if self._settings is None or self._updating:
            return
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            value = round(value / self._settings.bold_interval) * self._settings.bold_interval
            self.zeroYSlider.blockSignals(True)
            self.zeroYSlider.setValue(value)
            self.zeroYSlider.blockSignals(False)
        self._settings.set_label_y_zero_step(value)
        self._update_zero_summary()

    def _on_zero_x_changed(self, value):
        if self._settings is None or self._updating:
            return
        if QApplication.keyboardModifiers() & Qt.KeyboardModifier.ShiftModifier:
            value = round(value / self._settings.bold_interval) * self._settings.bold_interval
            self.zeroXSlider.blockSignals(True)
            self.zeroXSlider.setValue(value)
            self.zeroXSlider.blockSignals(False)
        self._settings.set_label_x_zero_step(value)
        self._update_zero_summary()
