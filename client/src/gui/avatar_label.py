"""聊天与动态共用的头像展示。"""

import base64

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QLabel

DEFAULT_AVATARS = {"user": "res/gui/user_icon.png", "agent": "res/gui/chat_agent_icon.png"}


class AvatarLabel(QLabel):
    clicked = Signal(str)

    def __init__(
        self, author_type: str, size: int = 34, parent=None, avatars=None, *, editable=False, default_agent=None
    ):
        super().__init__(parent)
        self.author_type = author_type
        self.avatars = avatars
        self.editable = editable
        self.default_agent = default_agent or DEFAULT_AVATARS["agent"]
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: transparent; border: none;")
        if editable:
            self.setCursor(Qt.CursorShape.PointingHandCursor)
        if avatars:
            avatars.changed.connect(self.refresh)
        self.refresh()

    def mousePressEvent(self, event):
        if self.editable and event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit(self.author_type)
        super().mousePressEvent(event)

    def refresh(self):
        self.set_image(self.avatars.image(self.author_type) if self.avatars else None)

    def set_image(self, image: str | None):
        pixmap = QPixmap()
        if image:
            try:
                pixmap.loadFromData(base64.b64decode(image.split(",", 1)[1]))
            except (IndexError, ValueError):
                pixmap = QPixmap()
        if pixmap.isNull() and self.author_type in DEFAULT_AVATARS:
            pixmap = QPixmap(self.default_agent if self.author_type == "agent" else DEFAULT_AVATARS[self.author_type])
        if pixmap.isNull():
            self.setPixmap(QPixmap())
            self.setText({"user": "你", "agent": "天依", "system": "系统"}.get(self.author_type, "你"))
        else:
            self.setText("")
            rounded = QPixmap(self.size())
            rounded.fill(Qt.GlobalColor.transparent)
            painter = QPainter(rounded)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            clip = QPainterPath()
            clip.addEllipse(QRectF(rounded.rect()))
            painter.setClipPath(clip)
            scaled = pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            painter.drawPixmap(
                (self.width() - scaled.width()) // 2,
                (self.height() - scaled.height()) // 2,
                scaled,
            )
            painter.end()
            self.setPixmap(rounded)
