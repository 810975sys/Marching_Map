"""
绘制控制台
"""

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QButtonGroup,
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

class DrawingControlDock(QDockWidget):
    """绘制控制台：替代绘图后的确认弹窗。"""

    def __init__(self, parent=None):
        super().__init__("绘制控制台", parent)
        self.setObjectName("drawingControlDock")
        self.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)    # 禁止停靠
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)  # 允许关闭

        content = QWidget(self)
        layout = QVBoxLayout(content)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)
        # 线段/多边形参数区域，包含点位个数与间隔设置，根据工具类型显示不同的内容
        self.lineSegmentWidget = QWidget(content)
        line_layout = QVBoxLayout(self.lineSegmentWidget)
        line_layout.setContentsMargins(0, 0, 0, 0)
        line_layout.setSpacing(6)
        # 将线段工具参数区域添加到主布局
        layout.addWidget(self.lineSegmentWidget)

        self._scene = None  # 场景引用
        self._syncing_line_segment_controls = False # 内部状态：是否正在同步线段工具控制状态，避免信号循环
        self._sampling_tool_name = "线段"   # 当前采样工具名称
        self._sampling_supported_tools = {"线段", "弧", "曲线/折线", "圆", "多边形", "填充四边形"}  # 支持显示采样设置的工具集合

        self.statusLabel = QLabel("", content)  # 当前绘制状态提示
        layout.addWidget(self.statusLabel)

        self.drawingRematchWidget = QWidget(content)
        drawing_rematch_layout = QHBoxLayout(self.drawingRematchWidget)
        drawing_rematch_layout.setContentsMargins(0, 0, 0, 0)
        drawing_rematch_layout.setSpacing(6)
        self.rematchButton = QPushButton("重新匹配点位", self.drawingRematchWidget)
        self.previousMatchButton = QPushButton("上一个", self.drawingRematchWidget)
        self.nextMatchButton = QPushButton("下一个", self.drawingRematchWidget)
        self.keepMatchButton = QPushButton("保持", self.drawingRematchWidget)
        drawing_rematch_layout.addWidget(self.rematchButton)
        drawing_rematch_layout.addWidget(self.previousMatchButton)
        drawing_rematch_layout.addWidget(self.nextMatchButton)
        drawing_rematch_layout.addWidget(self.keepMatchButton)
        layout.addWidget(self.drawingRematchWidget)

        self.adjustWidget = QWidget(content)
        adjust_layout = QVBoxLayout(self.adjustWidget)
        adjust_layout.setContentsMargins(0, 0, 0, 0)
        adjust_layout.setSpacing(6)

        adjust_mode_row = QWidget(self.adjustWidget)
        adjust_mode_layout = QHBoxLayout(adjust_mode_row)
        adjust_mode_layout.setContentsMargins(0, 0, 0, 0)
        adjust_mode_layout.setSpacing(6)

        self.adjustModeGroup = QButtonGroup(self.adjustWidget)
        self.adjustModeGroup.setExclusive(True)
        self.adjustModeButtons = {}
        self._adjustment_mode_tips = {
            "比例": "保持长宽比缩放，整体等比例变化。",
            "伸展": "沿拖拽方向拉伸或压缩，可单独改变宽高。",
            "倾斜": "拖动角点产生斜切效果，保持对边关系。",
            "歪曲": "对四角做非均匀变形，允许更自由的形变。",
        }
        for mode_name in ["比例", "伸展", "倾斜", "歪曲"]:
            button = QToolButton(self.adjustWidget)
            button.setText(mode_name)
            button.setCheckable(True)
            button.setToolTip(self._adjustment_mode_tips[mode_name])
            self.adjustModeGroup.addButton(button)
            self.adjustModeButtons[mode_name] = button
            adjust_mode_layout.addWidget(button)
            button.toggled.connect(lambda checked, name=mode_name: self._on_adjustment_mode_button_toggled(name, checked))

        self.adjustModeTipLabel = QLabel("", self.adjustWidget)
        self.adjustModeTipLabel.setWordWrap(True)
        self.adjustModeTipLabel.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        
        self.rotationAngleLabel = QLabel("旋转角度", self.adjustWidget)
        self.rotationAngleLabel.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.rotationAngleSpin = QDoubleSpinBox(self.adjustWidget)
        self.rotationAngleSpin.setRange(-360.0, 360.0)
        self.rotationAngleSpin.setDecimals(1)
        self.rotationAngleSpin.setSingleStep(1.0)
        
        rotation_row = QWidget(self.adjustWidget)
        rotation_layout = QHBoxLayout(rotation_row)
        rotation_layout.setContentsMargins(0, 0, 0, 0)
        rotation_layout.setSpacing(6)
        rotation_layout.addWidget(self.rotationAngleLabel)
        rotation_layout.addWidget(self.rotationAngleSpin)

        adjust_layout.addWidget(adjust_mode_row)
        adjust_layout.addWidget(self.adjustModeTipLabel)
        adjust_layout.addWidget(rotation_row)
        layout.addWidget(self.adjustWidget)

        self.confirmButton = QPushButton("确认 Enter", content)   # 确认按钮，完成绘制并清空草稿状态
        self._confirm_shortcut_enter = QShortcut(QKeySequence(Qt.Key.Key_Return), self)  # 绑定快捷键
        self._confirm_shortcut_enter.setContext(Qt.ShortcutContext.ApplicationShortcut) # 设置快捷方式上下文为应用程序级，确保在任何情况下按下 Enter 都能触发确认操作
        self._confirm_shortcut_enter.activated.connect(self._trigger_confirm_shortcut)
        
        self.cancelButton = QPushButton("取消 Esc", content)    # 取消按钮，放弃草稿并清空草稿状态
        self._cancel_shortcut_esc = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self._cancel_shortcut_esc.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._cancel_shortcut_esc.activated.connect(self._trigger_cancel_shortcut)

        # 默认点位个数设置
        self.linePointCountLabel = QLabel("点位个数", content)
        self.linePointCountSpin = QSpinBox(content)
        self.linePointCountSpin.setRange(1, 99)
        self.linePointCountSpin.setValue(1)
        self.linePointCountAutoButton = QToolButton(content)
        self.linePointCountAutoButton.setText("自动")
        self.linePointCountAutoButton.setCheckable(True)
        self.linePointCountAutoButton.setChecked(True)

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
        self.lineSpacingAutoButton.setChecked(False)    # 默认固定两步间隔，并允许用户手动启用自动
        
        # 线段工具参数行1：点位个数与间隔
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

        # 填充四边形的第二个扩展方向
        # 点位设置
        self.lineShiftPointCountLabel = QLabel("P0-P2 点位个数", content)
        self.lineShiftPointCountSpin = QSpinBox(content)
        self.lineShiftPointCountSpin.setRange(1, 99)
        self.lineShiftPointCountSpin.setValue(1)
        self.lineShiftPointCountAutoButton = QToolButton(content)
        self.lineShiftPointCountAutoButton.setText("自动")
        self.lineShiftPointCountAutoButton.setCheckable(True)
        self.lineShiftPointCountAutoButton.setChecked(True)

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
        self.lineShiftSpacingAutoButton.setChecked(False)    # 默认固定两步间隔，并允许用户手动启用自动

        # 线段工具参数行2：仅填充四边形显示，控制第二个方向的点位个数与间隔
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
        
        # 多边形边数设置
        self.polygonSideCountLabel = QLabel("边数", content)
        self.polygonSideCountSpin = QSpinBox(content)
        self.polygonSideCountSpin.setRange(2, 99)
        self.polygonSideCountSpin.setValue(6)

        # 多边形工具参数行：仅多边形显示，控制边数
        self._polygon_row = QWidget(self.lineSegmentWidget)
        polygon_row_layout = QHBoxLayout(self._polygon_row)
        polygon_row_layout.setContentsMargins(0, 0, 0, 0)
        polygon_row_layout.setSpacing(6)
        polygon_row_layout.addWidget(self.polygonSideCountLabel)
        polygon_row_layout.addWidget(self.polygonSideCountSpin)
        
        # 曲线/折线模式选择（仅在曲线/折线工具生效）
        self.curveModeLabel = QLabel("曲线类型：", content)
        self.curveModeCombo = QComboBox(content)
        self.curveModeCombo.addItems(["折线", "曲线"])  # 默认折线
        
        # 曲线/折线工具参数区域：仅包含模式选择
        self.curve_row = QWidget(self.lineSegmentWidget)
        curve_row_layout = QHBoxLayout(self.curve_row)
        curve_row_layout.setContentsMargins(0, 0, 0, 0)
        curve_row_layout.setSpacing(6)
        curve_row_layout.addWidget(self.curveModeLabel)
        curve_row_layout.addWidget(self.curveModeCombo)

        # 将参数区域添加到线段工具参数总区域
        line_layout.addWidget(self._p01_row)
        line_layout.addWidget(self._p02_row)
        line_layout.addWidget(self._polygon_row)
        line_layout.addWidget(self.curve_row)
        
        # 确认/取消按钮区域
        button_layout = QHBoxLayout()
        button_layout.addWidget(self.confirmButton)
        button_layout.addWidget(self.cancelButton)
        layout.addLayout(button_layout)
        
        layout.addStretch(1)    # 底部弹性空间
        self.setWidget(content) # 将内容设置为窗口的主体
        self.setMinimumWidth(240)   # 设置最小宽度，防止内容过于拥挤
        self._draft_active = False  # 设置绘制草稿状态标志，控制确认/取消按钮的启用状态
        # self.setLineSegmentVisible(False)   # 默认隐藏线段工具参数区域，直到绑定场景并设置工具后根据工具类型显示相应参数
        self.setCurveModeVisible(False)     # 默认隐藏曲线/折线模式选择，直到绑定场景并设置工具后根据工具类型显示
        self.setAdjustmentControlsVisible(False)
        self.setDrawingRematchVisible(False)
        
        # 连接信号与槽函数
            # 线段工具参数控制
        self.linePointCountSpin.valueChanged.connect(self._on_line_count_changed) # 点位个数变化时同步到场景
        self.lineSpacingSpin.valueChanged.connect(self._on_line_spacing_changed)  # 点位间隔变化时同步到场景
        self.linePointCountAutoButton.toggled.connect(self._on_line_count_auto_toggled)   # 点位个数自动按钮切换时同步到场景
        self.lineSpacingAutoButton.toggled.connect(self._on_line_spacing_auto_toggled)    # 点位间隔自动按钮切换时同步到场景
            # 填充四边形第二个方向控制
        self.lineShiftSpacingSpin.valueChanged.connect(self._on_line_count_changed2) # P0-P2 点位间隔变化时同步到场景
        self.lineShiftPointCountSpin.valueChanged.connect(self._on_line_spacing_changed2)  # P0-P2 点位个数变化时同步到场景
        self.lineShiftSpacingAutoButton.toggled.connect(self._on_line_count_auto_toggled2)   # P0-P2 点位间隔自动按钮切换时同步到场景
        self.lineShiftPointCountAutoButton.toggled.connect(self._on_line_spacing_auto_toggled2)    # P0-P2 点位个数自动按钮切换时同步到场景
            # 多边形控制
        self.polygonSideCountSpin.valueChanged.connect(self._on_polygon_side_count_changed) # 多边形边数变化时同步到场景
        
        # 折线/曲线切换控制
        def _on_curve_mode_changed():
            parent = getattr(self, 'parent', lambda: None)()
            # parent() may not exist in some contexts; fallback to self.parent()
            if parent is None:
                parent = self.parent()
            scene = getattr(parent, 'scene', None)
            if scene is None:
                return
            mode = 'polyline' if self.curveModeCombo.currentText() == '折线' else 'curve'
            # if hasattr(scene, 'set_curve_mode'):
            scene.set_curve_mode(mode)
        self.curveModeCombo.currentIndexChanged.connect(_on_curve_mode_changed)

    def setAdjustmentControlsVisible(self, visible: bool):
        """设置调整模式控制的可见性"""
        self.adjustWidget.setVisible(bool(visible))

    def setDrawingRematchVisible(self, visible: bool):
        """设置绘图重匹配控制区可见性。"""
        self.drawingRematchWidget.setVisible(bool(visible))

    def setDrawingRematchState(self, *, rematch_enabled: bool, previous_enabled: bool, next_enabled: bool, keep_enabled: bool, confirm_enabled: bool):
        """同步绘图重匹配按钮状态。"""
        self.rematchButton.setEnabled(bool(rematch_enabled))
        self.previousMatchButton.setEnabled(bool(previous_enabled))
        self.nextMatchButton.setEnabled(bool(next_enabled))
        self.keepMatchButton.setEnabled(bool(keep_enabled))
        self.confirmButton.setEnabled(bool(confirm_enabled))

    def setAdjustmentMode(self, mode_name: str):
        """设置调整模式，并同步按钮状态"""
        button = self.adjustModeButtons.get(mode_name)
        if button is not None:
            button.setChecked(True)
        self._update_adjustment_mode_tip(mode_name)

    def setAdjustmentRotation(self, angle: float):
        """设置调整旋转角度，并同步数值显示"""
        self.rotationAngleSpin.blockSignals(True)
        self.rotationAngleSpin.setValue(float(angle))
        self.rotationAngleSpin.blockSignals(False)

    def _update_adjustment_mode_tip(self, mode_name: str):
        tip_text = self._adjustment_mode_tips.get(mode_name, "")
        self.adjustModeTipLabel.setText(tip_text)

    def _on_adjustment_mode_button_toggled(self, mode_name: str, checked: bool):
        if checked:
            self._update_adjustment_mode_tip(mode_name)

    def bind_scene(self, scene):
        """绑定场景引用，以便根据场景状态同步控制显示内容"""
        self._scene = scene
        self.sync_sampling_settings(self._sampling_tool_name)

    def setSamplingTool(self, tool_name: str):
        """设置当前采样工具名称，并根据工具类型调整参数显示内容"""
        self._sampling_tool_name = tool_name
        
        self._polygon_row.setVisible(tool_name == "多边形")
        self._p01_row.setVisible(True)
        
        # 填充四边形时显示修改
        is_fill_quad = tool_name == "填充四边形"
        self._p02_row.setVisible(is_fill_quad)
        if is_fill_quad:
            self.linePointCountLabel.setText("P0-P1 点位个数")
            self.lineSpacingLabel.setText("间隔")
            self.lineShiftPointCountLabel.setText("P0-P2 点位个数")
            self.lineShiftSpacingLabel.setText("间隔")
        else:
            self.linePointCountLabel.setText("点位个数")
            self.lineSpacingLabel.setText("点位间隔")

    def _on_line_count_changed(self, value: int):
        """当点位个数变化时同步到场景，并根据自动设置状态调整另一个参数的自动状态。"""
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if self.linePointCountAutoButton.isChecked():
            self.linePointCountAutoButton.blockSignals(True)
            self.linePointCountAutoButton.setChecked(False)
            self.linePointCountAutoButton.blockSignals(False)
        # if hasattr(self._scene, "set_sampling_point_count"):
        self._scene.set_sampling_point_count(self._sampling_tool_name, int(value))

    def setLinePointCount(self, value: int):
        """设置点位个数，并根据自动设置状态调整另一个参数的自动状态。"""
        self._syncing_line_segment_controls = True  # 避免在程序matic设置值时触发信号导致循环调用
        try:
            self.linePointCountSpin.setValue(max(1, int(value)))    # 确保点位个数至少为1
        finally:
            self._syncing_line_segment_controls = False # 重置同步状态，允许用户交互触发信号

    def _on_line_spacing_changed(self, value: float):
        """当点位间隔变化时同步到场景，并根据自动设置状态调整另一个参数的自动状态。"""
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if self.lineSpacingAutoButton.isChecked():
            self.lineSpacingAutoButton.blockSignals(True)
            self.lineSpacingAutoButton.setChecked(False)
            self.lineSpacingAutoButton.blockSignals(False)
        # if hasattr(self._scene, "set_sampling_spacing"):
        self._scene.set_sampling_spacing(self._sampling_tool_name, float(value))

    def _on_line_count_auto_toggled(self, checked: bool):
        """当点位个数自动状态切换时同步到场景，并根据状态调整另一个参数的自动状态。"""
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if checked and self.lineSpacingAutoButton.isChecked():
            self._syncing_line_segment_controls = True
            try:
                self.lineSpacingAutoButton.setChecked(False)
            finally:
                self._syncing_line_segment_controls = False
            # if hasattr(self._scene, "set_sampling_spacing_auto_enabled"):
            self._scene.set_sampling_spacing_auto_enabled(self._sampling_tool_name, False)
        # if hasattr(self._scene, "set_sampling_point_count_auto_enabled"):
        self._scene.set_sampling_point_count_auto_enabled(self._sampling_tool_name, bool(checked))
        self.sync_sampling_settings(self._sampling_tool_name)

    def _on_line_spacing_auto_toggled(self, checked: bool):
        """当点位间隔自动状态切换时同步到场景，并根据状态调整另一个参数的自动状态。"""
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if checked and self.linePointCountAutoButton.isChecked():
            self._syncing_line_segment_controls = True
            try:
                self.linePointCountAutoButton.setChecked(False)
            finally:
                self._syncing_line_segment_controls = False
            # if hasattr(self._scene, "set_sampling_point_count_auto_enabled"):
            self._scene.set_sampling_point_count_auto_enabled(self._sampling_tool_name, False)
        # if hasattr(self._scene, "set_sampling_spacing_auto_enabled"):
        self._scene.set_sampling_spacing_auto_enabled(self._sampling_tool_name, bool(checked))
        self.sync_sampling_settings(self._sampling_tool_name)

    """填充四边形第二个方向控制的槽函数，逻辑与第一个方向类似，但互不影响。"""
    def _on_line_count_auto_toggled2(self, checked: bool):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if checked and self.lineShiftPointCountAutoButton.isChecked():
            self._syncing_line_segment_controls = True
            try:
                self.lineShiftPointCountAutoButton.setChecked(False)
            finally:
                self._syncing_line_segment_controls = False
            # if hasattr(self._scene, "set_sampling_point_count_shift_auto_enabled"):
            self._scene.set_sampling_point_count_shift_auto_enabled(self._sampling_tool_name, False)
        # if hasattr(self._scene, "set_sampling_shift_auto_enabled"):
        self._scene.set_sampling_shift_auto_enabled(self._sampling_tool_name, bool(checked))
        self.sync_sampling_settings(self._sampling_tool_name)

    def _on_line_count_changed2(self, value: float):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if self.lineShiftSpacingAutoButton.isChecked():
            self.lineShiftSpacingAutoButton.blockSignals(True)
            self.lineShiftSpacingAutoButton.setChecked(False)
            self.lineShiftSpacingAutoButton.blockSignals(False)
        # if hasattr(self._scene, "set_sampling_spacing_shift"):
        self._scene.set_sampling_spacing_shift(self._sampling_tool_name, float(value))

    def _on_line_spacing_auto_toggled2(self, checked: bool):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if checked and self.lineShiftSpacingAutoButton.isChecked():
            self._syncing_line_segment_controls = True
            try:
                self.lineShiftSpacingAutoButton.setChecked(False)
            finally:
                self._syncing_line_segment_controls = False
            # if hasattr(self._scene, "set_sampling_shift_auto_enabled"):
            self._scene.set_sampling_shift_auto_enabled(self._sampling_tool_name, False)
        # if hasattr(self._scene, "set_sampling_point_count_shift_auto_enabled"):
        self._scene.set_sampling_point_count_shift_auto_enabled(self._sampling_tool_name, bool(checked))
        self.sync_sampling_settings(self._sampling_tool_name)

    def _on_line_spacing_changed2(self, value: int):
        if self._syncing_line_segment_controls or self._scene is None:
            return
        if self.lineShiftPointCountAutoButton.isChecked():
            self.lineShiftPointCountAutoButton.blockSignals(True)
            self.lineShiftPointCountAutoButton.setChecked(False)
            self.lineShiftPointCountAutoButton.blockSignals(False)
        # if hasattr(self._scene, "set_sampling_point_count_shift"):
        self._scene.set_sampling_point_count_shift(self._sampling_tool_name, int(value))

    def _on_polygon_side_count_changed(self, value: int):
        """当多边形边数变化时同步到场景。"""
        if self._syncing_line_segment_controls or self._scene is None:
            return
        # if hasattr(self._scene, "set_polygon_side_count"):
        self._scene.set_polygon_side_count(self._sampling_tool_name, int(value))

    def sync_sampling_settings(self, tool_name: str | None = None):
        """根据当前工具名称从场景获取采样设置，并同步到控制界面显示。"""
        if self._scene is None:
            return
        if tool_name is None:
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

    def setCurveModeVisible(self, visible: bool):
        """设置曲线模式可见性"""
        self.curve_row.setVisible(bool(visible))

    def setSamplingToolVisible(self, tool_name: str | None, visible: bool):
        """设置采样工具参数区域可见性，并根据工具名称同步参数显示内容"""
        if tool_name is not None:
            self.setSamplingTool(tool_name)
        self.lineSegmentWidget.setVisible(bool(visible))

    def setDraftActive(self, active: bool):
        """设置草图激活状态，控制确认/取消按钮的启用状态"""
        self._draft_active = active
        self.setAllowedAreas(Qt.DockWidgetArea.NoDockWidgetArea)
        self.setFeatures(QDockWidget.DockWidgetFeature.DockWidgetClosable)

    def _trigger_confirm_shortcut(self):
        if QApplication.activeModalWidget() is not None:
            return
        if self.isVisible() and self.confirmButton.isEnabled():
            self.confirmButton.click()

    def _trigger_cancel_shortcut(self):
        if QApplication.activeModalWidget() is not None:
            return
        if self.isVisible() and self.cancelButton.isEnabled():
            self.cancelButton.click()

    def closeEvent(self, event):
        """当绘制控制台被关闭时，如果草图处于激活状态则取消当前绘制，清理草图状态"""
        if self._draft_active:
            scene = getattr(self.parent(), "scene", None)
            if scene is not None:
                scene.cancel_current_drawing()
        super().closeEvent(event)
