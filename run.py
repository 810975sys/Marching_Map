#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import sys
import os

# 确保 Python 能找到 src 包
sys.path.insert(0, os.path.dirname(__file__))
# sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from PyQt6.QtWidgets import QApplication
from src.mainwindow import MainWindow  # 假设你的 mainwindow.py 中定义了 MainWindow 类

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec())