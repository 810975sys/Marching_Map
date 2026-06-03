import sys
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QToolBar,
    QVBoxLayout, QWidget, QFileDialog, 
    QHBoxLayout, QPushButton, QSizePolicy, QToolButton, QGridLayout, QFrame,
    QLabel, QLineEdit, QSlider, QButtonGroup, QDialog,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QIcon
from pathlib import Path

# 导入自定义场景
from field_info import (
    SCALE_MIN,
    SCALE_MAX,
    ZOOM_PERCENT_FACTOR,
    ZOOM_PERCENT_MIN,
    ZOOM_PERCENT_MAX,
    field_default_dir, 
    saveFieldInfo, 
    loadFieldInfo, 
)
from field_move import FieldMove
from scheme_scene import SchemeScene
from field_settings_dock import FieldSettingsDock
from timeline_widget import TimelineWidget, TimelineScrollArea
# from mainwindow_docks import DrawingControlDock, TimelineScrollArea, ToolOptionDock
from drawing_control_dock import DrawingControlDock
from mainwindow_notice import MainWindowNotice
from tip_window import TipWindow
# from field_info import _field_default_dir


def scheme_default_dir() -> Path:
    """获取方案文件默认目录。"""
    project_root = Path(__file__).resolve().parent.parent
    directory = project_root / "saves"
    directory.mkdir(parents=True, exist_ok=True)
    return directory

