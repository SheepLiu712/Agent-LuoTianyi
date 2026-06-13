'''
Author: Dpon
Data: 2026-04-07
Description: 主界面UI实现，包含Live2D显示和聊天窗口两部分，以及它们的交互逻辑。通过Binder与后端处理逻辑连接。
'''
import os
import time
from collections import deque
from PySide6.QtCore import Qt, QTimerEvent, QRect, QEvent, QTimer, QPoint, QPointF, Signal
from PySide6.QtGui import QMouseEvent, QPainter, QPen, QColor, QImage, QResizeEvent, QIcon, QPixmap
from PySide6.QtWidgets import (QApplication, QWidget, QHBoxLayout, QVBoxLayout,
                               QTextEdit, QScrollArea, QLabel,
                                QFrame, QPushButton, QFileDialog, QSlider,
                                QMessageBox)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import *
from typing import Dict, Any, List

from ..live2d import Live2dModel
from .binder import AgentBinder
from ..types import ConversationItem
from .chat_bubble import ChatBubble, ChatTextBubble, ChatImageBubble, BubblePlaybackManager
from .preferences_dialog import PreferencesDialog



class Live2DWidget(QOpenGLWidget):
    '''
    live2d的显示组件，负责加载模型、渲染模型、处理与模型的交互（如点击和拖动）。
    '''
    def __init__(self, live2d_config: Dict[str, Any], agent_binder: AgentBinder, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop)
        self.model: Live2dModel = Live2dModel(live2d_config)
        self.agent_binder = agent_binder
        agent_binder.on_set_model(self.model)
        self.agent_binder.expression_signal.connect(self.on_expression_changed)
        self.setMouseTracking(True)
        # 点击间隔控制（防止服务端过载）
        self._click_interval = 0.3  # 300ms
        self._last_click_time = 0.0
        # 点击频率统计（供LLM分析）
        self._click_timestamps: deque = deque(maxlen=50)

        # 目光跟随插值状态
        self._gaze_current_x = 0.0
        self._gaze_current_y = 0.0
        self._gaze_target_x = 0.0
        self._gaze_target_y = 0.0
        self._mouse_inside = False

        # 触摸事件控制（最大每秒一次）
        self._touch_send_interval = 1.0
        self._last_touch_sent_time = 0.0
        self._touch_count_since_last_sent = 0
        self._pending_touch_areas: list[str] = []

        # 触摸反馈圆环动画状态（由 paintGL 绘制）
        self._ripples: list[dict] = []

        # 触摸区域名称映射（HitArea -> 发送给服务端的标准区域）
        self._part_to_touch = {
            "Part24": "头",
            "Part8": "头",
            "Part11": "头",
            "Part21": "手",
            "ArtMesh129_Skinning": "手",
            "ArtMesh48_Skinning": "手",
            "Part18": "身体",
            "Part17": "身体"
        }

    def initializeGL(self) -> None:
        # Load model config
        self.model.model_init()

        # Set clear color to transparent
        try:
            glClearColor(0, 0, 0, 0)
        except Exception as e:
            print(f"initializeGL glClearColor error: {e}")

        self._gaze_target_x = self.width() / 2
        self._gaze_target_y = self.height() / 2

        # Start update timer (approx 60 FPS)
        self.startTimer(int(1000 / 60))

    def on_expression_changed(self, expression: str) -> None:
        if self.model:
            self.model.set_expression_by_cmd(expression)

    def resizeGL(self, w: int, h: int) -> None:
        glViewport(0, 0, w, h)
        if self.model:
            self.model.Resize(w, h)

    def paintGL(self) -> None:
        # Clear with transparency
        try:
            glClearColor(0, 0, 0, 0)
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        except Exception as e:
            print(f"paintGL error: {e}")
            pass
        
        if self.model:
            self.model.Update()
            self.model.Draw()

        # 在GL渲染之上绘制触摸反馈圆环
        if self._ripples:
            painter = QPainter(self)
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            for r in self._ripples:
                pen = QPen(QColor(173, 216, 230, int(r["opacity"] * 255)))
                pen.setWidth(3)
                painter.setPen(pen)
                painter.setBrush(Qt.BrushStyle.NoBrush)
                painter.drawEllipse(QPointF(r["x"], r["y"]), r["radius"], r["radius"])
            painter.end()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        '''
        处理鼠标点击事件，检测所有配置的触摸区域并分组为 head/body/legs/hands。
        生成浅蓝色圆环视觉反馈，并以新格式通过 WebSocket 发送触摸事件。
        '''
        if not self.model:
            return

        now = time.time()
        x, y = event.position().x(), event.position().y()
        hitparts : List[str] = self.model.model.HitPart(x,y, True)

        # 检测所有 HitArea，并映射为标准触摸区域
        hit_area_names: set[str] = set()
        for hitpart in hitparts:
            area_name = self._part_to_touch.get(hitpart)
            if area_name:
                hit_area_names.add(area_name)            

        if not hit_area_names:
            return  # 没有点击到模型的可触摸区域

        # 生成视觉反馈圆环
        self._ripples.append({
            "x": x, "y": y,
            "radius": 0,
            "opacity": 1.0,
            "max_radius": 60,
        })
        # 触摸次数统计（用于发送）
        self._touch_count_since_last_sent += 1
        self._pending_touch_areas.extend(hit_area_names)


        # 发送频率控制：最大每秒一次
        time_since_last = now - self._last_touch_sent_time
        if time_since_last >= self._touch_send_interval:
            touch_areas = list(set(self._pending_touch_areas))
            self._pending_touch_areas.clear()
            touch_count = self._touch_count_since_last_sent
            self._touch_count_since_last_sent = 0
            self._last_touch_sent_time = now
            self.agent_binder.on_send_touch(
                touch_area=touch_areas,
                touch_meta={
                    "timeSinceLastSentTouch": time_since_last,
                    "touchCount": touch_count,
                }
            )

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        '''
        处理鼠标移动事件：模型目光跟随鼠标指针，鼠标移出区域后平滑回到默认位置。
        '''
        if not self.model:
            return
        x = event.position().x()
        y = event.position().y()
        if 0 <= x <= self.width() and 0 <= y <= self.height():
            self._gaze_target_x = x
            self._gaze_target_y = y
            self._mouse_inside = True
        else:
            self._gaze_target_x = self.width() / 2
            self._gaze_target_y = self.height() / 2
            self._mouse_inside = False

    def enterEvent(self, event):
        self._mouse_inside = True
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._mouse_inside = False
        self._gaze_target_x = self.width() / 2
        self._gaze_target_y = self.height() / 2
        super().leaveEvent(event)

    def timerEvent(self, event: QTimerEvent) -> None:
        # 目光跟随插值
        if self.model:
            dx = self._gaze_target_x - self._gaze_current_x
            dy = self._gaze_target_y - self._gaze_current_y
            dist_sq = dx * dx + dy * dy
            if dist_sq > 1.0:
                self._gaze_current_x += dx * 0.15
                self._gaze_current_y += dy * 0.15
                drag_x = self._gaze_current_x - self.x()
                drag_y = self._gaze_current_y - self.y()
                self.model.Drag(drag_x, drag_y)
            elif not self._mouse_inside:
                self._gaze_current_x = self._gaze_target_x
                self._gaze_current_y = self._gaze_target_y
                drag_x = self._gaze_current_x - self.x()
                drag_y = self._gaze_current_y - self.y()
                self.model.Drag(drag_x, drag_y)

        # 触摸反馈圆环动画
        self._ripples = [r for r in self._ripples if r["opacity"] > 0.01]
        dt = 0.016
        for r in self._ripples:
            r["radius"] += (r["max_radius"] / 0.5) * dt
            progress = r["radius"] / r["max_radius"]
            r["opacity"] = 1.0 - progress

        self.update()

