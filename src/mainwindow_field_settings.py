import json
from pathlib import Path

from PyQt6.QtWidgets import QFileDialog


class MainWindowFieldSettings:
    """主窗口中的场地设置导入导出逻辑。"""

    def _field_settings_default_dir(self) -> Path:
        """获取场地配置默认目录。"""
        project_root = Path(__file__).resolve().parent.parent
        directory = project_root / "fields"
        directory.mkdir(parents=True, exist_ok=True)
        return directory

    def _field_settings_default_path(self) -> Path:
        """获取场地配置默认文件路径。"""
        return self._field_settings_default_dir() / "field_settings.json"

    def saveFieldSettings(self):
        """保存场地设置：沿用文件保存窗口，完成后右上角非阻塞提示。"""
        settings = self.scene.field_settings
        default_path = self._field_settings_default_path()
        file_path, _ = QFileDialog.getSaveFileName(
            self,
            "保存场地设置",
            str(default_path),
            "JSON 文件 (*.json)",
        )
        if not file_path:
            return

        target = Path(file_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        try:
            with open(target, "w", encoding="utf-8") as f:
                json.dump(settings.to_dict(), f, ensure_ascii=False, indent=2)
            self._show_menu_notice(f"保存成功：{target}")
        except Exception as exc:
            self._show_menu_notice(f"保存失败：{exc}", failed=True)

    def importFieldSettings(self):
        """导入场地设置：沿用文件选择窗口，完成后右上角非阻塞提示。"""
        default_dir = self._field_settings_default_dir()
        file_path, _ = QFileDialog.getOpenFileName(
            self,
            "导入场地设置",
            str(default_dir),
            "JSON 文件 (*.json)",
        )
        if not file_path:
            return

        target = Path(file_path)
        try:
            with open(target, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.scene.field_settings.load_from_dict(data)
            self._show_menu_notice(f"导入成功：{target}")
        except Exception as exc:
            self._show_menu_notice(f"导入失败：{exc}", failed=True)
