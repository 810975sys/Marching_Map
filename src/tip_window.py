"""Tips Window"""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QDialog, QLabel, QVBoxLayout


class TipWindow(QDialog):
    """用于展示 Tips 内容的弹窗。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tips")
        self.setWindowFlag(Qt.WindowType.Tool, True)
        self.setModal(False)
        self.setMinimumSize(420, 300)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(16, 16, 16, 16)
        main_layout.setSpacing(12)

        self.tip_content = QLabel(("- 画布：滚轮缩放；鼠标中键/右键拖动\n\n"+
                              "- 方案图节点：右键编辑；快捷键'+'新增；双击插入；Ctrl+滚轮缩放\n"+
                              "  删除节点时，会同步删除该节点与下一个节点的“路径”、“跟随”状态\n\n"+
                              "- “选择”功能：按 Shift 反转组内选择；按 Ctrl 可进行单点选择\n"+
                              "  “框选”功能：按 Ctrl 可保持选择点位\n\n"+
                              "- 场地坐标：旋转角度为负则不显示"), self)
        self.tip_content.setWordWrap(True)
        self.tip_content.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.tip_content.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.tip_content.setStyleSheet("padding: 4px 0; line-height: 1.4;")

        font = self.tip_content.font()
        font.setPointSize(12)
        self.tip_content.setFont(font)
        main_layout.addWidget(self.tip_content)

    # def set_tip_text(self, text: str):
    #     """设置 Tips 文本内容。"""
    #     self.contentEdit.setPlainText(text)
