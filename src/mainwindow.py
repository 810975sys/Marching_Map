import sys
import json
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QToolBar,
    QVBoxLayout, QWidget, QFileDialog, 
    QHBoxLayout, QPushButton, QSizePolicy, QToolButton, QGridLayout, QFrame,
    QLabel, QLineEdit, QSlider, QButtonGroup, QDialog, QSpinBox,
    QMessageBox, QProgressDialog,
)
from PyQt6.QtCore import Qt, QTimer, QElapsedTimer, QUrl
from PyQt6.QtGui import QIcon, QShortcut, QKeySequence
from PyQt6.QtMultimedia import QMediaPlayer, QAudioOutput
from pathlib import Path
import time

# 导入自定义场景
from src.field_info import (
    SCALE_MIN,
    SCALE_MAX,
    ZOOM_PERCENT_FACTOR,
    ZOOM_PERCENT_MIN,
    ZOOM_PERCENT_MAX,
    field_default_dir, 
    saveFieldInfo, 
    loadFieldInfo, 
)
from src.field_move import FieldMove
from src.scheme_scene import SchemeScene
from src.field_settings_dock import FieldSettingsDock
from src.timeline_widget import TimelineWidget, TimelineScrollArea
from src.tempo_data import Tempo
from src.drawing_control_dock import DrawingControlDock
from src.app_settings_dock import AppSettingsDock
from src.mainwindow_notice import MainWindowNotice
from src.tip_window import TipWindow


def scheme_default_dir() -> Path:
    """获取方案文件默认目录。"""
    project_root = Path(__file__).resolve().parent.parent
    directory = project_root / "saves"
    directory.mkdir(parents=True, exist_ok=True)
    return directory

# 历史文件：记录最后保存的方案文件路径
LAST_SCHEME_PATH_FILE = Path(__file__).resolve().parent / "last_scheme_path.json"

