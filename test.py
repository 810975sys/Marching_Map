import sys
import random
import string
import time
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QTextEdit, QPlainTextEdit,
                             QPushButton, QGroupBox)
from PyQt6.QtCore import Qt  # 在 PyQt6 中，Qt 枚举值可能需要通过类访问，但核心模块仍是 QtCore

class CompareTextEdits(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("PyQt6: QTextEdit vs QPlainTextEdit 对比演示")
        self.setGeometry(100, 100, 1000, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QHBoxLayout(central_widget)

        # -------------------- 左侧：QTextEdit（富文本） --------------------
        left_group = QGroupBox("QTextEdit（支持富文本、图片、表格）")
        left_layout = QVBoxLayout()
        self.text_edit = QTextEdit()
        # 设置初始富文本内容
        self.text_edit.setHtml("""
            <h2>欢迎使用 QTextEdit (PyQt6)</h2>
            <p>你可以使用 <b>粗体</b>、<i>斜体</i>、<u>下划线</u>。</p>
            <p><font color="red">彩色文字</font> 和 <font size="+2">不同大小</font> 也很简单。</p>
            <ul>
                <li>支持列表</li>
                <li>支持表格</li>
            </ul>
            <table border="1">
                <tr><th>表格</th><th>示例</th></tr>
                <tr><td>富文本</td><td>支持</td></tr>
            </table>
        """)
        left_layout.addWidget(self.text_edit)

        # 按钮：获取纯文本与HTML
        btn_left_get = QPushButton("获取 QTextEdit 内容")
        btn_left_get.clicked.connect(self.on_get_textedit)
        left_layout.addWidget(btn_left_get)

        left_group.setLayout(left_layout)
        main_layout.addWidget(left_group)

        # -------------------- 右侧：QPlainTextEdit（纯文本） --------------------
        right_group = QGroupBox("QPlainTextEdit（纯文本，高性能，支持列选择）")
        right_layout = QVBoxLayout()
        self.plain_edit = QPlainTextEdit()
        self.plain_edit.setPlainText("""QPlainTextEdit 专为纯文本优化 (PyQt6)。
- 可以快速处理几十MB的日志文件。
- 按住 Alt 键，用鼠标拖拽可以按列选择文本。
- 这里不支持富文本，所有格式标记都会显示为原始字符。""")

        right_layout.addWidget(self.plain_edit)

        # 按钮：加载大量随机文本（演示性能差异）
        btn_load_big = QPushButton("加载 50 万行随机文本（演示性能）")
        btn_load_big.clicked.connect(self.on_load_huge_text)
        right_layout.addWidget(btn_load_big)

        # 按钮：获取纯文本
        btn_right_get = QPushButton("获取 QPlainTextEdit 内容")
        btn_right_get.clicked.connect(self.on_get_plaintextedit)
        right_layout.addWidget(btn_right_get)

        right_group.setLayout(right_layout)
        main_layout.addWidget(right_group)

        # 设置拉伸比例，让两个控件初始宽度相近
        main_layout.setStretch(0, 1)
        main_layout.setStretch(1, 1)

    def on_get_textedit(self):
        """演示 QTextEdit 可以分别获取纯文本和 HTML"""
        plain = self.text_edit.toPlainText()
        html = self.text_edit.toHtml()
        print("="*50)
        print("【QTextEdit 纯文本内容】:\n", plain[:200], "...(截断)")
        print("【QTextEdit HTML内容(前300字符)】:\n", html[:300], "...")

    def on_get_plaintextedit(self):
        """QPlainTextEdit 只能获取纯文本"""
        text = self.plain_edit.toPlainText()
        print("="*50)
        print("【QPlainTextEdit 纯文本内容】:\n", text[:200], "...")

    def on_load_huge_text(self):
        """生成大量随机文本，对比两个控件的加载/滚动体验"""
        print("正在生成 50 万行随机文本，QPlainTextEdit 会很快，QTextEdit 可能会明显卡顿...")
        lines = []
        for i in range(500000):
            length = random.randint(10, 30)
            line = ''.join(random.choices(string.ascii_letters + string.digits + ' ', k=length))
            lines.append(f"{i:06d}: {line}")
        huge_text = "\n".join(lines)

        # 分别写入两个控件并计时
        start = time.perf_counter()
        self.plain_edit.setPlainText(huge_text)
        print(f"QPlainTextEdit 加载完成，耗时 {time.perf_counter() - start:.2f} 秒")

        start = time.perf_counter()
        self.text_edit.setPlainText(huge_text)
        print(f"QTextEdit 加载完成，耗时 {time.perf_counter() - start:.2f} 秒")
        print("现在可以尝试滚动两个区域，QPlainTextEdit 会非常流畅，QTextEdit 可能会掉帧。")

        # 提示用户如何恢复
        self.text_edit.append("\n\n[注意] 由于大量文本，可能操作卡顿，建议重启程序恢复。")

def main():
    app = QApplication(sys.argv)
    window = CompareTextEdits()
    window.show()
    sys.exit(app.exec())  # 注意这里是 .exec() 而不是 .exec_()

if __name__ == "__main__":
    main()