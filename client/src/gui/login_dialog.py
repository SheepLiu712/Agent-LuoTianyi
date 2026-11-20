import uuid
from enum import Enum

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QMessageBox,
    QTabWidget,
    QWidget,
    QCheckBox,
)
from PySide6.QtCore import Qt, QObject, QRunnable, QThreadPool, Signal

from .agreement_sign_dialog import AgreementSignDialog
from .binder import AgentBinder
from ..network.auth import RegisterOutcome
from ..safety import credential
from ..utils import registration_resume
from ..utils.logger import get_logger
from .window_operation import WindowOperation


class _RegisterSignals(QObject):
    finished = Signal(str, object)


class ExistingAgreementResult(Enum):
    LOGGED_IN = "logged_in"
    EXIT_CLIENT = "exit_client"
    RETURN_TO_LOGIN = "return_to_login"


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
            # 请求是否已被服务端接纳未知：必须保留同一 request ID 供核验，不能开新请求。
            outcome = RegisterOutcome(False, str(error), code="REGISTRATION_RESULT_UNKNOWN")
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
        # 仅保存在本进程内，用于在未知结果期间阻止用户改表单后误开新请求。
        # 密码和邀请码绝不写入 registration_resume 的跨进程记录。
        self._pending_context: dict | None = None
        self._pending_login_confirmation_username: str | None = None
        self._resuming_registration = False
        self._active_register_token: str | None = None
        self.last_existing_agreement_result: ExistingAgreementResult | None = None

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
        self._account_operation = WindowOperation(self)
        self._account_operation.completed.connect(self._account_completed)
        self._account_operation.settled.connect(self._account_settled)
        self._account_child = None
        self._account_button = None
        self._account_button_text = None
        self._account_closed = False

        self.tabs.currentChanged.connect(self.update_default_button)
        self.update_default_button(self.tabs.currentIndex())

        cred = credential.load_credentials()
        if cred:
            username, token, do_auto_login, saved_url = cred if len(cred) >= 4 else (*cred, None)
            self.l_auto_login.setChecked(do_auto_login)
            self.l_username.setText(username or "")
            self.saved_token = token
            if saved_url:
                self.custom_base_url = saved_url

    def _clear_pending_registration_best_effort(self) -> None:
        try:
            registration_resume.clear_pending()
        except OSError as error:
            self.logger.warning(f"Failed to clear pending registration: {error}")

    def _settle_pending_registration(self, username: str, server_url: str | None = None) -> None:
        pending = registration_resume.load_pending()
        if not pending:
            return
        if server_url is None:
            identity = getattr(self.binder, "on_registration_server_identity", None)
            server_url = identity() if identity else ""
        if (
            pending.get("username") == username
            and pending.get("server_url") == registration_resume.normalize_server_url(server_url)
        ):
            self._clear_pending_registration_best_effort()
            self._pending_context = None
            self._pending_login_confirmation_username = None
            self._resuming_registration = False

    def _start_account(self, action, button, child=None, **values):
        if self._account_closed or self._account_operation.busy:
            return
        try:
            request = self.binder.prepare_account_request(action, **values)
        except Exception as exc:
            QMessageBox.critical(child or self, "请求失败", str(exc))
            return
        self._account_child = child
        self._account_button = button
        self._account_button_text = button.text()
        self.tabs.setEnabled(False)
        button.setText("处理中…")
        button.setEnabled(False)
        cancelled = self._account_operation.start(request)
        if child is not None:
            child.finished.connect(lambda _result, token=cancelled: token.set())
            child.destroyed.connect(lambda _obj=None, token=cancelled: token.set())
            for field in child.findChildren(QLineEdit):
                field.setEnabled(False)

    def _account_settled(self):
        if self._account_closed:
            return
        self.tabs.setEnabled(True)
        try:
            if self._account_child is None or self._account_child.isVisible():
                self._account_button.setEnabled(True)
                self._account_button.setText(self._account_button_text)
                if self._account_child is not None:
                    for field in self._account_child.findChildren(QLineEdit):
                        field.setEnabled(True)
        except RuntimeError:
            pass  # 子窗口可能已实际删除；只恢复仍存活的父窗口。

    def _account_completed(self, request, result):
        child = self._account_child
        if self._account_closed:
            return
        try:
            if child is not None and not child.isVisible():
                return
        except RuntimeError:
            return
        if request.context != self.binder.account_context():
            return
        try:
            success, message = self.binder.apply_account_result(request, result)
        except Exception as exc:
            success, message = False, str(exc)
        if not success and request.action == "login" and result[2].get("code") == "AGREEMENT_REQUIRED":
            outcome = self._sign_existing_user(
                mode="password",
                username=request.username,
                password=request.password,
                version=result[2].get("agreement_version", ""),
            )
            self.last_existing_agreement_result = outcome
            if outcome is ExistingAgreementResult.LOGGED_IN:
                self.accept()
            elif outcome is ExistingAgreementResult.EXIT_CLIENT:
                self.reject()
            return
        if not success:
            QMessageBox.critical(child or self, "请求失败", message)
        elif request.action == "login":
            self._settle_pending_registration(request.username, request.base_url)
            self.accept()
        elif request.action == "register":
            QMessageBox.information(self, "成功", "注册成功，请登录")
            self.tabs.setCurrentIndex(0)
        elif request.action == "reset":
            QMessageBox.information(child, "成功", "账号重置成功，请使用新账号登录")
            self.l_username.setText(request.username)
            self.tabs.setCurrentIndex(0)
            child.accept()
        elif request.action == "server":
            self.custom_base_url = request.base_url
            QMessageBox.information(child, "成功", "服务器地址验证成功，地址已保存")
            child.accept()

    def done(self, result):
        self._account_closed = True
        self._account_operation.close()
        super().done(result)

    def update_default_button(self, index):
        # Qt 的默认按钮属于整个对话框，切页时只保留当前页的主动作。
        self.l_btn.setDefault(index == 0)
        self.r_btn.setDefault(index == 1)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            # 取消登录会结束客户端启动，仅显式关闭窗口才走该路径。
            event.accept()
            return
        super().keyPressEvent(event)

    def try_auto_login(self) -> bool:
        try:
            if self.l_auto_login.isChecked() and self.saved_token and self.l_username.text():
                self.logger.info("Attempting auto login...")
                detailed = getattr(self.binder, "on_auto_login_with_details", None)
                if detailed:
                    success, message, data = detailed(self.l_username.text(), self.saved_token)
                    if success:
                        self._settle_pending_registration(self.l_username.text())
                        self.logger.info("Auto login successful")
                        return True
                    if data.get("code") == "AGREEMENT_REQUIRED":
                        result = self._sign_existing_user(
                            mode="auto_login",
                            username=self.l_username.text(),
                            token=self.saved_token,
                            version=data.get("agreement_version", ""),
                        )
                        self.last_existing_agreement_result = result
                        if result is ExistingAgreementResult.EXIT_CLIENT:
                            return False
                        if result is ExistingAgreementResult.LOGGED_IN:
                            return True
                        if result is ExistingAgreementResult.RETURN_TO_LOGIN:
                            return False
                        ret = False
                    ret = False
                else:
                    ret = self.binder.on_auto_login(self.l_username.text(), self.saved_token)
                if ret:
                    self._settle_pending_registration(self.l_username.text())
                    self.logger.info("Auto login successful")
                    return True
                else:
                    self.logger.info("Auto login failed")
                    # AGREEMENT_REQUIRED is an authenticated-but-not-yet-signed state;
                    # its valid token must remain available for the signing flow.
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
        self.l_btn.setAutoDefault(False)
        self.l_btn.clicked.connect(self.do_login)
        self.l_btn.setStyleSheet(
            "QPushButton { font-size: 16px; padding: 5px;"
            " background-color: #44BBEE; color: white; border-radius: 5px; }"
            " QPushButton:hover { background-color: #66CCFF; }"
        )

        self.reset_btn = QPushButton("重置账号")
        self.reset_btn.setAutoDefault(False)
        self.reset_btn.setStyleSheet(
            "QPushButton { font-size: 16px; padding: 4px; color: #4488BB;"
            " border: none; text-align: left; }"
            " QPushButton:hover { color: #77BBEE; }"
        )
        self.reset_btn.clicked.connect(self.open_reset_account_dialog)

        self.server_btn = QPushButton("服务器地址")
        self.server_btn.setAutoDefault(False)
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
        self.r_btn.setAutoDefault(False)
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
        if self._account_operation.busy:
            return
        username = self.l_username.text()
        password = self.l_password.text()
        do_auto_login = self.l_auto_login.isChecked()

        if not username or not password:
            QMessageBox.warning(self, "错误", "请输入用户名和密码")
            return

        self._start_account("login", self.l_btn, username=username, password=password, remember=do_auto_login)

    def _sign_existing_user(
        self,
        *,
        mode: str,
        username: str,
        version: str,
        password: str | None = None,
        token: str | None = None,
    ) -> ExistingAgreementResult:
        """Complete the old-user flow: sign, then issue a separate login request."""
        if not version:
            QMessageBox.critical(self, "登录失败", "服务器未返回协议版本")
            return ExistingAgreementResult.RETURN_TO_LOGIN
        dialog = AgreementSignDialog(self, load_document=self._load_agreement)
        dialog.set_reject_text("不同意并退出")
        result = {"ok": False, "submitting": False}

        def submit(agreement_version: str) -> None:
            if result["submitting"]:
                return
            result["submitting"] = True
            try:
                accepted, message, details = self.binder.on_accept_agreement(
                    username,
                    agreement_version,
                    password=password if mode == "password" else None,
                    token=token if mode == "auto_login" else None,
                )
            except Exception as error:  # noqa: BLE001 - keep the modal retryable
                result["submitting"] = False
                result.pop("terminal", None)
                dialog.finish_submit(False, str(error) or "网络错误，请重试")
                return
            if accepted:
                try:
                    if mode == "password":
                        logged_in, login_message, login_details = self.binder.on_login_with_details(
                            username, password or "", self.l_auto_login.isChecked()
                        )
                    else:
                        logged_in, login_message, login_details = self.binder.on_auto_login_with_details(
                            username, token or ""
                        )
                except Exception as error:  # noqa: BLE001 - keep the modal retryable
                    logged_in, login_message, login_details = (
                        False,
                        str(error) or "网络错误，请重试",
                        {},
                    )
                login_details = login_details if isinstance(login_details, dict) else {}
                login_code = login_details.get("code")
                if not logged_in and login_code in {
                    "AGREEMENT_REQUIRED",
                    "AGREEMENT_CHANGED",
                }:
                    result["submitting"] = False
                    result.pop("terminal", None)
                    dialog.finish_submit(False, login_message or "用户协议已更新，请重新阅读")
                    dialog.reload_document()
                    return
                result["ok"] = bool(logged_in)
                result["submitting"] = False
                if logged_in:
                    result.pop("terminal", None)
                    dialog.finish_submit(True)
                    return
                if login_details.get("status_code") == 401:
                    if mode == "auto_login":
                        self.saved_token = None
                        self.l_auto_login.setChecked(False)
                        credential.save_credentials(username, None, False)
                    result["terminal"] = ExistingAgreementResult.RETURN_TO_LOGIN
                    dialog.finish_submit(False, login_message or "登录失败，请重试", close=True)
                    return
                # 429/5xx/network failures remain retryable and must not poison a later reject.
                result.pop("terminal", None)
                dialog.finish_submit(False, login_message or "网络错误，请重试")
                return
            elif details.get("code") == "AGREEMENT_CHANGED":
                result["submitting"] = False
                result.pop("terminal", None)
                dialog.finish_submit(False, "用户协议已更新，请重新阅读")
                dialog.reload_document()
            elif details.get("status_code") == 401:
                result["submitting"] = False
                if mode == "auto_login":
                    self.saved_token = None
                    self.l_auto_login.setChecked(False)
                    credential.save_credentials(username, None, False)
                result["terminal"] = ExistingAgreementResult.RETURN_TO_LOGIN
                dialog.finish_submit(False, message, close=True)
            else:
                result["submitting"] = False
                result.pop("terminal", None)
                dialog.finish_submit(False, message)

        dialog.submit_requested.connect(submit)
        accepted = dialog.exec() == QDialog.DialogCode.Accepted
        if accepted and result["ok"]:
            self._settle_pending_registration(username)
            return ExistingAgreementResult.LOGGED_IN
        if result.get("terminal") is ExistingAgreementResult.RETURN_TO_LOGIN:
            return ExistingAgreementResult.RETURN_TO_LOGIN
        return ExistingAgreementResult.EXIT_CLIENT

    def do_register(self):
        if self._account_operation.busy:
            return
        username = self.r_username.text()
        password = self.r_password.text()
        confirm_password = self.r_confirm_password.text()
        invite = self.r_invite.text().strip()

        if not username or not password or not confirm_password or not invite:
            QMessageBox.warning(self, "错误", "请填写所有信息")
            return

        if password != confirm_password:
            QMessageBox.warning(self, "错误", "两次输入的密码不一致")
            return

        # 本地校验通过后才打开协议窗口：此时不建账号、不占用邀请码。
        pending = registration_resume.load_pending()
        identity = getattr(self.binder, "on_registration_server_identity", None)
        server_url = registration_resume.normalize_server_url(identity() if identity else "")
        if pending and not pending.get("server_url"):
            QMessageBox.warning(
                self,
                "注册结果待确认",
                "待确认的注册请求缺少服务器身份，请先在原服务器上核验，不能自动重试。",
            )
            return
        if pending and pending.get("server_url") != server_url:
            QMessageBox.warning(
                self,
                "注册结果待确认",
                "待确认的注册请求属于另一台服务器，请切回原服务器核验后再继续。",
            )
            return
        if pending and pending.get("username") != username:
            QMessageBox.warning(
                self,
                "注册结果待确认",
                "上一次注册结果尚未确认，请先使用原用户名、密码和邀请码重试；确认后才能修改注册信息。",
            )
            return

        if self._pending_context and any(
            self._pending_context.get(key) != value
            for key, value in {
                "username": username,
                "password": password,
                "invite": invite,
            }.items()
        ):
            QMessageBox.warning(
                self,
                "注册结果待确认",
                "上一次注册结果尚未确认，请先用原注册信息重试；不能在结果未知时新建请求。",
            )
            return

        request_id = registration_resume.request_id_for(username, resume_pending=bool(pending))
        resume_version = ""
        if pending and pending.get("username") == username and pending.get("registration_request_id") == request_id:
            resume_version = pending.get("agreement_version", "")
        # N12：恢复是在确认上一次未成功的提交，必须让用户知道要用原账号信息，而不是新建注册。
        self._resuming_registration = bool(resume_version)
        if self._resuming_registration:
            QMessageBox.information(
                self,
                "继续上次注册",
                "上次注册结果尚未确认，需要再次提交确认。\n"
                "请使用上次注册时的用户名和密码；如果提示无法确认，请用原账号登录。",
            )
        self._submit_context = {
            "username": username,
            "password": password,
            "invite": invite,
            "request_id": request_id,
            "resume_agreement_version": resume_version,
            "resumed_from_disk": bool(pending),
            "server_url": server_url,
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
            dialog.deleteLater()
        if not accepted:
            # 不同意只回注册表单：输入保留，不创建账号、不消耗邀请码、不退出客户端。
            return
        self._clear_pending_registration_best_effort()
        if self._resuming_registration:
            # N12：恢复成功对应的是原账号，不是这次输入的新内容。
            QMessageBox.information(self, "成功", "已确认上次注册成功，请使用原账号登录")
        else:
            QMessageBox.information(self, "成功", "注册成功，请登录")
        self.l_username.setText(username)
        self.tabs.setCurrentIndex(0)

    def _load_agreement(self):
        """协议正文加载器；与只读窗口共用 (ok, detail, payload) 契约。"""
        fetch = getattr(self.binder, "on_fetch_agreement", None)
        if fetch is None:
            return False, "协议加载功能暂时不可用", None
        return fetch()

    def _start_registration_submit(self, agreement_version: str) -> None:
        context = self._submit_context or {}
        dialog = self._sign_dialog
        if not context or dialog is None:
            return
        # 未决请求恢复必须重放原协议版本；没有原版本时才使用当前窗口版本。
        submit_version = context.get("resume_agreement_version") or agreement_version
        registration_resume.save_pending(
            context["request_id"],
            context["username"],
            submit_version,
            context.get("server_url", ""),
        )
        if not context.get("resumed_from_disk", False):
            self._pending_context = {
                **context,
                "resume_agreement_version": submit_version,
            }
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

    def _register_with_agreement(self, context: dict, agreement_version: str) -> RegisterOutcome:
        submit = getattr(self.binder, "on_register_with_agreement", None)
        outcome = (
            submit(
                username=context["username"],
                password=context["password"],
                invite_code=context["invite"],
                registration_request_id=context["request_id"],
                agreement_version=agreement_version,
                accepted=True,
            )
            if submit
            else None
        )
        if outcome is None:
            self.logger.error("Register with agreement callback is not wired")
            return RegisterOutcome(
                False,
                "当前客户端未接线协议注册，未发送请求",
                code="REGISTRATION_NOT_SENT",
            )
        return outcome

    def _on_register_finished(self, token: str, outcome: RegisterOutcome) -> None:
        dialog = self._sign_dialog
        if dialog is None or token != self._active_register_token or getattr(dialog, "submit_token", "") != token:
            return
        if not isinstance(outcome, RegisterOutcome):
            outcome = RegisterOutcome(bool(outcome and outcome[0]), str(outcome[1]) if outcome else "")
        if outcome.ok:
            self._pending_context = None
            dialog.finish_submit(True)
            return
        if outcome.code == "AGREEMENT_CHANGED":
            # 服务端已换版：提示重读并拉取最新正文，阅读计时与"到过底部"随之重置。
            self._resuming_registration = False
            # 这是已确认的无副作用结果，旧 V1 请求不再作为新版本提交使用。
            registration_resume.clear_pending()
            context = self._submit_context
            if context is not None:
                context["request_id"] = registration_resume.new_request_id()
                context["resume_agreement_version"] = ""
                context["resumed_from_disk"] = False
            self._pending_context = None
            dialog.finish_submit(False, "用户协议已更新，请重新阅读")
            dialog.reload_document()
            return
        if outcome.code == "REGISTRATION_REQUEST_CONFLICT":
            # 冲突意味着该 ID 已绑定另一组原提交内容；只提供明确放弃入口，默认保留。
            dialog.finish_submit(
                False,
                outcome.message or "注册请求不一致，请用原用户名、密码和邀请码核验；不会创建新请求",
            )
            self._offer_conflict_discard(dialog, self._submit_context or {})
            return
        if outcome.code == "REGISTRATION_REQUEST_UNVERIFIABLE":
            self._pending_login_confirmation_username = (self._submit_context or {}).get("username")
            context = self._submit_context or {}
            registration_resume.save_pending(
                context.get("request_id", ""),
                context.get("username", ""),
                context.get("resume_agreement_version", ""),
                context.get("server_url", ""),
                confirmation_required="same_user_login",
            )
            message = "原注册结果无法核验，请使用同一用户名和密码登录确认。"
            dialog.finish_submit(False, message, close=True)
            self.l_username.setText(str(context.get("username", "")))
            self.tabs.setCurrentIndex(0)
            QMessageBox.information(self, "请先登录确认", message)
            return
        if outcome.code == "REGISTRATION_RESULT_UNKNOWN":
            # 网络异常不代表服务端未接纳：保留同一 ID，要求用户用原信息核验。
            dialog.finish_submit(
                False,
                "注册结果未知，请使用原用户名、密码和邀请码重试确认；确认前不能修改注册信息。",
            )
            return
        if outcome.code == "REGISTRATION_NOT_SENT":
            context = self._submit_context or {}
            if not context.get("resumed_from_disk", False):
                registration_resume.clear_pending()
                self._pending_context = None
            dialog.finish_submit(False, outcome.message or "注册请求尚未发送，请重试")
            return
        known_no_side_effect = {
            (400, ""),  # 服务端普通邀请码/用户名校验失败
            (403, "AGREEMENT_REQUIRED"),
            (422, "INVALID_AGREEMENT_INPUT"),
        }
        if (outcome.status_code, outcome.code) in known_no_side_effect:
            # 仅释放服务端明确映射为注册事务前失败的结果。
            # 未知 code、409、429、5xx 及不可核验结果必须保留原 ID。
            registration_resume.clear_pending()
            self._pending_context = None
            self._resuming_registration = False
            dialog.finish_submit(False, outcome.message, close=True)
            QMessageBox.critical(self, "注册失败", outcome.message)
            return
        dialog.finish_submit(False, outcome.message)

    def _offer_conflict_discard(self, dialog, context: dict) -> None:
        """Only a real request conflict may offer local recovery abandonment."""
        request_id = context.get("request_id", "")
        if not request_id:
            return
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Warning)
        box.setWindowTitle("确认放弃本地恢复")
        box.setText("该注册请求与服务端记录不一致。")
        box.setInformativeText(
            "建议先核验原用户名、密码和邀请码，或先登录确认。\n"
            "清除本地记录不代表旧注册失败，不会撤销已创建账号，也不会退还邀请码。\n"
            "确认放弃后，本次窗口将关闭；下次注册需重新阅读协议。"
        )
        keep_button = box.addButton("保留记录，稍后核验", QMessageBox.ButtonRole.RejectRole)
        discard_button = box.addButton("确认放弃本地恢复", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep_button)
        box.exec()
        if box.clickedButton() is not discard_button:
            return
        pending = registration_resume.load_pending()
        if not pending or pending.get("registration_request_id") != request_id:
            return
        registration_resume.clear_pending()
        self._pending_context = None
        self._submit_context = None
        dialog.reject()
        self.tabs.setCurrentIndex(1)

    def open_reset_account_dialog(self):
        """打开重置账号对话框"""
        if self._account_operation.busy:
            return
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
            if self._account_operation.busy:
                return
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

            self._start_account("reset", btn, child=dialog, username=new_username, password=new_password, invite=invite)

        btn.clicked.connect(do_reset)
        dialog.exec()

    def open_server_settings_dialog(self):
        """打开服务器地址设置对话框"""
        if self._account_operation.busy:
            return
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
            if self._account_operation.busy:
                return
            url = url_input.text().strip().rstrip("/")
            if not url:
                QMessageBox.warning(dialog, "错误", "请输入服务器地址")
                return

            # 自动补全协议头
            if not url.startswith("http://") and not url.startswith("https://"):
                url = "https://" + url

            self._start_account("server", btn, child=dialog, server_url=url)

        btn.clicked.connect(do_verify)
        dialog.exec()