class MainWindow(MainWindowNotice, QMainWindow):
    """主窗口：组织菜单、场景、时间轴与各类控制台。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scheme_file_path: Path | None = None
        self._scheme_dirty = False
        self._scheme_dirty_suppressed = False
        # 按钮字体大小（由 AppSettingsDock 统一管理）
        self._font_size = 9
        # 播放演示状态
        self._playback_timer = QTimer(self)
        self._playback_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self._playback_timer.timeout.connect(self._on_playback_tick)
        self._playback_active = False
        self._playback_elapsed = QElapsedTimer()
        self._playback_start_beat = 0.0  # 开始播放时的拍位（float）
        # 音频播放（音频为主时钟：有合成音轨时点位向音频当前位置对齐，无音频时按设置速度×经过时间推进）
        self._audio_player = QMediaPlayer(self)
        self._audio_output = QAudioOutput(self)
        self._audio_output.setVolume(1.0)
        self._audio_player.setAudioOutput(self._audio_output)
        # 合成整轨播放：音频/速度/时间轴变化后置为 True，播放前据此重新合成
        self._audio_dirty = True
        self._playback_synth_path: str | None = None   # 当前播放使用的合成整轨音频文件路径
        self._playback_use_synth = False               # 当前播放是否使用合成整轨（否则无音频）
        # 工具栏按钮映射：工具名 -> QToolButton
        self.toolButtons = {}   # 保存工具按钮引用，便于根据工具名更新按钮状态
        self.activeToolName = "框选"
        self._sampling_tools = {"线段", "弧", "曲线/折线", "圆", "多边形", "填充四边形", "路径", "跟随"}    # 需要在绘制控制台显示采样设置的工具（"路径" 为特例，仅显示曲线模式）
        self._drawing_tools = {"点", "线段", "弧", "曲线/折线", "填充四边形", "圆", "多边形", "路径", "跟随"}
        self._text_tools = {"文本"}
        self._label_tools = {"标签"}
        self._group_tools = {"分组"}
        self._select_tools = {"选择", "框选"}
        self._transform_tools = {"调整", "路径", "旋转"}
        self._p0_forbidden_transform_tools = {"跟随", "路径", "间隔", "旋转"}
        self._multi_select_tools = {"跟随", "间隔"}
        
        self.setupMenus()   # 菜单栏
        self.setupToolBar()    # 工具栏
        self.setupCentralView() # 主场景视图
        self.setupTimeline()    # 底部时间轴
        self.setupFieldSettingsDock()   # 场地设置浮动面板
        self.setupDrawingControlDock()  # 绘制控制浮动面板
        self.setupAppSettingsDock()     # 应用设置浮动面板
        self.setupInteractions()    # 信号与槽绑定
        self.setupMainLayout()  # 主窗口整体布局

        # 启动时从历史文件恢复上次编辑的方案
        self._restore_last_scheme()
        
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
        export_pdf = fileMenu.addAction("保存并导出为PDF")
        export_pdf.triggered.connect(self._export_pdf)
        fileMenu.addSeparator()
        self.actionAppSettings = fileMenu.addAction("设置")  # 设置字号、点位大小、颜色、拖动框等全局设置
        self.actionAppSettings.setCheckable(True)

        # 撤销和重做直接作为主菜单栏按钮，添加图标
        # undo_icon = QIcon.fromTheme("edit-undo")
        # redo_icon = QIcon.fromTheme("edit-redo")
        # undo = self.menuBar().addAction(undo_icon, "撤销")
        # undo.setShortcut("Ctrl+Z")
        # redo = self.menuBar().addAction(redo_icon, "重做")
        # redo.setShortcut("Ctrl+Y")

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

    def _mark_audio_dirty(self, *args):
        """标记音频（或其轴对齐依据：时间轴/速度）已变化，需重新合成整轨音频。"""
        self._audio_dirty = True

    def _on_audio_changed(self):
        """音频段数据变化：标记未保存且需重新合成；若正在播放，已加载的合成整轨失效，停止播放。"""
        self._audio_dirty = True
        self._mark_scheme_dirty()
        if self._playback_active and self._playback_use_synth:
            # 合成整轨在播放中发生变化：已加载的合成文件失效，停止播放，下次播放重新合成
            self._stop_playback()

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

    def _build_scheme_payload(self) -> dict:
        """收集当前方案的已确认数据。"""
        return {
            "field_info": self.scene.field_info.to_dict(),
            "tempo_info": self.timelineMainWidget.to_dict(),
            "scene": self.scene.to_dict(),
            "audio": self.timelineMainWidget.audio_to_dict(),
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
            tempo_info = payload.get("tempo_info", {})
            audio_payload = payload.get("audio")
            # 恢复音频段需预解码各源文件（可能耗时），存在音频段时弹出进度提示框，
            # 样式与音频导入一致：无取消按钮、模态、完成后自动关闭。
            segments_data = audio_payload.get("segments", []) if isinstance(audio_payload, dict) else []
            progress = None
            progress_cb = None
            if segments_data:
                progress = QProgressDialog("正在加载音频...", "", 0, len(segments_data), self)
                progress.setWindowTitle("加载音频")
                progress.setWindowModality(Qt.WindowModality.WindowModal)
                progress.setMinimumDuration(0)
                progress.setCancelButton(None)
                progress.setAutoClose(True)
                progress.setAutoReset(False)
                progress.setMinimumWidth(320)
                progress.show()
                QApplication.processEvents()   # 立即显示初始提示，避免首个文件解码期间无反馈

                def _on_audio_load_progress(done: int, n: int, name: str):
                    progress.setValue(done)
                    progress.setLabelText(f"正在加载：{name}（{done}/{n}）")
                    QApplication.processEvents()

                progress_cb = _on_audio_load_progress

            # 音频随 tempo_info 一起恢复（file 为绝对路径，直接按路径读取）
            self.timelineMainWidget.load_from_dict(
                tempo_info, audio_data=audio_payload, progress_cb=progress_cb
            )
            if progress is not None:
                progress.setValue(len(segments_data))   # 加载完成，进度归满
                progress.close()                        # 自动关闭提示框
            self._audio_dirty = True   # 音频段已按方案恢复，播放前需按当前状态重新合成
            # self.timelineMainWidget.set_graph_list(graph_list)

            scene_data = payload.get("scene", {})
            self.scene.load_confirmed_state(scene_data, node_count=len(self.timelineMainWidget.graph_list))

            self._apply_active_tool("框选")
            self._configure_drawing_control_dock("框选")
            self.drawingControlDock.hide()

            self.onTimelineNodeSelected(self.timelineMainWidget.selected_node)
            self.scene.set_preview_beat(self.timelineMainWidget.current_beat)

            field_info_data = payload.get("field_info", {})
            self.scene.field_info.load_from_dict(field_info_data)
            
            self.bpmSpinBox.setValue(int(self.timelineMainWidget._bpm_at_beat(0)))
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
        old_path = self._scheme_file_path
        self._scheme_file_path = target
        if old_path is None or old_path.resolve() != target.resolve():
            self._audio_dirty = True   # 方案保存路径变化 → 合成整轨音频需写到新位置
        self._save_last_scheme_path()
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
        self._save_scheme_to_path(file_path)
        return True

    def _save_scheme(self, checked=False):
        """保存当前方案；若尚未指定文件则转为另存为。"""
        if self._scheme_file_path is None:
            return self._save_scheme_as()
        self._save_scheme_to_path(self._scheme_file_path)
        return True

    def _open_scheme(self, checked=False):
        """打开方案文件并恢复到当前窗口。"""
        self._stop_playback()
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
        with open(file_path, "r", encoding="utf-8") as f:
            payload = json.load(f)
        self._apply_scheme_payload(payload)
        self._scheme_file_path = Path(file_path)
        self._save_last_scheme_path()
        self._show_menu_notice(f"已打开：{Path(file_path).name}")
        return True

    def _export_pdf(self, checked=False):
        """将每个方案图节点导出为一页 A4 PDF。"""
        if self._scheme_file_path is None:
            self._save_scheme_as()
            if self._scheme_file_path is None:
                return False
        else:
            self._save_scheme_to_path(self._scheme_file_path)
        
        pdf_path = self._scheme_file_path
        stem = pdf_path.stem
        conductor = pdf_path.with_name(f"{stem}_指挥视角.pdf")
        performer = pdf_path.with_name(f"{stem}_表演者视角.pdf")
        self.scene.export_conductor_pdf(conductor, self.timelineMainWidget.graph_list)
        self.scene.export_performer_pdf(performer, self.timelineMainWidget.graph_list)

        self._show_menu_notice(f"已导出 pdf 到 {stem}")
        return True

    def _new_scheme(self, checked=False):
        """新建一个空白方案。"""
        self._stop_playback()
        if not self._ensure_scheme_can_be_replaced("新建方案"):
            return False
        self._scheme_dirty_suppressed = True
        try:
            self._scheme_file_path = None
            self.scene.load_confirmed_state({})
            self.timelineMainWidget.load_from_dict({})
            self._audio_dirty = True
            self._apply_active_tool("框选")
            self._configure_drawing_control_dock("框选")
            self.drawingControlDock.hide()
            self.onTimelineNodeSelected(0)
            self.scene.set_preview_beat(0)
            self.bpmSpinBox.setValue(120)
        finally:
            self._scheme_dirty_suppressed = False
        self._set_scheme_dirty(False)
        self._show_menu_notice("已新建空白方案")
        return True

    # ──────────────── 历史文件管理 ────────────────
    def _save_last_scheme_path(self):
        """将当前方案文件路径保存到历史文件。"""
        path = self._scheme_file_path
        data = {"last_scheme_path": str(path) if path else ""}
        LAST_SCHEME_PATH_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(LAST_SCHEME_PATH_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def _restore_last_scheme(self):
        """启动时从历史文件恢复上次编辑的方案。"""
        if not LAST_SCHEME_PATH_FILE.exists():
            return

        try:
            with open(LAST_SCHEME_PATH_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            return
        last_path = data.get("last_scheme_path", "")
        if not last_path:
            return

        target = Path(last_path)
        if not target.exists():
            QMessageBox.warning(
                self,
                "文件未找到",
                "上次编辑的文件已移动或删除，请重新打开方案文件。",
                QMessageBox.StandardButton.Ok,
            )
            # 清空历史文件
            with open(LAST_SCHEME_PATH_FILE, "w", encoding="utf-8") as f:
                json.dump({"last_scheme_path": ""}, f, ensure_ascii=False, indent=2)
            return

        try:
            with open(target, "r", encoding="utf-8") as f:
                payload = json.load(f)
            self._apply_scheme_payload(payload)
            self._scheme_file_path = target
            self._show_menu_notice(f"已恢复：{target.name}")
        except Exception:
            QMessageBox.warning(
                self,
                "文件读取失败",
                f"上次编辑的文件 {target.name} 无法读取或格式无效，请重新打开方案文件。",
                QMessageBox.StandardButton.Ok,
            )
            # 清空历史文件
            with open(LAST_SCHEME_PATH_FILE, "w", encoding="utf-8") as f:
                json.dump({"last_scheme_path": ""}, f, ensure_ascii=False, indent=2)

    def closeEvent(self, event):
        """关闭窗口前处理未保存修改。"""
        self._stop_playback()
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
        self._show_menu_notice("导入成功！")
    
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
            ['跟随', '路径', "间隔", '旋转'],   # 变换工具
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
        # 播放演示中点击任何工具按钮都停止播放
        if self._playback_active:
            self._stop_playback()
        tool_text = {
            '点': "点击绘制参考点；拖动空心矩形可对单点进行修正。",
            '线段': "确定线段起止点；拖动空心矩形可对单点进行修正。",
            '弧': "确定弧的起止点和弧上任意一点；拖动空心矩形可对单点进行修正。",
            '圆': "确定圆心和圆上任意一点；拖动空心矩形可对单点进行修正。",
            '多边形': "确定多边形中心点及一个顶点；拖动空心矩形可对单点进行修正。",
            '填充四边形': "确定填充四边形三个顶点；拖动空心矩形可对单点进行修正。",
            '曲线/折线': "确定曲线/折线的经过点；拖动空心矩形可对单点进行修正。",
            '文本': "确定对角点绘制文本框",
            '调整': "拖动角点与中心点调整所选点位（旋转仅调整位置，点位轨迹为直线）",
            '分组': "对点位分组进行连接、分割", 
            '跟随': "确定路径的经过点，所选点位跟随组leader沿路径移动",
            '路径': "确定路径的经过点，所选点位沿路径平移",
            "间隔": "拖动点位，组内其余点位以固定间隔移动",
            '旋转': "设置旋转角度，所选点位绕中心点旋转（点位轨迹为圆弧）",
            '箭头': "绘制箭头标注",
            '标签': "设置选中点位的标签前缀与起始序号",
        }
        self.drawingControlDock.statusLabel.setText(tool_text.get(tool_name, ""))

        if tool_name in {"调整", "分组", "旋转", "跟随", "标签"} and not self.scene._selected_point_ids:
            self._show_menu_notice("请先选中点位。", failed=True)
            self._set_active_tool("框选")
            return
        if tool_name in {"路径", "间隔"} and len(getattr(self.scene, "_selected_point_ids", set())) < 2:
            self._show_menu_notice("请至少选中2个点位。", failed=True)
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
        # setCentralWidget 在 setupTimeline 里统一设置

    def setupTimeline(self):
        """创建底部时间轴与播放控制区。"""
        # 时间轴主容器（高度在创建 TimelineWidget 后统一计算）
        self.timelineWidget = QWidget(self)     # 实例化窗口容器
        self.timelineWidget.setStyleSheet("background:#f0f0f0;")    # 设置背景色

        # 左侧动画播放组件区域
        self.animControlWidget = QWidget(self.timelineWidget)
        animLayout = QVBoxLayout()
        animLayout.setContentsMargins(8, 0, 8, 0)   # 设置内边距，确保按钮不贴边
        animLayout.setSpacing(1)    # 设置按钮间距

        # BPM 速度调节（仅修改 beat_tempo[0]）
        bpmLayout = QHBoxLayout()
        bpmLayout.setContentsMargins(0, 0, 0, 0)
        bpmLayout.setSpacing(0)
        bpmLayout.setAlignment(Qt.AlignmentFlag.AlignTop)
        bpmLabel = QLabel("bpm", self.animControlWidget)
        self.bpmSpinBox = QSpinBox(self.animControlWidget)
        self.bpmSpinBox.setRange(1, 300)
        self.bpmSpinBox.setValue(120)
        self.bpmSpinBox.setFixedWidth(75)
        bpmLayout.addWidget(bpmLabel)
        bpmLayout.addWidget(self.bpmSpinBox)
        animLayout.addLayout(bpmLayout)

        # 展开/折叠按钮 + 播放按钮（同一行，播放按钮在右侧）
        expand_row = QHBoxLayout()
        expand_row.setAlignment(Qt.AlignmentFlag.AlignBottom)
        expand_row.setContentsMargins(0, 0, 0, 0)
        expand_row.setSpacing(2)
        self.btnExpand = QPushButton("展开", self.animControlWidget)
        # self.btnExpand = QPushButton("⚙", self.animControlWidget)
        self.btnExpand.setFixedSize(32, 32)
        self.btnExpand.setToolTip("展开/折叠时间轴（速度轴/音频栏）")
        self.btnExpand.setCheckable(True)
        self.btnExpand.clicked.connect(self._toggle_timeline_expanded)
        expand_row.addWidget(self.btnExpand)

        # 播放、暂停按钮
        self.btnPlayPause = QPushButton("▶", self.animControlWidget)
        self.btnPlayPause.setFixedSize(48, 32)  # 加宽主播放按钮

        # 设置更大字体
        btnFont = self.btnPlayPause.font()
        btnFont.setPointSize(18)
        self.btnPlayPause.setFont(btnFont)
        expand_row.addWidget(self.btnPlayPause)
        expand_row.addStretch(1)
        animLayout.addLayout(expand_row)

        # BPM 只写回 beat_tempo[0].start_bpm
        self.bpmSpinBox.valueChanged.connect(self._on_bpm_changed)

        # 播放/暂停切换逻辑
        def toggle_play_pause():
            if self._playback_active:
                self._stop_playback()
            else:
                self._start_playback()
        self.btnPlayPause.clicked.connect(toggle_play_pause)    # 绑定按钮点击事件
        # 全局空格键绑定播放/暂停（ApplicationShortcut 在任何焦点下均响应）
        self._playback_shortcut = QShortcut(QKeySequence("Space"), self)
        self._playback_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self._playback_shortcut.activated.connect(toggle_play_pause)
        self.animControlWidget.setLayout(animLayout)    # 设置布局
        self.animControlWidget.setFixedWidth(120)       # 设置固定宽度，确保播放控制区大小稳定
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
        # 统一计算时间轴主容器高度（初始为折叠态）
        self.timelineWidget.setFixedHeight(self._timeline_container_height(False))

    def setupInteractions(self):
        """绑定时间轴、场景和控制台信号。"""
        self.timelineMainWidget.nodeSelected.connect(self.onTimelineNodeSelected)
        self.timelineMainWidget.timelineChanged.connect(self._mark_scheme_dirty)
        self.timelineMainWidget.timelineChanged.connect(self._mark_audio_dirty)
        self.timelineMainWidget.tempoChanged.connect(self._on_tempo_changed)
        self.timelineMainWidget.expandedChanged.connect(self._on_timeline_expanded_changed)
        self.timelineMainWidget.audioChanged.connect(self._on_audio_changed)
        self.timelineMainWidget.importAudioRequested.connect(self._import_audio)
        self.timelineMainWidget.currentBeatChanged.connect(self.scene.set_preview_beat)
        self.timelineMainWidget.currentBeatChanged.connect(self.updateDrawToolAvailability)
        self.timelineMainWidget.currentBeatChanged.connect(self.updateConvertToolAvailability)
        self.timelineMainWidget.currentBeatChanged.connect(self.updateMultiSelectToolAvailability)

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
        self.drawingControlDock.setIntervalControlsVisible(tool_name == "间隔")
        self.drawingControlDock.setRotateControlsVisible(tool_name == "旋转")
        self.drawingControlDock.setArrowControlsVisible(tool_name == "箭头")
        self.drawingControlDock.setLabelSettingsVisible(tool_name == "标签")
        
        if tool_name == "调整":
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

        if tool_name == "间隔":
            self.drawingControlDock.setSamplingToolVisible(None, False)
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.setDraftActive(False)
            self.drawingControlDock.confirmButton.setEnabled(True)
            self.drawingControlDock.cancelButton.setEnabled(True)
            return

        if tool_name == "旋转":
            self.drawingControlDock.setSamplingToolVisible(None, False)
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.setDraftActive(False)
            self.drawingControlDock.setRotateAngle(float(getattr(self.scene, "_rotate_angle", 0.0)))
            self.drawingControlDock.confirmButton.setEnabled(True)
            self.drawingControlDock.cancelButton.setEnabled(True)
            return

        if tool_name == "箭头":
            self.drawingControlDock.setSamplingToolVisible(None, False)
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.setDraftActive(True)
            self.drawingControlDock.confirmButton.setEnabled(True)
            self.drawingControlDock.cancelButton.setEnabled(True)
            self.drawingControlDock.setArrowControlsVisible(True)
            self.drawingControlDock.setDeleteArrowEnabled(False)
            self.drawingControlDock.setNewArrowEnabled(False)
            # 同步场景状态到控制台
            if hasattr(self.scene, '_sync_arrow_dock_state'):
                self.scene._sync_arrow_dock_state()
            return

        if tool_name == "标签":
            self.drawingControlDock.setSamplingToolVisible(None, False)
            self.drawingControlDock.setCurveModeVisible(False)
            self.drawingControlDock.setDraftActive(True)
            self.drawingControlDock.confirmButton.setEnabled(True)
            self.drawingControlDock.cancelButton.setEnabled(True)
            self.drawingControlDock.setLabelSettingsVisible(True)
            self._init_label_settings_dock()
            return

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
        if self._playback_active:
            self._stop_playback()
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
        if tool_name not in self._sampling_tools or tool_name != self.activeToolName:
            return
        if getattr(self.drawingControlDock, "linePointCountAutoButton", None) is not None and self.drawingControlDock.linePointCountAutoButton.isChecked():
            self.drawingControlDock.sync_sampling_settings(tool_name)
            return
        self.drawingControlDock.setSamplingTool(tool_name)
        self.drawingControlDock.setLinePointCount(int(point_count))

    def onSamplingSpacingChanged(self, tool_name: str, spacing: float):
        """圆、弧、多边形等采样间隔自动变化时，同步控制台显示。"""
        if tool_name not in self._sampling_tools or tool_name != self.activeToolName:
            return
        self.drawingControlDock.setSamplingTool(tool_name)
        self.drawingControlDock.lineSpacingSpin.blockSignals(True)
        self.drawingControlDock.lineSpacingSpin.setValue(float(spacing))
        self.drawingControlDock.lineSpacingSpin.blockSignals(False)

    def onSampling2ndPointCountChanged(self, tool_name: str, point_count: int):
        """填充四边形的 P0-P2 点位个数变化时，同步控制台显示。"""
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
        btn = self.toolButtons.get('文本')
        if btn is not None:
            btn.setEnabled(bool(beat_at_node))
        # 箭头工具始终可用（只要在节点拍上）
        btn = self.toolButtons.get('箭头')
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

    def updateMultiSelectToolAvailability(self, beat: int, selected_count: int = 0):
        """控制需要至少2个选中点位的工具（路径、间隔）的可用性。"""
        is_p0 = int(beat) == 0
        beat_at_node = self.timelineMainWidget.node_index_at_beat(beat) is not None
        has_enough = int(selected_count) >= 2
        for name in self._multi_select_tools:
            btn = self.toolButtons.get(name)
            if btn is not None:
                btn.setEnabled(beat_at_node and has_enough and not (is_p0 and name in self._p0_forbidden_transform_tools))

    def updateLabelToolAvailability(self, beat: int, selected_count: int):
        """根据选中点位数量，控制标签工具可用性。"""
        has_selection = int(selected_count) > 0
        for name in self._label_tools:
            btn = self.toolButtons.get(name)
            if btn is not None:
                btn.setEnabled(has_selection)
        # 如果当前处于标签工具但没有选中点位，回退到框选
        if self.activeToolName in self._label_tools and not has_selection:
            self._set_active_tool("框选")

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
        self.updateMultiSelectToolAvailability(beat, selected_count)
        self.updateGroupToolAvailability(beat, selected_count)
        self.updateLabelToolAvailability(beat, selected_count)

        # 自动切换工具：如果当前工具不可用，且没有选中点位，则切换到框选；如果在P0且当前工具在P0禁止列表中，也切换到框选。
        if not (is_p0 or has_selection) and (self.activeToolName in self._drawing_tools | self._transform_tools | self._multi_select_tools):
            self._set_active_tool("框选")
        elif self.activeToolName in self._multi_select_tools and int(selected_count) < 2:
            self._set_active_tool("框选")
        elif is_p0 and self.activeToolName in self._p0_forbidden_transform_tools:
            self._set_active_tool("框选")
        elif self.timelineMainWidget.node_index_at_beat(beat) is None and self.activeToolName == '文本':
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
        self.drawingControlDock.setLabelSettingsVisible(False)
        self.drawingControlDock.confirmButton.clicked.connect(self._on_control_confirmed)
        self.drawingControlDock.cancelButton.clicked.connect(self._on_control_cancelled)
        self.drawingControlDock.deleteTextBoxButton.clicked.connect(self._on_delete_textbox_requested)
        self.drawingControlDock.textBoxFontSizeSpin.valueChanged.connect(self._on_textbox_font_size_changed)
        self.drawingControlDock.rematchButton.clicked.connect(self._on_drawing_rematch_requested)
        self.drawingControlDock.previousMatchButton.clicked.connect(self._on_drawing_match_previous_requested)
        self.drawingControlDock.nextMatchButton.clicked.connect(self._on_drawing_match_next_requested)
        self.drawingControlDock.keepMatchButton.clicked.connect(self._on_drawing_match_keep_requested)
        self.drawingControlDock.rotationAngleSpin.valueChanged.connect(self.scene.set_adjustment_rotation)
        self.drawingControlDock.rotateAngleSpin.valueChanged.connect(self.scene.set_rotate_angle)
        for mode_name, button in self.drawingControlDock.adjustModeButtons.items():
            button.toggled.connect(lambda checked=False, mode=mode_name: self._on_adjustment_mode_toggled(mode, checked))
        # 分组按钮连接
        self.drawingControlDock.group_split_button.clicked.connect(self.scene.clear_temp_groups)
        self.drawingControlDock.group_set_next_button.clicked.connect(self.scene.set_next_temp_group)

    def setupAppSettingsDock(self):
        """创建应用全局设置面板。"""
        self.appSettingsDock = AppSettingsDock(self)
        self.appSettingsDock.bind(self.scene, self)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.appSettingsDock)
        self.appSettingsDock.hide()
        # 菜单 "设置" 联动
        self.actionAppSettings.toggled.connect(self.appSettingsDock.setVisible)
        self.appSettingsDock.visibilityChanged.connect(self.actionAppSettings.setChecked)
        # 应用设置到各归属对象
        self.appSettingsDock._apply_all_to_targets()

    def _apply_button_fonts(self):
        """将 _font_size 应用到主窗口各按钮，并调用 adjustSize() 自适应大小。"""
        size = self._font_size
        font = self.font()
        font.setPointSize(size)
        # 遍历工具栏中的按钮
        if hasattr(self, "toolButtons"):
            for btn in self.toolButtons.values():
                btn.setFont(font)
                btn.adjustSize()
        # 播放/暂停按钮使用较大的字体
        if hasattr(self, "btnPlayPause"):
            play_font = self.btnPlayPause.font()
            play_font.setPointSize(max(size, size + 2))
            self.btnPlayPause.setFont(play_font)
            self.btnPlayPause.adjustSize()

    def _on_adjustment_mode_toggled(self, mode_name: str, checked: bool):
        if not checked or self.activeToolName != "调整":
            return
        self.scene.set_adjustment_mode(mode_name)

    def _on_control_confirmed(self):
        if self.activeToolName == "调整":
            self.scene.confirm_current_adjustment()
        elif self.activeToolName == "文本":
            self.scene.confirm_textbox_preview()
        elif self.activeToolName == "分组":
            # 将临时分组写回并退出分组模式
            self.scene.confirm_temp_groups()
        elif self.activeToolName == "旋转":
            self.scene.confirm_rotate()
        elif self.activeToolName == "箭头":
            self.scene.confirm_current_arrow()
        elif self.activeToolName == "标签":
            self._on_label_apply()
        else:
            if self.scene.confirm_current_drawing() is False:
                self._sync_drawing_rematch_controls()
                # return
        self.scene._selected_point_ids.clear()
        self.onToolButtonClicked("框选")  # 草稿完成后自动切回选择工具
        self.updateContextToolAvailability(self.timelineMainWidget.current_beat, 0)

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
        if self.activeToolName == "旋转":
            self.scene.cancel_rotate()
            return
        if self.activeToolName == "箭头":
            self.scene.cancel_current_arrow()
            return
        if self.activeToolName == "标签":
            self.onToolButtonClicked("框选")
            return
        if self.activeToolName in {"路径", "跟随"}:
            # 路径/跟随模式下取消：仅清除场景草稿状态，保留绘制控制台内容与可见性
            self.scene._pending_points = []
            self.scene._draft_tool_name = None
            self.scene._draft_reference_points = []
            self.scene._reset_drawing_rematch_state(active=False)
            self.scene._clear_draft_items()
            self.scene._clear_pending_preview_items()
            self.scene._clear_draft_preview_items()
            self.scene._render_points_for_active_node()
            self.scene.drawingRematchStateChanged.emit()
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

    def _init_label_settings_dock(self):
        """同步标签设置面板：若最小id已有标签则以其为准，否则默认serial=id+1、prefix为空。"""
        min_id = min(int(pid) for pid in self.scene._selected_point_ids)
        lable = self.scene.point_lable
        self.drawingControlDock.labelSerialSpin.setValue(int(1))
        if 0 <= min_id < len(lable) and lable[min_id] is not None:
            entry = lable[min_id]
            self.drawingControlDock.labelPrefixEdit.setText(str(entry.get("prefix", "")))
            # self.drawingControlDock.labelSerialSpin.setValue(int(entry.get("serial", min_id + 1)))
        else:
            self.drawingControlDock.labelPrefixEdit.setText("")

    def _on_label_apply(self):
        """应用标签设置：将前缀和序号应用到选中点位。"""
        prefix = self.drawingControlDock.labelPrefixEdit.text()
        serial_start = self.drawingControlDock.labelSerialSpin.value()
        for i, pid in enumerate(sorted(list(self.scene._selected_point_ids))):
            self.scene._set_point_label_prefix(pid, prefix)
            self.scene._set_point_label_serial(pid, serial_start + i)
        self.scene._render_points_for_active_node()
        self.scene.dataChanged.emit()

    def _on_delete_points_triggered(self):
        """响应菜单删除点位：弹出确认对话框，确认后调用场景删除方法。"""
        action = self._confirm_delete_points_dialog(len(self.scene._selected_point_ids))
        if not action:
            return
        if action == "delete":
            self.scene.delete_selected_points()
            self._show_menu_notice("删除成功！")
        elif action == "restore":
            self.scene.restore_selected_points_to_prev()
            self._show_menu_notice("已恢复转换点位置。")
        else:
            return

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
        # p0 仅允许删除表演者点位，禁用转换点删除按钮
        if getattr(self.scene, "active_node", 0) == 0:
            del_switch.setEnabled(False)

        res = dlg.exec()
        return getattr(dlg, "result_action", None)

    def _positionDrawingControlDock(self):
        """将绘制控制台放到绘图区左上角。"""
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
        if tool_name == "箭头":
            return
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
        if self.activeToolName == "箭头":
            return
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

    # ──────────────── 时间轴展开与速度联动 ────────────────
    def _toggle_timeline_expanded(self, checked: bool):
        """点击展开按钮：切换时间轴展开/折叠状态。"""
        self.timelineMainWidget.set_expanded(checked)

    def _timeline_container_height(self, expanded: bool) -> int:
        """统一计算时间轴主容器高度：TimelineWidget 自身所需高度 + 水平滚动条预留高度。"""
        widget_height = (
            self.timelineMainWidget._expanded_min_height
            if expanded
            else self.timelineMainWidget._collapsed_min_height
        )
        return widget_height + 14

    def _on_timeline_expanded_changed(self, expanded: bool):
        """时间轴展开/折叠后，联动整体高度与按钮状态。"""
        self.btnExpand.blockSignals(True)
        self.btnExpand.setChecked(expanded)
        self.btnExpand.setText("折叠" if expanded else "展开")
        self.btnExpand.blockSignals(False)
        # 展开/折叠后统一重算容器高度，为速度轴与音频栏腾出/收回空间
        self.timelineWidget.setFixedHeight(self._timeline_container_height(expanded))
        self.timelineWidget.adjustSize()

    def _on_bpm_changed(self, value: int):
        """BPM 输入框只修改 beat_tempo[0]（起始速度）。"""
        self.timelineMainWidget.set_tempo_at_beat(0, Tempo(start_bpm=int(value)))
        self.timelineMainWidget.update()

    def _on_tempo_changed(self):
        """速度数据变化时，同步 BPM 输入框显示（仅反映 beat_tempo[0]），并标记需重新合成音频。"""
        self._audio_dirty = True   # 轴对齐依赖 beat_tempo，速度变化后合成整轨需更新
        tempo0 = self.timelineMainWidget.beat_tempo.get(0, None)
        if tempo0 is not None:
            self.bpmSpinBox.blockSignals(True)
            self.bpmSpinBox.setValue(int(round(tempo0.start_bpm)))
            self.bpmSpinBox.blockSignals(False)

    # ──────────────── 音频导入 ────────────────
    def _import_audio(self):
        """导入音频文件，追加到现有波形右侧（首尾相连）。

        读取音频时长等信息可能耗时，因此导入期间弹出进度提示框，导入成功后自动关闭。
        """
        files, _ = QFileDialog.getOpenFileNames(
            self,
            "导入音频",
            "",
            "音频文件 (*.mp3 *.wav *.flac *.ogg *.m4a *.aac *.wma);;所有文件 (*)",
        )
        if not files:
            return
        total = len(files)
        # 进度提示框：无取消按钮、模态，防止导入期间误操作；完成后自动关闭。
        progress = QProgressDialog("正在导入音频...", "", 0, total, self)
        progress.setWindowTitle("导入音频")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setAutoClose(True)
        progress.setAutoReset(False)
        progress.setMinimumWidth(320)
        progress.show()
        QApplication.processEvents()   # 立即显示初始提示，避免首个文件解析期间无反馈

        def _on_import_progress(done: int, n: int, file_path: str):
            progress.setValue(done)
            progress.setLabelText(f"正在导入：{Path(file_path).name}（{done}/{n}）")
            QApplication.processEvents()

        added = self.timelineMainWidget.import_audio_files(files, progress_cb=_on_import_progress)
        progress.setValue(total)   # 导入完成，进度归满
        progress.close()           # 自动关闭提示框

        if not added:
            self._show_menu_notice("导入失败：无法读取音频文件。", failed=True)
            return
        # 展开时间轴以显示音频栏
        self.timelineMainWidget.set_expanded(True)
        self._mark_scheme_dirty()
        self._show_menu_notice(f"已导入 {len(added)} 个音频段")

    # ──────────────── 合成整轨音频 ────────────────
    def _synthesized_audio_path(self) -> Path:
        """合成整轨音频的输出路径：与方案文件同级；无方案文件时回退到默认方案目录。

        文件名固定带 SYNTH_FILE_SUFFIX 保留后缀，加载方案时据此识别合成整轨并跳过，
        保证它永远只是“播放用的派生产物”，不会被误当作音频段源文件。
        """
        if self._scheme_file_path is not None:
            base_dir = self._scheme_file_path.parent
            stem = self._scheme_file_path.stem
        else:
            base_dir = scheme_default_dir()
            stem = "marching_map_scheme"
        return base_dir / f"{stem}_合成音频.wav"

    def _ensure_synthesized_audio(self) -> str | None:
        """若音频自上次合成后发生变化，则重新合成整轨音频（无音频段处为静音）并保存；返回合成文件路径（失败返回 None）。

        参照 _import_audio：合成（需解码音频，可能耗时）期间弹出进度提示框，完成后自动关闭。
        """
        segments = self.timelineMainWidget.audio_segments
        if not segments:
            return None
        out_path = self._synthesized_audio_path()
        if not self._audio_dirty and out_path.exists():
            return str(out_path)

        total = len(segments)
        # 进度提示框：无取消按钮、模态，防止合成期间误操作；完成后自动关闭。
        progress = QProgressDialog("正在合成音频...", "", 0, total, self)
        progress.setWindowTitle("合成音频")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumDuration(0)
        progress.setCancelButton(None)
        progress.setAutoClose(True)
        progress.setAutoReset(False)
        progress.setMinimumWidth(360)
        progress.show()
        QApplication.processEvents()   # 立即显示初始提示，避免首个文件解码期间无反馈

        def _on_synth_progress(done: int, n: int, name: str):
            progress.setValue(done)
            progress.setLabelText(f"正在合成：{name}（{done}/{n}）")
            QApplication.processEvents()

        ok = self.timelineMainWidget.synthesize_playback_audio(
            str(out_path), progress_cb=_on_synth_progress
        )
        progress.setValue(total)   # 合成完成，进度归满
        progress.close()           # 自动关闭提示框

        if not ok:
            self._show_menu_notice("音频合成失败，将无音频播放（按经过时间推算）。", failed=True)
            return None
        self._audio_dirty = False
        return str(out_path)

    # ──────────────── 播放演示 ────────────────
    def _start_playback(self):
        """开始播放演示。

        有音频段时：若音频自上次合成后发生变化，先合成整轨音频（无音频段处为静音），
        再从 current_beat 对应的轨道时间开始播放合成音频；动画等待合成完成后与音频同步。
        无音频段时：按“经过时间 × 设置的速度”推进（_beat_from_elapsed）。
        """
        total_beats = self.timelineMainWidget.total_beats()
        if total_beats <= 0:
            return

        self._playback_use_synth = False
        self._playback_synth_path = None
        if self.timelineMainWidget.audio_segments:
            synth_path = self._ensure_synthesized_audio()
            if synth_path is not None:
                self._playback_use_synth = True
                self._playback_synth_path = synth_path

        self._playback_active = True
        self.btnPlayPause.setText("⏸")
        cur_beat = self.timelineMainWidget.current_beat
        start_beat = 0.0 if cur_beat >= total_beats else float(cur_beat)
        self._playback_start_beat = start_beat
        self._playback_elapsed.restart()
        self._playback_elapsed.start()
        if self._playback_use_synth:
            # 合成整轨：定位到起始拍对应的轨道时间并播放（动画由音频位置驱动）
            self._audio_start_synth_playback(start_beat)
        # 无合成音频（无音频段或合成失败）：不播放音频，点位按经过时间推算
        # 以约 60fps 刷新，点位移动向音频对齐（无音频时按设置速度平滑演示）
        self._playback_timer.start(60)

    def _audio_start_synth_playback(self, start_beat: float):
        """用合成整轨启动播放：把合成音频定位到起始拍对应的轨道时间并播放。"""
        url = QUrl.fromLocalFile(self._playback_synth_path)
        player = self._audio_player
        if player.source() != url:
            player.setSource(url)
        target_ms = int(round(self.timelineMainWidget.audio_time_at_beat(start_beat) * 1000.0))
        player.setPosition(target_ms)
        player.play()

    def _stop_playback(self):
        """停止播放演示，恢复编辑态预览。"""
        self._playback_timer.stop()
        self._audio_player.stop()
        self._playback_active = False
        self._playback_use_synth = False
        self._playback_synth_path = None
        self.btnPlayPause.setText("▶")
        # 若当前拍位与选中节点不在同一节点才切换
        node_idx = self.timelineMainWidget.node_index_at_beat(self.timelineMainWidget.current_beat)
        if node_idx is None or node_idx != self.timelineMainWidget.selected_node:
            self.timelineMainWidget._switch_next()
        # 恢复编辑态渲染
        self.scene.set_preview_beat(int(self.timelineMainWidget.current_beat))

    def _playback_beat(self) -> float:
        """当前演示拍位。

        合成整轨播放：用合成音频实际播放位置反推拍位（点位向音频对齐）；
        否则回退到“经过时间 × 设置的速度”推算（_beat_from_elapsed）。
        """
        if self._playback_use_synth:
            player = self._audio_player
            if player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
                pos_ms = player.position()
                if pos_ms >= 0:
                    return self.timelineMainWidget.audio_beat_at_time(pos_ms / 1000.0)

        elapsed_ms = self._playback_elapsed.elapsed()
        elapsed_minutes = elapsed_ms / 60000.0
        return self.timelineMainWidget._beat_from_elapsed(
            self._playback_start_beat, elapsed_minutes
        )

    def _on_playback_tick(self):
        """定时器回调：合成整轨播放时直接由音频位置驱动；无音频时按经过时间推算。"""
        if not self._playback_active:
            return

        total_beats = self.timelineMainWidget.total_beats()
        if total_beats <= 0:
            self._stop_playback()
            return

        # 优先取音频当前位置反推的拍位；无音频/未播放时回退到经过时间推算
        beat_float = self._playback_beat()

        if beat_float >= float(total_beats):
            self._stop_playback()
            return

        self._update_playback_display(beat_float)   # 点位移动 / 时间轴游标
        if self._playback_use_synth:
            # 合成整轨为单一连续文件：无需段切换/预加载，仅确保正在播放
            player = self._audio_player
            if player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
                player.play()

    def _update_playback_display(self, beat_float: float):
        """按浮点拍位同步时间轴游标（自动滚动）与场景 sub-beat 动画。"""
        int_beat = int(beat_float)

        # 同步时间轴游标（不触发信号，避免数据回写）：
        # 以浮点拍位跟随播放，负拍前导区与段内亚拍位均平滑连续移动
        # （负拍 int() 会向零截断停在整拍，故直接写回 beat_float）。
        if self.timelineMainWidget.current_beat != beat_float:
            self.timelineMainWidget.current_beat = beat_float
            self.timelineMainWidget.update()
            # 自动滚动时间轴使游标保持可见（按整拍定位滚动）
            cursor_x = self.timelineMainWidget._beat_to_x(int_beat)
            scroll_bar = self.timelineScrollArea.horizontalScrollBar()
            if scroll_bar is not None:
                viewport_width = self.timelineScrollArea.viewport().width()
                half_view = viewport_width // 2
                scroll_bar.setValue(max(0, cursor_x - half_view))

        # 场景 sub-beat 渲染（不写回数据）
        self.scene.set_preview_sub_beat(beat_float)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
