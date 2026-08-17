# SPDX-License-Identifier: GPL-3.0-only
# Copyright (C) 2026 吴佳晟
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, version 3 of the License.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import sys
import os

# 确保 Python 能找到 src 包
sys.path.insert(0, os.path.dirname(__file__))
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from PyQt6.QtWidgets import QApplication
from src.mainwindow import MainWindow  # 假设你的 mainwindow.py 中定义了 MainWindow 类
from src.ffmpeg_utils import configure_pydub_ffmpeg  # 打包后 ffmpeg 不在 PATH，需显式配置给 pydub
from src.logging import setup_logging

if __name__ == "__main__":
    # 把随程序打包的 ffmpeg.exe（或开发环境找到的 ffmpeg）配置给 pydub，
    # 保证导入/导出音频时不依赖系统 PATH。
    configure_pydub_ffmpeg()
    # setup_logging()
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())