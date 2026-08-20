"""视频导出模块。

包含：
1. ``VideoExportDialog`` —— 导出参数设置弹窗（导出视角 / 分辨率 / 帧率 / 保存路径）。
2. ``export_video`` —— 按“完整播放演示”一致的动画逐帧渲染，并用 ffmpeg 合成视频。

帧渲染不依赖 QGraphicsScene 的图元层级，而是直接读取已确认数据
（node_points / field_info 等）用 QPainter 逐帧绘制，渲染逻辑与播放演示的
``set_preview_sub_beat → _render_points_for_sub_beat + drawBackground`` 保持一致：
- 背景网格/场地线/坐标标签：GridRenderer 按导出缩放绘制；
- 上一节点点位：灰色半透明圆点（pre_view 样式）；
- 当前点位：彩色圆点 + 标签（按 sub-beat 插值移动）。

这样导出过程不影响当前编辑状态，且相比“重建 QGraphicsScene 图元再 render”更快。
"""
from __future__ import annotations

import math
import os
import subprocess
import tempfile
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, Qt
from PyQt6.QtGui import QImage, QPainter, QColor, QPen, QFont, QBrush
from PyQt6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QFormLayout,
    QComboBox,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QLabel,
    QFileDialog,
    QDialogButtonBox,
    QMessageBox,
)

from src.field_info import FieldInfo
from src.field_renderer import GridRenderer
from src.scene_items import PerformerPointItem
from src.ffmpeg_utils import find_ffmpeg

VIEW_CONDUCTOR = "指挥视角"
VIEW_PERFORMER = "表演者视角"

# 基准缩放（像素/米）：对应默认窗口缩放，用于让视频里的点位/标签与场地保持比例
REF_SCALE = 22.0

# 预设分辨率（label, 宽, 高）
RESOLUTION_PRESETS = [
    ("1920×1080（16:9）", 1920, 1080),
    ("1280×720（16:9）", 1280, 720),
    ("1600×1200（4:3）", 1600, 1200),
    ("1280×960（4:3）", 1280, 960),
    ("1024×768（4:3）", 1024, 768),
    ("800×600（4:3）", 800, 600),
]
_CUSTOM_RES = "自定义…"


