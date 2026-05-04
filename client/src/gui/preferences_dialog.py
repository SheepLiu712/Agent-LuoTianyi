"""
用户偏好设置对话框 - 让用户可以自定义重要日期和相处模式
"""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QWidget, QLabel, QLineEdit, QPushButton, QComboBox,
                               QCheckBox, QListWidget, QListWidgetItem, QTextEdit,
                               QTimeEdit, QSpinBox, QMessageBox, QDateEdit)
from PySide6.QtCore import Qt, QTime, QDate
from PySide6.QtGui import QFont
from .user_preferences_manager import UserPreferencesManager


class UserPreferencesDialog(QDialog):
    """用户偏好设置对话框"""
    
    def __init__(self, preferences_manager: UserPreferencesManager, parent=None):
        super().__init__(parent)
        self.preferences_manager = preferences_manager
        self.setWindowTitle("用户自定义设置")
        self.setMinimumSize(600, 500)
        self.setModal(True)
        
        self.init_ui()
        self.load_current_settings()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout()
        
        # 创建标签页
        tab_widget = QTabWidget()
        
        # 标签页1: 重要日期
        self.dates_tab = self._create_dates_tab()
        tab_widget.addTab(self.dates_tab, "📅 重要日期")
        
        # 标签页2: 相处模式
        self.relationship_tab = self._create_relationship_tab()
        tab_widget.addTab(self.relationship_tab, "💬 相处模式")
        
        # 标签页3: 提醒设置
        self.reminder_tab = self._create_reminder_tab()
        tab_widget.addTab(self.reminder_tab, "⏰ 提醒设置")
        
        layout.addWidget(tab_widget)
        
        # 按钮区域
        button_layout = QHBoxLayout()
        button_layout.addStretch()
        
        self.save_button = QPushButton("保存")
        self.save_button.clicked.connect(self.save_settings)
        self.save_button.setStyleSheet("""
            QPushButton {
                background-color: #66CCFF;
                color: white;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #55BBEE;
            }
        """)
        
        self.cancel_button = QPushButton("取消")
        self.cancel_button.clicked.connect(self.reject)
        self.cancel_button.setStyleSheet("""
            QPushButton {
                background-color: #D8D8D8;
                color: #333333;
                border: none;
                padding: 8px 20px;
                border-radius: 4px;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #C8C8C8;
            }
        """)
        
        button_layout.addWidget(self.cancel_button)
        button_layout.addWidget(self.save_button)
        
        layout.addLayout(button_layout)
        self.setLayout(layout)
    
    def _create_dates_tab(self) -> QWidget:
        """创建重要日期标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 添加日期区域
        add_group = QVBoxLayout()
        add_group.addWidget(QLabel("添加重要日期"))
        
        # 名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("名称:"))
        self.date_name_input = QLineEdit()
        self.date_name_input.setPlaceholderText("例如：我的生日")
        name_layout.addWidget(self.date_name_input)
        add_group.addLayout(name_layout)
        
        # 日期
        date_layout = QHBoxLayout()
        date_layout.addWidget(QLabel("日期:"))
        self.date_input = QDateEdit()
        self.date_input.setCalendarPopup(True)
        self.date_input.setDate(QDate.currentDate())
        date_layout.addWidget(self.date_input)
        add_group.addLayout(date_layout)
        
        # 类型
        type_layout = QHBoxLayout()
        type_layout.addWidget(QLabel("类型:"))
        self.date_type_combo = QComboBox()
        self.date_type_combo.addItems(["生日", "纪念日", "日程", "其他"])
        type_layout.addWidget(self.date_type_combo)
        type_layout.addStretch()
        add_group.addLayout(type_layout)
        
        # 提醒消息
        msg_layout = QHBoxLayout()
        msg_layout.addWidget(QLabel("提醒消息:"))
        self.date_message_input = QLineEdit()
        self.date_message_input.setPlaceholderText("留空则使用默认消息")
        msg_layout.addWidget(self.date_message_input)
        add_group.addLayout(msg_layout)
        
        # 添加按钮
        add_button = QPushButton("添加日期")
        add_button.clicked.connect(self.add_important_date)
        add_group.addWidget(add_button)
        
        layout.addLayout(add_group)
        
        # 分隔线
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setFrameShadow(QFrame.Shadow.Sunken)
        layout.addWidget(line)
        
        # 日期列表
        layout.addWidget(QLabel("已设置的重要日期:"))
        self.dates_list = QListWidget()
        layout.addWidget(self.dates_list)
        
        # 删除按钮
        delete_button = QPushButton("删除选中")
        delete_button.clicked.connect(self.delete_selected_date)
        layout.addWidget(delete_button)
        
        widget.setLayout(layout)
        return widget
    
    def _create_relationship_tab(self) -> QWidget:
        """创建相处模式标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 关系类型
        rel_layout = QHBoxLayout()
        rel_layout.addWidget(QLabel("关系类型:"))
        self.relationship_combo = QComboBox()
        self.relationship_combo.addItems(["朋友", "亲密朋友", "恋人", "家人", "导师", "学生", "其他"])
        self.relationship_combo.setEditable(True)
        rel_layout.addWidget(self.relationship_combo)
        rel_layout.addStretch()
        layout.addLayout(rel_layout)
        
        # 表达风格
        style_layout = QHBoxLayout()
        style_layout.addWidget(QLabel("表达风格:"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(["友好温和", "活泼可爱", "成熟稳重", "幽默风趣", "专业严谨", "随意自然"])
        self.style_combo.setEditable(True)
        style_layout.addWidget(self.style_combo)
        style_layout.addStretch()
        layout.addLayout(style_layout)
        
        # 性格特点
        layout.addWidget(QLabel("性格特点 (用逗号分隔):"))
        self.personality_input = QLineEdit()
        self.personality_input.setPlaceholderText("例如：温柔、耐心、善解人意")
        layout.addWidget(self.personality_input)
        
        # 自定义上下文
        layout.addWidget(QLabel("自定义上下文 (可选):"))
        self.custom_context_input = QTextEdit()
        self.custom_context_input.setMaximumHeight(100)
        self.custom_context_input.setPlaceholderText("在这里添加任何你想让天依知道的关于你们关系的信息...")
        layout.addWidget(self.custom_context_input)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def _create_reminder_tab(self) -> QWidget:
        """创建提醒设置标签页"""
        widget = QWidget()
        layout = QVBoxLayout()
        
        # 启用提醒
        self.enable_reminder_check = QCheckBox("启用重要日期提醒")
        layout.addWidget(self.enable_reminder_check)
        
        # 提醒时间
        time_layout = QHBoxLayout()
        time_layout.addWidget(QLabel("每天提醒时间:"))
        self.reminder_time_edit = QTimeEdit()
        self.reminder_time_edit.setTime(QTime(9, 0))
        time_layout.addWidget(self.reminder_time_edit)
        time_layout.addStretch()
        layout.addLayout(time_layout)
        
        # 检查间隔
        interval_layout = QHBoxLayout()
        interval_layout.addWidget(QLabel("检查间隔 (小时):"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(1, 24)
        self.interval_spin.setValue(1)
        interval_layout.addWidget(self.interval_spin)
        interval_layout.addStretch()
        layout.addLayout(interval_layout)
        
        layout.addStretch()
        widget.setLayout(layout)
        return widget
    
    def load_current_settings(self):
        """加载当前设置"""
        # 加载重要日期
        dates = self.preferences_manager.get_important_dates()
        self.dates_list.clear()
        for date_info in dates:
            enabled = "✓" if date_info.get("enabled", True) else "✗"
            item_text = f"{enabled} {date_info['name']} - {date_info['date']} ({date_info['type']})"
            item = QListWidgetItem(item_text)
            item.setData(Qt.ItemDataRole.UserRole, date_info.get("id"))
            self.dates_list.addItem(item)
        
        # 加载相处模式
        mode = self.preferences_manager.get_relationship_mode()
        relationship = mode.get("relationship", "朋友")
        speaking_style = mode.get("speaking_style", "友好温和")
        personality_traits = mode.get("personality_traits", [])
        custom_context = mode.get("custom_context", "")
        
        # 设置关系类型
        index = self.relationship_combo.findText(relationship)
        if index >= 0:
            self.relationship_combo.setCurrentIndex(index)
        else:
            self.relationship_combo.setCurrentText(relationship)
        
        # 设置表达风格
        index = self.style_combo.findText(speaking_style)
        if index >= 0:
            self.style_combo.setCurrentIndex(index)
        else:
            self.style_combo.setCurrentText(speaking_style)
        
        # 设置性格特点
        self.personality_input.setText("、".join(personality_traits))
        
        # 设置自定义上下文
        self.custom_context_input.setText(custom_context)
        
        # 加载提醒设置
        reminder_settings = self.preferences_manager.get_reminder_settings()
        self.enable_reminder_check.setChecked(reminder_settings.get("enable_reminders", True))
        
        reminder_time = reminder_settings.get("reminder_time", "09:00")
        time_parts = reminder_time.split(":")
        self.reminder_time_edit.setTime(QTime(int(time_parts[0]), int(time_parts[1])))
        
        self.interval_spin.setValue(reminder_settings.get("check_interval_hours", 1))
    
    def add_important_date(self):
        """添加重要日期"""
        name = self.date_name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "警告", "请输入日期名称！")
            return
        
        date = self.date_input.date().toString("yyyy-MM-dd")
        type_map = {"生日": "birthday", "纪念日": "anniversary", "日程": "schedule", "其他": "other"}
        date_type = type_map.get(self.date_type_combo.currentText(), "other")
        message = self.date_message_input.text().strip()
        
        if self.preferences_manager.add_important_date(name, date, date_type, message):
            self.date_name_input.clear()
            self.date_message_input.clear()
            self.load_current_settings()  # 刷新列表
            QMessageBox.information(self, "成功", "重要日期已添加！")
        else:
            QMessageBox.warning(self, "错误", "添加重要日期失败！")
    
    def delete_selected_date(self):
        """删除选中的重要日期"""
        selected_items = self.dates_list.selectedItems()
        if not selected_items:
            QMessageBox.warning(self, "警告", "请先选择要删除的日期！")
            return
        
        for item in selected_items:
            date_id = item.data(Qt.ItemDataRole.UserRole)
            self.preferences_manager.remove_important_date(date_id)
        
        self.load_current_settings()  # 刷新列表
        QMessageBox.information(self, "成功", "已删除选中的日期！")
    
    def save_settings(self):
        """保存所有设置"""
        try:
            # 保存相处模式
            relationship = self.relationship_combo.currentText()
            speaking_style = self.style_combo.currentText()
            personality_traits = [t.strip() for t in self.personality_input.text().split("、") if t.strip()]
            custom_context = self.custom_context_input.toPlainText().strip()
            
            self.preferences_manager.set_relationship_mode(
                relationship=relationship,
                speaking_style=speaking_style,
                personality_traits=personality_traits,
                custom_context=custom_context
            )
            
            # 保存提醒设置
            enable_reminders = self.enable_reminder_check.isChecked()
            reminder_time = self.reminder_time_edit.time().toString("HH:mm")
            check_interval = self.interval_spin.value()
            
            self.preferences_manager.set_reminder_settings(
                enable_reminders=enable_reminders,
                reminder_time=reminder_time,
                check_interval_hours=check_interval
            )
            
            QMessageBox.information(self, "成功", "设置已保存！")
            self.accept()
        
        except Exception as e:
            QMessageBox.warning(self, "错误", f"保存设置失败: {e}")
