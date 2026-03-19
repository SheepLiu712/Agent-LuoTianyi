from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QFontMetrics, QTextOption
from PySide6.QtWidgets import ( QWidget, QHBoxLayout,
                               QTextEdit, QLabel, 
                               QSizePolicy, QFrame, QMenu)

class ChatImageBubble(QWidget):
    def __init__(self, image_path, is_user=False, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self.image_path = image_path
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        
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
        
        # Alignment
        if self.is_user:
            layout.addStretch()
            layout.addWidget(self.image_label)
        else:
            layout.addWidget(self.image_label)
            layout.addStretch()
            
        self.setLayout(layout)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Minimum)

class CustomTextEdit(QTextEdit):
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

class ChatBubble(QWidget):
    def __init__(self, text, is_user=False, parent=None):
        super().__init__(parent)
        self.is_user = is_user
        self.text = text
        self.init_ui()

    def init_ui(self):
        layout = QHBoxLayout()
        layout.setContentsMargins(10, 5, 10, 5)
        
        self.text_edit = CustomTextEdit()
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