class Live2DContainer(QWidget):
    '''
    Live2D部分的容器组件，负责显示Live2DWidget和思考气泡，并根据Agent的状态控制思考气泡的显示和动画。
    '''

    def __init__(self, gui_config, live2d_config, agent_binder: AgentBinder, parent=None):
        super().__init__(parent)
        self.live2d_widget = Live2DWidget(live2d_config, agent_binder = agent_binder, parent=self)
        self.gui_config = gui_config
        self.agent_binder = agent_binder
        self.agent_binder.agent_thinking_signal.connect(self.on_agent_thinking)
        self.live2d_config: Dict[str, Any] = live2d_config
        self.background_image = None
        self.thinking_visible = False
        self.thinking_bubble_frames = [
            QPixmap("res/gui/thinking_bubble1.png"),
            QPixmap("res/gui/thinking_bubble2.png"),
            QPixmap("res/gui/thinking_bubble3.png"),
        ]
        self._thinking_frame_index = 0
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(500) # 每500ms切换一帧动画
        self._thinking_timer.timeout.connect(self._advance_thinking_frame)

        self.thinking_bubble_label = QLabel(self)
        self.thinking_bubble_label.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.thinking_bubble_label.setStyleSheet("background: transparent;")
        self.load_background()
        self.update_thinking_bubble()

    def update_thinking_bubble(self):
        if not self.thinking_bubble_frames:
            self.thinking_bubble_label.hide()
            return

        frame = self.thinking_bubble_frames[self._thinking_frame_index]
        if frame.isNull():
            self.thinking_bubble_label.hide()
            return

        bubble_width = max(1, int(self.width() / 4))
        scaled = frame.scaledToWidth(
            bubble_width,
            Qt.TransformationMode.SmoothTransformation
        )
        self.thinking_bubble_label.setPixmap(scaled)
        self.thinking_bubble_label.resize(scaled.size())

        x = int((self.width() - self.thinking_bubble_label.width()) * 0.94) # 一些超参数，反正这样就是可以
        y = int(self.height() * 0.15)
        self.thinking_bubble_label.move(x, y)
        self.thinking_bubble_label.raise_()
        self.thinking_bubble_label.setVisible(self.thinking_visible)

    def on_agent_thinking(self, is_thinking: bool):
        self.set_thinking_visible(is_thinking)

    def set_thinking_visible(self, visible: bool):
        self.thinking_visible = visible
        if not self.thinking_bubble_frames or all(frame.isNull() for frame in self.thinking_bubble_frames):
            self._thinking_timer.stop()
            self.thinking_bubble_label.hide()
            return

        if visible:
            self._thinking_frame_index = 0
            self.update_thinking_bubble()
            if not self._thinking_timer.isActive():
                self._thinking_timer.start()
        else:
            self._thinking_timer.stop()
            self.thinking_bubble_label.hide()

    def _advance_thinking_frame(self):
        if not self.thinking_visible:
            self._thinking_timer.stop()
            self.thinking_bubble_label.hide()
            return
        self._thinking_frame_index = (self._thinking_frame_index + 1) % len(self.thinking_bubble_frames)
        self.update_thinking_bubble()
        
    def load_background(self): # 加载背景图片
        bg_path = self.gui_config["live2d_background"]["image_path"]
        if os.path.exists(bg_path):
            self.background_image = QImage(bg_path)
        else:
            print(f"Warning: Background not found at {bg_path}")

    def resizeEvent(self, event: QResizeEvent):
        self.live2d_widget.resize(self.size())
        self.update_thinking_bubble()
        super().resizeEvent(event)

    def paintEvent(self, event):
        painter = QPainter(self)
        if self.background_image:
            # Draw background, cropping to fill (AspectFill)
            # Target rect is self.rect()
            # Source rect needs to be calculated
            
            target_rect = self.rect()
            img_w = self.background_image.width()
            img_h = self.background_image.height()
            
            widget_ratio = target_rect.width() / target_rect.height()
            img_ratio = img_w / img_h
            
            source_rect = QRect(0, 0, img_w, img_h)
            
            if widget_ratio > img_ratio:
                # Widget is wider than image. Crop top/bottom.
                new_h = int(img_w / widget_ratio)
                center_y = img_h // 2
                source_rect.setTop(center_y - new_h // 2)
                source_rect.setHeight(new_h)
            else:
                # Widget is taller than image. Crop left/right.
                new_w = int(img_h * widget_ratio)
                center_x = img_w // 2
                source_rect.setLeft(center_x - new_w // 2)
                source_rect.setWidth(new_w)
                
            painter.drawImage(target_rect, self.background_image, source_rect)
        else:
            painter.fillRect(self.rect(), Qt.GlobalColor.black)

class CustomToolTip(QLabel):
    '''
    自定义的工具提示Label，提供更美观的样式和半透明背景，用于HoverButton的提示显示。
    '''
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self.setWindowFlags(Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setWindowOpacity(0.8)
        self.setStyleSheet("""
            QLabel {
                background-color: #BBBBBB;
                color: #222222;
                border: 1px solid #76797C;
                border-radius: 4px;
                padding: 4px;
                font-size: 14px;
            }
        """)
        
    def showEvent(self, event):
        super().showEvent(event)
        self.adjustSize()

class HoverButton(QPushButton):
    '''
    工具栏的按钮，支持显示自定义工具提示。
    '''
    def __init__(self, tooltip_text="", parent=None):
        super().__init__(parent)
        self.tooltip_text = tooltip_text
        self.tooltip_widget = None

    def enterEvent(self, event):
        # 绘制工具提示
        if self.tooltip_text and self.isEnabled():
            if not self.tooltip_widget:
                self.tooltip_widget = CustomToolTip(self.tooltip_text, None) 
            
            # Position the tooltip
            self.tooltip_widget.adjustSize()
            global_pos = self.mapToGlobal(QPoint(0, 0))
            x = global_pos.x()
            y = global_pos.y() - self.tooltip_widget.height() - 5
            
            self.tooltip_widget.move(x, y)
            self.tooltip_widget.show()
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hide_tooltip()
        super().leaveEvent(event)

    def hide_tooltip(self):
        if self.tooltip_widget:
            self.tooltip_widget.hide()
            self.tooltip_widget.deleteLater()
            self.tooltip_widget = None

class ChatWidget(QWidget):
    '''
    位于界面右侧的聊天窗口组件，包含消息显示区、输入区和工具栏。负责处理用户输入、显示聊天消息，并通过Binder与Agent进行交互。
    我不太会写UI，这部分主要是AI写的。关键的回调逻辑是我看过的，也比较trivial，不详细解释了。
    '''

    def __init__(self, config: Dict, agent_binder: AgentBinder, network_client=None, parent=None):
        super().__init__(parent)
        self.config = config if config is not None else {}
        self.agent = agent_binder
        self.network_client = network_client
        self.preferences_manager = None  # Will be set from main.py
        self.agent.response_signal.connect(self.on_agent_response)
        self.agent.delete_signal.connect(self.on_agent_delete)
        self.playback_manager = BubblePlaybackManager(
            play_audio_callback=self.agent.on_play_local_tts,
            stop_audio_callback=self.agent.on_stop_local_tts,
        )
        self.agent.local_tts_state_signal.connect(self.playback_manager.on_local_tts_state_changed)
        
        # History loading
        self.agent.history_signal.connect(self.on_history_loaded)
        self.load_history_num = self.config.get("load_history_num", 20)
        self.current_history_index = -1
        self.is_loading_history = False
        self.first_load = True
        self.agent_bubbles: dict[str, ChatBubble] = {}
        
        self.init_ui()
        
        # Initial load
        QTimer.singleShot(100, lambda: self.agent.load_history(self.load_history_num, -1))

    def init_ui(self):
        # Right side background color
        self.setObjectName("ChatWidget")
        self.setStyleSheet("""
            QWidget#ChatWidget {
                background-color: #DDDDDD;
            }
            QToolTip {
                background-color: #66ccff;
                color: #000000;
                border: 1px solid #76797C;
                padding: 1px;
            }
        """)
        self.setMinimumWidth(500)
        
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        
        # History Area
        self.scroll_area = QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_area.setStyleSheet("""
            QScrollArea {
                background-color: transparent;
                border: none;
            }
            QScrollBar:vertical {
                border: none;
                background: transparent;
                width: 10px;
                margin: 0px 0px 0px 0px;
            }
            QScrollBar::handle:vertical {
                background: #A8A8A8;
                min-height: 20px;
                border-radius: 5px;
            }
            QScrollBar::add-line:vertical {
                height: 0px;
                subcontrol-position: bottom;
                subcontrol-origin: margin;
            }
            QScrollBar::sub-line:vertical {
                height: 0px;
                subcontrol-position: top;
                subcontrol-origin: margin;
            }
            QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {
                background: none;
            }
        """)
        
        self.history_container = QWidget()
        self.history_container.setStyleSheet("background-color: transparent;")
        self.history_layout = QVBoxLayout(self.history_container)
        self.history_layout.addStretch() # Push messages to bottom
        
        self.scroll_area.setWidget(self.history_container)
        self.scroll_area.verticalScrollBar().valueChanged.connect(self.on_scroll_value_changed)
        
        # Horizontal Line
        self.h_line = QFrame()
        self.h_line.setFrameShape(QFrame.Shape.HLine)
        self.h_line.setFrameShadow(QFrame.Shadow.Sunken)
        self.h_line.setStyleSheet("background-color: #B9B9B9; border: none;") # DarkGray
        self.h_line.setFixedHeight(2)

        # Toolbar
        self.toolbar = QWidget()
        self.toolbar.setStyleSheet("background-color: transparent; padding: 5px; border-radius: 0px; border: none;")
        self.toolbar.setFixedHeight(30)
        self.toolbar_layout = QHBoxLayout(self.toolbar)
        self.toolbar_layout.setContentsMargins(10, 0, 10, 0)
        
        # Picture Button
        self.picture_btn = HoverButton(tooltip_text="发送图片")
        self.picture_btn.setIcon(QIcon("res/gui/picture_icon.png"))
        self.picture_btn.setFixedSize(24, 24)
        self.picture_btn.setStyleSheet("QPushButton { border: none; background-color: transparent; } QPushButton:hover { background-color: #E0E0E0; border-radius: 4px; }")

        self.picture_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.picture_btn.clicked.connect(self.on_picture_clicked)

        self.volume_btn = HoverButton(tooltip_text="音量")
        self.volume_btn.setIcon(QIcon("res/gui/volume.png"))
        self.volume_btn.setFixedSize(24, 24)
        self.volume_btn.setStyleSheet("QPushButton { border: none; background-color: transparent; } QPushButton:hover { background-color: #E0E0E0; border-radius: 4px; }")
        self.volume_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.volume_btn.pressed.connect(self.on_volume_button_clicked)

        self.volume_popup = QFrame(
            None,
            Qt.WindowType.Popup
            | Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.NoDropShadowWindowHint,
        )
        self.volume_popup.setStyleSheet("background-color: #F6F6F6; border: 1px solid #B8B8B8; border-radius: 6px;")
        self.volume_popup.setFixedSize(32, 150)
        volume_layout = QVBoxLayout(self.volume_popup)
        volume_layout.setContentsMargins(4, 10, 4, 6)
        self.volume_slider = QSlider(Qt.Orientation.Vertical, self.volume_popup)
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(70)
        self.volume_slider.setTickPosition(QSlider.TickPosition.NoTicks)
        self.volume_slider.setStyleSheet("""
            QSlider::groove:vertical {
                background: #D8D8D8;
                width: 8px;
                border-radius: 4px;
            }
            QSlider::sub-page:vertical {
                background: #D8D8D8;
                border-radius: 4px;
            }
            QSlider::add-page:vertical {
                background: #66ccff;
                border-radius: 4px;
            }
            QSlider::handle:vertical {
                background: #FFFFFF;
                border: 1px solid #9A9A9A;
                height: 14px;
                margin: -2px -4px;
                border-radius: 7px;
            }
        """)
        self.volume_slider.valueChanged.connect(self.on_volume_changed)
        volume_layout.addWidget(self.volume_slider)
        
        self.toolbar_layout.addWidget(self.picture_btn)
        self.toolbar_layout.addWidget(self.volume_btn)
        
        # Settings Button
        self.settings_btn = HoverButton(tooltip_text="偏好设置")
        icon_path = os.path.join("res", "gui", "setting.png")
        self.settings_btn.setIcon(QIcon(icon_path))
        self.settings_btn.setFixedSize(24, 24)
        self.settings_btn.setStyleSheet("""
            QPushButton { 
                border: none; 
                background-color: transparent; 

            } 
            QPushButton:hover { 
                background-color: #E0E0E0; 
                border-radius: 4px; 
            }
        """)
        self.settings_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.settings_btn.clicked.connect(self.open_settings)
        self.toolbar_layout.addWidget(self.settings_btn)
        
        self.toolbar_layout.addStretch()

        # Horizontal Line 2
        self.h_line_2 = QFrame()
        self.h_line_2.setFrameShape(QFrame.Shape.HLine)
        self.h_line_2.setFrameShadow(QFrame.Shadow.Sunken)
        self.h_line_2.setStyleSheet("background-color: #CCCCCC; border: none;") 
        self.h_line_2.setFixedHeight(2)

        # Input Area
        self.input_box = QTextEdit()
        self.input_box.setStyleSheet("background-color: transparent; padding: 5px; border-radius: 0px; border: none; font-size: 16px;")
        self.input_box.setFixedHeight(120) # Fixed height
        self.input_box.installEventFilter(self)
        self.input_box.textChanged.connect(self.on_text_changed)

        # Send Button
        self.send_button = QPushButton("发送", self.input_box)
        self.send_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.send_button.resize(80, 30)
        self.send_button.clicked.connect(self.on_send_clicked)
        
        self.can_send = False
        self.agent_free = True
        self.update_send_button_state()
        self.on_volume_changed(self.volume_slider.value())
        
        layout.addWidget(self.scroll_area)
        layout.addWidget(self.h_line)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.h_line_2)
        layout.addWidget(self.input_box)
        
        self.setLayout(layout)
        self.temp_is_user = True

    def open_settings(self):
        print("Opening preferences dialog...")
        if self.network_client:
            dialog = PreferencesDialog(self.network_client, self)
            dialog.exec()
        else:
            QMessageBox.warning(self, "提示", "网络客户端未就绪，无法打开偏好设置")
    
    def on_scroll_value_changed(self, value):
        if value == 0 and not self.is_loading_history and self.current_history_index > 0:
            self.is_loading_history = True
            self.agent.on_load_history(self.load_history_num, self.current_history_index)

    def on_history_loaded(self, history_list: List[ConversationItem], start_index):
        self.is_loading_history = False
        if not history_list:
            return
        
        if start_index >=0:
            self.current_history_index = start_index
        
        # Save scroll position
        scrollbar = self.scroll_area.verticalScrollBar()
        old_max = scrollbar.maximum()
        old_value = scrollbar.value()
        
        # Prepend messages
        for item in reversed(history_list):
            item_type = item.type
            is_user = (item.source == "user")
            if item_type == "image":
                image_path = item.content
                bubble = ChatImageBubble(
                    image_path,
                    conv_uuid=item.uuid,
                    is_user=is_user,
                    playback_manager=self.playback_manager,
                )
            else:
                bubble = ChatTextBubble(
                    item.content,
                    conv_uuid=item.uuid,
                    is_user=is_user,
                    playback_manager=self.playback_manager,
                )
            self.history_layout.insertWidget(0, bubble)
            
        # Restore scroll position
        QApplication.processEvents()
        new_max = scrollbar.maximum()
        
        if self.first_load:
            # Use QTimer to ensure layout is updated and scrollbar max is correct
            QTimer.singleShot(5, lambda: scrollbar.setValue(scrollbar.maximum()))
            self.first_load = False
        elif old_max != new_max:
             QTimer.singleShot(5, lambda: scrollbar.setValue(old_value + scrollbar.maximum() - old_max))
        else:
            QTimer.singleShot(5, lambda: scrollbar.setValue(scrollbar.maximum() - old_max))

    def on_text_changed(self):
        text = self.input_box.toPlainText()
        text_length = len(text)
        self.agent.on_send_typing(text_length)
        self.can_send = bool(text.strip())
        self.update_send_button_state()

    def update_send_button_state(self):
        self.send_button.setEnabled(self.can_send)
        if self.can_send:
            self.send_button.setStyleSheet("""
                QPushButton {
                    background-color: #66CCFF;
                    color: white;
                    border: none;
                    border-radius: 5px;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #55BBEE;
                }
            """)
        else:
            self.send_button.setStyleSheet("""
                QPushButton {
                    background-color: #D8D8D8;
                    color: #B8B8B8;
                    border: none;
                    border-radius: 5px;
                    font-size: 14px;
                }
            """)
    
    def update_send_pic_button_state(self):
        if self.can_send_pic:
            self.picture_btn.setEnabled(True)
            self.picture_btn.setIcon(QIcon("res/gui/picture_icon.png"))
        else:
            self.picture_btn.setEnabled(False)
            self.picture_btn.setIcon(QIcon("res/gui/picture_icon_un.png"))

    def on_send_clicked(self): # 按发送按钮
        self.handle_text_input()

    def on_picture_clicked(self): # 按工具栏的图片按钮
        # 先发送图片选择中事件，让服务端进入等待状态
        self.agent.on_image_selecting_start()
        file_path, _ = QFileDialog.getOpenFileName(
            self, 
            "Select Image", 
            "", 
            "Images (*.png *.xpm *.jpg *.jpeg *.bmp *.svg)"
        )
        if file_path:
            self.can_send_pic = False
            bubble = self.add_message("image", file_path, is_user=True)
            self.agent.on_send_image(file_path, bubble)
        else:
            # 用户取消了选择：通知服务端重置等待时间
            self.agent.on_image_selecting_cancel()

    def on_volume_button_clicked(self): # 按工具栏的音量按钮
        if self.volume_popup.isVisible():
            self.volume_popup.hide()
            return

        # Avoid tooltip staying over the popup.
        self.volume_btn.hide_tooltip()

        popup_pos = self.volume_btn.mapToGlobal(QPoint(0, 0))
        x = popup_pos.x() + (self.volume_btn.width() - self.volume_popup.width()) // 2
        y = popup_pos.y() - self.volume_popup.height() - 6
        self.volume_popup.move(x, y)
        self.volume_popup.show()

    def on_volume_changed(self, value: int):
        # Backend treats 70% as baseline for server-streamed audio level.
        self.agent.on_set_volume(value)

    def add_message(self, type: str, content: str, conv_uuid: str = "", is_user: bool = False) -> ChatBubble | ChatImageBubble:
        if type == "image":
            bubble = ChatImageBubble(
                content,
                conv_uuid=conv_uuid,
                is_user=is_user,
                playback_manager=self.playback_manager,
            )
        elif type == "text":
            bubble = ChatTextBubble(
                content,
                conv_uuid=conv_uuid,
                is_user=is_user,
                playback_manager=self.playback_manager,
            )

        self.history_layout.insertWidget(self.history_layout.count() - 1, bubble)
        QApplication.processEvents() # Ensure layout updates
        QTimer.singleShot(10, lambda: self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum()))
        return bubble

    def eventFilter(self, obj, event):
        if obj == self.input_box:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                    if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                        self.handle_text_input()
                        return True
            elif event.type() == QEvent.Type.Resize:
                s = self.send_button.size()
                self.send_button.move(self.input_box.width() - s.width() - 10, 
                                      self.input_box.height() - s.height() - 10)
        return super().eventFilter(obj, event)

    def set_preferences_manager(self, preferences_manager):
        """设置用户偏好管理器"""
        self.preferences_manager = preferences_manager
        print("Preferences manager set in ChatWidget") 

    def handle_text_input(self):
        if self.can_send == False:
            return
        text = self.input_box.toPlainText().strip()
        if not text:
            return

        bubble = self.add_message("text", text, conv_uuid="", is_user=True)
        self.input_box.clear()
        
        self.agent.on_send_text(text, bubble)

    def on_agent_response(self, uuid: str, text: str):
        bubble = self.add_message("text", text, conv_uuid=uuid, is_user=False)
        # register mapping so Binder can update this bubble later (e.g., when audio saved)
        try:
            self.agent.msg_to_bubble[uuid] = bubble
        except Exception:
            pass
    
    def on_agent_delete(self):
        count = self.history_layout.count()
        if count > 1:
            item = self.history_layout.itemAt(count - 2)
            widget = item.widget()
            if isinstance(widget, ChatBubble):
                widget.setParent(None)
                widget.deleteLater()
                QApplication.processEvents()
                self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())



