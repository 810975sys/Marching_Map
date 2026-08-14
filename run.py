#!/usr/bin/env python3
# -*- coding: utf-8 -*-

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