class VideoExportDialog(QDialog):
    """视频导出参数设置弹窗。"""

    def __init__(self, parent=None, default_path=None):
        super().__init__(parent)
        self.setWindowTitle("导出为视频")
        self.setMinimumWidth(480)

        form = QFormLayout()

        # ── 导出视角 ──
        self.view_combo = QComboBox(self)
        self.view_combo.addItem(VIEW_CONDUCTOR)
        self.view_combo.addItem(VIEW_PERFORMER)
        self.view_combo.setCurrentText(VIEW_CONDUCTOR)
        self.view_combo.currentTextChanged.connect(self._on_view_changed)
        form.addRow("导出视角：", self.view_combo)

        # ── 分辨率（预设 + 自定义） ──
        res_row = QHBoxLayout()
        self.res_combo = QComboBox(self)
        for label, w, h in RESOLUTION_PRESETS:
            self.res_combo.addItem(label, (int(w), int(h)))
        self.res_combo.addItem(_CUSTOM_RES, None)
        self.res_combo.currentIndexChanged.connect(self._on_res_changed)
        res_row.addWidget(self.res_combo, 1)

        self.width_spin = QSpinBox(self)
        self.width_spin.setRange(320, 3840)
        self.width_spin.setValue(1920)
        self.height_spin = QSpinBox(self)
        self.height_spin.setRange(240, 2160)
        self.height_spin.setValue(1080)
        res_row.addWidget(QLabel("宽："))
        res_row.addWidget(self.width_spin)
        res_row.addWidget(QLabel("高："))
        res_row.addWidget(self.height_spin)
        form.addRow("分辨率：", res_row)
        self._on_res_changed()  # 初始化自定义控件状态

        # ── 帧率 ──
        self.fps_spin = QSpinBox(self)
        self.fps_spin.setRange(1, 120)
        self.fps_spin.setValue(30)
        self.fps_spin.setToolTip("视频帧率，帧率越高动画越平滑，导出耗时越长")
        form.addRow("帧率（fps）：", self.fps_spin)

        # ── 保存路径 ──
        self.path_edit = QLineEdit(str(default_path) if default_path else "", self)
        browse_btn = QPushButton("浏览…", self)
        browse_btn.clicked.connect(self._browse_path)
        path_row = QHBoxLayout()
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse_btn)
        form.addRow("保存位置：", path_row)

        # hint = QLabel("导出的视频与“播放演示”一致：点位按节拍移动、音频随整轨播放。")
        # hint.setWordWrap(True)
        # hint.setStyleSheet("color:#666;")
        # form.addRow(hint)

        # ── 按钮 ──
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            self,
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("导出")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("取消")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        layout.addLayout(form)
        layout.addWidget(buttons)

    # ──────────────── 交互 ────────────────
    def _on_view_changed(self, text: str):
        """视角切换时，若文件名带旧的视角后缀则替换为新视角，保持目录不变。"""
        p = Path(self.path_edit.text().strip())
        if not p.name:
            return
        name = p.stem
        for v in (VIEW_CONDUCTOR, VIEW_PERFORMER):
            if name.endswith("_" + v):
                name = name[: -len(v) - 1]
                break
        self.path_edit.setText(str(p.parent / f"{name}_{text}{p.suffix}"))

    def _on_res_changed(self):
        """仅当选择“自定义”时启用宽高输入框。"""
        is_custom = self.res_combo.currentData() is None
        self.width_spin.setEnabled(is_custom)
        self.height_spin.setEnabled(is_custom)
        if not is_custom and self.res_combo.currentData() is not None:
            w, h = self.res_combo.currentData()
            self.width_spin.setValue(int(w))
            self.height_spin.setValue(int(h))

    def _browse_path(self):
        """弹出文件保存对话框选择输出路径。"""
        current = self.path_edit.text().strip()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存视频",
            current,
            "MP4 视频 (*.mp4)",
        )
        if file_path:
            self.path_edit.setText(file_path)

    def result_settings(self) -> dict | None:
        """返回导出参数字典；路径为空时返回 None。"""
        path = self.path_edit.text().strip()
        if not path:
            return None
        data = self.res_combo.currentData()
        if data is not None:
            w, h = data
        else:
            w, h = self.width_spin.value(), self.height_spin.value()
        return {
            "view": self.view_combo.currentText(),
            "width": int(w),
            "height": int(h),
            "fps": int(self.fps_spin.value()),
            "path": str(Path(path)),
        }