class MainWindow(QWidget):
    def __init__(self, gui_config, live2d_config, ui_binder: AgentBinder, network_client=None):
        super().__init__()
        self.setWindowTitle("Chat with Luo Tianyi")
        self.resize(1100, 800)
        
        self.layout = QHBoxLayout()
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.layout.setSpacing(0)
        
        # Left Side (Live2D)
        self.live2d_container = Live2DContainer(gui_config["live2d_container"], live2d_config, ui_binder)
        # We don't set fixed size here initially, we let resizeEvent handle it
        
        # Vertical Line
        self.v_line = QFrame()
        self.v_line.setFrameShape(QFrame.Shape.VLine)
        self.v_line.setFrameShadow(QFrame.Shadow.Sunken)
        self.v_line.setStyleSheet("background-color: #B9B9B9; border: none;") # DarkGray
        self.v_line.setFixedWidth(2)

        # Right Side (Chat)
        self.chat_widget = ChatWidget(config=gui_config["chat_window"], agent_binder=ui_binder, network_client=network_client)
        self.layout.addWidget(self.live2d_container)
        self.layout.addWidget(self.v_line)
        self.layout.addWidget(self.chat_widget)
        
        self.setLayout(self.layout)

    def resizeEvent(self, event: QResizeEvent):
        # 我们保证左侧界面的宽高比为4:3，右侧聊天界面占满剩余空间
        h = self.height()
        w_live2d = int(h * 3 / 4)
        
        # Set fixed width for Live2D container
        self.live2d_container.setFixedWidth(w_live2d)
        
        # Chat widget will automatically take the remaining space
        
        super().resizeEvent(event)
