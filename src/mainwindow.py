import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QToolBar,
    QVBoxLayout, QWidget,
    QHBoxLayout, QPushButton, QSizePolicy, QToolButton, QGridLayout, QFrame,
    QLabel, QLineEdit, QSlider
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon

# 导入自定义场景
from scheme_scene import SchemeScene
from field_settings import (
    SCALE_MIN,
    SCALE_MAX,
    ZOOM_PERCENT_FACTOR,
    ZOOM_PERCENT_MIN,
    ZOOM_PERCENT_MAX,
)
from field_settings_panel import FieldSettingsDock
from timeline_widget import TimelineWidget
from mainwindow_docks import DrawingControlDock, TimelineScrollArea, ToolOptionDock
from mainwindow_notice import MainWindowNotice
from mainwindow_field_settings import MainWindowFieldSettings


class MainWindow(MainWindowNotice, MainWindowFieldSettings, QMainWindow):
    """主窗口：组织菜单、场景、时间轴与各类控制台。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 工具栏按钮映射：工具名 -> QToolButton
        self.toolButtons = {}
        self.activeToolName = "框选"
        self.pendingToolName = None
        self._sampling_tools = {"线段", "弧", "曲线/折线", "圆", "多边形", "填充四边形"}
        self._dialog_required_tools = {
            "线段", "弧", "曲线/折线", "填充四边形", "圆", "多边形",
            "调整", "旋转", "跟随", "路径", "间隔行进",
            "标签", "文本", "箭头",
        }
        self._drawing_tools = {"点", "线段", "弧", "曲线/折线", "填充四边形", "圆", "多边形"}
        self.setupMenus()
        self.setupToolBar_()
        # self.setupDockWidgets()
        self.setupCentralView()
        self.setupTimeline()
        self.setupInteractions()
        self.setupMainLayout()
        self.setupFieldSettingsDock()
        self.setupToolOptionDock()
        self.setupDrawingControlDock()
        self.setWindowTitle("Marching Map Editor")
        self.resize(1200, 800)
        self.showMaximized()

    def setupMenus(self):
        """创建主菜单及快捷操作。"""
        fileMenu = self.menuBar().addMenu("文件")
        new = fileMenu.addAction("新建方案")
        new.setShortcut("Ctrl+N")
        open = fileMenu.addAction("打开")
        open.setShortcut("Ctrl+O")
        save = fileMenu.addAction("保存")
        save.setShortcut("Ctrl+S")
        saveAs = fileMenu.addAction("另存为")
        saveAs.setShortcut("Ctrl+Shift+S")
        fileMenu.addSeparator()
        fileMenu.addAction("导出为PDF")
        # fileMenu.addSeparator()
        # fileMenu.addAction("设置")

        # 撤销和重做直接作为主菜单栏按钮，添加图标
        undo_icon = QIcon.fromTheme("edit-undo")
        redo_icon = QIcon.fromTheme("edit-redo")
        undo = self.menuBar().addAction(undo_icon, "撤销")
        undo.setShortcut("Ctrl+Z")
        redo = self.menuBar().addAction(redo_icon, "重做")
        redo.setShortcut("Ctrl+Y")

        # 场地设置
        groundMenu = self.menuBar().addMenu("场地设置")
        self.actionGroundImport = groundMenu.addAction("导入")
        self.actionGroundImport.triggered.connect(self.importFieldSettings)
        self.actionGroundSave = groundMenu.addAction("保存")
        self.actionGroundSave.triggered.connect(self.saveFieldSettings)
        self.actionGroundModify = groundMenu.addAction("修改")

        del_player = self.menuBar().addAction("删除点位")
        del_player.setShortcut("Delete")

        # 菜单栏右侧非阻塞提示。
        self.setup_menu_notice()

        # 可扩展
        # viewMenu = self.menuBar().addMenu("视图")

    # def setupToolBar(self):
    #     # 工具分组，遇到分隔符就新建一行
    #     tool_groups = [
    #         ["框选", "套索", "选择整组"],
    #         ["点", "直线", "弧", "曲线", "矩形", "圆", "多边形"],
    #         ["调整", "旋转", "跟随", "路径"],
    #         ["标签", "文本"]
    #     ]
    #     for idx, group in enumerate(tool_groups):
    #         toolBar = QToolBar(f"工具栏{idx+1}", self)
    #         for action in group:
    #             toolBar.addAction(action)
    #         self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolBar)

    def setupToolBar_(self):
        """
        自定义多行分组工具栏示例：每组工具用QWidget+QGridLayout实现多行，组间用竖直分割线分隔，整体放在主窗口顶部。
        保留目前的分组与布局设置。
        """
        rows = 2  # 每组工具的行数
        # 工具分组及布局（每组：按钮文本列表，行数，列数）
        tool_groups = [
            ['组选', '框选', '套索'],  # 选择工具
            ['点', '线段', '弧', '曲线/折线', '填充四边形', '圆', '多边形'],  # 绘制工具
            ['调整', '旋转', '跟随', '路径', '间隔行进'],  # 变换工具
            ['标签', '文本', '箭头']  # 标注工具
        ]
        
        container = QWidget(self)
        h_layout = QHBoxLayout()
        h_layout.setContentsMargins(0, 0, 0, 0)
        h_layout.setSpacing(8)

        for idx, group in enumerate(tool_groups):
            # 组间添加竖直分割线（最后一组不加）
            if idx > 0: 
                line = QFrame()
                line.setFrameShape(QFrame.Shape.VLine)
                line.setFrameShadow(QFrame.Shadow.Sunken)
                h_layout.addWidget(line)
                
            cols = (len(group) + rows - 1) // rows  # 计算列数
            group_widget = QWidget()
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setSpacing(2)
            for i, name in enumerate(group):
                btn = QToolButton()
                btn.setText(name)
                btn.setCheckable(True)
                btn.clicked.connect(lambda checked, tool_name=name: self.onToolButtonClicked(tool_name, checked))
                self.toolButtons[name] = btn
                grid.addWidget(btn, i // cols, i % cols)
            group_widget.setLayout(grid)
            h_layout.addWidget(group_widget)
        container.setLayout(h_layout)
        # 用QToolBar包裹，便于后续扩展
        toolBar = QToolBar("自定义工具栏", self)
        toolBar.addWidget(container)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolBar)

        if self.activeToolName in self.toolButtons:
            self.toolButtons[self.activeToolName].setChecked(True)

    # def setupDockWidgets(self):
    #     self.propertyDock = QDockWidget("属性", self)
    #     self.propertyDock.setWidget(QWidget())  # 后续替换为属性面板
    #     self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.propertyDock)

    #     self.layerDock = QDockWidget("图层", self)
    #     self.layerDock.setWidget(QWidget())  # 后续替换为图层面板
    #     self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.layerDock)

    def setupCentralView(self):
        """创建场景与视图。"""
        from scheme_view import SchemeView
        self.scene = SchemeScene(self)
        self.view = SchemeView(self.scene, self)
        # self.view.setScene(self.scene)
        # setCentralWidget 在 setupTimeline 里统一设置

    def setupTimeline(self):
        """创建底部时间轴与播放控制区。"""
        # 时间轴主容器
        self.timelineWidget = QWidget(self)
        self.timelineWidget.setFixedHeight(72)
        self.timelineWidget.setStyleSheet("background:#f0f0f0;")

        # 左侧动画播放组件区域
        self.animControlWidget = QWidget(self.timelineWidget)
        animLayout = QHBoxLayout()
        animLayout.setContentsMargins(8, 0, 8, 0)
        animLayout.setSpacing(4)
        # 预留播放、暂停、前进、后退等按钮
        self.btnPlayPause = QPushButton("▶", self.animControlWidget)
        self.btnPlayPause.setFixedSize(48, 32)  # 加宽主播放按钮
        self.btnPrev = QPushButton("⏮", self.animControlWidget)
        self.btnPrev.setFixedSize(32, 32)
        self.btnNext = QPushButton("⏭", self.animControlWidget)
        self.btnNext.setFixedSize(32, 32)

        # 设置更大字体
        btnFont = self.btnPlayPause.font()
        btnFont.setPointSize(18)
        for btn in [self.btnPrev, self.btnPlayPause, self.btnNext]:
            btn.setFont(btnFont)
            animLayout.addWidget(btn)

        # 播放/暂停切换逻辑（仅UI，后续可绑定实际播放状态）
        def toggle_play_pause():
            if self.btnPlayPause.text() == "▶":
                self.btnPlayPause.setText("⏸")
            else:
                self.btnPlayPause.setText("▶")
        self.btnPlayPause.clicked.connect(toggle_play_pause)
        self.animControlWidget.setLayout(animLayout)
        self.animControlWidget.setFixedWidth(160)
        self.animControlWidget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)

        # 右侧时间轴主控件（横向滚动，不压缩每拍宽度）
        self.timelineMainWidget = TimelineWidget(self.timelineWidget)
        self.timelineScrollArea = TimelineScrollArea(self.timelineWidget)
        self.timelineScrollArea.setWidget(self.timelineMainWidget)
        self.timelineScrollArea.setWidgetResizable(False)
        self.timelineScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        self.timelineScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.timelineScrollArea.setFrameShape(QFrame.Shape.NoFrame)
        self.timelineScrollArea.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        # 水平布局：左动画控件 + 右时间轴
        timelineLayout = QHBoxLayout()
        timelineLayout.setContentsMargins(0, 0, 0, 0)
        timelineLayout.setSpacing(0)
        timelineLayout.addWidget(self.animControlWidget)
        # 添加竖直分割线
        vline = QFrame()
        vline.setFrameShape(QFrame.Shape.VLine)
        vline.setFrameShadow(QFrame.Shadow.Sunken)
        vline.setLineWidth(1)
        timelineLayout.addWidget(vline)
        timelineLayout.addWidget(self.timelineScrollArea)
        self.timelineWidget.setLayout(timelineLayout)

    def setupInteractions(self):
        """绑定时间轴、场景和控制台信号。"""
        self.timelineMainWidget.nodeSelected.connect(self.onTimelineNodeSelected)
        self.timelineMainWidget.currentBeatChanged.connect(self.scene.set_preview_beat)
        self.timelineMainWidget.nodeAdded.connect(self.scene.on_node_added)
        self.timelineMainWidget.nodeInserted.connect(self.scene.on_node_inserted)
        self.timelineMainWidget.nodeDeleted.connect(self.onTimelineNodeDeleted)
        self.scene.selectedPointsChanged.connect(self.onSelectedPointsChanged)
        self.scene.draftStarted.connect(self.onDraftStarted)
        self.scene.draftFinished.connect(self.onDraftFinished)
        self.scene.lineSegmentPointCountChanged.connect(self.onLineSegmentPointCountChanged)
        self.scene.lineSegmentSpacingChanged.connect(self.onLineSegmentSpacingChanged)
        self.scene.samplingPointCountChanged.connect(self.onSamplingPointCountChanged)
        self.scene.samplingSpacingChanged.connect(self.onSamplingSpacingChanged)
        self.scene.samplingShiftSpacingChanged.connect(self.onSamplingShiftSpacingChanged)
        self.scene.samplingShiftPointCountChanged.connect(self.onSamplingShiftPointCountChanged)

        self.scene.set_active_tool(self.activeToolName)
        self.onTimelineNodeSelected(self.timelineMainWidget.selected_node)
        # 初始化场景预览拍位，确保启动时状态与时间轴一致。
        self.scene.set_preview_beat(self.timelineMainWidget.current_beat)

    def onToolButtonClicked(self, tool_name: str, checked: bool):
        """处理工具栏按钮点击，并在需要时转到浮动控制台确认。"""
        if not checked:
            if self.activeToolName == tool_name and tool_name in self.toolButtons:
                self.toolButtons[tool_name].setChecked(True)
            return

        if tool_name == "点":
            self.drawingControlDock.statusLabel.setText("点击绘制参考点，拖动空心矩形可对单点进行修正。")
        elif tool_name == '线段':
            self.drawingControlDock.statusLabel.setText("确定线段起止点，拖动空心矩形可对单点进行修正。")
        elif tool_name == '弧':
            self.drawingControlDock.statusLabel.setText("确定弧的起止点和弧上任意一点，拖动空心矩形可对单点进行修正。")
        elif tool_name == '圆':
            self.drawingControlDock.statusLabel.setText("确定圆心和圆上任意一点，拖动空心矩形可对单点进行修正。")
        elif tool_name == '多边形':
            self.drawingControlDock.statusLabel.setText("确定多边形中心点及一个顶点，拖动空心矩形可对单点进行修正。")
        elif tool_name == '填充四边形':
            self.drawingControlDock.statusLabel.setText("确定填充四边形三个顶点，拖动空心矩形可对单点进行修正。")
        elif tool_name == '曲线/折线':
            self.drawingControlDock.statusLabel.setText("确定曲线/折线的经过点，拖动空心矩形可对单点进行修正。")

        if tool_name == "点":
            self.pendingToolName = None
            self.toolOptionDock.hide()
            self._apply_active_tool(tool_name)
            self.drawingControlDock.setSamplingToolVisible(None, False)
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.setDraftActive(True)
            self.drawingControlDock.confirmButton.setEnabled(False)
            self.drawingControlDock.cancelButton.setEnabled(False)
            self.drawingControlDock.show()
            self._positionDrawingControlDock()
            self.drawingControlDock.raise_()
            return

        if tool_name in self._drawing_tools:
            self.pendingToolName = None
            self.toolOptionDock.hide()
            self._apply_active_tool(tool_name)
            self.drawingControlDock.setSamplingToolVisible(tool_name if tool_name in self._sampling_tools else None, tool_name in self._sampling_tools)
            self.drawingControlDock.setCurveModeVisible(tool_name == "曲线/折线")
            self.drawingControlDock.setDraftActive(False)
            if tool_name in self._sampling_tools:
                self.drawingControlDock.sync_sampling_settings(tool_name)
            self.drawingControlDock.confirmButton.setEnabled(False)
            self.drawingControlDock.cancelButton.setEnabled(False)
            self.drawingControlDock.show()
            self._positionDrawingControlDock()
            self.drawingControlDock.raise_()
            return
        
        # if tool_name in self._dialog_required_tools:
        #     self.pendingToolName = tool_name
        #     self._sync_tool_button_states(self.activeToolName)
        #     self.toolOptionDock.titleLabel.setText(f"待配置工具：{tool_name}")
        #     self.toolOptionDock.show()
        #     self.toolOptionDock.raise_()
        #     return

        self._apply_active_tool(tool_name)
        if hasattr(self, "drawingControlDock"):
            self.drawingControlDock.setSamplingToolVisible(None, False)
            self.drawingControlDock.setCurveModeVisible(False)

    def _sync_tool_button_states(self, checked_tool: str):
        """同步工具按钮选中状态，避免递归触发信号。"""
        for name, btn in self.toolButtons.items():
            btn.blockSignals(True)
            btn.setChecked(name == checked_tool)
            btn.blockSignals(False)

    def _apply_active_tool(self, tool_name: str):
        """应用工具切换到场景，并更新按钮状态。"""
        self._sync_tool_button_states(tool_name)
        self.activeToolName = tool_name
        if hasattr(self, "scene"):
            self.scene.set_active_tool(tool_name)

    def _set_active_tool(self, tool_name: str):
        """通过按钮点击触发工具切换，保留现有行为。"""
        if tool_name not in self.toolButtons:
            return
        btn = self.toolButtons[tool_name]
        if not btn.isEnabled():
            return
        btn.click()

    def onTimelineNodeSelected(self, node_index: int):
        """时间轴选中节点变化时，同步场景与工具可用状态。"""
        self.scene.set_active_node(node_index)
        self.updateContextToolAvailability(node_index, len(getattr(self.scene, "_selected_point_ids", set())))

    def onSelectedPointsChanged(self, selected_count: int):
        """场景选中点位变化后，刷新绘制与变换工具可用状态。"""
        self.updateContextToolAvailability(self.timelineMainWidget.selected_node, int(selected_count))

    def onLineSegmentPointCountChanged(self, point_count: int):
        """线段自动布点数量变化时，同步控制台显示。"""
        if not hasattr(self, "drawingControlDock"):
            return
        if self.activeToolName != "线段":
            return
        if getattr(self.drawingControlDock, "linePointCountAutoButton", None) is not None and self.drawingControlDock.linePointCountAutoButton.isChecked():
            self.drawingControlDock.sync_sampling_settings("线段")
            return
        self.drawingControlDock.setLinePointCount(int(point_count))

    def onLineSegmentSpacingChanged(self, spacing: float):
        """线段自动间隔变化时，同步控制台显示。"""
        if not hasattr(self, "drawingControlDock"):
            return
        if self.activeToolName != "线段":
            return
        self.drawingControlDock.lineSpacingSpin.blockSignals(True)
        self.drawingControlDock.lineSpacingSpin.setValue(float(spacing))
        self.drawingControlDock.lineSpacingSpin.blockSignals(False)

    def onSamplingShiftPointCountChanged(self, tool_name: str, point_count: int):
        """填充四边形的 P0-P2 点位个数变化时，同步控制台显示。"""
        if not hasattr(self, "drawingControlDock"):
            return
        if self.activeToolName != tool_name:
            return
        if tool_name != "填充四边形":
            return
        if getattr(self.drawingControlDock, "lineShiftPointCountAutoButton", None) is not None and self.drawingControlDock.lineShiftPointCountAutoButton.isChecked():
            self.drawingControlDock.sync_sampling_settings(tool_name)
            return
        self.drawingControlDock.lineShiftPointCountSpin.blockSignals(True)
        self.drawingControlDock.lineShiftPointCountSpin.setValue(int(point_count))
        self.drawingControlDock.lineShiftPointCountSpin.blockSignals(False)

    def onSamplingPointCountChanged(self, tool_name: str, point_count: int):
        """圆、弧、多边形等采样点数自动变化时，同步控制台显示。"""
        if not hasattr(self, "drawingControlDock"):
            return
        if tool_name not in self._sampling_tools or tool_name == "线段":
            return
        if self.activeToolName != tool_name:
            return
        if getattr(self.drawingControlDock, "linePointCountAutoButton", None) is not None and self.drawingControlDock.linePointCountAutoButton.isChecked():
            self.drawingControlDock.sync_sampling_settings(tool_name)
            return
        self.drawingControlDock.setSamplingTool(tool_name)
        self.drawingControlDock.setLinePointCount(int(point_count))

    def onSamplingSpacingChanged(self, tool_name: str, spacing: float):
        """圆、弧、多边形等采样间隔自动变化时，同步控制台显示。"""
        if not hasattr(self, "drawingControlDock"):
            return
        if tool_name not in self._sampling_tools or tool_name == "线段":
            return
        if self.activeToolName != tool_name:
            return
        self.drawingControlDock.setSamplingTool(tool_name)
        self.drawingControlDock.lineSpacingSpin.blockSignals(True)
        self.drawingControlDock.lineSpacingSpin.setValue(float(spacing))
        self.drawingControlDock.lineSpacingSpin.blockSignals(False)

    def onSamplingShiftSpacingChanged(self, tool_name: str, spacing: float):
        """填充四边形的第二方向间隔变化时，同步控制台显示。"""
        if not hasattr(self, "drawingControlDock"):
            return
        if self.activeToolName != tool_name:
            return
        # 仅在填充四边形工具时生效
        if tool_name != "填充四边形":
            return
        self.drawingControlDock.lineShiftSpacingSpin.blockSignals(True)
        self.drawingControlDock.lineShiftSpacingSpin.setValue(float(spacing))
        self.drawingControlDock.lineShiftSpacingSpin.blockSignals(False)

    def onTimelineNodeDeleted(self, deleted_index: int):
        """节点删除后同步场景数据并重置选中状态。"""
        # 关键：时间轴删除只是拍数与索引变化，场景里的 node_points/node_shapes
        # 也必须按同样规则重排，否则会出现“拍数对了但点位串位”的问题。
        self.scene.on_node_deleted(deleted_index)
        self.onTimelineNodeSelected(self.timelineMainWidget.selected_node)

    def updateContextToolAvailability(self, node_index: int, selected_count: int):
        """根据当前节点和选中点位数量，控制绘制与变换工具可用性。"""
        is_p0 = int(node_index) == 0
        has_selection = int(selected_count) > 0

        drawing_tools = ["点", "线段", "弧", "曲线/折线", "填充四边形", "圆", "多边形"]
        transform_tools = ["调整", "旋转", "跟随", "路径", "间隔行进"]
        p0_forbidden_transform_tools = {"跟随", "路径", "间隔行进"}

        for name in drawing_tools:
            btn = self.toolButtons.get(name)
            if btn is not None:
                btn.setEnabled(is_p0 or has_selection)

        for name in transform_tools:
            btn = self.toolButtons.get(name)
            if btn is not None:
                btn.setEnabled(has_selection and not (is_p0 and name in p0_forbidden_transform_tools))

        if not (is_p0 or has_selection) and self.activeToolName in drawing_tools + transform_tools:
            self._set_active_tool("框选")
        elif is_p0 and self.activeToolName in p0_forbidden_transform_tools:
            self._set_active_tool("框选")

    def setupMainLayout(self):
        """
        主窗口布局：上方为 self.view（场景视图），下方为 self.timelineWidget（时间轴）
        """
        mainLayout = QVBoxLayout()
        mainLayout.setContentsMargins(0, 0, 0, 0)
        mainLayout.setSpacing(0)
        mainLayout.addWidget(self.view)

        # 缩放条区域（放在时间轴上方）
        zoomLayout = QHBoxLayout()
        zoomLayout.addStretch(1)
        zoomLabel = QLabel("缩放：")
        zoomLabel.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        zoomSlider = QSlider(Qt.Orientation.Horizontal)
        zoomSlider.setMinimum(ZOOM_PERCENT_MIN)
        zoomSlider.setMaximum(ZOOM_PERCENT_MAX)
        zoomSlider.setValue(int(self.scene.field_settings.scale * ZOOM_PERCENT_FACTOR))  # scale=10~100 -> 50~500%
        zoomSlider.setSingleStep(1)
        zoomSlider.setFixedWidth(180)
        zoomInput = QLineEdit(f"{zoomSlider.value()}")
        zoomInput.setFixedWidth(35)
        zoomInput.setAlignment(Qt.AlignmentFlag.AlignRight)
        # zoomInput.setToolTip("输入缩放百分比，回车或失焦生效")
        percentLabel = QLabel("%")
        percentLabel.setMinimumWidth(16)
        percentLabel.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        zoomLayout.addWidget(zoomLabel)
        zoomLayout.addWidget(zoomSlider)
        zoomLayout.addWidget(zoomInput)
        zoomLayout.addWidget(percentLabel)
        zoomLayout.setContentsMargins(0, 0, 8, 4)

        # 缩放条事件
        def on_zoom_slider(val):
            # 50~500 -> scale 10~100
            scale = int(val / ZOOM_PERCENT_FACTOR)
            scale = max(SCALE_MIN, min(SCALE_MAX, scale))
            self.scene.field_settings.set_scale(scale)
            zoomInput.setText(str(val))
            self.scene.update()
        zoomSlider.valueChanged.connect(on_zoom_slider)

        def set_zoom_from_input():
            text = zoomInput.text().strip()
            try:
                val = int(text)
            except ValueError:
                val = zoomSlider.value()
            val = max(ZOOM_PERCENT_MIN, min(ZOOM_PERCENT_MAX, val))
            zoomSlider.setValue(val)
        zoomInput.returnPressed.connect(set_zoom_from_input)
        zoomInput.editingFinished.connect(set_zoom_from_input)

        # 反向联动：如果用Ctrl+滚轮缩放，也更新滑块
        orig_set_scale = self.scene.field_settings.set_scale
        def set_scale_and_update_slider(scale):
            orig_set_scale(scale)
            val = int(scale * ZOOM_PERCENT_FACTOR)
            val = max(ZOOM_PERCENT_MIN, min(ZOOM_PERCENT_MAX, val))
            zoomSlider.blockSignals(True)
            zoomSlider.setValue(val)
            zoomSlider.blockSignals(False)
            zoomInput.setText(str(val))
        self.scene.field_settings.set_scale = set_scale_and_update_slider

        mainLayout.addLayout(zoomLayout)
        mainLayout.addWidget(self.timelineWidget)
        central = QWidget(self)
        central.setLayout(mainLayout)
        self.setCentralWidget(central)

    def setupFieldSettingsDock(self):
        """创建场地参数编辑面板。"""
        self.fieldSettingsDock = FieldSettingsDock(self)
        self.fieldSettingsDock.bind_scene(self.scene)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.fieldSettingsDock)
        self.fieldSettingsDock.hide()
        self.actionGroundModify.setCheckable(True)
        self.actionGroundModify.toggled.connect(self.fieldSettingsDock.setVisible)
        self.fieldSettingsDock.visibilityChanged.connect(self.actionGroundModify.setChecked)

    # def showFieldSettingsDock(self):
    #     """显示并激活场地参数编辑面板。"""
    #     # 历史辅助方法：当前通过菜单 actionGroundModify.toggled 控制显隐，无调用方。
    #     self.fieldSettingsDock.show()
    #     self.fieldSettingsDock.raise_()
    #     self.fieldSettingsDock.activateWindow()
    #     self.actionGroundModify.setChecked(True)

    def setupToolOptionDock(self):
        """创建工具配置浮动控制台。"""
        self.toolOptionDock = ToolOptionDock(self)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.toolOptionDock)
        self.toolOptionDock.hide()
        self.toolOptionDock.applyButton.clicked.connect(self.applyPendingTool)
        self.toolOptionDock.cancelButton.clicked.connect(self.cancelPendingTool)

    def applyPendingTool(self):
        """应用待确认的工具切换。"""
        if not self.pendingToolName:
            return
        tool_name = self.pendingToolName
        self.pendingToolName = None
        self._apply_active_tool(tool_name)
        self.toolOptionDock.titleLabel.setText("待配置工具：无")

    def cancelPendingTool(self):
        """取消待确认的工具切换，恢复当前工具。"""
        self.pendingToolName = None
        self._sync_tool_button_states(self.activeToolName)
        self.toolOptionDock.titleLabel.setText("待配置工具：无")

    def setupDrawingControlDock(self):
        """创建绘制确认浮动控制台。"""
        self.drawingControlDock = DrawingControlDock(self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.drawingControlDock)
        self.drawingControlDock.setFloating(True)
        self.drawingControlDock.bind_scene(self.scene)
        self.drawingControlDock.hide()
        self.drawingControlDock.confirmButton.setEnabled(False)
        self.drawingControlDock.cancelButton.setEnabled(False)
        self.drawingControlDock.setSamplingToolVisible(None, False)
        self.drawingControlDock.setCurveModeVisible(False)
        self.drawingControlDock.confirmButton.clicked.connect(self.scene.confirm_current_drawing)
        self.drawingControlDock.cancelButton.clicked.connect(self.scene.cancel_current_drawing)

    def _positionDrawingControlDock(self):
        """将绘制控制台放到绘图区左上角。"""
        if not hasattr(self, "drawingControlDock"):
            return
        if not hasattr(self, "view"):
            return
        dock = self.drawingControlDock
        if not dock.isFloating():
            dock.setFloating(True)

        dock.adjustSize()
        dock_size = dock.sizeHint()
        margin = 12
        viewport = self.view.viewport()
        top_left = viewport.mapToGlobal(viewport.rect().topLeft())
        dock.move(top_left.x() + margin, top_left.y() + margin)

    def onDraftStarted(self, tool_name: str):
        """场景进入草稿态时，启用确认/取消按钮。"""
        self.drawingControlDock.setDraftActive(True)
        self.drawingControlDock.setSamplingToolVisible(tool_name if tool_name in self._sampling_tools else None, tool_name in self._sampling_tools)
        self.drawingControlDock.setCurveModeVisible(tool_name == "曲线/折线")
        if tool_name in self._sampling_tools:
            self.drawingControlDock.setSamplingTool(tool_name)
            self.drawingControlDock.sync_sampling_settings(tool_name)
        self.drawingControlDock.setFloating(True)
        self.drawingControlDock.confirmButton.setEnabled(True)
        self.drawingControlDock.cancelButton.setEnabled(True)
        self.drawingControlDock.show()
        self._positionDrawingControlDock()
        self.drawingControlDock.raise_()

    def onDraftFinished(self):
        """场景结束草稿态时，复位绘制控制台状态。"""
        self.drawingControlDock.setDraftActive(False)
        self.drawingControlDock.setSamplingToolVisible(self.activeToolName if self.activeToolName in self._sampling_tools else None, self.activeToolName in self._sampling_tools)
        pending_count = len(getattr(self.scene, "_pending_points", []))
        if self.activeToolName == "曲线/折线":
            self.drawingControlDock.setSamplingTool(self.activeToolName)
            self.drawingControlDock.sync_sampling_settings(self.activeToolName)
            self.drawingControlDock.setCurveModeVisible(True)
            self.drawingControlDock.confirmButton.setEnabled(pending_count >= 2)
            self.drawingControlDock.cancelButton.setEnabled(pending_count >= 1)
            return

        if self.activeToolName in self._sampling_tools:
            self.drawingControlDock.setSamplingTool(self.activeToolName)
            self.drawingControlDock.sync_sampling_settings(self.activeToolName)
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.confirmButton.setEnabled(False)
            self.drawingControlDock.cancelButton.setEnabled(pending_count >= 1)
            return

        if self.activeToolName in self._drawing_tools and pending_count >= 1:
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.confirmButton.setEnabled(False)
            self.drawingControlDock.cancelButton.setEnabled(True)
            return

        self.drawingControlDock.setCurveModeVisible(False)
        self.drawingControlDock.confirmButton.setEnabled(False)
        self.drawingControlDock.cancelButton.setEnabled(False)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "drawingControlDock") and self.drawingControlDock.isVisible():
            self._positionDrawingControlDock()
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
