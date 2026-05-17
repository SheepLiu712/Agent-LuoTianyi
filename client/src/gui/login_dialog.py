from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QMessageBox, QTabWidget, QWidget, QCheckBox)
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit,
                               QPushButton, QMessageBox, QTabWidget, QWidget, QCheckBox,
                               QComboBox, QHBoxLayout)
from PySide6.QtCore import Qt

from .binder import AgentBinder
from ..safety import credential
from ..utils.logger import get_logger
from ..utils.http_client import HttpClientFactory


class PreferenceGuideDialog(QDialog):
    """注册后的快速偏好设置引导"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置你的相处偏好")
        self.setFixedSize(420, 320)
        self.result_data = {}

        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(25, 25, 25, 25)

        title = QLabel("欢迎！在开始聊天前，可以简单设置一下天依和你的相处方式~")
        title.setWordWrap(True)
        title.setStyleSheet("font-size: 14px; color: #555;")
        layout.addWidget(title)

        # 关系类型
        rel_layout = QHBoxLayout()
        rel_layout.addWidget(QLabel("你和天依的关系："))
        self.relationship_combo = QComboBox()
        self.relationship_combo.addItems(["朋友", "知己", "粉丝", "搭档", "家人", "其他"])
        self.relationship_combo.setCurrentText("朋友")
        self.relationship_combo.setStyleSheet("font-size: 14px; padding: 4px;")
        rel_layout.addWidget(self.relationship_combo)
        rel_layout.addStretch()
        layout.addLayout(rel_layout)

        # 表达风格
        style_layout = QHBoxLayout()
        style_layout.addWidget(QLabel("希望天依的风格：（可留空）"))
        self.style_combo = QComboBox()
        self.style_combo.addItems(["", "活泼可爱", "温柔可人", "俏皮调皮", "诗意文艺", "热情洋溢", "文静恬淡"])
        self.style_combo.setCurrentText("")
        self.style_combo.setStyleSheet("font-size: 14px; padding: 4px;")
        style_layout.addWidget(self.style_combo)
        style_layout.addStretch()
        layout.addLayout(style_layout)

        # 提示文字
        hint = QLabel("这些设置后续可以在「设置」中随时修改~")
        hint.setStyleSheet("font-size: 12px; color: #999;")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(hint)

        layout.addStretch()

        # 按钮
        btn_layout = QHBoxLayout()
        skip_btn = QPushButton("先试试看")
        skip_btn.setStyleSheet("font-size: 14px; padding: 8px 20px; background-color: #E0E0E0; border-radius: 5px;")
        skip_btn.clicked.connect(self.reject)

        confirm_btn = QPushButton("确认")
        confirm_btn.setStyleSheet("font-size: 14px; padding: 8px 20px; background-color: #66ccff; color: white; border-radius: 5px;")
        confirm_btn.clicked.connect(self.accept)

        btn_layout.addStretch()
        btn_layout.addWidget(skip_btn)
        btn_layout.addSpacing(15)
        btn_layout.addWidget(confirm_btn)
        layout.addLayout(btn_layout)

        self.setLayout(layout)

    def get_preferences(self) -> dict:
        relationship = self.relationship_combo.currentText()
        speaking_style = self.style_combo.currentText()
        prefs = {"relationship": relationship}
        if speaking_style:
            prefs["speaking_style"] = speaking_style
        return prefs


class LoginDialog(QDialog):
    def __init__(self, binder: AgentBinder, preferences_manager=None):
        super().__init__()
        self.logger = get_logger(self.__class__.__name__)
        self.binder = binder
        self.preferences_manager = preferences_manager
        self.user_id = None
        self.saved_token = None
        self.custom_base_url = None  # 自定义服务器地址

        self.setWindowTitle("ChatWithLuoTianyi - 登录/注册")
        self.setFixedSize(420, 380)

        layout = QVBoxLayout()

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab { font-size: 16px; min-height: 28px; }")
        self.login_tab = QWidget()
        self.register_tab = QWidget()

        self.tabs.addTab(self.login_tab, "登录")
        self.tabs.addTab(self.register_tab, "注册")

        self.setup_login_ui()
        self.setup_register_ui()

        layout.addWidget(self.tabs)

        self.setLayout(layout)

        cred = credential.load_credentials()
        if cred:
            username, token, do_auto_login, saved_url = cred if len(cred) >= 4 else (*cred, None)
            self.l_auto_login.setChecked(do_auto_login)
            self.l_username.setText(username or "")
            self.saved_token = token
            if saved_url:
                self.custom_base_url = saved_url

    def try_auto_login(self) -> bool:
        try:
            if self.l_auto_login.isChecked() and self.saved_token and self.l_username.text():
                self.logger.info("Attempting auto login...")
                ret = self.binder.on_auto_login(self.l_username.text(), self.saved_token)
                if ret:
                    self.logger.info("Auto login successful")
                    return True
                else:
                    self.logger.info("Auto login failed")
                    self.saved_token = None
                    self.l_auto_login.setChecked(False)
                    credential.save_credentials(self.l_username.text(), None, False)
        except Exception as e:
            self.logger.error(f"Auto login exception: {e}")
        return False

    def setup_login_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)
        style = "font-size: 16px; padding: 5px;"

        self.l_username = QLineEdit()
        self.l_username.setPlaceholderText("用户名")
        self.l_username.setStyleSheet(style)

        self.l_password = QLineEdit()
        self.l_password.setPlaceholderText("密码")
        self.l_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.l_password.setStyleSheet(style)

        self.l_auto_login = QCheckBox("自动登录")
        self.l_auto_login.setStyleSheet("font-size: 16px; padding: 5px;")

        self.l_btn = QPushButton("登录")
        self.l_btn.clicked.connect(self.do_login)
        self.l_btn.setStyleSheet(
            "QPushButton { font-size: 16px; padding: 5px;"
            " background-color: #44BBEE; color: white; border-radius: 5px; }"
            " QPushButton:hover { background-color: #66ccff; }"
        )

        self.reset_btn = QPushButton("重置账号")
        self.reset_btn.setStyleSheet(
            "QPushButton { font-size: 16px; padding: 4px; color: #4488BB;"
            " border: none; text-align: left; }"
            " QPushButton:hover { color: #77BBEE; }"
        )
        self.reset_btn.clicked.connect(self.open_reset_account_dialog)

        self.server_btn = QPushButton("服务器地址")
        self.server_btn.setStyleSheet(
            "QPushButton { font-size: 16px; padding: 4px; color: #4488BB;"
            " border: none; text-align: left; }"
            " QPushButton:hover { color: #77BBEE; }"
        )
        self.server_btn.clicked.connect(self.open_server_settings_dialog)

        layout.addWidget(self.l_username)
        layout.addSpacing(20)
        layout.addWidget(self.l_password)
        layout.addSpacing(10)
        layout.addWidget(self.l_auto_login)
        layout.addSpacing(8)
        layout.addWidget(self.reset_btn)
        layout.addSpacing(8)
        layout.addWidget(self.server_btn)
        layout.addStretch()
        layout.addWidget(self.l_btn)
        self.login_tab.setLayout(layout)

    def setup_register_ui(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(0)
        style = "font-size: 16px; padding: 5px;"

        self.r_username = QLineEdit()
        self.r_username.setPlaceholderText("用户名")
        self.r_username.setStyleSheet(style)

        self.r_password = QLineEdit()
        self.r_password.setPlaceholderText("密码")
        self.r_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.r_password.setStyleSheet(style)

        self.r_confirm_password = QLineEdit()
        self.r_confirm_password.setPlaceholderText("确认密码")
        self.r_confirm_password.setEchoMode(QLineEdit.EchoMode.Password)
        self.r_confirm_password.setStyleSheet(style)

        self.r_invite = QLineEdit()
        self.r_invite.setPlaceholderText("邀请码")
        self.r_invite.setStyleSheet(style)

        self.r_btn = QPushButton("注册")
        self.r_btn.clicked.connect(self.do_register)
        self.r_btn.setStyleSheet(
            "QPushButton { font-size: 16px; padding: 5px;"
            " background-color: #44BBEE; color: white; border-radius: 5px; }"
            " QPushButton:hover { background-color: #66ccff; }"
        )

        layout.addWidget(self.r_username)
        layout.addSpacing(20)
        layout.addWidget(self.r_password)
        layout.addSpacing(20)
        layout.addWidget(self.r_confirm_password)
        layout.addSpacing(20)
        layout.addWidget(self.r_invite)
        layout.addStretch()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(self.r_btn)
        self.register_tab.setLayout(layout)

    def do_login(self):
        username = self.l_username.text()
        password = self.l_password.text()
        do_auto_login = self.l_auto_login.isChecked()
        
        if not username or not password:
            QMessageBox.warning(self, "错误", "请输入用户名和密码")
            return
            
        success, msg = self.binder.on_login(username, password, do_auto_login=do_auto_login)
        if success:
            self.accept()
        else:
            QMessageBox.critical(self, "登录失败", msg)

    def do_register(self):
        username = self.r_username.text()
        password = self.r_password.text()
        confirm_password = self.r_confirm_password.text()
        invite = self.r_invite.text()

        if not username or not password or not confirm_password or not invite:
            QMessageBox.warning(self, "错误", "请填写所有信息")
            return

        if password != confirm_password:
            QMessageBox.warning(self, "错误", "两次输入的密码不一致")
            return

        success, msg = self.binder.on_register(username, password, invite)
        if success:
            # 注册成功后显示偏好引导
            if self.preferences_manager:
                guide = PreferenceGuideDialog(self)
                if guide.exec() == QDialog.DialogCode.Accepted:
                    prefs = guide.get_preferences()
                    self.preferences_manager.set_relationship_mode(
                        relationship=prefs.get("relationship", "朋友"),
                        speaking_style=prefs.get("speaking_style", ""),
                    )
            QMessageBox.information(self, "成功", "注册成功，请登录")
            self.tabs.setCurrentIndex(0)
        else:
            QMessageBox.critical(self, "注册失败", msg)

    def open_reset_account_dialog(self):
        """打开重置账号对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("重置账号")
        dialog.setFixedSize(380, 280)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)
        style = "font-size: 14px; padding: 5px;"

        desc = QLabel("输入已使用的邀请码和新账号信息来重置账号：")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #666;")
        layout.addWidget(desc)

        invite_input = QLineEdit()
        invite_input.setPlaceholderText("已使用的邀请码")
        invite_input.setStyleSheet(style)
        layout.addWidget(invite_input)

        username_input = QLineEdit()
        username_input.setPlaceholderText("新用户名")
        username_input.setStyleSheet(style)
        layout.addWidget(username_input)

        password_input = QLineEdit()
        password_input.setPlaceholderText("新密码")
        password_input.setEchoMode(QLineEdit.EchoMode.Password)
        password_input.setStyleSheet(style)
        layout.addWidget(password_input)

        confirm_input = QLineEdit()
        confirm_input.setPlaceholderText("确认新密码")
        confirm_input.setEchoMode(QLineEdit.EchoMode.Password)
        confirm_input.setStyleSheet(style)
        layout.addWidget(confirm_input)

        btn = QPushButton("确认重置")
        btn.setStyleSheet("font-size: 14px; padding: 8px; background-color: #FF6B6B; color: white; border-radius: 5px;")
        layout.addWidget(btn)

        def do_reset():
            invite = invite_input.text().strip()
            new_username = username_input.text().strip()
            new_password = password_input.text().strip()
            confirm = confirm_input.text().strip()

            if not invite or not new_username or not new_password or not confirm:
                QMessageBox.warning(dialog, "错误", "请填写所有信息")
                return
            if new_password != confirm:
                QMessageBox.warning(dialog, "错误", "两次输入的密码不一致")
                return

            success, msg = self.binder.on_reset_account(invite, new_username, new_password)
            if success:
                QMessageBox.information(dialog, "成功", "账号重置成功，请使用新账号登录")
                self.l_username.setText(new_username)
                self.tabs.setCurrentIndex(0)
                dialog.accept()
            else:
                QMessageBox.critical(dialog, "重置失败", msg)

        btn.clicked.connect(do_reset)
        dialog.exec()

    def open_server_settings_dialog(self):
        """打开服务器地址设置对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("服务器地址设置")
        dialog.setFixedSize(400, 200)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        desc = QLabel("输入自定义服务器地址（URL），输入后会自动验证连接：")
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #666;")
        layout.addWidget(desc)

        url_input = QLineEdit()
        url_input.setPlaceholderText("例如：https://your-server.com:60030")
        url_input.setStyleSheet("font-size: 14px; padding: 6px;")
        if self.custom_base_url:
            url_input.setText(self.custom_base_url)
        layout.addWidget(url_input)

        btn = QPushButton("验证并保存")
        btn.setStyleSheet("font-size: 14px; padding: 8px; background-color: #66CCFF; color: white; border-radius: 5px;")
        layout.addWidget(btn)

        def do_verify():
            url = url_input.text().strip().rstrip("/")
            if not url:
                QMessageBox.warning(dialog, "错误", "请输入服务器地址")
                return

            # 自动补全协议头
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url

            # 尝试获取 public key 来验证服务器
            try:
                session = HttpClientFactory.get_session(verify_ssl=True)
                resp = session.get(f"{url}/auth/public_key", timeout=10)
                if resp.status_code == 200:
                    self.custom_base_url = url
                    credential.save_server_url(url, verify_ssl=True)
                    # 同步更新 NetworkClient（AuthApi + WsTransport）
                    self.binder.on_set_base_url(url, verify_ssl=True)
                    QMessageBox.information(dialog, "成功", "服务器地址验证成功，地址已保存")
                    dialog.accept()
                else:
                    QMessageBox.critical(dialog, "验证失败", f"服务器返回状态码: {resp.status_code}")
            except Exception as e:
                QMessageBox.critical(dialog, "验证失败", f"无法连接到服务器: {e}")

        btn.clicked.connect(do_verify)
        dialog.exec()
