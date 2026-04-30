from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QComboBox,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QToolButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class TimelineScrollArea(QScrollArea):
    """时间轴滚轮操作."""

    def wheelEvent(self, event):
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.angleDelta().x()
        if delta != 0:
            step = 40
            bar = self.horizontalScrollBar()
            direction = -1 if delta > 0 else 1
            bar.setValue(bar.value() + direction * step)
            event.accept()
            return
        super().wheelEvent(event)


class ToolOptionDock(QDockWidget):
    """绘图工具配置控制台：非阻塞确认工具切换。"""

    def __init__(self, parent=None):
        super().__init__("绘图工具控制台", parent)
        self.setObjectName("toolOptionDock")
        self.setAllowedAreas(Qt.DockWidgetArea.AllDockWidgetAreas)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self.titleLabel = QLabel("待配置工具：无", content)
        self.tipLabel = QLabel("无需关闭窗口，可继续操作画布。", content)
        self.applyButton = QPushButton("应用并切换", content)
        self.cancelButton = QPushButton("取消", content)

        layout.addWidget(self.titleLabel)
        layout.addWidget(self.tipLabel)
        layout.addWidget(self.applyButton)
        layout.addWidget(self.cancelButton)
        layout.addStretch(1)
        self.setWidget(content)
        self.setMinimumWidth(240)


