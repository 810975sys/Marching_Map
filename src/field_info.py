"""
场地与网格模块
- FieldInfo: 存储网格和场地参数
- GridRenderer: 根据设置绘制网格和数字
"""
from PyQt6.QtCore import QObject, QPointF, QRectF, pyqtSignal
from PyQt6.QtGui import QColor, QPen, QFont, QPainter
from pathlib import Path
import json

SCALE_MIN = 10  # 最小scale比例
SCALE_MAX = 100 # 最大缩放比例
ZOOM_PERCENT_FACTOR = 5 # 缩放百分比与缩放比例的换算因子（% = scale * factor），便于UI显示和调整缩放级别。
ZOOM_PERCENT_MIN = SCALE_MIN * ZOOM_PERCENT_FACTOR
ZOOM_PERCENT_MAX = SCALE_MAX * ZOOM_PERCENT_FACTOR

def field_default_dir() -> Path:
    """获取场地配置默认目录。"""
    project_root = Path(__file__).resolve().parent.parent
    directory = project_root / "fields"
    directory.mkdir(parents=True, exist_ok=True)
    return directory

def _parse_color(value, fallback: QColor) -> QColor:
    """把字符串颜色值解析为 `QColor`，失败则回退到默认值。"""
    if isinstance(value, str):
        color = QColor(value)
        if color.isValid():
            return color
    return QColor(fallback)

def format_value(value: float) -> str:
    """格式化坐标标签数值，整数显示为整数，小数显示三位有效数字。"""
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.3f}".rstrip("0").rstrip(".")

