import sys
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QMenu, QMenuBar, QToolBar, QDockWidget,
    QGraphicsView, QStatusBar, QVBoxLayout, QWidget,
    QHBoxLayout, QPushButton, QSizePolicy, QToolButton, QGridLayout, QFrame
)
from PyQt6.QtWidgets import QGraphicsScene
from PyQt6.QtCore import Qt

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

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupMenus()
        self.setupToolBar_()
        # self.setupDockWidgets()
        self.setupCentralView()
        self.setupTimeline()
        self.setupMainLayout()
        self.setupFieldSettingsDock()
        self.setWindowTitle("Marching Map Editor")
        self.resize(1200, 800)
        self.showMaximized()

    def setupMenus(self):
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
        fileMenu.addSeparator()
        fileMenu.addAction("设置")

        # 撤销和重做直接作为主菜单栏按钮
        undo = self.menuBar().addAction("撤销")
        undo.setShortcut("Ctrl+Z")
        redo = self.menuBar().addAction("重做")
        redo.setShortcut("Ctrl+Y")
        
        # 场地设置
        groundMenu = self.menuBar().addMenu("场地设置")
        groundMenu.addAction("导入")
        groundMenu.addAction("保存")
        self.actionGroundModify = groundMenu.addAction("修改")

        # 可扩展
        # viewMenu = self.menuBar().addMenu("视图")

    # def setupToolBar(self):
    #     # 工具分组，遇到分隔符就新建一行
    #     tool_groups = [
    #         ["框选", "套索", "选择整组"],
    #         ["点", "直线", "弧", "曲线", "矩形", "圆形", "多边形"],
    #         ["移动/缩放", "旋转", "跟随", "路径"],
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
            ['组选', '框选', '套索'], 
            ['点', '线段', '弧', '曲线/折线', '填充矩形', '圆形', '多边形'],
            ['移动/缩放', '旋转', '跟随', '路径', '间隔行进'],
            ['标签', '文本', '箭头']
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
                grid.addWidget(btn, i // cols, i % cols)
            group_widget.setLayout(grid)
            h_layout.addWidget(group_widget)
        container.setLayout(h_layout)
        # 用QToolBar包裹，便于后续扩展
        toolBar = QToolBar("自定义工具栏", self)
        toolBar.addWidget(container)
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolBar)

    # def setupDockWidgets(self):
    #     self.propertyDock = QDockWidget("属性", self)
    #     self.propertyDock.setWidget(QWidget())  # 后续替换为属性面板
    #     self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.propertyDock)

    #     self.layerDock = QDockWidget("图层", self)
    #     self.layerDock.setWidget(QWidget())  # 后续替换为图层面板
    #     self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.layerDock)

    def setupCentralView(self):
        from scheme_view import SchemeView
        self.scene = SchemeScene(self)
        self.view = SchemeView(self.scene, self)
        # self.view.setScene(self.scene)
        # setCentralWidget 在 setupTimeline 里统一设置

    def setupTimeline(self):
        # 时间轴主容器
        self.timelineWidget = QWidget(self)
        self.timelineWidget.setFixedHeight(80)
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

        # 右侧为时间轴主控件区域（后续可自定义QWidget）
        self.timelineMainWidget = QWidget(self.timelineWidget)
        # 预留布局，后续可添加三层结构控件
        timelineMainLayout = QHBoxLayout()
        timelineMainLayout.setContentsMargins(0, 0, 0, 0)
        self.timelineMainWidget.setLayout(timelineMainLayout)
        self.timelineMainWidget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

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
        timelineLayout.addWidget(self.timelineMainWidget)
        self.timelineWidget.setLayout(timelineLayout)

    def setupMainLayout(self):
        """
        主窗口布局：上方为 self.view（场景视图），下方为 self.timelineWidget（时间轴）
        """
        from PyQt6.QtWidgets import QSlider, QLabel, QHBoxLayout, QLineEdit

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
        zoomInput.setToolTip("输入缩放百分比，回车或失焦生效")
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
        self.fieldSettingsDock = FieldSettingsDock(self)
        self.fieldSettingsDock.bind_scene(self.scene)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.fieldSettingsDock)
        self.fieldSettingsDock.hide()
        self.actionGroundModify.setCheckable(True)
        self.actionGroundModify.toggled.connect(self.fieldSettingsDock.setVisible)
        self.fieldSettingsDock.visibilityChanged.connect(self.actionGroundModify.setChecked)

    def showFieldSettingsDock(self):
        self.fieldSettingsDock.show()
        self.fieldSettingsDock.raise_()
        self.fieldSettingsDock.activateWindow()
        self.actionGroundModify.setChecked(True)
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