class MainWindow(MainWindowNotice, QMainWindow):
    """主窗口：组织菜单、场景、时间轴与各类控制台。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scheme_file_path: Path | None = None
        self._scheme_dirty = False
        self._scheme_dirty_suppressed = False
        # 工具栏按钮映射：工具名 -> QToolButton
        self.toolButtons = {}   # 保存工具按钮引用，便于根据工具名更新按钮状态
        self.activeToolName = "框选"
        # self.pendingToolName = None
        self._sampling_tools = {"线段", "弧", "曲线/折线", "圆", "多边形", "填充四边形", "路径"}    # 需要在绘制控制台显示采样设置的工具（"路径" 为特例，仅显示曲线模式）
        # self._dialog_required_tools = {
        #     "线段", "弧", "曲线/折线", "填充四边形", "圆", "多边形",
        #     "调整", "跟随", "路径", "间隔行进",
        #     "标签", "文本", "箭头",
        # }
        self._drawing_tools = {"点", "线段", "弧", "曲线/折线", "填充四边形", "圆", "多边形", "路径"}
        self._text_tools = {"文本"}
        self._group_tools = {"分组"}
        self._select_tools = {"选择", "框选"}
        self._transform_tools = {"调整", "跟随", "路径", "间隔行进"}
        self._p0_forbidden_transform_tools = {"跟随", "路径", "间隔行进"}
        
        self.setupMenus()   # 菜单栏
        self.setupToolBar()    # 工具栏
        # self.setupDockWidgets()
        self.setupCentralView() # 主场景视图
        self.setupTimeline()    # 底部时间轴
        self.setupInteractions()    # 信号与槽绑定
        self.setupMainLayout()  # 主窗口整体布局
        self.setupFieldSettingsDock()   # 场地设置浮动面板
        # self.setupToolOptionDock()      # 工具选项浮动面板
        self.setupDrawingControlDock()  # 绘制控制浮动面板
        
        self.setWindowTitle("Marching Map Editor")
        self.resize(1200, 800)
        self.showMaximized() # 默认最大化窗口


    def setupMenus(self):
        """创建主菜单及快捷操作。"""
        fileMenu = self.menuBar().addMenu("文件")
        new = fileMenu.addAction("新建方案")
        new.setShortcut("Ctrl+N")
        new.triggered.connect(self._new_scheme)
        open = fileMenu.addAction("打开")
        open.setShortcut("Ctrl+O")
        open.triggered.connect(self._open_scheme)
        save = fileMenu.addAction("保存")
        save.setShortcut("Ctrl+S")
        save.triggered.connect(self._save_scheme)
        saveAs = fileMenu.addAction("另存为")
        saveAs.setShortcut("Ctrl+Shift+S")
        saveAs.triggered.connect(self._save_scheme_as)
        fileMenu.addSeparator()
        export_pdf = fileMenu.addAction("导出为PDF")
        export_pdf.triggered.connect(self._export_pdf)
        fileMenu.addSeparator()
        fileMenu.addAction("设置")  # 设置字号、点位大小、颜色、拖动框等全局设置

        # 撤销和重做直接作为主菜单栏按钮，添加图标
        undo_icon = QIcon.fromTheme("edit-undo")
        redo_icon = QIcon.fromTheme("edit-redo")
        undo = self.menuBar().addAction(undo_icon, "撤销")
        undo.setShortcut("Ctrl+Z")
        redo = self.menuBar().addAction(redo_icon, "重做")
        redo.setShortcut("Ctrl+Y")

        # 场地设置
        groundMenu = self.menuBar().addMenu("场地")
        self.actionGroundImport = groundMenu.addAction("导入")
        self.actionGroundImport.triggered.connect(self._load_field_info)
        self.actionGroundSave = groundMenu.addAction("保存")
        self.actionGroundSave.triggered.connect(self._save_field_info)
        self.actionGroundModify = groundMenu.addAction("修改")

        self.actionDeletePoint = self.menuBar().addAction("删除点位")
        self.actionDeletePoint.setShortcut("Delete")
        self.actionDeletePoint.setEnabled(False)
        self.actionDeletePoint.triggered.connect(self._on_delete_points_triggered)
        
        self.tips = self.menuBar().addAction("Tips")
        self.tips.triggered.connect(self._show_tips_window)
        self.tipWindow = TipWindow(self)

        # 菜单栏右侧非阻塞提示。
        self.setup_menu_notice()

    def _show_tips_window(self):
        """显示 Tips 弹窗，若已存在则直接前置。"""
        if self.tipWindow.isVisible():
            self.tipWindow.raise_()
            self.tipWindow.activateWindow()
            return

        self.tipWindow.show()
        self.tipWindow.raise_()
        self.tipWindow.activateWindow()

    def _set_scheme_dirty(self, dirty: bool = True):
        """更新当前方案是否存在未保存修改。"""
        if self._scheme_dirty_suppressed:
            return
        self._scheme_dirty = bool(dirty)

    def _mark_scheme_dirty(self, *args):
        """标记当前方案为未保存。"""
        self._set_scheme_dirty(True)

    def _prompt_unsaved_changes(self, operation_name: str) -> str | None:
        """在丢弃未保存修改前询问用户如何处理。"""
        if not self._scheme_dirty:
            return "discard"

        dialog = QDialog(self)
        dialog.setWindowTitle(operation_name)
        layout = QVBoxLayout(dialog)
        layout.addWidget(QLabel(f"当前方案有未保存修改，是否在{operation_name}前保存？", dialog))

        button_row = QHBoxLayout()
        save_button = QPushButton("保存", dialog)
        save_as_button = QPushButton("另存为", dialog)
        discard_button = QPushButton("不保存", dialog)
        cancel_button = QPushButton("取消", dialog)
        save_button.setDefault(True)

        dialog.result_action = None
        save_button.clicked.connect(lambda: (setattr(dialog, "result_action", "save"), dialog.accept()))
        save_as_button.clicked.connect(lambda: (setattr(dialog, "result_action", "save_as"), dialog.accept()))
        discard_button.clicked.connect(lambda: (setattr(dialog, "result_action", "discard"), dialog.accept()))
        cancel_button.clicked.connect(lambda: (setattr(dialog, "result_action", None), dialog.reject()))

        button_row.addWidget(save_button)
        button_row.addWidget(save_as_button)
        button_row.addWidget(discard_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        dialog.exec()
        return getattr(dialog, "result_action", None)

    def _ensure_scheme_can_be_replaced(self, operation_name: str) -> bool:
        """在打开或新建前处理未保存修改。"""
        decision = self._prompt_unsaved_changes(operation_name)
        if decision is None:
            return False
        if decision == "save":
            return self._save_scheme()
        if decision == "save_as":
            return self._save_scheme_as()
        return True
        
    def _save_field_info(self):
        # try:
        default_path = field_default_dir() / "field_settings.json"
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存场地设置",
            str(default_path),
            "JSON 文件 (*.json)",
        )
        if not file_path:
            return

        saveFieldInfo(self.scene.field_info, file_path)
        self._show_menu_notice("保存成功！")
        # except Exception as e:
        #     print(e)
        #     self._show_menu_notice(f"保存失败：{e}", failed=True)

    def _build_scheme_payload(self) -> dict:
        """收集当前方案的已确认数据。"""
        return {
            "schema_version": 1,
            "field_info": self.scene.field_info.to_dict(),
            "graph_list": list(self.timelineMainWidget.graph_list),
            "scene": self.scene.export_confirmed_state(),
        }

    def _apply_scheme_payload(self, payload: dict):
        """将方案文件内容恢复到当前窗口。"""
        if not isinstance(payload, dict):
            raise ValueError("方案文件格式无效")

        self._scheme_dirty_suppressed = True
        try:
            graph_list = payload.get("graph_list", [0])
            if not isinstance(graph_list, list):
                raise ValueError("方案文件中的 graph_list 格式无效")
            self.timelineMainWidget.set_graph_list(graph_list, selected_node=0, current_beat=0, emit_signals=False)

            scene_data = payload.get("scene", {})
            self.scene.load_confirmed_state(scene_data, node_count=len(self.timelineMainWidget.graph_list))

            self._apply_active_tool("框选")
            self._configure_drawing_control_dock("框选")
            self.drawingControlDock.hide()

            self.onTimelineNodeSelected(self.timelineMainWidget.selected_node)
            self.scene.set_preview_beat(self.timelineMainWidget.current_beat)

            field_info_data = payload.get("field_info", {})
            self.scene.field_info.load_from_dict(field_info_data)

            self._scheme_file_path = None
        finally:
            self._scheme_dirty_suppressed = False
        self._set_scheme_dirty(False)

    def _save_scheme_to_path(self, file_path: str | Path):
        """将当前方案保存到指定文件。"""
        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = self._build_scheme_payload()
        with open(target, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)
        self._scheme_file_path = target
        self._set_scheme_dirty(False)
        self._show_menu_notice(f"已保存：{target.name}")
        return True

    def _save_scheme_as(self, checked=False):
        """另存为当前方案。"""
        default_path = self._scheme_file_path or (scheme_default_dir() / "marching_map_scheme.json")
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "另存为方案",
            str(default_path),
            "方案文件 (*.json)",
        )
        if not file_path:
            return False
        # try:
        self._save_scheme_to_path(file_path)
        return True
        # except Exception as e:
        #     print(e)
        #     self._show_menu_notice(f"另存为失败：{e}", failed=True)
        #     return False

    def _save_scheme(self, checked=False):
        """保存当前方案；若尚未指定文件则转为另存为。"""
        if self._scheme_file_path is None:
            return self._save_scheme_as()
        # try:
        self._save_scheme_to_path(self._scheme_file_path)
        return True
        # except Exception as e:
        #     print(e)
        #     self._show_menu_notice(f"保存失败：{e}", failed=True)
        #     return False

    def _open_scheme(self, checked=False):
        """打开方案文件并恢复到当前窗口。"""
        if not self._ensure_scheme_can_be_replaced("打开方案"):
            return False
        default_path = self._scheme_file_path or (scheme_default_dir() / "marching_map_scheme.json")
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "打开方案",
            str(default_path),
            "方案文件 (*.json)",
        )
        if not file_path:
            return False
        # try:
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        self._apply_scheme_payload(payload)
        self._scheme_file_path = Path(file_path)
        self._show_menu_notice(f"已打开：{Path(file_path).name}")
        return True
        # except Exception as e:
        #     print(e)
        #     self._show_menu_notice(f"打开失败：{e}", failed=True)
        #     return False

    def _export_pdf(self, checked=False):
        """将每个方案图节点导出为一页 A4 PDF。"""
        
        if self._scheme_file_path is None:
            return self._save_scheme_as()
        # try:
        self._save_scheme_to_path(self._scheme_file_path)
        
        # default_name = "marching_map_export.pdf"
        # default_path = (
        #     (self._scheme_file_path.with_suffix(".pdf") if self._scheme_file_path is not None else (scheme_default_dir() / default_name))
        # )
        # file_path, _ = QFileDialog.getSaveFileName(
        #     self,
        #     "导出为 PDF",
        #     str(default_path),
        #     "PDF 文件 (*.pdf)",
        # )
        # if not file_path:
        #     return False

        # try:
        pdf_path = self._scheme_file_path
        stem = pdf_path.stem
        conductor = pdf_path.with_name(f"{stem}_指挥视角.pdf")
        performer = pdf_path.with_name(f"{stem}_表演者视角.pdf")
        self.scene.export_conductor_pdf(conductor, self.timelineMainWidget.graph_list)
        self.scene.export_performer_pdf(performer, self.timelineMainWidget.graph_list)

        self._show_menu_notice(f"已导出 pdf 到 {stem}")
        return True
        # except Exception as e:
        #     self._show_menu_notice(f"导出失败：{e}", failed=True)
        #     print(e)
        #     return False

    def _new_scheme(self, checked=False):
        """新建一个空白方案。"""
        if not self._ensure_scheme_can_be_replaced("新建方案"):
            return False
        self._scheme_dirty_suppressed = True
        try:
            self._scheme_file_path = None
            self.scene.load_confirmed_state({})
            self.timelineMainWidget.set_graph_list([0], selected_node=0, current_beat=0, emit_signals=False)
            self._apply_active_tool("框选")
            self._configure_drawing_control_dock("框选")
            self.drawingControlDock.hide()
            self.onTimelineNodeSelected(0)
            self.scene.set_preview_beat(0)
        finally:
            self._scheme_dirty_suppressed = False
        self._set_scheme_dirty(False)
        self._show_menu_notice("已新建空白方案")
        return True

    def closeEvent(self, event):
        """关闭窗口前处理未保存修改。"""
        decision = self._prompt_unsaved_changes("退出")
        if decision is None:
            event.ignore()
            return
        if decision == "save":
            if not self._save_scheme():
                event.ignore()
                return
        elif decision == "save_as":
            if not self._save_scheme_as():
                event.ignore()
                return
        event.accept()

    def _load_field_info(self):
        # try:
        default_path = field_default_dir() / "field_settings.json"
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入场地设置",
            str(default_path),
            "JSON 文件 (*.json)",
        )
        if not file_path:
            return

        loadFieldInfo(self.scene.field_info, Path(file_path))
        # self.scene.set_field_info(field_info)
        self._show_menu_notice("导入成功！")
        # except Exception as e:
        #     print(e)
        #     self._show_menu_notice(f"导入失败：{e}", failed=True)
            # print(f"Error loading field info: {e}")
    
    def setupToolBar(self):
        """
        自定义多行分组工具栏示例：每组工具用QWidget+QGridLayout实现多行，组间用竖直分割线分隔，整体放在主窗口顶部。
        保留目前的分组与布局设置。
        """
        rows = 2  # 每组工具的行数
        # 工具分组及布局（每组：按钮文本列表，行数，列数）
        tool_groups = [
            ['选择', '框选'],   # 选择工具
            ['点', '线段', '弧', '曲线/折线', '填充四边形', '圆', '多边形'],    # 绘制工具
            ['调整', '分组'],   # 调整工具
            ['跟随', '路径', '间隔行进'],   # 变换工具
            ['标签', '文本', '箭头']    # 标注工具
        ]
        
        # 创建按钮组并设为互斥模式，确保工具按钮单选
        self.toolButtonGroup = QButtonGroup(self)
        self.toolButtonGroup.setExclusive(True)
        
        container = QWidget(self)   # 实例化窗口容器，放置工具按钮和分割线
        h_layout = QHBoxLayout()    # 水平布局容器，组间用竖线分隔
        h_layout.setContentsMargins(0, 0, 0, 0) # 去掉外边距，让工具栏紧贴边缘
        h_layout.setSpacing(8)  # 组间水平间距，分割线宽度会占用部分空间，无需过大

        # 根据工具分组创建按钮，并添加到布局中
        for idx, group in enumerate(tool_groups):
            # 组间添加竖直分割线（最后一组不加）
            if idx > 0: 
                line = QFrame() # 实例化竖直分割线
                line.setFrameShape(QFrame.Shape.VLine)      # 竖线
                line.setFrameShadow(QFrame.Shadow.Sunken)   # 凹陷效果
                h_layout.addWidget(line)    # 添加分割线到布局
            
            cols = (len(group) + rows - 1) // rows  # 计算列数
            group_widget = QWidget()    # 实例化工具组容器
            grid = QGridLayout()        # 实例化布局控件
            grid.setContentsMargins(0, 0, 0, 0) # 去掉内边距，让按钮紧凑排列
            grid.setSpacing(2)          # 设置按钮间距
            
            # 创建工具按钮，设置为可切换状态，并连接点击事件
            for i, name in enumerate(group):
                btn = QToolButton()     # 实例化按钮
                btn.setText(name)       # 设置按钮文本
                btn.setCheckable(True)  # 使按钮可切换状态
                # 连接点击事件，传递工具名和选中状态
                btn.clicked.connect(lambda checked=False, tool_name=name: self.onToolButtonClicked(tool_name))
                self.toolButtons[name] = btn    # 保存按钮引用，便于后续状态更新
                self.toolButtonGroup.addButton(btn)         # 将按钮添加到按钮组
                grid.addWidget(btn, i // cols, i % cols)    # 添加按钮到网格布局，自动换行
            group_widget.setLayout(grid)        # 设置组容器布局
            h_layout.addWidget(group_widget)    # 添加组容器到水平布局
        container.setLayout(h_layout)           # 设置总容器布局
        
        # 用QToolBar包裹，便于后续扩展
        toolBar = QToolBar("自定义工具栏", self)    # 创建工具栏
        toolBar.addWidget(container)    # 将自定义布局的容器添加到工具栏
        self.addToolBar(Qt.ToolBarArea.TopToolBarArea, toolBar) # 将工具栏添加到主窗口顶部

        # 初始化时设置默认工具状态
        if self.activeToolName in self.toolButtons:
            self.toolButtons[self.activeToolName].setChecked(True)

    def onToolButtonClicked(self, tool_name: str):
        """处理工具栏按钮点击，并在需要时转到浮动控制台确认。"""
        # if not checked:
        #     if self.activeToolName == tool_name and tool_name in self.toolButtons:
        #         self.toolButtons[tool_name].setChecked(True)
        #     return
        tool_text = {
            '点': "点击绘制参考点；拖动空心矩形可对单点进行修正。",
            '线段': "确定线段起止点；拖动空心矩形可对单点进行修正。",
            '弧': "确定弧的起止点和弧上任意一点；拖动空心矩形可对单点进行修正。",
            '圆': "确定圆心和圆上任意一点；拖动空心矩形可对单点进行修正。",
            '多边形': "确定多边形中心点及一个顶点；拖动空心矩形可对单点进行修正。",
            '填充四边形': "确定填充四边形三个顶点；拖动空心矩形可对单点进行修正。",
            '曲线/折线': "确定曲线/折线的经过点；拖动空心矩形可对单点进行修正。",
            '文本': "确定对角点绘制文本框",
            '调整': "拖动角点与中心点调整所选点位",
            '分组': "对点位分组进行连接、分割", 
        }
        self.drawingControlDock.statusLabel.setText(tool_text.get(tool_name, ""))

        if tool_name == "调整" and not self.scene._selected_point_ids:
            self._show_menu_notice("请先选中点位，再进入调整模式。", failed=True)
            self._set_active_tool("框选")
            return

        self._apply_active_tool(tool_name)
        self._configure_drawing_control_dock(tool_name)

        if tool_name in self._select_tools:
            self.drawingControlDock.hide()
        else:
            self.drawingControlDock.show()
            self._positionDrawingControlDock()
            self.drawingControlDock.raise_()
        
    def setupCentralView(self):
        """创建场景与视图。"""
        self.scene = SchemeScene(self)
        self.view = FieldMove(self.scene, self)
        # self.view.setScene(self.scene)
        # setCentralWidget 在 setupTimeline 里统一设置

    def setupTimeline(self):
        """创建底部时间轴与播放控制区。"""
        # 时间轴主容器
        self.timelineWidget = QWidget(self)     # 实例化窗口容器
        self.timelineWidget.setFixedHeight(72)  # 设置时间轴区域高度，确保足够显示工具按钮和时间轴内容
        self.timelineWidget.setStyleSheet("background:#f0f0f0;")    # 设置背景色

        # 左侧动画播放组件区域
        self.animControlWidget = QWidget(self.timelineWidget)
        animLayout = QHBoxLayout()
        animLayout.setContentsMargins(8, 0, 8, 0)   # 设置内边距，让按钮不贴边显示
        animLayout.setSpacing(4)    # 设置按钮间距
        # 预留播放、暂停、前进、后退等按钮
        self.btnPlayPause = QPushButton("▶", self.animControlWidget)
        self.btnPlayPause.setFixedSize(48, 32)  # 加宽主播放按钮
        # self.btnPrev = QPushButton("⏮", self.animControlWidget)
        # self.btnPrev.setFixedSize(32, 32)
        # self.btnNext = QPushButton("⏭", self.animControlWidget)
        # self.btnNext.setFixedSize(32, 32)

        # 设置更大字体
        btnFont = self.btnPlayPause.font()
        btnFont.setPointSize(18)
        self.btnPlayPause.setFont(btnFont)
        animLayout.addWidget(self.btnPlayPause)
        # for btn in [self.btnPrev, self.btnPlayPause, self.btnNext]:
        #     btn.setFont(btnFont)
        #     animLayout.addWidget(btn)

        # 播放/暂停切换逻辑（仅UI，后续可绑定实际播放状态）
        def toggle_play_pause():
            if self.btnPlayPause.text() == "▶":
                self.btnPlayPause.setText("⏸")
            else:
                self.btnPlayPause.setText("▶")
        self.btnPlayPause.clicked.connect(toggle_play_pause)    # 绑定按钮点击事件
        self.animControlWidget.setLayout(animLayout)    # 设置布局
        self.animControlWidget.setFixedWidth(80)       # 设置固定宽度，确保播放控制区大小稳定
        self.animControlWidget.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Expanding)    # 水平固定，垂直扩展

        # 右侧时间轴主控件（横向滚动，不压缩每拍宽度）
        self.timelineMainWidget = TimelineWidget(self.timelineWidget)
        self.timelineScrollArea = TimelineScrollArea(self.timelineWidget)
        self.timelineScrollArea.setWidget(self.timelineMainWidget)  # 将时间轴主控件放入滚动区域
        self.timelineScrollArea.setWidgetResizable(False)           # 不允许自动调整大小，保持每拍固定宽度，启用水平滚动条
        self.timelineScrollArea.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)  # 需要时显示水平滚动条
        self.timelineScrollArea.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)   # 始终隐藏垂直滚动条
        self.timelineScrollArea.setFrameShape(QFrame.Shape.NoFrame) # 去掉滚动区域边框
        self.timelineScrollArea.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)   # 水平扩展，垂直扩展，填满剩余空间

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
        self.timelineMainWidget.timelineChanged.connect(self._mark_scheme_dirty)
        self.timelineMainWidget.currentBeatChanged.connect(self.scene.set_preview_beat)
        self.timelineMainWidget.currentBeatChanged.connect(self.updateDrawToolAvailability)
        self.timelineMainWidget.currentBeatChanged.connect(self.updateConvertToolAvailability)

        self.timelineMainWidget.nodeAdded.connect(self.scene.on_node_added)
        self.timelineMainWidget.nodeInserted.connect(self.scene.on_node_inserted)
        self.timelineMainWidget.nodeDeleted.connect(self.onTimelineNodeDeleted)
        
        self.scene.selectedPointsChanged.connect(self.onSelectedPointsChanged)
        self.scene.drawingRematchStateChanged.connect(self._sync_drawing_rematch_controls)
        self.scene.textBoxSelectionChanged.connect(self._on_textbox_selection_changed)
        self.scene.dataChanged.connect(self._mark_scheme_dirty)
        self.scene.field_info.changed.connect(self._mark_scheme_dirty)
        self.scene.draftStarted.connect(self.onDraftStarted)
        self.scene.draftFinished.connect(self.onDraftFinished)
        # self.scene.lineSegmentPointCountChanged.connect(self.onLineSegmentPointCountChanged)
        # self.scene.lineSegmentSpacingChanged.connect(self.onLineSegmentSpacingChanged)
        self.scene.samplingPointCountChanged.connect(self.onSamplingPointCountChanged)
        self.scene.samplingSpacingChanged.connect(self.onSamplingSpacingChanged)
        self.scene.samplingShiftSpacingChanged.connect(self.onSampling2ndSpacingChanged)
        self.scene.samplingShiftPointCountChanged.connect(self.onSampling2ndPointCountChanged)

        self.scene.set_active_tool(self.activeToolName)
        self.onTimelineNodeSelected(self.timelineMainWidget.selected_node)  # 根据当前时间轴选中节点初始化场景状态
        # 初始化场景预览拍位，确保启动时状态与时间轴一致。
        self.scene.set_preview_beat(self.timelineMainWidget.current_beat)

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
        self.scene.set_active_tool(tool_name)

    def _configure_drawing_control_dock(self, tool_name: str):
        """按当前工具切换绘制控制台的可见内容"""
        self.drawingControlDock.setAdjustmentControlsVisible(tool_name == "调整")
        self.drawingControlDock.setDrawingRematchVisible(False)
        self.drawingControlDock.setTextBoxControlsVisible(tool_name == "文本")
        self.drawingControlDock.setGroupSettingVisible(tool_name == "分组")
        if tool_name == "调整":
            # self.drawingControlDock.setOperationLabels("确认调整 Enter", "取消调整 Esc")
            self.drawingControlDock.setSamplingToolVisible(None, False)
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.setDraftActive(True)
            self.drawingControlDock.confirmButton.setEnabled(True)
            self.drawingControlDock.cancelButton.setEnabled(True)
            self.drawingControlDock.setAdjustmentMode(self.scene._adjustment_mode)
            self.drawingControlDock.setAdjustmentRotation(self.scene._adjustment_rotation)
            return

        if tool_name == "文本":
            self.drawingControlDock.setSamplingToolVisible(None, False)
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.setDraftActive(True)
            self.drawingControlDock.confirmButton.setEnabled(True)
            self.drawingControlDock.cancelButton.setEnabled(True)
            self.drawingControlDock.setTextBoxFontSize(int(getattr(self.scene, "_textbox_font_size", 14)))
            self.drawingControlDock.setDeleteTextBoxEnabled(False)
            return

        if tool_name == "分组":
            self.drawingControlDock.setSamplingToolVisible(None, False)
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.setDraftActive(False)
            self.scene.start_temp_group_edit_from_selection()   # 初始化临时分组
            self.drawingControlDock.confirmButton.setEnabled(True)
            self.drawingControlDock.cancelButton.setEnabled(True)
            return

        # self.drawingControlDock.setOperationLabels("确认绘制 Enter", "取消绘制 Esc")
        self.drawingControlDock.setSamplingToolVisible(tool_name if tool_name in self._sampling_tools else None, tool_name in self._sampling_tools)
        self.drawingControlDock.setCurveModeVisible(tool_name in {"曲线/折线", "路径", "跟随"})
        self.drawingControlDock.setDraftActive(tool_name == "点")
        if tool_name in self._sampling_tools:
            self.drawingControlDock.sync_sampling_settings(tool_name)
        self.drawingControlDock.confirmButton.setEnabled(False)
        self.drawingControlDock.cancelButton.setEnabled(False)
        self._sync_drawing_rematch_controls()

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
        self.updateContextToolAvailability(self.timelineMainWidget.current_beat, int(selected_count))
        # 启用/禁用 删除点位 菜单
        self.actionDeletePoint.setEnabled(int(selected_count) > 0)
        if self.activeToolName == "调整":
            self.scene.refresh_adjustment_preview()
        self._sync_drawing_rematch_controls()

    def _sync_drawing_rematch_controls(self):
        """根据场景中的绘图重匹配状态同步控制台按钮。"""
        if not hasattr(self, "drawingControlDock"):
            return
        if self.activeToolName not in self._drawing_tools:
            self.drawingControlDock.setDrawingRematchVisible(False)
            return

        status = self.scene._drawing_rematch_snapshot()
        visible = bool(status.get("selected_ids")) and self.activeToolName not in {"路径", "跟随"}
        self.drawingControlDock.setDrawingRematchVisible(visible)
        if not visible:
            return

        # 当进入重匹配激活状态时，允许确认操作（由场景逻辑控制实际写回行为），因此在 active 时直接启用确认按钮；
        # 非 active 时保留当前按钮状态。
        confirm_enabled = True if bool(status.get("active", False)) else self.drawingControlDock.confirmButton.isEnabled()
        self.drawingControlDock.setDrawingRematchState(
            rematch_enabled=bool(status.get("rematch_enabled", False)),
            previous_enabled=bool(status.get("previous_enabled", False)),
            next_enabled=bool(status.get("next_enabled", False)),
            keep_enabled=bool(status.get("keep_enabled", False)),
            confirm_enabled=confirm_enabled,
        )


    def onSamplingPointCountChanged(self, tool_name: str, point_count: int):
        """采样点数自动变化时，同步控制台显示。"""
        # if not hasattr(self, "drawingControlDock"):
        #     return
        if tool_name not in self._sampling_tools or tool_name != self.activeToolName:
            return
        if getattr(self.drawingControlDock, "linePointCountAutoButton", None) is not None and self.drawingControlDock.linePointCountAutoButton.isChecked():
            self.drawingControlDock.sync_sampling_settings(tool_name)
            return
        self.drawingControlDock.setSamplingTool(tool_name)
        self.drawingControlDock.setLinePointCount(int(point_count))

    def onSamplingSpacingChanged(self, tool_name: str, spacing: float):
        """圆、弧、多边形等采样间隔自动变化时，同步控制台显示。"""
        # if not hasattr(self, "drawingControlDock"):
        #     return
        if tool_name not in self._sampling_tools or tool_name != self.activeToolName:
            return
        self.drawingControlDock.setSamplingTool(tool_name)
        self.drawingControlDock.lineSpacingSpin.blockSignals(True)
        self.drawingControlDock.lineSpacingSpin.setValue(float(spacing))
        self.drawingControlDock.lineSpacingSpin.blockSignals(False)

    def onSampling2ndPointCountChanged(self, tool_name: str, point_count: int):
        """填充四边形的 P0-P2 点位个数变化时，同步控制台显示。"""
        # if not hasattr(self, "drawingControlDock"):
        #     return
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

    def onSampling2ndSpacingChanged(self, tool_name: str, spacing: float):
        """填充四边形的第二方向间隔变化时，同步控制台显示。"""
        # if not hasattr(self, "drawingControlDock"):
        #     return
        if self.activeToolName != tool_name:
            return
        # 仅在填充四边形工具时生效
        if tool_name != "填充四边形":
            return
        self.drawingControlDock.lineShiftSpacingSpin.blockSignals(True)
        self.drawingControlDock.lineShiftSpacingSpin.setValue(float(spacing))
        self.drawingControlDock.lineShiftSpacingSpin.blockSignals(False)

    def onTimelineNodeDeleted(self, deleted_index: int):
        """方案图节点删除后同步场景数据并重置选中状态。"""
        # 关键：时间轴删除只是拍数与索引变化，场景里的 node_points/node_shapes
        # 也必须按同样规则重排，否则会出现“拍数对了但点位串位”的问题。
        self.scene.on_node_deleted(deleted_index)
        self.onTimelineNodeSelected(self.timelineMainWidget.selected_node)

    def updateDrawToolAvailability(self, beat: int, has_selection: bool = False):
        """根据当前节拍和选中点位数量，控制绘制工具可用性。"""
        is_p0 = int(beat) == 0
        beat_at_node = self.timelineMainWidget.node_index_at_beat(beat) is not None
        for name in self._drawing_tools:
            btn = self.toolButtons.get(name)
            if btn is not None:
                btn.setEnabled(beat_at_node and (is_p0 or has_selection))
        for name in self._text_tools:
            btn = self.toolButtons.get(name)
            if btn is not None:
                btn.setEnabled(bool(beat_at_node))
                
    def updateConvertToolAvailability(self, beat: int, has_selection: bool = False):
        """根据当前节点和选中点位数量，控制变换工具可用性。"""
        is_p0 = int(beat) == 0
        beat_at_node = self.timelineMainWidget.node_index_at_beat(beat) is not None
        for name in self._transform_tools:
            btn = self.toolButtons.get(name)
            if btn is not None:
                btn.setEnabled(beat_at_node and has_selection and not (is_p0 and name in self._p0_forbidden_transform_tools))

    def updateGroupToolAvailability(self, beat: int, selected_count: int):
        """根据当前节点和选中点位数量，控制分组工具可用性并在必要时回退工具。"""
        can_group = int(selected_count) >= 2
        beat_at_node = self.timelineMainWidget.node_index_at_beat(beat) is not None
        for name in self._group_tools:
            btn = self.toolButtons.get(name)
            if btn is not None:
                btn.setEnabled(beat_at_node and can_group)
        # 如果当前处于分组工具但不满足分组条件，回退到框选
        if self.activeToolName in self._group_tools and not can_group:
            self._set_active_tool("框选")

    def updateContextToolAvailability(self, beat: int, selected_count: int):
        """根据当前节点和选中点位数量，控制绘制与变换工具可用性。"""
        is_p0 = int(beat) == 0
        has_selection = int(selected_count) > 0

        self.updateDrawToolAvailability(beat, has_selection)
        self.updateConvertToolAvailability(beat, has_selection)
        self.updateGroupToolAvailability(beat, selected_count)

        # 自动切换工具：如果当前工具不可用，且没有选中点位，则切换到框选；如果在P0且当前工具在P0禁止列表中，也切换到框选。
        if not (is_p0 or has_selection) and (self.activeToolName in self._drawing_tools | self._transform_tools):
            self._set_active_tool("框选")
        elif is_p0 and self.activeToolName in self._p0_forbidden_transform_tools:
            self._set_active_tool("框选")
        elif self.timelineMainWidget.node_index_at_beat(beat) is None and self.activeToolName in self._text_tools:
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
        zoomSlider.setValue(int(self.scene.field_info.scale * ZOOM_PERCENT_FACTOR))  # scale=10~100 -> 50~500%
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
        orig_set_scale = self.scene.field_info.set_scale
        def on_zoom_slider(val):
            """根据滑块值设置缩放，并更新输入框显示。"""
            # 50~500 -> scale 10~100
            scale = int(val / ZOOM_PERCENT_FACTOR)
            scale = max(SCALE_MIN, min(SCALE_MAX, scale))
            orig_set_scale(scale)
            zoomInput.setText(str(val))
            self.scene.update()
        zoomSlider.valueChanged.connect(on_zoom_slider)

        def set_zoom_from_input():
            """从输入框设置缩放，回车或失焦时生效。"""
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
        def set_scale_and_update_slider(scale):
            """在设置缩放的同时更新滑块位置，保持UI同步。"""
            orig_set_scale(scale)
            val = int(scale * ZOOM_PERCENT_FACTOR)
            val = max(ZOOM_PERCENT_MIN, min(ZOOM_PERCENT_MAX, val))
            zoomSlider.blockSignals(True)
            zoomSlider.setValue(val)
            zoomSlider.blockSignals(False)
            zoomInput.setText(str(val))
        self.scene.field_info.set_scale = set_scale_and_update_slider

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
        self.drawingControlDock.setTextBoxControlsVisible(False)
        self.drawingControlDock.setGroupSettingVisible(False)
        self.drawingControlDock.confirmButton.clicked.connect(self._on_control_confirmed)
        self.drawingControlDock.cancelButton.clicked.connect(self._on_control_cancelled)
        self.drawingControlDock.deleteTextBoxButton.clicked.connect(self._on_delete_textbox_requested)
        self.drawingControlDock.textBoxFontSizeSpin.valueChanged.connect(self._on_textbox_font_size_changed)
        self.drawingControlDock.rematchButton.clicked.connect(self._on_drawing_rematch_requested)
        self.drawingControlDock.previousMatchButton.clicked.connect(self._on_drawing_match_previous_requested)
        self.drawingControlDock.nextMatchButton.clicked.connect(self._on_drawing_match_next_requested)
        self.drawingControlDock.keepMatchButton.clicked.connect(self._on_drawing_match_keep_requested)
        self.drawingControlDock.rotationAngleSpin.valueChanged.connect(self.scene.set_adjustment_rotation)
        for mode_name, button in self.drawingControlDock.adjustModeButtons.items():
            button.toggled.connect(lambda checked=False, mode=mode_name: self._on_adjustment_mode_toggled(mode, checked))
        # 分组按钮连接
        self.drawingControlDock.group_split_button.clicked.connect(self.scene.clear_temp_groups)
        self.drawingControlDock.group_set_next_button.clicked.connect(self.scene.set_next_temp_group)

    def _on_adjustment_mode_toggled(self, mode_name: str, checked: bool):
        if not checked or self.activeToolName != "调整":
            return
        self.scene.set_adjustment_mode(mode_name)

    def _on_control_confirmed(self):
        if self.activeToolName == "调整":
            self.scene.confirm_current_adjustment()
        elif self.activeToolName == "文本":
            if self.scene.confirm_textbox_preview() is False:
                return
        elif self.activeToolName == "分组":
            # 将临时分组写回并退出分组模式
            self.scene.confirm_temp_groups()
        else:
            if self.scene.confirm_current_drawing() is False:
                self._sync_drawing_rematch_controls()
                return
        self.onToolButtonClicked("框选")  # 草稿完成后自动切回选择工具

    def _on_control_cancelled(self):
        if self.activeToolName == "调整":
            self.scene.cancel_current_adjustment()
            self.drawingControlDock.setAdjustmentMode(self.scene._adjustment_mode)
            self.drawingControlDock.setAdjustmentRotation(self.scene._adjustment_rotation)
            return
        if self.activeToolName == "文本":
            self.scene.cancel_textbox_preview()
            self.drawingControlDock.setDeleteTextBoxEnabled(False)
            return
        if self.activeToolName == "分组":
            # 取消分组编辑：清除临时分组预览，但保留绘制控制台的内容与可见性
            self.scene.clear_temp_groups()
            self.onToolButtonClicked("框选")
            return
        self.scene.cancel_current_drawing()

    def _on_drawing_rematch_requested(self):
        if self.scene.start_drawing_rematch():
            self._sync_drawing_rematch_controls()

    def _on_drawing_match_previous_requested(self):
        if self.scene.drawing_match_previous():
            self._sync_drawing_rematch_controls()

    def _on_drawing_match_next_requested(self):
        if self.scene.drawing_match_next():
            self._sync_drawing_rematch_controls()

    def _on_drawing_match_keep_requested(self):
        if self.scene.drawing_match_keep():
            self._sync_drawing_rematch_controls()

    def _on_delete_textbox_requested(self):
        if self.activeToolName != "文本":
            return
        if self.scene.delete_selected_textbox():
            self.drawingControlDock.setDeleteTextBoxEnabled(False)

    def _on_textbox_font_size_changed(self, value: int):
        if self.activeToolName != "文本":
            return
        self.scene.set_textbox_font_size(int(value))

    def _on_textbox_selection_changed(self, textbox_id):
        if self.activeToolName != "文本":
            return
        has_selection = textbox_id is not None and int(textbox_id) > 0
        self.drawingControlDock.setDeleteTextBoxEnabled(bool(has_selection))
        self.drawingControlDock.setTextBoxFontSize(int(self.scene.selected_textbox_font_size()))

    def _on_delete_points_triggered(self):
        """响应菜单删除点位：弹出确认对话框，确认后调用场景删除方法。"""
        action = self._confirm_delete_points_dialog(len(self.scene._selected_point_ids))
        if not action:
            return
        # try:
        if action == "delete":
            self.scene.delete_selected_points()
            self._show_menu_notice("删除成功！")
        elif action == "restore":
            self.scene.restore_selected_points_to_prev()
            self._show_menu_notice("已恢复转换点位置。")
        else:
            return
        # except Exception as e:
        #     print(e)
        #     self._show_menu_notice(f"操作失败：{e}", failed=True)

    def _confirm_delete_points_dialog(self, count: int) -> str | None:
        """显示确认对话框，返回动作字符串：'delete'、'restore' 或 None（取消）。"""
        dlg = QDialog(self)
        dlg.setWindowTitle("删除")
        layout = QVBoxLayout()
        label = QLabel(f"确认删除选中的 {count} 个点位？")
        layout.addWidget(label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch(1)
        cancel_btn = QPushButton("取消 Esc", dlg)
        cancel_btn.setShortcut("Esc")
        del_switch = QPushButton("删除转换点 Backspace", dlg)
        del_switch.setShortcut("Backspace")
        del_point = QPushButton("删除表演者 Enter", dlg)
        del_point.setShortcut("Return")
        del_point.setStyleSheet("background:#d9534f;color:white;")
        cancel_btn.clicked.connect(dlg.reject)
        # 区分按钮动作：del_switch -> 恢复转换点（restore），del_point -> 删除点位（delete）
        cancel_btn.clicked.connect(lambda: setattr(dlg, "result_action", None))
        del_switch.clicked.connect(lambda: (setattr(dlg, "result_action", "restore"), dlg.accept()))
        del_point.clicked.connect(lambda: (setattr(dlg, "result_action", "delete"), dlg.accept()))
        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(del_switch)
        btn_layout.addWidget(del_point)
        layout.addLayout(btn_layout)
        dlg.setLayout(layout)
        # p0 仅允许删除表演者点位，禁用恢复按钮
        if getattr(self.scene, "active_node", 0) == 0:
            del_switch.setEnabled(False)

        res = dlg.exec()
        return getattr(dlg, "result_action", None)

    def _positionDrawingControlDock(self):
        """将绘制控制台放到绘图区左上角。"""
        # if not hasattr(self, "drawingControlDock"):
        #     return
        # if not hasattr(self, "view"):
        #     return
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
        self.drawingControlDock.setCurveModeVisible(tool_name in {"曲线/折线", "路径", "跟随"})
        if tool_name in self._sampling_tools:
            self.drawingControlDock.setSamplingTool(tool_name)
            self.drawingControlDock.sync_sampling_settings(tool_name)
        self.drawingControlDock.setFloating(True)
        self.drawingControlDock.confirmButton.setEnabled(True)
        self.drawingControlDock.cancelButton.setEnabled(True)
        self._sync_drawing_rematch_controls()
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
        self._sync_drawing_rematch_controls()
        # 隐藏分组面板（非分组工具时）
        self.drawingControlDock.setGroupSettingVisible(False)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
