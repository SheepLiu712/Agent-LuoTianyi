from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit, 
                               QPushButton, QMessageBox, QTabWidget, QWidget, QCheckBox)
from PySide6.QtCore import Qt

from src.network_client import NetworkClient
from ..safety import credential
from ..utils.logger import get_logger


class LoginDialog(QDialog):
    def __init__(self, network_client: NetworkClient):
        super().__init__()
        self.logger = get_logger(self.__class__.__name__)
        self.network_client = network_client
        self.user_id = None
        self.saved_token = None
        
        self.setWindowTitle("ChatWithLuoTianyi - 登录/注册")
        self.setFixedSize(400, 300)
        
        layout = QVBoxLayout()
        
        self.tabs = QTabWidget()
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
            user_id, token, do_auto_login = cred
            self.l_auto_login.setChecked(do_auto_login)
            self.l_username.setText(user_id or "")
            self.saved_token = token

    def try_auto_login(self) -> bool:
        try:
            if self.l_auto_login.isChecked() and self.saved_token and self.l_username.text():
                self.logger.info("Attempting auto login...")
                if self.network_client.auto_login(self.l_username.text(), self.saved_token):
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
        layout.addWidget(self.r_invite)
        layout.addStretch()
        layout.setContentsMargins(20, 20, 20, 20)
        layout.addWidget(self.r_btn)
        self.register_tab.setLayout(layout)

    def do_login(self):
        username = self.l_username.text()
        password = self.l_password.text()
        request_token = self.l_auto_login.isChecked()
        
        if not username or not password:
            QMessageBox.warning(self, "错误", "请输入用户名和密码")
            return
            
        success, msg = self.network_client.login(username, password, request_token=request_token)
        if success:
            self.accept()
        else:
            QMessageBox.critical(self, "登录失败", msg)

    def do_register(self):
        username = self.r_username.text()
        password = self.r_password.text()
        invite = self.r_invite.text()
        
        if not username or not password or not invite:
            QMessageBox.warning(self, "错误", "请填写所有信息")
            return
            
        success, msg = self.network_client.register(username, password, invite)
        if success:
            QMessageBox.information(self, "成功", "注册成功，请登录")
            self.tabs.setCurrentIndex(0)
        else:
            QMessageBox.critical(self, "注册失败", msg)