class DrawingControlDock(QDockWidget):
    """绘制控制台：替代绘图后的确认弹窗。"""

    def __init__(self, parent=None):
        super().__init__("绘制控制台", parent)
        self.setObjectName("drawingControlDock")
        self.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        self._scene = None
        self._syncing_line_segment_controls = False
        self._sampling_tool_name = "线段"
        self._sampling_supported_tools = {"线段", "弧", "曲线/折线", "圆", "多边形", "填充四边形"}

        self.statusLabel = QLabel("", content)
        self.confirmButton = QPushButton("确认绘制", content)
        self.cancelButton = QPushButton("取消绘制", content)

        # self.lineSegmentTitleLabel = QLabel("线段参数：", content)
        self.linePointCountLabel = QLabel("点位个数", content)
        self.linePointCountSpin = QSpinBox(content)
        self.linePointCountSpin.setRange(1, 9999)
        self.linePointCountSpin.setValue(1)
        self.linePointCountAutoButton = QToolButton(content)
        self.linePointCountAutoButton.setText("自动")
        self.linePointCountAutoButton.setCheckable(True)
        self.linePointCountAutoButton.setChecked(True)

        self.lineShiftPointCountLabel = QLabel("P0-P2 点位个数", content)
        self.lineShiftPointCountSpin = QSpinBox(content)
        self.lineShiftPointCountSpin.setRange(1, 9999)
        self.lineShiftPointCountSpin.setValue(1)
        self.lineShiftPointCountAutoButton = QToolButton(content)
        self.lineShiftPointCountAutoButton.setText("自动")
        self.lineShiftPointCountAutoButton.setCheckable(True)
        self.lineShiftPointCountAutoButton.setChecked(True)

        # p0-p1 间隔
        self.lineSpacingLabel = QLabel("点位间隔", content)
        self.lineSpacingSpin = QDoubleSpinBox(content)
        self.lineSpacingSpin.setRange(0.001, 99.0)
        self.lineSpacingSpin.setDecimals(3)
        self.lineSpacingSpin.setSingleStep(0.1)
        self.lineSpacingSpin.setValue(2.0)
        self.lineSpacingAutoButton = QToolButton(content)
        self.lineSpacingAutoButton.setText("自动")
        self.lineSpacingAutoButton.setCheckable(True)
        # 默认关闭“自动”，使用默认两步间隔并允许用户手动启用自动
        self.lineSpacingAutoButton.setChecked(False)

        # p0-p2 间隔（仅填充四边形）
        self.lineShiftSpacingLabel = QLabel("P0-P2 点位间隔", content)
        self.lineShiftSpacingSpin = QDoubleSpinBox(content)
        self.lineShiftSpacingSpin.setRange(0.001, 99.0)
        self.lineShiftSpacingSpin.setDecimals(3)
        self.lineShiftSpacingSpin.setSingleStep(0.1)
        self.lineShiftSpacingSpin.setValue(2.0)
        self.lineShiftSpacingAutoButton = QToolButton(content)
        self.lineShiftSpacingAutoButton.setText("自动")
        self.lineShiftSpacingAutoButton.setCheckable(True)
        # 默认关闭“自动”，使用默认两步间隔并允许用户手动启用自动
        self.lineShiftSpacingAutoButton.setChecked(False)

        # self.lineSegmentHintLabel = QLabel("修改后会立即刷新线段预览；数值按步数显示。", content)
        # self.lineSegmentHintLabel.setWordWrap(True)

        self.polygonSideCountLabel = QLabel("边数", content)
        self.polygonSideCountSpin = QSpinBox(content)
        self.polygonSideCountSpin.setRange(2, 9999)
        self.polygonSideCountSpin.setValue(6)
        # self.polygonSideCountSpin.setToolTip("正多边形的边数，最小为 2")

        # 曲线/折线模式选择（仅在曲线/折线工具生效）
        self.curveModeLabel = QLabel("曲线类型：", content)
        self.curveModeCombo = QComboBox(content)
        self.curveModeCombo.addItems(["折线", "曲线"])  # 默认折线

        layout.addWidget(self.statusLabel)

        self.lineSegmentWidget = QWidget(content)
        line_layout = QVBoxLayout(self.lineSegmentWidget)
        line_layout.setContentsMargins(0, 0, 0, 0)
        line_layout.setSpacing(6)

        self._p01_row = QWidget(self.lineSegmentWidget)
        p01_row_layout = QHBoxLayout(self._p01_row)
        p01_row_layout.setContentsMargins(0, 0, 0, 0)
        p01_row_layout.setSpacing(6)
        p01_row_layout.addWidget(self.linePointCountLabel)
        p01_row_layout.addWidget(self.linePointCountSpin)
        p01_row_layout.addWidget(self.linePointCountAutoButton)
        p01_row_layout.addWidget(self.lineSpacingLabel)
        p01_row_layout.addWidget(self.lineSpacingSpin)
        p01_row_layout.addWidget(self.lineSpacingAutoButton)

        self._p02_row = QWidget(self.lineSegmentWidget)
        p02_row_layout = QHBoxLayout(self._p02_row)
        p02_row_layout.setContentsMargins(0, 0, 0, 0)
        p02_row_layout.setSpacing(6)
        p02_row_layout.addWidget(self.lineShiftPointCountLabel)
        p02_row_layout.addWidget(self.lineShiftPointCountSpin)
        p02_row_layout.addWidget(self.lineShiftPointCountAutoButton)
        p02_row_layout.addWidget(self.lineShiftSpacingLabel)
        p02_row_layout.addWidget(self.lineShiftSpacingSpin)
        p02_row_layout.addWidget(self.lineShiftSpacingAutoButton)

        self._polygon_row = QWidget(self.lineSegmentWidget)
        polygon_row_layout = QHBoxLayout(self._polygon_row)
        polygon_row_layout.setContentsMargins(0, 0, 0, 0)
        polygon_row_layout.setSpacing(6)
        polygon_row_layout.addWidget(self.polygonSideCountLabel)
        polygon_row_layout.addWidget(self.polygonSideCountSpin)

        line_layout.addWidget(self._p01_row)
        line_layout.addWidget(self._p02_row)
        line_layout.addWidget(self._polygon_row)

        # layout.addWidget(self.lineSegmentTitleLabel)
        layout.addWidget(self.lineSegmentWidget)
        # layout.addWidget(self.lineSegmentHintLabel)

        layout.addWidget(self.curveModeLabel)
        layout.addWidget(self.curveModeCombo)
        layout.addWidget(self.confirmButton)
        layout.addWidget(self.cancelButton)
        layout.addStretch(1)
        self.setWidget(content)
        self.setMinimumWidth(240)
        self._draft_active = False
        self.setLineSegmentVisible(False)
        self.setCurveModeVisible(False)
        self.linePointCountSpin.valueChanged.connect(self._on_line_point_count_changed)
        self.lineSpacingSpin.valueChanged.connect(self._on_line_spacing_changed)
        self.lineShiftSpacingSpin.valueChanged.connect(self._on_line_shift_spacing_changed)
        self.lineShiftPointCountSpin.valueChanged.connect(self._on_line_shift_point_count_changed)
        self.polygonSideCountSpin.valueChanged.connect(self._on_polygon_side_count_changed)
        self.linePointCountAutoButton.toggled.connect(self._on_line_point_count_auto_toggled)
        self.lineSpacingAutoButton.toggled.connect(self._on_line_spacing_auto_toggled)
        self.lineShiftSpacingAutoButton.toggled.connect(self._on_line_shift_spacing_auto_toggled)
        self.lineShiftPointCountAutoButton.toggled.connect(self._on_line_shift_point_count_auto_toggled)
        # 连接控制：当用户切换模式时，尝试同步到场景
        def _on_curve_mode_changed(index: int):
            parent = getattr(self, 'parent', lambda: None)()
            # parent() may not exist in some contexts; fallback to self.parent()
            if parent is None:
                parent = self.parent()
            scene = getattr(parent, 'scene', None)
            if scene is None:
                return
            mode = 'polyline' if self.curveModeCombo.currentText() == '折线' else 'curve'
            if hasattr(scene, 'set_curve_mode'):
                scene.set_curve_mode(mode)

        self.curveModeCombo.currentIndexChanged.connect(_on_curve_mode_changed)

    def bind_scene(self, scene):
        self._scene = scene
        self.sync_sampling_settings(self._sampling_tool_name)

    def setSamplingTool(self, tool_name: str):
        if tool_name not in self._sampling_supported_tools:
            tool_name = "线段"
        self._sampling_tool_name = tool_name
        # self.lineSegmentTitleLabel.setText(f"{tool_name}参数：")
        # if tool_name == "多边形":
        #     # self.lineSegmentHintLabel.setText("修改后会立即刷新多边形预览；边数控制顶点数量，其他数值按步数显示。")
        # else:
        #     self.lineSegmentHintLabel.setText(f"修改后会立即刷新{tool_name}预览；数值按步数显示。")
        polygon_visible = tool_name == "多边形"
        self._polygon_row.setVisible(polygon_visible)
        self._p01_row.setVisible(True)
        # 填充四边形时显示 P0-P1 / P0-P2；其他图形只显示通用表述
        is_fill_quad = tool_name == "填充四边形"
        self._p02_row.setVisible(is_fill_quad)
        if is_fill_quad:
            self.linePointCountLabel.setText("P0-P1 点位个数")
            self.lineSpacingLabel.setText("间隔")
            self.lineShiftPointCountLabel.setText("P0-P2 点位个数")
            self.lineShiftSpacingLabel.setText("间隔")
            # self.linePointCountSpin.setToolTip("P0-P1 方向生成点位的实际数量")
            # self.lineSpacingSpin.setToolTip("P0-P1 方向相邻点位的间隔，按网格步数计；例如 2.000 表示两步距离")
            # self.lineShiftPointCountSpin.setToolTip("P0-P2 方向生成点位的实际数量。仅对填充四边形生效。")
            # self.lineShiftSpacingSpin.setToolTip("P0-P2 方向相邻点位的间隔，按网格步数计。仅对填充四边形生效。")
        else:
            self.linePointCountLabel.setText("点位个数")
            self.lineSpacingLabel.setText("点位间隔")

    def _on_line_point_count_changed(self, value: int):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if self.linePointCountAutoButton.isChecked():
            self.linePointCountAutoButton.blockSignals(True)
            self.linePointCountAutoButton.setChecked(False)
            self.linePointCountAutoButton.blockSignals(False)
        if hasattr(self._scene, "set_sampling_point_count"):
            self._scene.set_sampling_point_count(self._sampling_tool_name, int(value))

    def setLinePointCount(self, value: int):
        self._syncing_line_segment_controls = True
        try:
            self.linePointCountSpin.setValue(max(1, int(value)))
        finally:
            self._syncing_line_segment_controls = False

    def setLinePointCountAutoChecked(self, checked: bool):
        self._syncing_line_segment_controls = True
        try:
            self.linePointCountAutoButton.setChecked(bool(checked))
        finally:
            self._syncing_line_segment_controls = False

    def _on_line_spacing_changed(self, value: float):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if self.lineSpacingAutoButton.isChecked():
            self.lineSpacingAutoButton.blockSignals(True)
            self.lineSpacingAutoButton.setChecked(False)
            self.lineSpacingAutoButton.blockSignals(False)
        if hasattr(self._scene, "set_sampling_spacing"):
            self._scene.set_sampling_spacing(self._sampling_tool_name, float(value))

    def _on_polygon_side_count_changed(self, value: int):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if hasattr(self._scene, "set_polygon_side_count"):
            self._scene.set_polygon_side_count(self._sampling_tool_name, int(value))

    def setLineSpacingAutoChecked(self, checked: bool):
        self._syncing_line_segment_controls = True
        try:
            self.lineSpacingAutoButton.setChecked(bool(checked))
        finally:
            self._syncing_line_segment_controls = False

    def _on_line_point_count_auto_toggled(self, checked: bool):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if checked and self.lineSpacingAutoButton.isChecked():
            self._syncing_line_segment_controls = True
            try:
                self.lineSpacingAutoButton.setChecked(False)
            finally:
                self._syncing_line_segment_controls = False
            if hasattr(self._scene, "set_sampling_spacing_auto_enabled"):
                self._scene.set_sampling_spacing_auto_enabled(self._sampling_tool_name, False)
        if hasattr(self._scene, "set_sampling_point_count_auto_enabled"):
            self._scene.set_sampling_point_count_auto_enabled(self._sampling_tool_name, bool(checked))
        self.sync_sampling_settings(self._sampling_tool_name)

    def _on_line_spacing_auto_toggled(self, checked: bool):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if checked and self.linePointCountAutoButton.isChecked():
            self._syncing_line_segment_controls = True
            try:
                self.linePointCountAutoButton.setChecked(False)
            finally:
                self._syncing_line_segment_controls = False
            if hasattr(self._scene, "set_sampling_point_count_auto_enabled"):
                self._scene.set_sampling_point_count_auto_enabled(self._sampling_tool_name, False)
        if hasattr(self._scene, "set_sampling_spacing_auto_enabled"):
            self._scene.set_sampling_spacing_auto_enabled(self._sampling_tool_name, bool(checked))
        self.sync_sampling_settings(self._sampling_tool_name)

    def _on_line_shift_spacing_auto_toggled(self, checked: bool):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if checked and self.lineShiftPointCountAutoButton.isChecked():
            self._syncing_line_segment_controls = True
            try:
                self.lineShiftPointCountAutoButton.setChecked(False)
            finally:
                self._syncing_line_segment_controls = False
            if hasattr(self._scene, "set_sampling_point_count_shift_auto_enabled"):
                self._scene.set_sampling_point_count_shift_auto_enabled(self._sampling_tool_name, False)
        if hasattr(self._scene, "set_sampling_shift_auto_enabled"):
            self._scene.set_sampling_shift_auto_enabled(self._sampling_tool_name, bool(checked))
        self.sync_sampling_settings(self._sampling_tool_name)

    def _on_line_shift_spacing_changed(self, value: float):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if self.lineShiftSpacingAutoButton.isChecked():
            self.lineShiftSpacingAutoButton.blockSignals(True)
            self.lineShiftSpacingAutoButton.setChecked(False)
            self.lineShiftSpacingAutoButton.blockSignals(False)
        if hasattr(self._scene, "set_sampling_spacing_shift"):
            self._scene.set_sampling_spacing_shift(self._sampling_tool_name, float(value))

    def _on_line_shift_point_count_auto_toggled(self, checked: bool):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if checked and self.lineShiftSpacingAutoButton.isChecked():
            self._syncing_line_segment_controls = True
            try:
                self.lineShiftSpacingAutoButton.setChecked(False)
            finally:
                self._syncing_line_segment_controls = False
            if hasattr(self._scene, "set_sampling_shift_auto_enabled"):
                self._scene.set_sampling_shift_auto_enabled(self._sampling_tool_name, False)
        if hasattr(self._scene, "set_sampling_point_count_shift_auto_enabled"):
            self._scene.set_sampling_point_count_shift_auto_enabled(self._sampling_tool_name, bool(checked))
        self.sync_sampling_settings(self._sampling_tool_name)

    def _on_line_shift_point_count_changed(self, value: int):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if self.lineShiftPointCountAutoButton.isChecked():
            self.lineShiftPointCountAutoButton.blockSignals(True)
            self.lineShiftPointCountAutoButton.setChecked(False)
            self.lineShiftPointCountAutoButton.blockSignals(False)
        if hasattr(self._scene, "set_sampling_point_count_shift"):
            self._scene.set_sampling_point_count_shift(self._sampling_tool_name, int(value))

    def sync_sampling_settings(self, tool_name: str | None = None):
        if self._scene is None:
            return
        if tool_name is None:
            tool_name = self._sampling_tool_name
        if tool_name not in self._sampling_supported_tools:
            tool_name = "线段"
        if not hasattr(self._scene, "sampling_settings"):
            return

        point_limit, spacing = self._scene.sampling_settings(tool_name)
        shift_spacing = float(getattr(self._scene, "sampling_shift_spacing", lambda *_: spacing)(tool_name))
        # 新增：获取 P0-P2 点位个数
        shift_point_count = int(getattr(self._scene, "sampling_shift_point_count", lambda *_: 1)(tool_name))
        point_auto = bool(getattr(self._scene, "is_sampling_point_count_auto", lambda *_: True)(tool_name))
        spacing_auto = bool(getattr(self._scene, "is_sampling_spacing_auto", lambda *_: True)(tool_name))
        shift_auto = bool(getattr(self._scene, "is_sampling_shift_auto", lambda *_: True)(tool_name))
        shift_point_auto = bool(getattr(self._scene, "is_sampling_point_count_shift_auto", lambda *_: True)(tool_name))
        polygon_side_count = int(getattr(self._scene, "polygon_side_count", lambda *_: 6)(tool_name))
        self._syncing_line_segment_controls = True
        try:
            self.linePointCountSpin.setValue(max(1, int(point_limit)))
            self.lineSpacingSpin.setValue(float(spacing))
            self.lineShiftSpacingSpin.setValue(float(shift_spacing))
            self.lineShiftPointCountSpin.setValue(max(1, int(shift_point_count)))
            self.linePointCountAutoButton.setChecked(point_auto)
            self.lineSpacingAutoButton.setChecked(spacing_auto)
            self.lineShiftSpacingAutoButton.setChecked(shift_auto)
            self.lineShiftPointCountAutoButton.setChecked(shift_point_auto)
            self.polygonSideCountSpin.setValue(max(2, int(polygon_side_count)))
        finally:
            self._syncing_line_segment_controls = False
        self.linePointCountSpin.setEnabled(not self.linePointCountAutoButton.isChecked())
        self.lineSpacingSpin.setEnabled(not self.lineSpacingAutoButton.isChecked())
        self.lineShiftPointCountSpin.setEnabled(not self.lineShiftPointCountAutoButton.isChecked())
        self.lineShiftSpacingSpin.setEnabled(not self.lineShiftSpacingAutoButton.isChecked())

    def sync_line_segment_settings(self):
        self.setSamplingTool("线段")
        self.sync_sampling_settings("线段")

    def setCurveModeVisible(self, visible: bool):
        self.curveModeLabel.setVisible(bool(visible))
        self.curveModeCombo.setVisible(bool(visible))

    def setLineSegmentVisible(self, visible: bool):
        self.setSamplingTool(self._sampling_tool_name)
        # self.lineSegmentTitleLabel.setVisible(bool(visible))
        self.lineSegmentWidget.setVisible(bool(visible))
        # self.lineSegmentHintLabel.setVisible(bool(visible))

    def setSamplingToolVisible(self, tool_name: str | None, visible: bool):
        if tool_name is not None:
            self.setSamplingTool(tool_name)
        # self.lineSegmentTitleLabel.setVisible(bool(visible))
        self.lineSegmentWidget.setVisible(bool(visible))
        # self.lineSegmentHintLabel.setVisible(bool(visible))

    def setDraftActive(self, active: bool):
        self._draft_active = active
        self.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)

    def closeEvent(self, event):
        if self._draft_active:
            scene = getattr(self.parent(), "scene", None)
            if scene is not None:
                scene.cancel_current_drawing()
        super().closeEvent(event)
