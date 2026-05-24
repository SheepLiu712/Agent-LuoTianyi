"""
用户偏好设置对话框 - 让用户可以自定义重要日期和相处模式
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QWidget, QLabel, QLineEdit, QPushButton, QComboBox,
                               QCheckBox, QListWidget, QListWidgetItem, QTextEdit,
                               QTimeEdit, QSpinBox, QMessageBox, QDateEdit, QFrame)
from PySide6.QtCore import Qt, QTime, QDate
from PySide6.QtGui import QFont
from typing import TYPE_CHECKING
from ..utils.logger import get_logger

if TYPE_CHECKING:
    from ..network.network_client import NetworkClient

class PreferencesDialog(QDialog):
    """偏好设置对话框 - 从工具栏打开，从服务器加载/保存。"""

    def __init__(self, network_client: "NetworkClient", parent=None):
        super().__init__(parent)
        self.logger = get_logger(self.__class__.__name__)
        self.network_client = network_client
        self.setWindowTitle("设置与天依的相处模式")
        self.setMinimumSize(500, 480)
        self.setModal(True)

        self._preferences = {}
        self.init_ui()
        self.load_preferences()

    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("和天依的相处模式")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #66CCFF;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel("你可以在这里告诉天依你们之间的关系和相处方式，"
                       "这样天依会更好地了解你！")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #666; margin-bottom: 10px;")
        layout.addWidget(desc)

        # 关系类型
        rel_label = QLabel("你希望和天依的关系是：")
        rel_label.setStyleSheet("font-size: 14px; font-weight: 500;")
        layout.addWidget(rel_label)

        self.relationship_combo = QComboBox()
        self.relationship_combo.addItems(["朋友", "知己", "粉丝", "搭档", "家人", "其他"])
        self.relationship_combo.setEditable(True)
        self.relationship_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        layout.addWidget(self.relationship_combo)

        # 表达风格
        style_label = QLabel("你希望天依的表达风格偏向：")
        style_label.setStyleSheet("font-size: 14px; font-weight: 500; margin-top: 8px;")
        layout.addWidget(style_label)

        self.style_combo = QComboBox()
        self.style_combo.addItems(["活泼可爱", "温柔可人", "俏皮调皮", "诗意文艺", "热情洋溢", "文静恬淡", "随意自然"])
        self.style_combo.setEditable(True)
        self.style_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        layout.addWidget(self.style_combo)

        # 性格特点
        trait_label = QLabel("你希望天依的性格特点（用逗号分隔，可选）：")
        trait_label.setStyleSheet("font-size: 14px; font-weight: 500; margin-top: 8px;")
        layout.addWidget(trait_label)

        self.personality_input = QLineEdit()
        self.personality_input.setPlaceholderText("例如：温柔、耐心、善解人意")
        self.personality_input.setStyleSheet("font-size: 14px; padding: 6px;")
        layout.addWidget(self.personality_input)

        # 自定义上下文
        ctx_label = QLabel("其他你想让天依知道的（可选）：")
        ctx_label.setStyleSheet("font-size: 14px; font-weight: 500; margin-top: 8px;")
        layout.addWidget(ctx_label)

        self.custom_context_input = QTextEdit()
        self.custom_context_input.setMaximumHeight(80)
        self.custom_context_input.setPlaceholderText("在这里添加任何你想让天依知道的关于你们关系的信息...")
        self.custom_context_input.setStyleSheet("font-size: 13px; padding: 4px;")
        layout.addWidget(self.custom_context_input)

        layout.addStretch()

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(16)

        btn_layout.addStretch()

        self.save_btn = QPushButton("保存设置")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #4CAF50;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #45a049;
            }
        """)
        self.save_btn.clicked.connect(self.on_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def load_preferences(self):
        """从服务器加载偏好设置并填充 UI。"""
        try:
            data = self.network_client.get_preferences()
            if not data:
                return
            prefs = data if isinstance(data, dict) else {}
            if not prefs:
                return

            rel = prefs.get("relationship", "")
            if rel:
                idx = self.relationship_combo.findText(rel, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    self.relationship_combo.setCurrentIndex(idx)
                else:
                    self.relationship_combo.setEditText(rel)

            style = prefs.get("speaking_style", "")
            if style:
                idx = self.style_combo.findText(style, Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    self.style_combo.setCurrentIndex(idx)
                else:
                    self.style_combo.setEditText(style)

            personality_text = prefs.get("#sym:personality_text", "")
            if personality_text:
                self.personality_input.setText(personality_text)

            ctx = prefs.get("custom_context", "")
            if ctx:
                self.custom_context_input.setPlainText(ctx)

            self.logger.info("偏好设置已从服务器加载")
        except Exception as e:
            self.logger.warning(f"从服务器加载偏好设置失败: {e}")

    def get_preferences(self) -> dict:
        return self._preferences

    def on_save(self):
        relationship = self.relationship_combo.currentText().strip()
        speaking_style = self.style_combo.currentText().strip()
        personality_text = self.personality_input.text().strip()
        custom_context = self.custom_context_input.toPlainText().strip()

        self._preferences = {
            "relationship": relationship if relationship and relationship != "朋友" else "",
            "speaking_style": speaking_style if speaking_style and speaking_style != "活泼可爱" else "",
            "#sym:personality_text": personality_text,
            "custom_context": custom_context,
        }

        try:
            resp = self.network_client.overwrite_preferences(self._preferences)
            if resp.get("status") == "success":
                QMessageBox.information(self, "成功", "偏好设置已保存")
                self.accept()
            else:
                QMessageBox.critical(self, "保存失败", resp.get("message", "未知错误"))
        except Exception as e:
            self.logger.error(f"保存偏好设置失败: {e}")
            QMessageBox.critical(self, "保存失败", f"无法保存偏好设置: {e}")
