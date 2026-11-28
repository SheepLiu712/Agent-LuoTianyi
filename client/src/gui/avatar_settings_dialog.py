"""单侧头像编辑：圆形预览、拖动缩放裁剪，确认后才写入账号缓存。"""

import base64
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from ..avatars import SIDES
from .avatar_label import DEFAULT_AVATARS, AvatarLabel


class AvatarCropPreview(QWidget):
    """圆形头像裁剪预览，支持拖动和滚轮缩放。"""

    crop_changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(280, 280)
        self.setCursor(Qt.CursorShape.OpenHandCursor)
        self._image = None
        self._pixmap = QPixmap()
        self._base_scale = 1.0
        self._zoom = 1.0
        self._offset = QPointF()
        self._drag_start = None
        self._offset_start = QPointF()

    def set_source(self, source: str):
        try:
            if source.startswith("data:"):
                data = base64.b64decode(source.split(",", 1)[1])
            else:
                data = Path(source).read_bytes()
            with Image.open(BytesIO(data)) as loaded:
                if not source.startswith("data:") and loaded.format not in (
                    "PNG",
                    "JPEG",
                ):
                    raise ValueError("头像仅支持 PNG 或 JPEG 图片")
                self._image = ImageOps.exif_transpose(loaded).convert("RGBA").copy()
        except (OSError, ValueError, IndexError, UnidentifiedImageError) as exc:
            if isinstance(exc, ValueError) and str(exc) == "头像仅支持 PNG 或 JPEG 图片":
                raise
            raise ValueError("无法读取头像图片") from exc
        self._reset_view()

    def set_default(self, side: str):
        self._image = None
        self._pixmap = QPixmap(DEFAULT_AVATARS[side])
        self._base_scale = max(
            self.width() / max(1, self._pixmap.width()),
            self.height() / max(1, self._pixmap.height()),
        )
        self._zoom = 1.0
        self._offset = QPointF()
        self.update()

    def _reset_view(self):
        self._pixmap = QPixmap.fromImage(self._pil_qimage())
        self._base_scale = max(
            self.width() / max(1, self._pixmap.width()),
            self.height() / max(1, self._pixmap.height()),
        )
        self._zoom = 1.0
        self._offset = QPointF()
        self.update()

    def _pil_qimage(self):
        output = BytesIO()
        self._image.save(output, format="PNG")
        from PySide6.QtGui import QImage

        image = QImage()
        image.loadFromData(output.getvalue())
        return image

    def _scale(self):
        return self._base_scale * self._zoom

    def _image_rect(self):
        scale = self._scale()
        width = self._pixmap.width() * scale
        height = self._pixmap.height() * scale
        return (
            self.width() / 2 + self._offset.x() - width / 2,
            self.height() / 2 + self._offset.y() - height / 2,
            width,
            height,
        )

    def _clamp_offset(self):
        _, _, width, height = self._image_rect()
        max_x = max(0.0, (width - self.width()) / 2)
        max_y = max(0.0, (height - self.height()) / 2)
        self._offset.setX(max(-max_x, min(max_x, self._offset.x())))
        self._offset.setY(max(-max_y, min(max_y, self._offset.y())))

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        painter.fillRect(self.rect(), Qt.GlobalColor.black)
        if not self._pixmap.isNull():
            left, top, width, height = self._image_rect()
            painter.drawPixmap(
                int(left),
                int(top),
                max(1, int(width)),
                max(1, int(height)),
                self._pixmap,
            )
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        circle = QPainterPath()
        circle.addEllipse(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        outside = QPainterPath()
        outside.addRect(QRectF(self.rect()))
        painter.fillPath(outside.subtracted(circle), QColor(0, 0, 0, 153))
        painter.setPen(Qt.GlobalColor.white)
        painter.drawPath(circle)
        painter.end()

    def mousePressEvent(self, event):
        if self._image is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = event.position()
            self._offset_start = QPointF(self._offset)
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._drag_start is not None:
            self._offset = self._offset_start + event.position() - self._drag_start
            self._clamp_offset()
            self.crop_changed.emit()
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._image is not None and event.button() == Qt.MouseButton.LeftButton:
            self._drag_start = None
            self.setCursor(Qt.CursorShape.OpenHandCursor)
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._image is None:
            return
        self.zoom(1.1 if event.angleDelta().y() > 0 else 1 / 1.1)
        event.accept()

    def zoom(self, factor):
        if self._image is None:
            return
        self._zoom = max(1.0, min(8.0, self._zoom * factor))
        self._clamp_offset()
        self.crop_changed.emit()
        self.update()

    def pixmap(self):
        return self._pixmap

    def cropped_data(self) -> str | None:
        if self._image is None:
            return None
        left, top, _width, _height = self._image_rect()
        scale = max(self._scale(), 1e-9)
        source_width, source_height = self._image.size
        crop_size = max(1.0, min(float(source_width), float(source_height), self.width() / scale))
        crop_x = max(0.0, min(source_width - crop_size, (0 - left) / scale))
        crop_y = max(0.0, min(source_height - crop_size, (0 - top) / scale))
        x = min(source_width - 1, max(0, int(crop_x)))
        y = min(source_height - 1, max(0, int(crop_y)))
        size = max(1, min(source_width - x, source_height - y, int(round(crop_size))))
        box = (x, y, x + size, y + size)
        output = BytesIO()
        self._image.crop(box).resize((256, 256), Image.Resampling.LANCZOS).save(output, format="PNG")
        return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


class AvatarSettingsDialog(QDialog):
    """查看当前头像 → 选择图片 → 裁剪预览 → 保存；与手机端保持相同草稿语义。"""

    def __init__(self, avatars, side: str, parent=None):
        if side not in SIDES:
            raise ValueError("头像类型无效")
        super().__init__(parent)
        self.avatars = avatars
        self.side = side
        self._context = avatars.network.account_context()
        self._has_source = False
        self._restore_default = False
        name = "我的头像" if side == "user" else "天依头像"
        self.setWindowTitle(name)
        self.setObjectName("avatarSettingsDialog")
        self.setMinimumSize(400, 420)
        self.resize(440, 580)
        self.setStyleSheet("""
            QDialog#avatarSettingsDialog { background-color: #FFFFFF; }
            QWidget#avatarHeader { background-color: #FFFFFF; border-bottom: 1px solid #D5DEE7; }
            QWidget#avatarBody { background-color: #FFFFFF; }
            QWidget#avatarActions { background-color: #F6F7F9; border-top: 1px solid #D5DEE7; }
            QLabel { background: transparent; border: none; color: #243447; font-size: 14px; }
            QLabel#avatarTitle { font-size: 18px; font-weight: 600; }
            QLabel#avatarHint { color: #667481; font-size: 13px; }
            QLabel#avatarError { color: #B91C1C; font-size: 13px; }
            QScrollArea { background: #FFFFFF; border: none; }
            QPushButton { background-color: #FFFFFF; color: #243447; border: 1px solid #D5DEE7;
                border-bottom-color: #BBC7D2; border-radius: 6px; padding: 7px 14px; font-size: 14px; }
            QPushButton:hover { background-color: #F0F7FC; border-color: #A8CFE4; }
            QPushButton:pressed { background-color: #E6F4FE; }
            QPushButton:disabled { background-color: #F2F4F6; color: #98A5AE; border-color: #E2E7EC; }
            QPushButton#avatarSave { background-color: #66CCFF; color: #243447; border-color: #66CCFF; }
            QPushButton#avatarSave:hover { background-color: #8AD8FF; }
            QPushButton#avatarSave:pressed { background-color: #4CBCEE; }
            QPushButton#avatarSave:disabled { background-color: #E2EDF3; color: #98A5AE; border-color: #E2EDF3; }
            QPushButton#avatarChoose { border-color: #88CDEB; color: #147FB5; }
            QPushButton#avatarBack, QPushButton#avatarRestore { background: transparent; border: none; color: #667481; }
            QPushButton#avatarBack:hover, QPushButton#avatarRestore:hover { background-color: #E6F4FE; color: #147FB5; }
        """)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        header = QWidget()
        header.setObjectName("avatarHeader")
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(16, 14, 16, 14)
        self.cancel_button = QPushButton("返回")
        self.cancel_button.setObjectName("avatarBack")
        self.cancel_button.clicked.connect(self.reject)
        header_layout.addWidget(self.cancel_button)
        title = QLabel(name)
        title.setObjectName("avatarTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header_layout.addWidget(title, 1)
        self.save_button = QPushButton("保存")
        self.save_button.setObjectName("avatarSave")
        self.save_button.clicked.connect(self.save_side)
        header_layout.addWidget(self.save_button)
        root.addWidget(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        body = QWidget()
        body.setObjectName("avatarBody")
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(24, 20, 24, 20)
        body_layout.setSpacing(12)
        self.views = QStackedWidget()
        self.views.setFixedSize(280, 280)
        current = QWidget()
        current_layout = QVBoxLayout(current)
        current_layout.setContentsMargins(0, 0, 0, 0)
        self.current_avatar = AvatarLabel(side, size=192, editable=True)
        self.current_avatar.setToolTip("选择图片")
        self.current_avatar.clicked.connect(lambda _side: self.choose_image())
        current_layout.addWidget(self.current_avatar, alignment=Qt.AlignmentFlag.AlignCenter)
        self.views.addWidget(current)
        self.preview = AvatarCropPreview()
        self.views.addWidget(self.preview)
        body_layout.addWidget(self.views, alignment=Qt.AlignmentFlag.AlignCenter)
        self.hint_label = QLabel("拖动照片、滚轮缩放调整位置，圆框内为头像预览，保存后生效。")
        self.hint_label.setObjectName("avatarHint")
        self.hint_label.setWordWrap(True)
        self.hint_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        body_layout.addWidget(self.hint_label)
        self.zoom_controls = QWidget()
        zoom_layout = QHBoxLayout(self.zoom_controls)
        zoom_layout.setContentsMargins(0, 0, 0, 0)
        zoom_layout.setSpacing(12)
        self.zoom_out = QPushButton("缩小")
        self.zoom_out.clicked.connect(lambda: self.preview.zoom(1 / 1.2))
        self.zoom_in = QPushButton("放大")
        self.zoom_in.clicked.connect(lambda: self.preview.zoom(1.2))
        zoom_layout.addStretch()
        zoom_layout.addWidget(self.zoom_out)
        zoom_layout.addWidget(self.zoom_in)
        zoom_layout.addStretch()
        body_layout.addWidget(self.zoom_controls)
        body_layout.addStretch()
        scroll.setWidget(body)
        root.addWidget(scroll, 1)

        actions = QWidget()
        actions.setObjectName("avatarActions")
        actions_layout = QVBoxLayout(actions)
        actions_layout.setContentsMargins(24, 16, 24, 16)
        actions_layout.setSpacing(8)
        self.choose_button = QPushButton("选择图片")
        self.choose_button.setObjectName("avatarChoose")
        self.choose_button.setMinimumHeight(40)
        self.choose_button.clicked.connect(self.choose_image)
        actions_layout.addWidget(self.choose_button)
        self.restore_button = QPushButton("恢复默认")
        self.restore_button.setObjectName("avatarRestore")
        self.restore_button.setMinimumHeight(36)
        self.restore_button.clicked.connect(self.restore_default)
        actions_layout.addWidget(self.restore_button)
        self.status_label = QLabel()
        self.status_label.setObjectName("avatarError")
        self.status_label.setWordWrap(True)
        actions_layout.addWidget(self.status_label)
        root.addWidget(actions)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        self.save_button.setDefault(True)
        avatars.status_changed.connect(self.show_status)
        avatars.changed.connect(self.refresh)
        self.show_status(avatars.status)
        self.refresh()
        avatars.refresh()

    def show_status(self, message):
        # 编辑草稿与已保存头像的常规同步状态无关；仅展示失败。
        error = message if "同步失败" in message else ""
        self.status_label.setText(error)
        self.status_label.setVisible(bool(error))

    def refresh(self):
        context = self.avatars.network.account_context()
        if context != self._context:
            self._context = context
            self._has_source = False
            self._restore_default = False
        if not self._has_source:
            self.current_avatar.set_image(None if self._restore_default else self.avatars.image(self.side))
        self.views.setCurrentIndex(1 if self._has_source else 0)
        self.hint_label.setVisible(self._has_source)
        self.zoom_controls.setVisible(self._has_source)
        self.choose_button.setText("重新选择图片" if self._has_source else "选择图片")
        signed_in = bool(self.avatars.username)
        self.choose_button.setEnabled(signed_in)
        self.current_avatar.setEnabled(signed_in)
        self.restore_button.setEnabled(signed_in)
        self.save_button.setEnabled(signed_in and (self._has_source or self._restore_default))

    def choose_image(self):
        context = self.avatars.network.account_context()
        path, _ = QFileDialog.getOpenFileName(self, "选择头像", "", "图片 (*.png *.jpg *.jpeg)")
        if not path or context != self.avatars.network.account_context():
            return
        try:
            self.preview.set_source(path)
        except ValueError as exc:
            QMessageBox.warning(self, "无法使用头像", str(exc))
            return
        self._has_source = True
        self._restore_default = False
        self.refresh()

    def save_side(self):
        if not (self._has_source or self._restore_default):
            return
        try:
            image = None if self._restore_default else self.preview.cropped_data()
            self.avatars.save(self.side, image, context=self._context)
        except (OSError, ValueError) as exc:
            QMessageBox.warning(self, "头像保存失败", str(exc))
            return
        self.accept()

    def restore_default(self):
        self._has_source = False
        self._restore_default = True
        self.refresh()
