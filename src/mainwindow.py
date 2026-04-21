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

class MainWindow(QMainWindow):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupMenus()
        self.setupToolBar_()
        # self.setupDockWidgets()
        self.setupCentralView()
        self.setupTimeline()
        self.setupMainLayout()
        self.setWindowTitle("Marching Map Editor")
        self.resize(1200, 800)

    def setupMenus(self):
        fileMenu = self.menuBar().addMenu("文件")
        new = fileMenu.addAction("新建")
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
        # 初始居中显示场地
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
        mainLayout = QVBoxLayout()
        mainLayout.setContentsMargins(0, 0, 0, 0)
        mainLayout.setSpacing(0)
        mainLayout.addWidget(self.view)
        mainLayout.addWidget(self.timelineWidget)
        central = QWidget(self)
        central.setLayout(mainLayout)
        self.setCentralWidget(central)
        
if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
