from typing import Callable
import weakref

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPixmap, QFontMetrics, QTextOption
from PySide6.QtWidgets import ( QWidget, QHBoxLayout,
                               QTextEdit, QLabel, 
                               QSizePolicy, QFrame, QMenu)


agent_play_icon_path = "res/gui/play_agent_msg.png"
agent_stop_icon_path = "res/gui/stop_agent_msg.png"
agent_play_icon = None
agent_stop_icon = None


class BubblePlaybackManager:
    def __init__(
        self,
        play_audio_callback: Callable[[str], bool],
        stop_audio_callback: Callable[[], bool],
    ):
        self.play_audio_callback = play_audio_callback
        self.stop_audio_callback = stop_audio_callback
        self._active_bubble_ref: weakref.ReferenceType[ChatBubble] | None = None

    def register_bubble(self, bubble: "ChatBubble"):
        # Keep cleanup automatic when bubble is deleted.
        bubble.destroyed.connect(lambda *_: self._on_bubble_destroyed(bubble))

    def _on_bubble_destroyed(self, bubble: "ChatBubble"):
        active = self.get_active_bubble()
        if active is bubble:
            self._active_bubble_ref = None

    def get_active_bubble(self) -> "ChatBubble | None":
        if not self._active_bubble_ref:
            return None
        return self._active_bubble_ref()

    def _set_active_bubble(self, bubble: "ChatBubble | None"):
        self._active_bubble_ref = weakref.ref(bubble) if bubble else None

    def on_bubble_clicked(self, bubble: "ChatBubble"):
        active = self.get_active_bubble()
        if active is bubble:
            if self.stop_audio_callback:
                self.stop_audio_callback()
            bubble.set_play_icon()
            self._set_active_bubble(None)
            return

        if not self.play_audio_callback:
            return

        started = self.play_audio_callback(bubble.conv_uuid)
        if not started:
            return

        if active and active is not bubble:
            active.set_play_icon()
        bubble.set_stop_icon()
        self._set_active_bubble(bubble)

    def on_local_tts_state_changed(self, event: str, conv_uuid: str):
        # event can be: finished / stopped
        if event not in {"finished", "stopped"}:
            return
        active = self.get_active_bubble()
        if not active:
            return
        if conv_uuid and active.conv_uuid != conv_uuid:
            return
        active.set_play_icon()
        self._set_active_bubble(None)


