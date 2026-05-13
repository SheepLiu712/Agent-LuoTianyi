import json
import os

import requests
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit,
                               QPushButton, QMessageBox, QTabWidget, QWidget, QCheckBox, QHBoxLayout)
from PySide6.QtCore import Qt

from .binder import AgentBinder
from ..safety import credential
from ..utils.logger import get_logger


class LoginDialog(QDialog):
    def __init__(self, binder: AgentBinder):
        super().__init__()
        self.logger = get_logger(self.__class__.__name__)
        self.binder = binder
        self.user_id = None
        self.saved_token = None
        
        self.setWindowTitle("ChatWithLuoTianyi - 登录/注册")
        self.setFixedSize(400, 350)
        
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

        # 服务器设置按钮
        self.server_btn = QPushButton("服务器设置")
        self.server_btn.setStyleSheet("font-size: 12px; padding: 3px; color: #888;")
        self.server_btn.clicked.connect(self.show_server_config)
        layout.addWidget(self.server_btn)

        self.setLayout(layout)

        cred = credential.load_credentials()
        if cred:
            username, token, do_auto_login = cred
            self.l_auto_login.setChecked(do_auto_login)
            self.l_username.setText(username or "")
            self.saved_token = token

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
        self.l_btn.setStyleSheet(style + "background-color: #66ccff; color: white; border-radius: 5px;")
        
        layout.addWidget(self.l_username)
        layout.addSpacing(20)
        layout.addWidget(self.l_password)
        layout.addSpacing(10)
        layout.addWidget(self.l_auto_login)
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
        self.r_btn.setStyleSheet(style + "background-color: #66ccff; color: white; border-radius: 5px;")
        
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
            QMessageBox.information(self, "成功", "注册成功，请登录")
            self.tabs.setCurrentIndex(0)
        else:
            QMessageBox.critical(self, "注册失败", msg)

    def show_server_config(self):
        """弹出服务器地址配置对话框"""
        dialog = QDialog(self)
        dialog.setWindowTitle("服务器设置")
        dialog.setFixedSize(420, 200)

        layout = QVBoxLayout()
        style = "font-size: 16px; padding: 5px;"

        label = QLabel("请输入服务器地址（例如 https://example.com:60030）：")
        label.setStyleSheet("font-size: 14px;")

        url_input = QLineEdit()
        url_input.setPlaceholderText("服务器地址")
        url_input.setStyleSheet(style)

        # 读取当前配置的地址
        config_path = self._get_config_path()
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                current_config = json.load(f)
            is_debug = current_config.get("is_debug", False)
            mode_key = "debug_config" if is_debug else "release_config"
            current_url = current_config.get(mode_key, {}).get("base_url", "")
            url_input.setText(current_url)
        except Exception:
            pass

        btn_layout = QHBoxLayout()

        test_btn = QPushButton("测试连接")
        test_btn.setStyleSheet(style + "background-color: #66ccff; color: white; border-radius: 5px;")

        save_btn = QPushButton("保存")
        save_btn.setStyleSheet(style + "background-color: #4CAF50; color: white; border-radius: 5px;")

        def test_connection():
            url = url_input.text().strip().rstrip("/")
            if not url:
                QMessageBox.warning(dialog, "错误", "请输入服务器地址")
                return
            try:
                resp = requests.get(f"{url}/auth/public_key", timeout=10, verify=False)
                if resp.status_code == 200:
                    QMessageBox.information(dialog, "成功", "✅ 服务器连接成功！")
                    test_btn.setStyleSheet(style + "background-color: #4CAF50; color: white; border-radius: 5px;")
                else:
                    QMessageBox.critical(dialog, "失败", f"服务器返回状态码: {resp.status_code}")
            except requests.exceptions.SSLError:
                QMessageBox.critical(dialog, "失败", "SSL证书验证失败，请检查地址是否正确")
            except requests.exceptions.ConnectionError:
                QMessageBox.critical(dialog, "失败", "无法连接到服务器，请检查地址是否正确")
            except Exception as e:
                QMessageBox.critical(dialog, "失败", f"连接失败: {e}")

        def save_config():
            url = url_input.text().strip().rstrip("/")
            if not url:
                QMessageBox.warning(dialog, "错误", "请输入服务器地址")
                return
            try:
                config_path = self._get_config_path()
                with open(config_path, "r", encoding="utf-8") as f:
                    config_data = json.load(f)
                is_debug = config_data.get("is_debug", False)
                mode_key = "debug_config" if is_debug else "release_config"
                if mode_key not in config_data:
                    config_data[mode_key] = {}
                config_data[mode_key]["base_url"] = url
                # 自动推断 verify_ssl（https 开头的需要验证）
                config_data[mode_key]["verify_ssl"] = url.startswith("https://")
                with open(config_path, "w", encoding="utf-8") as f:
                    json.dump(config_data, f, ensure_ascii=False, indent=4)
                QMessageBox.information(dialog, "成功", "服务器地址已保存，请重启客户端生效。")
                dialog.accept()
            except Exception as e:
                QMessageBox.critical(dialog, "错误", f"保存配置失败: {e}")

        test_btn.clicked.connect(test_connection)
        save_btn.clicked.connect(save_config)

        btn_layout.addWidget(test_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(save_btn)

        layout.addWidget(label)
        layout.addSpacing(10)
        layout.addWidget(url_input)
        layout.addSpacing(20)
        layout.addLayout(btn_layout)
        dialog.setLayout(layout)
        dialog.exec()

    def _get_config_path(self):
        """获取客户端 config.json 的路径"""
        # 从当前文件向上定位到 client/config/config.json
        return os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "config", "config.json"
        )