class _FrameRenderer:
    """按播放演示一致的规则把某个拍位渲染为一帧图像。"""

    def __init__(self, scene, timeline, width: int, height: int, view_name: str):
        self.scene = scene
        self.timeline = timeline
        self.width = int(width)
        self.height = int(height)
        # 表演者视角：队形坐标取负（绕场地中心 180°），与 PDF 导出的“表演者视角”一致
        self.negate = view_name == VIEW_PERFORMER

        field = scene.field_info
        self.field_rect = field.field_rect
        self.export_scale = self._compute_export_scale()
        self.offset = QPointF(self._offset_x(), self._offset_y())

        # 导出用场地副本：背景网格/场地线/坐标标签按导出缩放绘制
        self.export_field_info = FieldInfo(None)
        self.export_field_info.load_from_dict(field.to_dict())
        self.export_field_info.scale = self.export_scale
        self.export_field_info.set_offset(self.offset.x(), self.offset.y())
        self.grid_renderer = GridRenderer(self.export_field_info)

        # 点位/标签按导出缩放相对基准缩放放大，保持与场地比例
        self.size_factor = self.export_scale / REF_SCALE
        self.dot_radius = (PerformerPointItem.default_size / 2.0) * self.size_factor
        self.pre_radius = scene.pre_point_radius * self.size_factor
        self.label_font_pt = max(4.0, scene.label_size * self.size_factor)
        self.label_offset_px = scene.label_offset * self.size_factor
        self.label_pos_deg = int(scene.label_pos) % 360
        self.label_color = QColor(scene.label_color)
        self.pre_point_color = QColor(scene.pre_point_color)
        self.dot_color = QColor(PerformerPointItem.dot_color)

        # 与 set_preview_sub_beat 一致的拍位上限（超出最后节点时保持最后一张图）
        self.total_beats = float(sum(getattr(timeline, "graph_list", [0])[1:]))

    def _content_padding(self, export_scale: float) -> tuple[float, float, float]:
        """计算内容区留白（水平、上、下），给坐标标签预留空间，保证信息显示完整。

        逻辑参考 scheme_scene._pdf_export_content_padding：
        - 标签字号像素 = label_zoom * 导出缩放（与 draw_field_labels 一致，
          且导出时字号受 max_font_size=36 限制，因此同样封顶到 36）；
        - 每侧需为“标签偏移 + 字号”预留空间；
        - 视频没有页脚文本，上/下留白保持对称（不同于 PDF 的下侧加倍）。

        返回 (horizontal_padding, top_padding, bottom_padding)。
        """
        field = self.scene.field_info
        font_px = min(36.0, float(field.label_zoom) * export_scale)
        offset_px = max(
            float(abs(field.label_x_offset)) + font_px,
            float(abs(field.label_y_offset)) + font_px,
        )
        horizontal_padding = max(8.0, offset_px * 2.0)
        vertical_padding = max(8.0, offset_px * 2.0)
        return horizontal_padding, vertical_padding, vertical_padding

    def _compute_export_scale(self) -> float:
        r = self.field_rect
        fw = max(1.0, float(r.width()))
        fh = max(1.0, float(r.height()))

        # 初步以画面尺寸估算缩放，再根据留白重新计算最终缩放（参考 _pdf_export_layout）。
        export_scale = min(self.width / fw, self.height / fh)
        hpad, top_pad, bottom_pad = self._content_padding(export_scale)
        content_width = self.width - hpad * 2.0
        content_height = self.height - top_pad - bottom_pad
        export_scale = min(content_width / fw, content_height / fh)

        # 重新基于最终缩放计算留白（以应对标签尺寸随缩放变化）。
        hpad, top_pad, bottom_pad = self._content_padding(export_scale)
        content_width = self.width - hpad * 2.0
        content_height = self.height - top_pad - bottom_pad
        export_scale = min(content_width / fw, content_height / fh)
        return max(0.01, export_scale)

    def _offset_x(self) -> float:
        r = self.field_rect
        hpad, _, _ = self._content_padding(self.export_scale)
        content_left = hpad
        content_width = self.width - hpad * 2.0
        return (
            content_left
            + (content_width - float(r.width()) * self.export_scale) / 2.0
            - float(r.left()) * self.export_scale
        )

    def _offset_y(self) -> float:
        r = self.field_rect
        _, top_pad, bottom_pad = self._content_padding(self.export_scale)
        content_top = top_pad
        content_height = self.height - top_pad - bottom_pad
        return (
            content_top
            + (content_height - float(r.height()) * self.export_scale) / 2.0
            - float(r.top()) * self.export_scale
        )

    def _to_px(self, fx: float, fy: float) -> tuple[float, float]:
        """场地坐标（米）→ 帧像素；表演者视角对坐标取负。"""
        x = fx if not self.negate else -fx
        y = fy if not self.negate else -fy
        return x * self.export_scale + self.offset.x(), y * self.export_scale + self.offset.y()

    def _points_at_beat(self, beat_float: float) -> tuple[list[dict], list[dict]]:
        """返回 (当前点位列表, 上一节点点位列表)，逻辑与 _render_points_for_sub_beat 一致。"""
        scene = self.scene
        beat_float = max(0.0, float(beat_float))
        if self.total_beats > 0:
            beat_float = min(beat_float, self.total_beats)

        starts = [scene._node_start_beat(i) for i in range(len(scene.node_points))]
        left_node = None
        right_node = None
        for left in range(len(starts) - 1):
            if starts[left] <= beat_float < starts[left + 1]:
                left_node, right_node = left, left + 1
                break

        int_beat = int(beat_float)
        node_at_beat = scene._node_index_at_beat(int_beat)
        is_exact_node = node_at_beat is not None and abs(beat_float - float(int_beat)) < 0.001

        if is_exact_node:
            preview_node = node_at_beat
            prev_points = scene.node_points[preview_node - 1] if preview_node > 0 else []
            current_points = scene.node_points[preview_node]
        elif left_node is not None and right_node is not None:
            prev_points = scene.node_points[left_node]
            current_points = scene._interpolate_points_at_sub_beat(left_node, right_node, beat_float)
        else:
            prev_points = scene.node_points[scene.active_node - 1] if scene.active_node > 0 else []
            current_points = scene.node_points[scene.active_node]
        return current_points, prev_points

    def render_frame(self, beat_float: float) -> QImage:
        """把拍位渲染为一帧 RGB 图像。"""
        image = QImage(self.width, self.height, QImage.Format.Format_RGB888)
        image.fill(Qt.GlobalColor.white)

        painter = QPainter(image)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # 背景网格 + 场地线 + 坐标标签（与 drawBackground 一致，但用导出缩放）
        frame_rect = QRectF(0, 0, self.width, self.height)
        self.grid_renderer.draw_background_grid(painter, frame_rect)
        self.grid_renderer.draw_field_lines(painter)
        self.grid_renderer.draw_field_labels(painter, max_font_size=36)

        current_points, prev_points = self._points_at_beat(beat_float)

        for point in prev_points:
            self._draw_prev_point(painter, point)
        for point in current_points:
            self._draw_point(painter, point)

        painter.end()
        return image

    def _draw_prev_point(self, painter: QPainter, point: dict):
        px, py = self._to_px(float(point["x"]), float(point["y"]))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.setBrush(QBrush(self.pre_point_color))
        painter.drawEllipse(QPointF(px, py), self.pre_radius, self.pre_radius)

    def _draw_point(self, painter: QPainter, point: dict):
        px, py = self._to_px(float(point["x"]), float(point["y"]))
        painter.setPen(QPen(Qt.PenStyle.NoPen))
        painter.setBrush(QBrush(self.dot_color))
        painter.drawEllipse(QPointF(px, py), self.dot_radius, self.dot_radius)

        text = self.scene._get_point_label_text(int(point["id"]))
        if not text:
            return
        font = QFont()
        font.setPointSizeF(self.label_font_pt)
        painter.setFont(font)
        painter.setPen(QPen(self.label_color))
        metrics = painter.fontMetrics()
        br = metrics.boundingRect(text)
        angle_rad = math.radians(self.label_pos_deg)
        dx = math.cos(angle_rad) * self.label_offset_px
        dy = math.sin(angle_rad) * self.label_offset_px
        painter.drawText(
            QRectF(
                px + dx - br.width() / 2.0,
                py + dy - br.height() / 2.0,
                br.width(),
                br.height(),
            ),
            Qt.AlignmentFlag.AlignCenter,
            text,
        )


