
import sys
import os
import json
from PySide6.QtCore import Qt, QTimerEvent, QSize, QRect, QEvent, QTimer
from PySide6.QtGui import QMouseEvent, QPainter, QColor, QImage, QPixmap, QResizeEvent, QSurfaceFormat, QFont, QFontMetrics, QTextOption, QIcon
from PySide6.QtWidgets import (QApplication, QWidget, QHBoxLayout, QVBoxLayout, 
                               QTextEdit, QLineEdit, QScrollArea, QLabel, 
                               QSizePolicy, QFrame, QPushButton)
from PySide6.QtOpenGLWidgets import QOpenGLWidget
from OpenGL.GL import *
from typing import Dict, Any, List, Optional

from ..live2d import Live2dModel, live2d
from .binder import AgentBinder

class Live2DWidget(QOpenGLWidget):
    def __init__(self, live2d_config: Dict[str, Any], agent_binder: AgentBinder, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_AlwaysStackOnTop)
        self.model: Live2dModel = Live2dModel(live2d_config)
        agent_binder.model = self.model
        self.setMouseTracking(True)

    def initializeGL(self) -> None:
        # Load model config
        self.model.model_init()

        # Set clear color to transparent
        glClearColor(0, 0, 0, 0)
        
        # Start update timer (approx 60 FPS)
        self.startTimer(int(1000 / 60))

    def resizeGL(self, w: int, h: int) -> None:
        glViewport(0, 0, w, h)
        if self.model:
            self.model.Resize(w, h)

    def paintGL(self) -> None:
        # Clear with transparency
        glClearColor(0, 0, 0, 0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        
        if self.model:
            self.model.Update()
            self.model.Draw()

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if not self.model:
            return
        x, y = event.position().x(), event.position().y()
        if self.model.HitTest("头", x, y):
            self.model.set_next_expression()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if not self.model:
            return
        x, y = event.position().x() - self.x(), event.position().y() - self.y()
        self.model.Drag(x, y)

    def timerEvent(self, event: QTimerEvent) -> None:
        self.update()

class Live2DContainer(QWidget):
    def __init__(self, gui_config, live2d_config, agent_binder: AgentBinder, parent=None):
        super().__init__(parent)
        self.live2d_widget = Live2DWidget(live2d_config, agent_binder = agent_binder, parent=self)
        self.gui_config = gui_config
        self.live2d_config: Dict[str, Any] = live2d_config
        self.background_image = None
        self.load_background()
        
    def load_background(self):
        bg_path = self.gui_config["live2d_background"]["image_path"]
        if os.path.exists(bg_path):
            self.background_image = QImage(bg_path)
        else:
            print(f"Warning: Background not found at {bg_path}")

    def resizeEvent(self, event: QResizeEvent):
        # Maintain 3:4 aspect ratio for the content area
        # But this widget is the container, it might be resized by the layout.
        # We want to draw the background and place the Live2D widget to fill this container.
        # The constraint "Live2d界面的比例保持为3:4不变" might mean the container itself should be 3:4
        # OR the content inside should be 3:4.
        # If the user resizes the window, we should try to keep this widget at 3:4?
        # Or just let it fill the left side?
        # Let's assume the user wants the VISIBLE area to be 3:4.
        # If we force the widget to be 3:4, we might have empty space around it.
        
        # For now, let's make the Live2D widget fill this container, 
        # and we will handle the aspect ratio in the parent layout or by enforcing size constraints.
        self.live2d_widget.resize(self.size())
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

class ChatBubble(QWidget):
    def __init__(self, text, is_user=False, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self.text = text
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        
        self.text_edit = QTextEdit()
        self.text_edit.setReadOnly(True)
        self.text_edit.setText(self.text)
        self.text_edit.setFrameShape(QFrame.Shape.NoFrame)
        self.text_edit.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.text_edit.setWordWrapMode(QTextOption.WrapMode.WrapAnywhere)
        self.text_edit.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.text_edit.document().setDocumentMargin(0)
        
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
        
        # Alignment
        if self.is_user:
            layout.addStretch()
            layout.addWidget(self.text_edit)
        else:
            layout.addWidget(self.text_edit)
            layout.addStretch()
            
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

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

class ChatWidget(QWidget):
    def __init__(self, parent=None, config: Dict = None, agent_binder: AgentBinder = None):
        super().__init__(parent)
        self.config = config if config is not None else {}
        self.agent = agent_binder if agent_binder is not None else AgentBinder()
        self.agent.response_signal.connect(self.on_agent_response)
        self.agent.update_signal.connect(self.on_agent_update)
        self.agent.delete_signal.connect(self.on_agent_delete)
        self.agent.free_signal.connect(self.on_agent_free_status_changed)
        
        # History loading
        self.agent.history_signal.connect(self.on_history_loaded)
        self.load_history_num = self.config.get("load_history_num", 20)
        self.current_history_index = -1
        self.is_loading_history = False
        self.first_load = True

        self.init_ui()

        # Initial load
        QTimer.singleShot(100, lambda: self.agent.load_history(self.load_history_num, -1))

    def init_ui(self):
        # Right side background color
        self.setStyleSheet("background-color: #DDDDDD;") # Light gray
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
        
        layout.addWidget(self.scroll_area)
        layout.addWidget(self.h_line)
        layout.addWidget(self.toolbar)
        layout.addWidget(self.h_line_2)
        layout.addWidget(self.input_box)
        
        self.setLayout(layout)
        self.temp_is_user = True

    def on_scroll_value_changed(self, value):
        if value == 0 and not self.is_loading_history and self.current_history_index > 0:
            self.is_loading_history = True
            self.agent.load_history(self.load_history_num, self.current_history_index)

    def on_history_loaded(self, history_list, start_index):
        self.is_loading_history = False
        if not history_list:
            return
            
        self.current_history_index = start_index
        
        # Save scroll position
        scrollbar = self.scroll_area.verticalScrollBar()
        old_max = scrollbar.maximum()
        old_value = scrollbar.value()
        
        # Prepend messages
        for item in reversed(history_list):
            is_user = (item["source"] == "user")
            bubble = ChatBubble(item["content"], is_user)
            self.history_layout.insertWidget(0, bubble)
            
        # Restore scroll position
        QApplication.processEvents()
        new_max = scrollbar.maximum()
        
        if self.first_load:
            # Use QTimer to ensure layout is updated and scrollbar max is correct
            QTimer.singleShot(50, lambda: scrollbar.setValue(scrollbar.maximum()))
            self.first_load = False
        elif old_max != new_max:
             QTimer.singleShot(50, lambda: scrollbar.setValue(old_value + scrollbar.maximum() - old_max))
        else:
            QTimer.singleShot(50, lambda: scrollbar.setValue(scrollbar.maximum() - old_max))

    def on_text_changed(self):
        self.can_send = bool(self.input_box.toPlainText().strip()) and self.agent_free
        self.update_send_button_state()

    def on_agent_free_status_changed(self, is_free: bool):
        self.agent_free = is_free
        self.can_send = bool(self.input_box.toPlainText().strip()) and self.agent_free
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

    def on_send_clicked(self):
        self.handle_input()

    def eventFilter(self, obj, event):
        if obj == self.input_box:
            if event.type() == QEvent.Type.KeyPress:
                if event.key() == Qt.Key.Key_Return or event.key() == Qt.Key.Key_Enter:
                    if not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
                        self.handle_input()
                        return True
            elif event.type() == QEvent.Type.Resize:
                s = self.send_button.size()
                self.send_button.move(self.input_box.width() - s.width() - 10, 
                                      self.input_box.height() - s.height() - 10)
        return super().eventFilter(obj, event)

    def handle_input(self):
        if self.can_send == False:
            return
        text = self.input_box.toPlainText().strip()
        if not text:
            return
        
        self.add_message(text, is_user=True)
        self.input_box.clear()
        
        self.agent.hear(text)

    def on_agent_response(self, text):
        self.add_message(text, is_user=False)

        QApplication.processEvents() # Ensure layout updates
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

    def on_agent_update(self, text):
        count = self.history_layout.count()
        if count > 1:
            item = self.history_layout.itemAt(count - 2)
            widget = item.widget()
            if isinstance(widget, ChatBubble):
                widget.set_text(text)
                QApplication.processEvents()
                self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())
    
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

    def add_message(self, text, is_user):
        bubble = ChatBubble(text, is_user)
        # Insert before the stretch item (which is the last item)
        self.history_layout.insertWidget(self.history_layout.count() - 1, bubble)
        
        # Scroll to bottom
        QApplication.processEvents() # Ensure layout updates
        self.scroll_area.verticalScrollBar().setValue(self.scroll_area.verticalScrollBar().maximum())

class MainWindow(QWidget):
    def __init__(self, gui_config, live2d_config, ui_binder: AgentBinder):
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
        self.chat_widget = ChatWidget(config=gui_config["chat_window"], agent_binder=ui_binder)
        self.layout.addWidget(self.live2d_container)
        self.layout.addWidget(self.v_line)
        self.layout.addWidget(self.chat_widget)
        
        self.setLayout(self.layout)

    def resizeEvent(self, event: QResizeEvent):
        # Calculate desired width for Live2D container based on window height
        h = self.height()
        w_live2d = int(h * 3 / 4)
        
        # Set fixed width for Live2D container
        self.live2d_container.setFixedWidth(w_live2d)
        
        # Chat widget will automatically take the remaining space
        
        super().resizeEvent(event)