class FieldInfo(QObject):
    """场地参数模型。

    负责统一存储网格、场地尺寸、坐标显示与缩放偏移，
    并通过 `changed` 信号通知视图重绘。
    """

    changed = pyqtSignal()
    # 参数即将被修改前发出，携带参数键（用于撤销/重做的“同一参数连续修改合并”）
    preChange = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        # 网格参数
        self.bg_grid_color = QColor(128, 255, 255)  # 背景网格颜色
        self.bg_grid_width = 1  # 背景网格线宽
        self.field_line_color = QColor(128, 128, 128)  # 行进场地经纬线颜色
        self.field_line_width = 2  # 行进场地经纬线线宽
        self.bold_interval = 8  # 每8条经纬线绘制一条场地线

        # 场地参数
        self.field_width = 40   # 场地长度（米）
        self.field_height = 30  # 场地宽度（米）
        self.scale = 22         # 显示缩放比例（像素/米）
        self.offset = QPointF(0, 0) # 画布偏移量（像素）
        self.unit = 5           # 相邻场地格线间距（米）
        self.grid_step = self.unit/self.bold_interval    # 网格绘制间距（米）
        
        # 坐标参数
        self.label_abs = True   # 坐标显示绝对值（True）还是相对值（False）
        self.label_zoom = 1    # 坐标字体大小（pt）（与缩放值共同决定字体实际像素大小）
        
        self.top_display = 0    # 上侧 横坐标显示 (不显示/旋转角度：-1/0+)
        self.bottom_display = 0 # 下侧 横坐标显示 (……)
        self.label_y_offset = -15       # 上下侧 横坐标偏移量，调整坐标距离边线的距离，单位像素
        self.label_y_cnt = 4            # 上下侧 横坐标显示数量（单侧，从0开始计数，另一边对称）
        self.label_y_zero_index = 4     # 从左起第几条场地线为0线（纵向）
        
        self.left_display = 0   # 左侧 纵坐标显示 (……)
        self.right_display = 0  # 右侧 纵坐标显示 (……)
        self.label_x_offset = -5        # 左右侧 纵坐标偏移量，调整坐标距离边线的距离，单位像素
        self.label_x_cnt = 2            # 左右侧 纵坐标显示数量（单侧，从0开始计数，另一边对称）
        self.label_x_zero_index = 3     # 从上起第几条场地线为0线（横向）
        self.label_y_zero_step = self.label_y_zero_index * self.bold_interval
        self.label_x_zero_step = self.label_x_zero_index * self.bold_interval

    def _emit_changed(self):
        """统一触发配置变更信号。"""
        self.changed.emit()

    def _notify_pre_change(self, key: str):
        """参数修改前通知（供撤销/重做合并同一参数的连续修改）。"""
        self.preChange.emit(key)

    def _clamp_zero_step(self, step: int, limit: int) -> int:
        """确保0线步数在合理范围内，避免标签显示异常。"""
        return max(0, min(limit, int(step)))

    def _zero_step_limit_x(self) -> int:
        """计算0线步数的最大合理值（以场地中心为0点，避免标签显示在场地外）"""
        return int(round(self.field_width / self.grid_step))

    def _zero_step_limit_y(self) -> int:
        """计算0线步数的最大合理值（以场地中心为0点，避免标签显示在场地外）"""
        return int(round(self.field_height / self.grid_step))

    @property
    def field_rect(self):
        # 动态计算当前场地矩形（米）
        w, h = self.field_width, self.field_height
        return QRectF(-w/2, -h/2, w, h)

    def to_dict(self) -> dict:
        """序列化为可持久化字典。"""
        return {
            "bg_grid_color": self.bg_grid_color.name(),
            "bg_grid_width": self.bg_grid_width,
            "field_line_color": self.field_line_color.name(),
            "field_line_width": self.field_line_width,
            "bold_interval": self.bold_interval,
            "field_width": self.field_width,
            "field_height": self.field_height,
            "label_abs": self.label_abs,
            "label_zoom": self.label_zoom,
            "top_display": self.top_display,
            "bottom_display": self.bottom_display,
            "left_display": self.left_display,
            "right_display": self.right_display,
            "label_y_offset": self.label_y_offset,
            "label_x_offset": self.label_x_offset,
            "label_y_cnt": self.label_y_cnt,
            "label_x_cnt": self.label_x_cnt,
            "label_y_zero_step": self.label_y_zero_step,
            "label_x_zero_step": self.label_x_zero_step,
        }

    def load_from_dict(self, data: dict):
        """从持久化字典恢复参数，并进行必要的边界修正。"""
        if not isinstance(data, dict):
            raise ValueError("场地设置文件格式无效")

        self.bg_grid_color = _parse_color(data.get("bg_grid_color"), self.bg_grid_color)
        self.bg_grid_width = max(1, int(data.get("bg_grid_width", self.bg_grid_width)))
        self.field_line_color = _parse_color(data.get("field_line_color"), self.field_line_color)
        self.field_line_width = max(1, int(data.get("field_line_width", self.field_line_width)))

        bold_interval = int(data.get("bold_interval", self.bold_interval))
        self.bold_interval = max(1, bold_interval)
        self.grid_step = self.unit / self.bold_interval

        field_width = int(data.get("field_width", self.field_width))
        field_height = int(data.get("field_height", self.field_height))
        self.field_width = max(5, int(round(field_width / 5)) * 5)
        self.field_height = max(5, int(round(field_height / 5)) * 5)

        self.label_abs = bool(data.get("label_abs", self.label_abs))
        self.label_zoom = max(0.1, float(data.get("label_zoom", self.label_zoom)))
        
        self.top_display = int(data.get("top_display", self.top_display))
        self.bottom_display = int(data.get("bottom_display", self.bottom_display))
        self.left_display = int(data.get("left_display", self.left_display))
        self.right_display = int(data.get("right_display", self.right_display))

        self.label_y_offset = int(data.get("label_y_offset", self.label_y_offset))
        self.label_x_offset = int(data.get("label_x_offset", self.label_x_offset))
        self.label_y_cnt = max(0, int(data.get("label_y_cnt", self.label_y_cnt)))
        self.label_x_cnt = max(0, int(data.get("label_x_cnt", self.label_x_cnt)))

        self.label_y_zero_step = self._clamp_zero_step(
            int(data.get("label_y_zero_step", self.label_y_zero_step)),
            self._zero_step_limit_x(),
        )
        self.label_x_zero_step = self._clamp_zero_step(
            int(data.get("label_x_zero_step", self.label_x_zero_step)),
            self._zero_step_limit_y(),
        )
        self.label_y_zero_index = self.label_y_zero_step / self.bold_interval
        self.label_x_zero_index = self.label_x_zero_step / self.bold_interval

        self._emit_changed()

    def set_field_size(self, width: int, height: int):
        """设置场地长宽（按 5 米网格对齐）。"""
        self._notify_pre_change("field_size")
        self.field_width = max(5, int(round(width / 5)) * 5)
        self.field_height = max(5, int(round(height / 5)) * 5)
        self.label_y_zero_step = self._clamp_zero_step(self.label_y_zero_step, self._zero_step_limit_x())
        self.label_x_zero_step = self._clamp_zero_step(self.label_x_zero_step, self._zero_step_limit_y())
        self._emit_changed()

    def set_scale(self, scale: float):
        """设置缩放比例（受全局最小/最大值约束）。"""
        self._notify_pre_change("scale")
        self.scale = max(SCALE_MIN, min(SCALE_MAX, scale))
        self._emit_changed()

    def set_offset(self, x: float, y: float):
        """设置画布偏移（像素）。"""
        self.offset = QPointF(x, y)
        self._emit_changed()

    def set_grid_step(self, step: float):
        """设置网格间距"""
        self.grid_step = step
        self._emit_changed()

    # 视觉参数接口
    def set_bg_grid_color(self, color: QColor):
        """设置背景网格颜色。"""
        self._notify_pre_change("bg_grid_color")
        self.bg_grid_color = color
        self._emit_changed()

    def set_bg_grid_width(self, width: int):
        """设置背景网格线宽。"""
        self._notify_pre_change("bg_grid_width")
        self.bg_grid_width = width
        self._emit_changed()

    def set_field_line_color(self, color: QColor):
        """设置场地经纬线颜色。"""
        self._notify_pre_change("field_line_color")
        self.field_line_color = color
        self._emit_changed()

    def set_field_line_width(self, width: int):
        """设置场地经纬线线宽。"""
        self._notify_pre_change("field_line_width")
        self.field_line_width = width
        self._emit_changed()

    def set_bold_interval(self, interval: int):
        """设置场地线间隔（每N条网格线绘制一条场地线）。"""
        self._notify_pre_change("bold_interval")
        self.bold_interval = interval
        self.grid_step = self.unit / self.bold_interval
        self.label_y_zero_step = self._clamp_zero_step(self.label_y_zero_step, self._zero_step_limit_x())
        self.label_x_zero_step = self._clamp_zero_step(self.label_x_zero_step, self._zero_step_limit_y())
        self._emit_changed()

    def set_label_abs(self, enabled: bool):
        """设置坐标显示绝对值（True）还是相对值（False）"""
        self._notify_pre_change("label_abs")
        self.label_abs = enabled
        self._emit_changed()

    def set_label_zoom(self, zoom: float):
        """设置坐标字体大小（pt）。实际像素大小由 `label_zoom` 与 `scale` 共同决定"""
        self._notify_pre_change("label_zoom")
        self.label_zoom = max(0.1, float(zoom))
        self._emit_changed()
        
    def set_label_display(self, top: int, bottom: int, left: int, right: int):
        """设置四侧坐标显示模式（旋转角度，-1表示不显示）"""
        self._notify_pre_change("label_display")
        self.top_display = top
        self.bottom_display = bottom
        self.left_display = left
        self.right_display = right
        self._emit_changed()

    def set_label_offsets(self, y_offset: int, x_offset: int):
        """设置坐标偏移量"""
        self._notify_pre_change("label_offsets")
        self.label_y_offset = int(y_offset)
        self.label_x_offset = int(x_offset)
        self._emit_changed()

    def set_label_counts(self, y_count: int, x_count: int):
        """设置坐标显示数量（单侧，从0开始计数，另一边对称）"""
        self._notify_pre_change("label_counts")
        self.label_y_cnt = max(0, int(y_count))
        self.label_x_cnt = max(0, int(x_count))
        self._emit_changed()

    def set_label_y_zero_step(self, step: int):
        """设置纵向0线位置（以中心为基准，单位为网格步数）"""
        self._notify_pre_change("label_y_zero_step")
        self.label_y_zero_step = self._clamp_zero_step(step, self._zero_step_limit_x())
        self.label_y_zero_index = self.label_y_zero_step / self.bold_interval
        self._emit_changed()

    def set_label_x_zero_step(self, step: int):
        """设置横向0线位置（以中心为基准，单位为网格步数）"""
        self._notify_pre_change("label_x_zero_step")
        self.label_x_zero_step = self._clamp_zero_step(step, self._zero_step_limit_y())
        self.label_x_zero_index = self.label_x_zero_step / self.bold_interval
        self._emit_changed()
    
    
def saveFieldInfo(field_info: FieldInfo, file_path: Path):
    """保存场地信息到指定文件。"""
    if not file_path:
        return
    target = Path(file_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(field_info.to_dict(), f, ensure_ascii=False, indent=2)

def loadFieldInfo(field: FieldInfo, file_path: Path):
    """从指定文件加载场地信息。"""
    if not file_path or not file_path.exists():
        raise FileNotFoundError(f"场地设置文件未找到：{file_path}")
    with open(file_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    field.load_from_dict(data)