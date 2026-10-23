import uuid

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QLabel, QLineEdit,
                               QPushButton, QMessageBox, QTabWidget, QWidget, QCheckBox)
from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from .agreement_sign_dialog import AgreementSignDialog
from .binder import AgentBinder
from ..network.auth import RegisterOutcome
from ..safety import credential
from ..utils import registration_resume
from ..utils.logger import get_logger
from ..utils.http_client import HttpClientFactory


class _RegisterSignals(QObject):
    finished = Signal(str, object)


class _RegisterTask(QRunnable):
    """在后台线程提交注册，避免阻塞界面（"正在提交…" 期间界面仍可响应）。"""

    def __init__(self, token: str, submit, signals: _RegisterSignals):
        super().__init__()
        self._token = token
        self._submit = submit
        self._signals = signals

    def run(self) -> None:  # pragma: no cover - 由线程池调用
        try:
            outcome = self._submit()
        except Exception as error:  # noqa: BLE001 - 统一转成可显示的结果
            outcome = RegisterOutcome(False, str(error))
        self._signals.finished.emit(self._token, outcome)


class LoginDialog(QDialog):
    def __init__(self, binder: AgentBinder):
        super().__init__()
        self.logger = get_logger(self.__class__.__name__)
        self.binder = binder
        self.user_id = None
        self.saved_token = None
        self.custom_base_url = None  # 自定义服务器地址
        self._thread_pool = QThreadPool.globalInstance()
        self._register_signals = _RegisterSignals()
        self._register_signals.finished.connect(self._on_register_finished)
        self._sign_dialog: AgreementSignDialog | None = None
        self._submit_context: dict | None = None
        self._active_register_token: str | None = None

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
            " QPushButton:hover { background-color: #66CCFF; }"
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
            " QPushButton:hover { background-color: #66CCFF; }"
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

        # 本地校验通过后才打开协议窗口：此时不建账号、不占用邀请码。
        pending = registration_resume.load_pending()
        if pending and pending.get("username") and pending["username"] != username:
            # spec：旧提交结果未知时应先以原提交确认，不能直接开始新请求覆盖恢复记录。
            QMessageBox.warning(
                self,
                "还有未确认的注册",
                f"上一次注册（用户名 {pending['username']}）结果尚未确认，请先用原用户名重试一次。",
            )
            return
        request_id = registration_resume.request_id_for(username)
        resume_version = ""
        if pending and pending.get("username") == username and pending.get("registration_request_id") == request_id:
            resume_version = pending.get("agreement_version", "")
        self._submit_context = {
            "username": username,
            "password": password,
            "invite": invite,
            "request_id": request_id,
            "resume_agreement_version": resume_version,
        }
        dialog = AgreementSignDialog(self, load_document=self._load_agreement)
        dialog.submit_token = uuid.uuid4().hex
        self._active_register_token = None
        dialog.set_reject_text("不同意，返回注册")
        dialog.submit_requested.connect(self._start_registration_submit)
        self._sign_dialog = dialog
        try:
            accepted = dialog.exec() == QDialog.DialogCode.Accepted
        finally:
            self._sign_dialog = None
        if not accepted:
            # 不同意只回注册表单：输入保留，不创建账号、不消耗邀请码、不退出客户端。
            return
        registration_resume.clear_pending()
        QMessageBox.information(self, "成功", "注册成功，请登录")
        self.l_username.setText(username)
        self.tabs.setCurrentIndex(0)

    def _load_agreement(self):
        """协议正文加载器；与只读窗口共用 (ok, detail, payload) 契约。"""
        fetch = getattr(self.binder, "on_fetch_agreement", None)
        if fetch is None:
            return False, "当前客户端未接线协议接口", None
        return fetch()

    def _start_registration_submit(self, agreement_version: str) -> None:
        context = self._submit_context or {}
        dialog = self._sign_dialog
        if not context or dialog is None:
            return
        # 未决请求恢复必须重放原协议版本；没有原版本时才使用当前窗口版本。
        submit_version = context.get("resume_agreement_version") or agreement_version
        registration_resume.save_pending(context["request_id"], context["username"], submit_version)
        flow_token = dialog.submit_token
        self._active_register_token = flow_token
        self._thread_pool.start(
            _RegisterTask(
                flow_token,
                lambda: self._register_with_agreement(context, submit_version),
                self._register_signals,
            )
        )
        dialog.submit_token = flow_token

    def _start_new_request_after_version_change(self) -> None:
        """协议换版后开始新请求：不再重放旧版本，也不复用旧请求 ID。

        spec：协议版本改变后开始新请求；原请求已成功时由服务端 replay 返回原结果，
        走到 AGREEMENT_CHANGED 的只可能是未成功的旧请求。
        """
        context = self._submit_context
        if not context:
            return
        context["resume_agreement_version"] = ""
        context["request_id"] = registration_resume.new_request_id()
        registration_resume.clear_pending()

    def _register_with_agreement(self, context: dict, agreement_version: str) -> RegisterOutcome:
        submit = getattr(self.binder, "on_register_with_agreement", None)
        outcome = submit(
            username=context["username"],
            password=context["password"],
            invite_code=context["invite"],
            registration_request_id=context["request_id"],
            agreement_version=agreement_version,
            accepted=True,
        ) if submit else None
        if outcome is None:
            self.logger.error("Register with agreement callback is not wired")
            return RegisterOutcome(False, "当前客户端未接线协议注册")
        return outcome

    def _on_register_finished(self, token: str, outcome) -> None:
        dialog = self._sign_dialog
        if dialog is None or token != self._active_register_token or getattr(dialog, "submit_token", "") != token:
            return
        if not isinstance(outcome, RegisterOutcome):
            outcome = RegisterOutcome(bool(outcome and outcome[0]), str(outcome[1]) if outcome else "")
        if outcome.ok:
            dialog.finish_submit(True)
            return
        if outcome.code == "AGREEMENT_CHANGED":
            # 服务端已换版：提示重读并拉取最新正文，阅读计时与"到过底部"随之重置。
            self._start_new_request_after_version_change()
            dialog.finish_submit(False, "用户协议已更新，请重新阅读")
            dialog.reload_document()
            return
        if outcome.status_code and 400 <= outcome.status_code < 500:
            # 服务端已明确拒绝（业务 4xx）：本次确定没有成功，结束未决状态，
            # 允许用户修正用户名/邀请码后直接开始新请求；只有结果未知（超时/断线）才保留记录。
            registration_resume.clear_pending()
        dialog.finish_submit(False, outcome.message)

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
