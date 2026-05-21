"""
非阻塞提示
在主窗口菜单栏右上角显示非阻塞提示
"""

from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtWidgets import QLabel, QSizePolicy

class MainWindowNotice:
    """主窗口菜单栏右上角的非阻塞提示逻辑。"""

    def setup_menu_notice(self):
        """初始化提示标签"""
        self.menuNoticeLabel = QLabel("", self)
        self.menuNoticeLabel.setMinimumWidth(140)
        self.menuNoticeLabel.setStyleSheet("color: #1f5e9c; padding-right: 8px;")
        self.menuBar().setCornerWidget(self.menuNoticeLabel, Qt.Corner.TopRightCorner)
        self._menu_notice_seq = 0
        self._menu_notice_raw_text = ""
        self._update_menu_notice_width()

    def _update_menu_notice_width(self):
        """根据窗口宽度限制右上角提示最大宽度，防止越界。"""
        max_width = max(180, int(self.width() * 0.38))
        self.menuNoticeLabel.setMaximumWidth(max_width)

    def _apply_menu_notice_text(self, text: str):
        """把提示文本做省略显示，完整内容放到 tooltip。"""
        self._menu_notice_raw_text = text
        self._update_menu_notice_width()
        available = max(80, self.menuNoticeLabel.maximumWidth() - 12)
        elided = self.menuNoticeLabel.fontMetrics().elidedText(
            text,
            Qt.TextElideMode.ElideMiddle,
            available,
        )
        self.menuNoticeLabel.setText(elided)
        # 把完整文本放到 tooltip，方便鼠标悬停查看完整内容
        self.menuNoticeLabel.setToolTip(text)

    def _show_menu_notice(self, text: str, failed: bool = False, timeout_ms: int = 3500):
        """在菜单栏右上角显示非阻塞提示，超时后自动清除。"""
        color = "#b00020" if failed else "#1f5e9c"
        self.menuNoticeLabel.setStyleSheet(f"color: {color}; padding-right: 8px;")
        self._apply_menu_notice_text(text)

        self._menu_notice_seq += 1
        current_seq = self._menu_notice_seq

        def clear_notice_if_latest():
            if current_seq == self._menu_notice_seq:
                self._menu_notice_raw_text = ""
                self.menuNoticeLabel.setText("")
                # 同时清除 tooltip
                self.menuNoticeLabel.setToolTip("")

        QTimer.singleShot(timeout_ms, clear_notice_if_latest)

    def resizeEvent(self, event):
        """窗口尺寸变化时重新计算提示宽度并重做省略。"""
        super().resizeEvent(event)
        self._update_menu_notice_width()
        if self._menu_notice_raw_text:
            self._apply_menu_notice_text(self._menu_notice_raw_text)