class ClickableLabel(QLabel):
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class ChatBubble(QWidget):
    def __init__(
        self,
        conv_uuid: str = "",
        is_user: bool = False,
        parent=None,
        playback_manager: BubblePlaybackManager | None = None,
    ):
        super().__init__(parent)
        self.is_user = is_user
        self._label: QLabel | None = None
        self.content_widget: QWidget | None = None
        self.conv_uuid = conv_uuid
        self.playback_manager = playback_manager
        self.init_ui()
        if self.playback_manager and not self.is_user:
            self.playback_manager.register_bubble(self)

    def build_content_widget(self) -> QWidget:
        raise NotImplementedError()

    def init_ui(self):
        global agent_play_icon, agent_stop_icon
        if agent_play_icon is None:
            agent_play_icon = QPixmap(agent_play_icon_path).scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        if agent_stop_icon is None:
            stop_pm = QPixmap(agent_stop_icon_path)
            if not stop_pm.isNull():
                agent_stop_icon = stop_pm.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)

        self.content_widget = self.build_content_widget()

        if self.is_user:
            self._label = ClickableLabel()
            self._label.setFixedSize(24, 24)
            self._label.setStyleSheet("background-color: transparent;")
            self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)

            layout.addStretch()
            layout.addWidget(self._label)
            layout.addSpacing(0)
            layout.addWidget(self.content_widget)
        else: # agent
            self._label = ClickableLabel()
            self._label.setFixedSize(24, 24)
            self._label.setStyleSheet("background-color: transparent;")
            self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._label.setPixmap(agent_play_icon)
            self._label.setCursor(Qt.CursorShape.PointingHandCursor)
            self._label.clicked.connect(self._on_agent_label_clicked)
            layout.addWidget(self.content_widget)
            layout.addSpacing(0)
            layout.addWidget(self._label)
            layout.addStretch()

        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

    def _on_agent_label_clicked(self):
        if self.is_user:
            return
        if not self.conv_uuid:
            return
        if not self.playback_manager:
            return

        self.playback_manager.on_bubble_clicked(self)

    def set_play_icon(self):
        if self._label and agent_play_icon is not None:
            self._label.setPixmap(agent_play_icon)

    def set_stop_icon(self):
        if not self._label:
            return
        if agent_stop_icon is not None:
            self._label.setPixmap(agent_stop_icon)
        elif agent_play_icon is not None:
            self._label.setPixmap(agent_play_icon)

    def set_status(self, status: str):
        if not self._label:
            return

        icon_path = None
        if status == "submitted":
            # icon_path = "res/gui/submitted_msg.png"
            icon_path = None # 提交成功后不显示任何状态
        elif status == "failed":
            icon_path = "res/gui/failed_msg.png"
        elif status == "waiting":
            icon_path = "res/gui/waiting_msg.png"

        if not icon_path:
            self._label.clear()
            return

        pixmap = QPixmap(icon_path)
        if pixmap.isNull():
            self._label.clear()
            return

        self._label.setPixmap(
            pixmap.scaled(24, 24, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
        )


class ChatImageBubble(ChatBubble):
    def __init__(self, image_path, conv_uuid="", is_user=False, parent=None, playback_manager: BubblePlaybackManager | None = None):
        self.image_label: QLabel | None = None
        self.image_path = image_path
        self.conv_uuid = conv_uuid
        super().__init__(
            conv_uuid=conv_uuid,
            is_user=is_user,
            parent=parent,
            playback_manager=playback_manager,
        )

    def build_content_widget(self) -> QWidget:
        self.image_label = QLabel()
        self.image_label.setStyleSheet("background-color: transparent;")

        # Load and scale image
        pixmap = QPixmap(self.image_path)
        if not pixmap.isNull():
            max_width = 250
            max_height = 250

            w = pixmap.width()
            h = pixmap.height()

            if w > max_width or h > max_height:
                pixmap = pixmap.scaled(max_width, max_height, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)

            self.image_label.setPixmap(pixmap)
        else:
            self.image_label.setText("Image not found")

        return self.image_label

class CustomTextEdit(QTextEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFrameShape(QFrame.Shape.NoFrame)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.document().setDocumentMargin(0)

    def contextMenuEvent(self, event):
        # 创建自定义菜单
        menu = QMenu(self)
        
        # 设置菜单样式（也可以在全局设置）
        menu.setStyleSheet("""
            QMenu { background-color: white; border: 1px solid #88EDFF; }
            QMenu::item { color: black; padding: 5px 20px; }
            QMenu::item:selected { background-color: #88EDFF; }
        """)

        # 添加自定义行为
        copy_action = menu.addAction("复制 (Copy)")
        select_all_action = menu.addAction("全选 (Select All)")
        
        # 执行菜单并获取用户点击的动作
        action = menu.exec(event.globalPos())
        
        if action == copy_action:
            self.copy()
        elif action == select_all_action:
            self.selectAll()

class ChatTextBubble(ChatBubble):
    def __init__(self, text, conv_uuid="", is_user=False, parent=None, playback_manager: BubblePlaybackManager | None = None):
        self.text = text
        self.conv_uuid = conv_uuid
        self.text_edit: CustomTextEdit | None = None
        super().__init__(
            conv_uuid=conv_uuid,
            is_user=is_user,
            parent=parent,
            playback_manager=playback_manager,
        )
        self.update_bubble_size()

    def build_content_widget(self) -> QWidget:
        self.text_edit = CustomTextEdit()
        self.text_edit.setText(self.text)
        
        # Style
        bg_color = "#FFFFFF" if self.is_user else "#88EDFF"
        text_color = "#000000"
        
        style = f"""
            QTextEdit {{
                background-color: {bg_color};
                color: {text_color};
                border-radius: 10px;
                padding: 10px;
                font-size: 16px;
            }}
        """
        self.text_edit.setStyleSheet(style)

        return self.text_edit

    def set_text(self, text):
        self.text = text
        self.text_edit.setText(text)
        self.update_bubble_size()

    def resizeEvent(self, event):
        self.update_bubble_size()
        super().resizeEvent(event)

    def update_bubble_size(self):
        max_w = int(self.width() * 0.6)
        if max_w <= 0: return

        font = self.text_edit.font()
        font.setPixelSize(16)
        fm = QFontMetrics(font)
        
        lines = self.text.split('\n')
        text_width = max([fm.horizontalAdvance(line) for line in lines]) if lines else 0
        
        target_width = text_width + 22 # Padding buffer
        
        final_width = min(target_width, max_w)
        final_width = max(final_width, 50) # Minimum width
        
        self.text_edit.setFixedWidth(final_width)
        
        # Adjust height
        doc = self.text_edit.document()
        doc.setTextWidth(final_width - 20) # Subtract padding
        
        doc_h = doc.size().height()
        final_height = int(doc_h + 20) 
        
        self.text_edit.setFixedHeight(final_height)
        self.setFixedHeight(final_height + 10)