def _frame_to_rgb24(image: QImage) -> bytes:
    """把 QImage 转为 ffmpeg rawvideo rgb24 所需的字节（去除每行对齐填充）。"""
    image = image.convertToFormat(QImage.Format.Format_RGB888)
    bpl = image.bytesPerLine()
    row = image.width() * 3
    height = image.height()
    # PyQt6 的 constBits() 返回 sip.voidptr，无长度信息，需用 asstring(n) 读取
    raw = bytes(image.constBits().asstring(bpl * height))
    if bpl == row:
        return raw
    buf = bytearray(row * height)
    for y in range(height):
        src = y * bpl
        dst = y * row
        buf[dst : dst + row] = raw[src : src + row]
    return bytes(buf)


def export_video(window, scene, timeline, settings, progress_cb=None, is_canceled=None) -> str | None:
    """按播放演示一致渲染整段并合成视频；返回输出文件路径，失败/取消返回 None。

    progress_cb(done: int, total: int, label: str) —— 进度回调（合成/渲染共用）；
    is_canceled() -> bool —— 返回是否应取消导出。
    """
    fps = int(settings["fps"])
    width = int(settings["width"])
    height = int(settings["height"])
    view_name = str(settings["view"])
    output_path = Path(settings["path"])
    if output_path.suffix.lower() != ".mp4":
        output_path = output_path.with_suffix(".mp4")

    duration = float(timeline._audio_right_time())
    if duration <= 0:
        if progress_cb is not None:
            progress_cb(1, 1, "没有可导出的内容")
        return None
    total_frames = max(1, int(round(duration * fps)))

    ffmpeg = find_ffmpeg()
    if ffmpeg is None:
        QMessageBox.warning(
            window,
            "未找到 ffmpeg",
            "未找到 ffmpeg，无法导出视频。\n请确认 ffmpeg 已安装或随程序一起打包。",
            QMessageBox.StandardButton.Ok,
        )
        return None

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # ── 1) 合成整轨音频（无音频段则视频为静音） ──
    audio_wav = None
    tmp_wav = None
    if timeline.audio_segments:
        fd, tmp_path = tempfile.mkstemp(suffix=".wav", prefix="mm_export_")
        os.close(fd)
        tmp_wav = tmp_path

        def _synth_progress(done: int, n: int, name: str):
            if progress_cb is not None:
                progress_cb(int(done), int(n), f"合成音频：{name}")

        ok = timeline.synthesize_playback_audio(tmp_wav, progress_cb=_synth_progress)
        if ok:
            audio_wav = tmp_wav
        elif is_canceled is not None and is_canceled():
            return None

    # ── 2) 启动 ffmpeg：stdin 接收 rawvideo 帧，音频单独输入并混流 ──
    cmd = [
        str(ffmpeg),
        "-y",
        "-f", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{width}x{height}",
        "-r", str(fps),
        "-i", "-",
    ]
    if audio_wav:
        cmd += ["-i", str(audio_wav)]
    cmd += [
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
    ]
    if audio_wav:
        cmd += ["-c:a", "aac", "-b:a", "192k", "-shortest"]
    else:
        cmd += ["-an"]
    cmd.append(str(output_path))

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception as exc:
        if progress_cb is not None:
            progress_cb(1, 1, f"启动 ffmpeg 失败：{exc}")
        return None

    renderer = _FrameRenderer(scene, timeline, width, height, view_name)
    # 导出期间临时关闭“调整”会话预览，保证渲染的是已确认点位数据
    adjust_active = bool(getattr(scene, "_adjustment_active", False))
    canceled = False
    try:
        scene._adjustment_active = False
        for i in range(total_frames):
            if is_canceled is not None and is_canceled():
                canceled = True
                break
            if proc.poll() is not None:
                canceled = True
                break
            t = i / fps
            beat = float(timeline.audio_beat_at_time(t))
            frame = renderer.render_frame(beat)
            try:
                proc.stdin.write(_frame_to_rgb24(frame))
            except (BrokenPipeError, OSError):
                canceled = True
                break
            if progress_cb is not None:
                progress_cb(i + 1, total_frames, f"渲染帧 {i + 1}/{total_frames}")
    finally:
        scene._adjustment_active = adjust_active

    try:
        proc.stdin.close()
    except Exception:
        pass
    if canceled:
        try:
            proc.kill()
        except Exception:
            pass
    proc.wait()

    # ── 3) 清理临时音频 ──
    if tmp_wav is not None:
        try:
            Path(tmp_wav).unlink()
        except OSError:
            pass

    if canceled:
        try:
            output_path.unlink()
        except OSError:
            pass
        return None

    if proc.returncode != 0:
        try:
            output_path.unlink()
        except OSError:
            pass
        if progress_cb is not None:
            progress_cb(1, 1, "ffmpeg 编码失败")
        return None

    return str(output_path)
