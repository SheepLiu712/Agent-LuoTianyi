import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from src.gui.chat_bubble import SystemMessage


def test_system_message_is_centered_muted_text_without_bubble_frame():
    app = QApplication.instance() or QApplication([])
    message = SystemMessage("WebSocket 错误")

    assert message.label.text() == "WebSocket 错误"
    assert message.label.alignment() & Qt.AlignmentFlag.AlignCenter
    assert "color: #555555" in message.label.styleSheet()
    assert "font-size: 14px" in message.label.styleSheet()
    assert "border: none" in message.label.styleSheet()

    message.deleteLater()
    app.processEvents()
