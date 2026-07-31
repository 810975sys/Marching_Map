"""应用设置侧边面板。

主要职责：
1. 将应用参数映射到可编辑控件。
    主要参数：
    (1) 字体大小（使用同一个字体大小），包括：
        src/mainwindow.py 各个按钮的字体大小（同步适配按钮大小）
        src/drawing_control_dock.py, src/app_settings_dock.py, src/field_settings_dock.py字体大小
    (2) 时间轴字体大小：（分为两个）
        src/timeline_widget.py 中的时间轴、方案图序号字体大小
    
    (3) 点位大小、颜色，包括当前点位(PerformerPointItem)和上一张图点位pre_point_radius、pre_point_color
    (4) 点位label信息：
        label_color、label_size、label_offset、label_pos
        
    (5) ReferenceHandleItem框大小、颜色
    (6) MovementControlHandleItem大小、颜色、内外圈比例
    (7) helper_radius
    
    (8) ArrowItem粗细、颜色、箭头大小
    
2. 在用户修改控件时刷新 UI，保持同步。(或许需要将origin备份，便于恢复)
3. 用户确认后才进行回写，否则舍弃
4. 恢复默认功能
"""

import json
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QColorDialog,
    QDockWidget,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from src.scene_items import (
    PerformerPointItem,
    ReferenceHandleItem,
    MovementControlHandleItem,
    ArrowItem,
)

# ── 路径常量 ──
_PROJECT_ROOT = Path(__file__).resolve().parent
_SETTINGS_PATH = _PROJECT_ROOT / "app_settings.json"
# _DEFAULTS_PATH = _PROJECT_ROOT / "app_settings_default.json"

# ── 内置默认值（当 app_settings_default.json 也不存在时使用）──
DEFAULT_SETTINGS: dict = {
    "common_font_size": 9,
    "dock_font_size": 9,
    # "timeline_node_font_size": 9,
    # "timeline_beat_font_size": 9,
    "performer_size": 10.0,
    "performer_dot_color": "#2aa6ff",
    "performer_selected_pen_color": "#f39c12",
    "pre_point_radius": 2.0,
    "pre_point_color": "#444444",
    "label_color": "#000000",
    "label_size": 12,
    "label_offset": 15,
    "label_pos": 90,
    "reference_handle_size": 10.0,
    "movement_handle_size": 32.0,
    "movement_handle_inner_ratio": 0.45,
    "helper_radius": 12,
    "arrow_size": 8.0,
    "arrow_current_color": "#d35400",
    "arrow_current_width": 2.5,
    "arrow_normal_color": "#000000",
    "arrow_normal_width": 1.5,
}


