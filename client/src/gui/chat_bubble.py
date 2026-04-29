'''
Author: Dpon
Date: 2026-04-07
聊天UI中每一条信息的承载气泡，包括文本气泡和图片气泡。
每个气泡旁边可能有一个状态图标（如提交中、失败、等待等），对于agent消息还可能有一个播放/停止图标用于控制文本转语音的播放。
'''
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
from ..utils.logger import get_logger

def has_wav_file(conv_uuid: str) -> bool:
    import os
    if not conv_uuid:
            return False
    wav_path = os.path.join(os.getcwd(), "temp", "tts_output", f"{conv_uuid}.wav")
    if not os.path.exists(wav_path):
        return False
    # WAV header is typically 44 bytes; smaller/equal indicates no usable audio payload.
    if os.path.getsize(wav_path) <= 44:
        return False
    return True

class BubblePlaybackManager:
    '''
    Agent消息气泡的播放管理器，负责协调同一时间只能有一个agent消息在播放文本转语音。
     - play_audio_callback: 当用户点击agent消息的播放图标时调用，参数为消息对应的conv_uuid，返回值表示是否成功开始播放。
     - stop_audio_callback: 当用户点击正在播放的agent消息的停止图标时调用，无参数，返回值表示是否成功停止播放。
    '''
    def __init__(
        self,
        play_audio_callback: Callable[[str], bool],
        stop_audio_callback: Callable[[], bool],
    ):
        self.play_audio_callback = play_audio_callback
        self.stop_audio_callback = stop_audio_callback
        self._active_bubble_ref: weakref.ReferenceType[ChatBubble] | None = None
        self.logger = get_logger("BubblePlaybackManager")

    def register_bubble(self, bubble: "ChatBubble"):
        # 注册一个agent消息气泡，监听其销毁信号以便清理播放状态
        bubble.destroyed.connect(lambda *_: self._on_bubble_destroyed(bubble))

    def _on_bubble_destroyed(self, bubble: "ChatBubble"):
        active = self.get_active_bubble()
        if active is bubble:
            self._active_bubble_ref = None

    def get_active_bubble(self) -> "ChatBubble | None":
        '''
        获得当前正在播放文本转语音的agent消息气泡实例，如果没有则返回None
        '''
        if not self._active_bubble_ref:
            return None
        return self._active_bubble_ref()

    def _set_active_bubble(self, bubble: "ChatBubble | None"):
        self._active_bubble_ref = weakref.ref(bubble) if bubble else None

    def on_bubble_clicked(self, bubble: "ChatBubble"):
        '''
        用户点击agent消息气泡的播放/停止图标时调用，负责协调播放状态切换
        '''
        active = self.get_active_bubble()
        if active is bubble:
            # 点击了正在播放的气泡，应该停止播放
            if self.stop_audio_callback:
                self.stop_audio_callback()
            bubble.set_play_icon()
            self._set_active_bubble(None)
            return

        if not self.play_audio_callback:
            self.logger.warning("No play_audio_callback defined in BubblePlaybackManager")
            return

        # 尝试启动新气泡的播放，如果成功则更新状态，否则保持原状态。这个同时会停止之前的播放（如果有）。
        started = self.play_audio_callback(bubble.conv_uuid)
        if not started:
            return

        # 成功开始播放后，如果之前有其他气泡在播放，应该切换它们的图标到播放状态
        if active and active is not bubble:
            active.set_play_icon()
        bubble.set_stop_icon()
        self._set_active_bubble(bubble)

    def on_local_tts_state_changed(self, event: str, conv_uuid: str):
        # 如果音频播放被打断或者正常结束，应该切换对应气泡的图标回播放状态
        # event can be: finished / stopped
        if event not in {"finished", "stopped"}:
            self.logger.warning(f"Unexpected event received: {event}")
            return
        active = self.get_active_bubble()
        if not active:
            return
        if conv_uuid and active.conv_uuid != conv_uuid:
            self.logger.warning(f"Event conv_uuid {conv_uuid} does not match active bubble conv_uuid {active.conv_uuid}")
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
        # keep reference for dynamic label insertion
        self._layout = layout

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
            # 如果有本地音频：
            if has_wav_file(self.conv_uuid):
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
            else:
                layout.addWidget(self.content_widget)
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
        # 设置Agent消息的播放图标，表示当前可以点击播放文本转语音
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
        # 设置user消息的状态图标，在发送失败（和正在重试）时提示。
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

    def add_audio_label(self):
        """
        动态为agent消息添加播放图标（在接收到本地TTS文件后调用）。
        如果_label已存在则什么也不做。
        """
        if self._label:
            # already has a label
            return
        if self.is_user:
            return
        # create clickable label
        self._label = ClickableLabel()
        self._label.setFixedSize(24, 24)
        self._label.setStyleSheet("background-color: transparent;")
        self._label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if agent_play_icon is not None:
            self._label.setPixmap(agent_play_icon)
        self._label.setCursor(Qt.CursorShape.PointingHandCursor)
        self._label.clicked.connect(self._on_agent_label_clicked)

        # insert into layout after content_widget if possible
        try:
            idx = self._layout.indexOf(self.content_widget)
            if idx >= 0:
                self._layout.insertWidget(idx + 1, self._label)
                self._layout.addStretch()
            else:
                # fallback: append at end
                self._layout.addWidget(self._label)
                self._layout.addStretch()
        except Exception:
            # silent fallback
            pass


class ChatImageBubble(ChatBubble):
    '''
    图片类型的消息气泡，content_widget是一个QLabel用于显示图片，目前限制最大宽高为250px以适应聊天界面。
    '''
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
    '''
    文本类型的消息气泡，text_edit用于显示文本内容，容器为自定义类型，方便控制行为。
    '''
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