def _load_json(path: Path) -> dict:
    """加载 JSON 文件，不存在则返回空字典。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def _save_json(path: Path, data: dict):
    """保存字典到 JSON 文件。"""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


class AppSettingsDock(QDockWidget):
    """应用全局视觉参数编辑面板（Dock 形式）。

    参数归属各自对象（SchemeScene、各类 Item 等），本面板仅负责读取、展示、
    回写与恢复默认。
    """

    def __init__(self, parent=None):
        super().__init__("应用设置", parent)
        self.setObjectName("appSettingsDock")
        self.setAllowedAreas(Qt.DockWidgetArea.LeftDockWidgetArea)
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
        )
        self.setMinimumWidth(380)

        # 字体大小（由自身管理，属于 (1) 的一部分）
        self._font_size = 9

        self._updating = False
        self._settings: dict = {}
        self._defaults: dict = DEFAULT_SETTINGS
        self._scene = None          # SchemeScene 引用
        self._main_window = None    # MainWindow 引用（用于按钮字体等）

        self._load_settings()
        self._build_ui()
        self._apply_to_controls()
        self._capture_original()

    # ────────────── 设置加载 / 保存 ──────────────

    def _load_settings(self):
        """加载用户设置与默认值；若任一 JSON 文件不存在则自动创建。"""
        # 确保用户设置文件存在
        if not _SETTINGS_PATH.exists():
            self._create_default_settings()
        else:
            self._settings = _load_json(_SETTINGS_PATH)
            # 用默认值补全缺失的键
            for key, val in self._defaults.items():
                if key not in self._settings:
                    self._settings[key] = val

    def _create_default_settings(self):
        """新建用户设置文件，内容完全拷贝默认设置。"""
        self._settings = dict(self._defaults)
        _save_json(_SETTINGS_PATH, self._settings)

    def _get(self, key: str, default=None):
        return self._settings.get(key, self._defaults.get(key, default))

    def _set(self, key: str, value):
        """更新内存中的设置（不写回）。"""
        self._settings[key] = value

    def _save(self):
        """将当前设置持久化到 JSON 文件。"""
        _save_json(_SETTINGS_PATH, self._settings)
        # 重置原始设置快照
        self._original_settings = dict(self._settings)

    def _capture_original(self):
        """捕获当前设置快照，用于取消修改时恢复。"""
        self._original_settings = dict(self._settings)

    def apply_settings(self):
        """确认修改：将当前设置写回 JSON 并更新快照。"""
        self._save()
        self._capture_original()

    def restore_original(self):
        """取消修改：恢复到上次确认时的设置。"""
        self._settings = dict(self._original_settings)
        self._apply_to_controls()
        self._apply_all_to_targets()

    def restore_defaults(self):
        """恢复所有设置为默认值（预览，需确认后才会保存）。"""
        self._settings = dict(self._defaults)
        self._apply_to_controls()
        self._apply_all_to_targets()

    # ────────────── 绑定外部对象 ──────────────

    def bind(self, scene, main_window):
        """绑定场景与主窗口引用。"""
        self._scene = scene
        self._main_window = main_window

    # ────────────── UI 构建 ──────────────

    def _build_ui(self):
        # ── 外层容器：滚动区 + 底部按钮栏 ──
        outer = QWidget(self)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(0)

        # ── 滚动区域 ──
        content = QWidget()
        root = QVBoxLayout(content)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(10)

        self._build_font_group(root)
        # self._build_timeline_font_group(root)
        self._build_point_group(root)
        self._build_label_group(root)
        self._build_handle_group(root)
        # self._build_helper_group(root)
        self._build_arrow_group(root)
        root.addStretch(1)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        outer_layout.addWidget(scroll, 1)

        # ── 分割线 ──
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        outer_layout.addWidget(sep)

        # ── 底部按钮栏（固定在滚动区外）──
        btn_row = QWidget()
        btn_layout = QHBoxLayout(btn_row)
        btn_layout.setContentsMargins(8, 4, 8, 4)
        comfirm_btn = QPushButton("确认修改", btn_row)
        comfirm_btn.clicked.connect(self.apply_settings)
        btn_layout.addWidget(comfirm_btn)
        cancel_btn = QPushButton("取消修改", btn_row)
        cancel_btn.clicked.connect(self.restore_original)
        btn_layout.addWidget(cancel_btn)
        restore_btn = QPushButton("恢复默认值（需要确认）", btn_row)
        restore_btn.clicked.connect(self.restore_defaults)
        btn_layout.addStretch(1)
        btn_layout.addWidget(restore_btn)
        outer_layout.addWidget(btn_row)

        self.setWidget(outer)

    def _make_group(self, title: str, parent: QWidget) -> QFormLayout:
        group = QGroupBox(title, parent)
        form = QFormLayout(group)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)
        parent.layout().addWidget(group)
        return form

    # ── (1) 通用字体大小 ──

    def _build_font_group(self, root: QVBoxLayout):
        form = self._make_group("通用字号调整", root.parent())

        self.commonFontSpin = QSpinBox(form.parent())
        self.commonFontSpin.setRange(2, 48)
        self.commonFontSpin.setSingleStep(1)
        self.commonFontSpin.valueChanged.connect(self._on_common_font_changed)
        form.addRow("工具栏字号大小", self.commonFontSpin)

        self.dockFontSpin = QSpinBox(form.parent())
        self.dockFontSpin.setRange(2, 48)
        self.dockFontSpin.setSingleStep(1)
        self.dockFontSpin.valueChanged.connect(self._on_dock_font_changed)
        form.addRow("控制台字号大小", self.dockFontSpin)

    def _on_common_font_changed(self, value: int):
        if self._updating:
            return
        self._set("common_font_size", int(value))
        self._apply_common_font()

    def _apply_common_font(self):
        """应用工具栏字体到主窗口按钮。"""
        size = int(self._get("common_font_size", 9))
        mw = self._main_window
        if mw is not None:
            mw._font_size = size
            if hasattr(mw, "_apply_button_fonts"):
                mw._apply_button_fonts()

    def _on_dock_font_changed(self, value: int):
        if self._updating:
            return
        self._set("dock_font_size", int(value))
        self._apply_dock_font()

    def _apply_dock_font(self):
        """应用控制台字号到三个 Dock 面板。"""
        size = int(self._get("dock_font_size", 9))
        # 自身
        self._font_size = size
        self.apply_font_size(size)
        # DrawingControlDock / FieldSettingsDock
        mw = self._main_window
        if mw is not None:
            if hasattr(mw, "drawingControlDock"):
                mw.drawingControlDock._font_size = size
                if hasattr(mw.drawingControlDock, "apply_font_size"):
                    mw.drawingControlDock.apply_font_size(size)
            if hasattr(mw, "fieldSettingsDock"):
                mw.fieldSettingsDock._font_size = size
                if hasattr(mw.fieldSettingsDock, "apply_font_size"):
                    mw.fieldSettingsDock.apply_font_size(size)

    def apply_font_size(self, size: int):
        """应用字号到本面板所有控件。"""
        font = self.font()
        font.setPointSize(size)
        self.setFont(font)
        w = self.widget()
        if w:
            w.setFont(font)

    # ── (3) 点位大小、颜色 ──

    def _build_point_group(self, root: QVBoxLayout):
        form = self._make_group("点位外观", root.parent())

        self.performerSizeSpin = QDoubleSpinBox(form.parent())
        self.performerSizeSpin.setRange(0.5, 50.0)
        self.performerSizeSpin.setSingleStep(0.5)
        self.performerSizeSpin.setDecimals(1)
        self.performerSizeSpin.valueChanged.connect(self._on_performer_size_changed)
        form.addRow("点位大小", self.performerSizeSpin)

        self.performerDotColorBtn = QPushButton("选择", form.parent())
        self.performerDotColorBtn.clicked.connect(self._choose_performer_dot_color)
        form.addRow("点位填充色", self.performerDotColorBtn)

        self.performerSelectedColorBtn = QPushButton("选择", form.parent())
        self.performerSelectedColorBtn.clicked.connect(self._choose_performer_selected_color)
        form.addRow("点位边框色（选中）", self.performerSelectedColorBtn)

        self.prePointRadiusSpin = QDoubleSpinBox(form.parent())
        self.prePointRadiusSpin.setRange(0.5, 50.0)
        self.prePointRadiusSpin.setSingleStep(0.5)
        self.prePointRadiusSpin.setDecimals(1)
        self.prePointRadiusSpin.valueChanged.connect(self._on_pre_point_radius_changed)
        form.addRow("前一点位大小", self.prePointRadiusSpin)

        self.prePointColorBtn = QPushButton("选择", form.parent())
        self.prePointColorBtn.clicked.connect(self._choose_pre_point_color)
        form.addRow("前一点位颜色", self.prePointColorBtn)

    def _on_performer_size_changed(self, value: float):
        if self._updating:
            return
        self._set("performer_size", float(value))
        PerformerPointItem.default_size = float(value)
        self._refresh_scene()

    def _on_pre_point_radius_changed(self, value: float):
        if self._updating:
            return
        self._set("pre_point_radius", float(value))
        self._apply_pre_point()

    def _choose_performer_dot_color(self):
        color = self._choose_color(
            self._get("performer_dot_color", "#2aa6ff"),
            "选择点位填充色",
        )
        if color is not None:
            self._set("performer_dot_color", color.name())
            PerformerPointItem.dot_color = color
            self._apply_color_button_style(self.performerDotColorBtn, color)
            self._refresh_scene()

    def _choose_performer_selected_color(self):
        color = self._choose_color(
            self._get("performer_selected_pen_color", "#f39c12"),
            "选择点位选中边框色",
        )
        if color is not None:
            self._set("performer_selected_pen_color", color.name())
            PerformerPointItem.selected_pen_color = color
            self._apply_color_button_style(self.performerSelectedColorBtn, color)
            self._refresh_scene()

    def _choose_pre_point_color(self):
        color = self._choose_color(
            self._get("pre_point_color", "#444444"),
            "选择上一点位颜色",
        )
        if color is not None:
            self._set("pre_point_color", color.name())
            self._apply_pre_point()
            self._apply_color_button_style(self.prePointColorBtn, color)

    def _apply_pre_point(self):
        scene = self._scene
        if scene is None:
            return
        scene.pre_point_radius = float(self._get("pre_point_radius", 2.0))
        scene.pre_point_color = QColor(self._get("pre_point_color", "#444444"))
        scene._render_points_for_active_node()
        scene.update()

    # ── (4) 点位 label ──

    def _build_label_group(self, root: QVBoxLayout):
        form = self._make_group("点位标签", root.parent())

        self.labelColorBtn = QPushButton("选择", form.parent())
        self.labelColorBtn.clicked.connect(self._choose_label_color)
        form.addRow("标签颜色", self.labelColorBtn)

        self.labelSizeSpin = QSpinBox(form.parent())
        self.labelSizeSpin.setRange(4, 72)
        self.labelSizeSpin.setSingleStep(1)
        self.labelSizeSpin.valueChanged.connect(self._on_label_size_changed)
        form.addRow("标签字号", self.labelSizeSpin)

        self.labelOffsetSpin = QSpinBox(form.parent())
        self.labelOffsetSpin.setRange(0, 200)
        self.labelOffsetSpin.setSingleStep(1)
        self.labelOffsetSpin.valueChanged.connect(self._on_label_offset_changed)
        form.addRow("标签距离", self.labelOffsetSpin)

        self.labelPosSpin = QSpinBox(form.parent())
        self.labelPosSpin.setRange(0, 360)
        self.labelPosSpin.setSingleStep(15)
        self.labelPosSpin.valueChanged.connect(self._on_label_pos_changed)
        form.addRow("标签角度 °", self.labelPosSpin)

    def _on_label_size_changed(self, value: int):
        if self._updating:
            return
        self._set("label_size", int(value))
        self._apply_label()

    def _on_label_offset_changed(self, value: int):
        if self._updating:
            return
        self._set("label_offset", int(value))
        self._apply_label()

    def _on_label_pos_changed(self, value: int):
        if self._updating:
            return
        self._set("label_pos", int(value))
        self._apply_label()

    def _choose_label_color(self):
        color = self._choose_color(
            self._get("label_color", "#000000"),
            "选择标签颜色",
        )
        if color is not None:
            self._set("label_color", color.name())
            self._apply_label()
            self._apply_color_button_style(self.labelColorBtn, color)

    def _apply_label(self):
        scene = self._scene
        if scene is None:
            return
        scene.label_color = QColor(self._get("label_color", "#000000"))
        scene.label_size = int(self._get("label_size", 12))
        scene.label_offset = int(self._get("label_offset", 15))
        scene.label_pos = int(self._get("label_pos", 90))
        scene._render_points_for_active_node()
        scene.update()

    # ── (5, 6, 7) 绘制辅助 ──

    def _build_handle_group(self, root: QVBoxLayout):
        form = self._make_group("绘制参考框 / 移动手柄 / 选择辅助圆", root.parent())

        self.refHandleSizeSpin = QDoubleSpinBox(form.parent())
        self.refHandleSizeSpin.setRange(2.0, 100.0)
        self.refHandleSizeSpin.setSingleStep(1.0)
        self.refHandleSizeSpin.setDecimals(1)
        self.refHandleSizeSpin.valueChanged.connect(self._on_ref_handle_size_changed)
        form.addRow("参考框大小", self.refHandleSizeSpin)

        # self.refHandleColorBtn = QPushButton("选择", form.parent())
        # self.refHandleColorBtn.clicked.connect(self._choose_ref_handle_color)
        # form.addRow("参考点框颜色", self.refHandleColorBtn)

        self.moveHandleSizeSpin = QDoubleSpinBox(form.parent())
        self.moveHandleSizeSpin.setRange(4.0, 200.0)
        self.moveHandleSizeSpin.setSingleStep(1.0)
        self.moveHandleSizeSpin.setDecimals(1)
        self.moveHandleSizeSpin.valueChanged.connect(self._on_move_handle_size_changed)
        form.addRow("移动手柄大小", self.moveHandleSizeSpin)

        # self.moveHandleColorBtn = QPushButton("选择", form.parent())
        # self.moveHandleColorBtn.clicked.connect(self._choose_move_handle_color)
        # form.addRow("移动手柄颜色", self.moveHandleColorBtn)

        self.moveHandleRatioSpin = QDoubleSpinBox(form.parent())
        self.moveHandleRatioSpin.setRange(0.1, 0.9)
        self.moveHandleRatioSpin.setSingleStep(0.05)
        self.moveHandleRatioSpin.setDecimals(2)
        self.moveHandleRatioSpin.valueChanged.connect(self._on_move_handle_ratio_changed)
        form.addRow("内外圈比例", self.moveHandleRatioSpin)

        self.helperRadiusSpin = QSpinBox(form.parent())
        self.helperRadiusSpin.setRange(2, 100)
        self.helperRadiusSpin.setSingleStep(1)
        self.helperRadiusSpin.valueChanged.connect(self._on_helper_radius_changed)
        form.addRow("辅助圆半径", self.helperRadiusSpin)
        
    def _on_ref_handle_size_changed(self, value: float):
        if self._updating:
            return
        self._set("reference_handle_size", float(value))
        ReferenceHandleItem.default_size = float(value)
        self._apply_handle_settings()

    def _on_move_handle_size_changed(self, value: float):
        if self._updating:
            return
        self._set("movement_handle_size", float(value))
        MovementControlHandleItem.default_size = float(value)
        self._apply_handle_settings()

    def _on_move_handle_ratio_changed(self, value: float):
        if self._updating:
            return
        self._set("movement_handle_inner_ratio", float(value))
        MovementControlHandleItem.default_inner_ratio = float(value)
        self._apply_handle_settings()

    def _apply_handle_settings(self):
        """将手柄大小/比例同步到场景中已有的图元实例。"""
        scene = self._scene
        if scene is None:
            return
        # 遍历场景中的所有 MovementControlHandleItem，更新大小和比例
        for item in scene.items():
            if isinstance(item, MovementControlHandleItem):
                item.set_size(MovementControlHandleItem.default_size)
                item.set_inner_ratio(MovementControlHandleItem.default_inner_ratio)
        # ReferenceHandleItem
        ref_size = ReferenceHandleItem.default_size
        for item in scene.items():
            if isinstance(item, ReferenceHandleItem):
                item.set_size(ref_size)
        scene.update()

    # def _build_helper_group(self, root: QVBoxLayout):
    #     form = self._make_group("辅助圆", root.parent())

    #     self.helperRadiusSpin = QSpinBox(form.parent())
    #     self.helperRadiusSpin.setRange(2, 100)
    #     self.helperRadiusSpin.setSingleStep(1)
    #     self.helperRadiusSpin.valueChanged.connect(self._on_helper_radius_changed)
    #     form.addRow("辅助圆半径", self.helperRadiusSpin)

    def _on_helper_radius_changed(self, value: int):
        if self._updating:
            return
        self._set("helper_radius", int(value))
        self._apply_helper_radius()

    def _apply_helper_radius(self):
        scene = self._scene
        if scene is None:
            return
        scene.helper_radius = int(self._get("helper_radius", 12))
        scene._render_points_for_active_node()
        scene.update()

    # ── (8) ArrowItem ──

    def _build_arrow_group(self, root: QVBoxLayout):
        form = self._make_group("箭头外观", root.parent())

        self.arrowSizeSpin = QDoubleSpinBox(form.parent())
        self.arrowSizeSpin.setRange(2.0, 100.0)
        self.arrowSizeSpin.setSingleStep(1.0)
        self.arrowSizeSpin.setDecimals(1)
        self.arrowSizeSpin.valueChanged.connect(self._on_arrow_size_changed)
        form.addRow("箭头大小", self.arrowSizeSpin)

        hdr = QLabel("<b>当前编辑箭头：</b>", form.parent())
        form.addRow(hdr)

        self.arrowCurrentColorBtn = QPushButton("选择", form.parent())
        self.arrowCurrentColorBtn.clicked.connect(self._choose_arrow_current_color)
        form.addRow("颜色", self.arrowCurrentColorBtn)

        self.arrowCurrentWidthSpin = QDoubleSpinBox(form.parent())
        self.arrowCurrentWidthSpin.setRange(0.5, 20.0)
        self.arrowCurrentWidthSpin.setSingleStep(0.5)
        self.arrowCurrentWidthSpin.setDecimals(1)
        self.arrowCurrentWidthSpin.valueChanged.connect(self._on_arrow_current_width_changed)
        form.addRow("粗细", self.arrowCurrentWidthSpin)

        hdr2 = QLabel("<b>普通箭头：</b>", form.parent())
        form.addRow(hdr2)

        self.arrowNormalColorBtn = QPushButton("选择", form.parent())
        self.arrowNormalColorBtn.clicked.connect(self._choose_arrow_normal_color)
        form.addRow("颜色", self.arrowNormalColorBtn)

        self.arrowNormalWidthSpin = QDoubleSpinBox(form.parent())
        self.arrowNormalWidthSpin.setRange(0.5, 20.0)
        self.arrowNormalWidthSpin.setSingleStep(0.5)
        self.arrowNormalWidthSpin.setDecimals(1)
        self.arrowNormalWidthSpin.valueChanged.connect(self._on_arrow_normal_width_changed)
        form.addRow("粗细", self.arrowNormalWidthSpin)

    def _on_arrow_size_changed(self, value: float):
        if self._updating:
            return
        self._set("arrow_size", float(value))
        ArrowItem.arrow_size = float(value)
        self._refresh_scene()

    def _on_arrow_current_width_changed(self, value: float):
        if self._updating:
            return
        self._set("arrow_current_width", float(value))
        ArrowItem.current_width = float(value)
        self._refresh_scene()

    def _on_arrow_normal_width_changed(self, value: float):
        if self._updating:
            return
        self._set("arrow_normal_width", float(value))
        ArrowItem.normal_width = float(value)
        self._refresh_scene()

    def _choose_arrow_current_color(self):
        color = self._choose_color(
            self._get("arrow_current_color", "#d35400"),
            "选择当前箭头颜色",
        )
        if color is not None:
            self._set("arrow_current_color", color.name())
            ArrowItem.current_color = color
            self._apply_color_button_style(self.arrowCurrentColorBtn, color)
            self._refresh_scene()

    def _choose_arrow_normal_color(self):
        color = self._choose_color(
            self._get("arrow_normal_color", "#000000"),
            "选择普通箭头颜色",
        )
        if color is not None:
            self._set("arrow_normal_color", color.name())
            ArrowItem.normal_color = color
            self._apply_color_button_style(self.arrowNormalColorBtn, color)
            self._refresh_scene()

    # ── (2) 时间轴字体 ──

    # def _build_timeline_font_group(self, root: QVBoxLayout):
    #     form = self._make_group("时间轴字号调整", root.parent())

    #     self.timelineNodeFontSpin = QSpinBox(form.parent())
    #     self.timelineNodeFontSpin.setRange(2, 48)
    #     self.timelineNodeFontSpin.setSingleStep(1)
    #     self.timelineNodeFontSpin.valueChanged.connect(self._on_timeline_node_font_changed)
    #     form.addRow("图节点字号", self.timelineNodeFontSpin)

    #     self.timelineBeatFontSpin = QSpinBox(form.parent())
    #     self.timelineBeatFontSpin.setRange(2, 48)
    #     self.timelineBeatFontSpin.setSingleStep(1)
    #     self.timelineBeatFontSpin.valueChanged.connect(self._on_timeline_beat_font_changed)
    #     form.addRow("刻度拍数字号", self.timelineBeatFontSpin)

    # def _on_timeline_node_font_changed(self, value: int):
    #     if self._updating:
    #         return
    #     self._set("timeline_node_font_size", int(value))
    #     self._apply_timeline_fonts()

    # def _on_timeline_beat_font_changed(self, value: int):
    #     if self._updating:
    #         return
    #     self._set("timeline_beat_font_size", int(value))
    #     self._apply_timeline_fonts()

    # def _apply_timeline_fonts(self):
    #     mw = self._main_window
    #     if mw is None:
    #         return
    #     tw = getattr(mw, "timelineMainWidget", None)
    #     if tw is None:
    #         return
    #     tw._node_font_size = int(self._get("timeline_node_font_size", 9))
    #     tw._beat_font_size = int(self._get("timeline_beat_font_size", 9))
    #     tw.update()

    # ────────────── 控件刷新 ──────────────

    def _apply_to_controls(self):
        """将当前设置映射到 UI 控件。"""
        self._updating = True
        self.commonFontSpin.setValue(int(self._get("common_font_size", 9)))
        self.dockFontSpin.setValue(int(self._get("dock_font_size", 9)))

        # self.timelineNodeFontSpin.setValue(int(self._get("timeline_node_font_size", 9)))
        # self.timelineBeatFontSpin.setValue(int(self._get("timeline_beat_font_size", 9)))

        self.performerSizeSpin.setValue(float(self._get("performer_size", 10.0)))
        self._apply_color_button_style(
            self.performerDotColorBtn,
            QColor(self._get("performer_dot_color", "#2aa6ff")),
        )
        self._apply_color_button_style(
            self.performerSelectedColorBtn,
            QColor(self._get("performer_selected_pen_color", "#f39c12")),
        )
        self.prePointRadiusSpin.setValue(float(self._get("pre_point_radius", 2.0)))
        self._apply_color_button_style(
            self.prePointColorBtn,
            QColor(self._get("pre_point_color", "#444444")),
        )

        self._apply_color_button_style(
            self.labelColorBtn,
            QColor(self._get("label_color", "#000000")),
        )
        self.labelSizeSpin.setValue(int(self._get("label_size", 12)))
        self.labelOffsetSpin.setValue(int(self._get("label_offset", 15)))
        self.labelPosSpin.setValue(int(self._get("label_pos", 90)))

        self.refHandleSizeSpin.setValue(float(self._get("reference_handle_size", 10.0)))
        self.moveHandleSizeSpin.setValue(float(self._get("movement_handle_size", 32.0)))
        self.moveHandleRatioSpin.setValue(float(self._get("movement_handle_inner_ratio", 0.45)))

        self.helperRadiusSpin.setValue(int(self._get("helper_radius", 12)))

        self.arrowSizeSpin.setValue(float(self._get("arrow_size", 8.0)))
        self._apply_color_button_style(
            self.arrowCurrentColorBtn,
            QColor(self._get("arrow_current_color", "#d35400")),
        )
        self.arrowCurrentWidthSpin.setValue(float(self._get("arrow_current_width", 2.5)))
        self._apply_color_button_style(
            self.arrowNormalColorBtn,
            QColor(self._get("arrow_normal_color", "#000000")),
        )
        self.arrowNormalWidthSpin.setValue(float(self._get("arrow_normal_width", 1.5)))
        
        self._updating = False

    def _apply_all_to_targets(self):
        """将当前设置同步到所有归属对象（程序启动时调用）。"""
        # (1) 通用字体
        self._apply_common_font()
        # (1b) 控制台面板字体
        self._apply_dock_font()
        # (2) 时间轴字体
        # self._apply_timeline_fonts()
        # (3) 点位
        PerformerPointItem.dot_color = QColor(self._get("performer_dot_color", "#2aa6ff"))
        PerformerPointItem.selected_pen_color = QColor(self._get("performer_selected_pen_color", "#f39c12"))
        PerformerPointItem.default_size = float(self._get("performer_size", 10.0))
        self._apply_pre_point()
        # (4) label
        self._apply_label()
        # (5) ReferenceHandleItem
        ReferenceHandleItem.default_size = float(self._get("reference_handle_size", 10.0))
        # (6) MovementControlHandleItem
        MovementControlHandleItem.default_size = float(self._get("movement_handle_size", 32.0))
        MovementControlHandleItem.default_inner_ratio = float(self._get("movement_handle_inner_ratio", 0.45))
        # (7) helper
        self._apply_helper_radius()
        # (8) ArrowItem
        ArrowItem.current_color = QColor(self._get("arrow_current_color", "#d35400"))
        ArrowItem.current_width = float(self._get("arrow_current_width", 2.5))
        ArrowItem.normal_color = QColor(self._get("arrow_normal_color", "#000000"))
        ArrowItem.normal_width = float(self._get("arrow_normal_width", 1.5))
        ArrowItem.arrow_size = float(self._get("arrow_size", 8.0))

    # ────────────── 工具方法 ──────────────

    def _choose_color(self, initial: str, title: str) -> QColor | None:
        color = QColorDialog.getColor(QColor(initial), self, title)
        if color.isValid():
            return color
        return None

    def _apply_color_button_style(self, button: QPushButton, color: QColor):
        brightness = (color.red() * 299 + color.green() * 587 + color.blue() * 114) / 1000
        text_color = "#000000" if brightness > 160 else "#ffffff"
        button.setText(color.name().upper())
        button.setStyleSheet(
            f"background-color: {color.name()}; color: {text_color};"
            f" border: 1px solid #666666; padding: 4px 10px;"
        )

    def _refresh_scene(self):
        """触发场景重绘。"""
        scene = self._scene
        if scene is None:
            return
        scene._render_points_for_active_node()
        scene.update()

    # 提供给外部的字体大小读取接口
    @property
    def font_size(self) -> int:
        return self._font_size
