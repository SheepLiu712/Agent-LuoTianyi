"""登录窗口的注册流程：校验→协议门禁→异步提交→成功回登录页并预填用户名。"""

from types import SimpleNamespace
from time import monotonic

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Signal
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from src.gui import login_dialog as login_module  # noqa: E402
from src.gui.agreement_sign_dialog import AgreementSignDialog  # noqa: E402
from src.gui.login_dialog import LoginDialog  # noqa: E402
from src.network.auth import RegisterOutcome  # noqa: E402
from src.utils import registration_resume  # noqa: E402

AGREEMENT = {
    "version": "terms-2026-10-v1",
    "title": "用户协议",
    "format": "agreement.richtext.v1",
    "blocks": [{"font_size": 16, "align": "justify", "runs": [{"text": "正文", "bold": False}]}],
}


class FakeSignDialog(QDialog):
    """替身：保留真实信号契约，但 exec() 立即返回以便测试不阻塞。"""

    submit_requested = Signal(str)
    next_result = QDialog.DialogCode.Accepted
    last_instance: "FakeSignDialog | None" = None

    def __init__(self, parent=None, *, load_document=None, **kwargs):
        super().__init__(parent)
        self.load_document = load_document
        self.reject_text = None
        self.reloads = 0
        self.submissions: list[tuple] = []
        self.submit_token = "fake-token"
        FakeSignDialog.last_instance = self

    def set_reject_text(self, text: str) -> None:
        self.reject_text = text

    def exec(self) -> int:
        return FakeSignDialog.next_result

    def deleteLater(self):
        # This fake exits exec immediately; retain it until parent teardown for simulated responses.
        pass

    def finish_submit(self, success: bool, message: str = "", *, close=False) -> None:
        self.submissions.append((success, message))
        if close:
            self.reject()

    def reload_document(self) -> bool:
        self.reloads += 1
        return True


class FakeBinder:
    def __init__(
        self,
        outcome=None,
        agreement=(True, "", AGREEMENT),
        login_result=(False, "登录失败"),
        auto_login_result=False,
    ):
        self.outcome = outcome
        self.agreement = agreement
        self.login_result = login_result
        self.auto_login_result = auto_login_result
        self.login_calls: list[tuple] = []
        self.auto_login_calls: list[tuple] = []
        self.calls: list[dict] = []
        self.server_url = "https://example.invalid"
        self.detail_login_result = None
        self.agreement_result = (False, "协议签署失败", {})
        self.detail_login_calls = 0

    def account_context(self):
        return (self.server_url,)

    def prepare_account_request(self, action, **values):
        return SimpleNamespace(
            context=self.account_context(),
            action=action,
            base_url=self.server_url,
            **values,
            execute=lambda _cancelled: (
                (False, "请签署协议", {"code": "AGREEMENT_REQUIRED"})
                if action == "register"
                else self.on_login_with_details(values["username"], values["password"], values.get("remember", False))
            ),
        )

    def apply_account_result(self, request, result):
        return result[:2]

    def on_registration_server_identity(self):
        return self.server_url

    def on_login_with_details(self, username, password, do_auto_login=False):
        self.detail_login_calls += 1
        if self.detail_login_result is None:
            return self.login_result[0], self.login_result[1], {}
        if self.detail_login_calls > 1:
            return True, "登录成功", {"user_id": username}
        return self.detail_login_result

    def on_auto_login_with_details(self, username, token):
        self.auto_login_calls.append((username, token))
        return self.detail_login_result or (self.auto_login_result, "登录结果", {})

    def on_accept_agreement(self, username, version, **kwargs):
        self.agreement_call = (username, version, kwargs)
        return self.agreement_result

    def on_fetch_agreement(self):
        return self.agreement

    def on_register_with_agreement(self, **kwargs):
        self.calls.append(kwargs)
        return self.outcome

    def on_login(self, username, password, do_auto_login=False):
        self.login_calls.append((username, password, do_auto_login))
        return self.login_result

    def on_auto_login(self, username, token):
        self.auto_login_calls.append((username, token))
        return self.auto_login_result


@pytest.fixture(scope="module")
def app():
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def messages(monkeypatch):
    recorded = SimpleNamespace(warnings=[], errors=[], infos=[])

    class FakeMessageBox:
        class Icon:
            Warning = object()

        class ButtonRole:
            RejectRole = object()
            DestructiveRole = object()

        def __init__(self, *args, **kwargs):
            self._buttons = [object(), object()]
            self._next_button = 0

        def setIcon(self, *_args):
            pass

        def setWindowTitle(self, *_args):
            pass

        def setText(self, *_args):
            pass

        def setInformativeText(self, *_args):
            pass

        def addButton(self, *_args):
            button = self._buttons[self._next_button]
            self._next_button += 1
            return button

        def setDefaultButton(self, *_args):
            pass

        def buttons(self):
            return self._buttons

        def exec(self):
            return None

        def clickedButton(self):
            return None

        @staticmethod
        def warning(*args):
            recorded.warnings.append(args[1:])

        @staticmethod
        def critical(*args):
            recorded.errors.append(args[1:])

        @staticmethod
        def information(*args):
            recorded.infos.append(args[1:])

    monkeypatch.setattr(login_module, "QMessageBox", FakeMessageBox)
    return recorded


@pytest.fixture
def dialog(app, monkeypatch, tmp_path, messages):
    monkeypatch.setattr(login_module, "AgreementSignDialog", FakeSignDialog)
    monkeypatch.setattr(login_module.credential, "load_credentials", lambda: None)
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))
    FakeSignDialog.last_instance = None
    FakeSignDialog.next_result = QDialog.DialogCode.Accepted
    binder = FakeBinder(outcome=RegisterOutcome(True, "Registration Successful"))
    widget = LoginDialog(binder)
    widget.fill_register_form = lambda username="newbie", password="pw", invite="INVITE": (
        widget.r_username.setText(username),
        widget.r_password.setText(password),
        widget.r_confirm_password.setText(password),
        widget.r_invite.setText(invite),
    )
    yield SimpleNamespace(widget=widget, binder=binder, messages=messages)
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_invalid_form_does_not_open_agreement(dialog):
    dialog.widget.r_username.setText("")
    register_and_wait(dialog.widget)

    assert FakeSignDialog.last_instance is None
    assert dialog.messages.warnings


def test_mismatched_passwords_do_not_open_agreement(dialog):
    dialog.widget.fill_register_form(password="pw")
    dialog.widget.r_confirm_password.setText("other")
    register_and_wait(dialog.widget)

    assert FakeSignDialog.last_instance is None
    assert dialog.messages.warnings


def test_reject_returns_to_form_and_keeps_input(dialog):
    FakeSignDialog.next_result = QDialog.DialogCode.Rejected
    dialog.widget.fill_register_form()
    dialog.widget.tabs.setCurrentIndex(1)  # 用户在注册页点了"注册"

    register_and_wait(dialog.widget)

    sign = FakeSignDialog.last_instance
    assert sign is not None
    assert sign.reject_text == "不同意，返回注册"
    assert dialog.binder.calls == []
    assert dialog.widget.r_username.text() == "newbie"
    assert dialog.widget.tabs.currentIndex() == 1  # 不同意只回原注册页，不跳到登录页、不退出客户端
    assert registration_resume.load_pending() is None


def test_success_returns_to_login_tab_with_prefilled_username(dialog):
    dialog.widget.fill_register_form()
    registration_resume.save_pending("req-1", "newbie", server_url="https://example.invalid")

    register_and_wait(dialog.widget)

    assert dialog.widget.l_username.text() == "newbie"
    assert dialog.widget.tabs.currentIndex() == 0
    assert dialog.messages.infos
    assert registration_resume.load_pending() is None  # 成功后才清除恢复记录


def test_submit_sends_request_id_version_and_acceptance(dialog):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)

    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    # 线程池任务同步执行：直接调用提交函数更便于断言参数
    outcome = dialog.widget._register_with_agreement(dialog.widget._submit_context, "terms-2026-10-v1")

    assert outcome.ok is True
    assert dialog.binder.calls[0] == {
        "username": "newbie",
        "password": "pw",
        "invite_code": "INVITE",
        "registration_request_id": dialog.widget._submit_context["request_id"],
        "agreement_version": "terms-2026-10-v1",
        "accepted": True,
    }
    assert registration_resume.load_pending() is not None  # 提交前先落盘请求 ID，供响应丢失后重试


def test_resume_submission_reuses_original_agreement_version(dialog):
    registration_resume.save_pending("req-old", "newbie", "terms-v1", "https://example.invalid")
    sign = FakeSignDialog()
    dialog.widget._sign_dialog = sign
    dialog.widget._submit_context = {
        "username": "newbie",
        "password": "pw",
        "invite": "INVITE",
        "request_id": "req-old",
        "resume_agreement_version": "terms-v1",
    }

    dialog.widget._start_registration_submit("terms-v2")

    assert registration_resume.load_pending()["agreement_version"] == "terms-v1"


def test_same_username_changed_password_or_invite_cannot_open_new_request(dialog):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    first_id = dialog.widget._submit_context["request_id"]
    dialog.widget._sign_dialog = FakeSignDialog()
    dialog.widget._start_registration_submit("terms-2026-10-v1")

    dialog.widget.r_password.setText("changed")
    dialog.widget.r_confirm_password.setText("changed")
    dialog.widget.r_invite.setText("OTHER")
    register_and_wait(dialog.widget)

    assert dialog.widget._submit_context["request_id"] == first_id
    assert registration_resume.load_pending()["registration_request_id"] == first_id
    assert dialog.messages.warnings


def test_version_change_clears_known_old_request_and_prepares_new_id(dialog):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    old_id = dialog.widget._submit_context["request_id"]

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(
            False,
            "用户协议已更新，请重新阅读",
            code="AGREEMENT_CHANGED",
            agreement_version="v2",
        ),
    )

    assert registration_resume.load_pending() is None
    assert dialog.widget._submit_context["request_id"] != old_id
    assert dialog.widget._submit_context["resume_agreement_version"] == ""
    assert dialog.widget._submit_context["resumed_from_disk"] is False


def test_unknown_result_keeps_pending_request_and_does_not_clear_identity(dialog):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    request_id = dialog.widget._submit_context["request_id"]

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "网络结果未知", code="REGISTRATION_RESULT_UNKNOWN"),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert sign.submissions == [
        (
            False,
            "注册结果未知，请使用原用户名、密码和邀请码重试确认；确认前不能修改注册信息。",
        )
    ]


@pytest.mark.parametrize(
    "status_code, code",
    [
        (409, ""),
        (409, "REGISTRATION_RESULT_UNVERIFIABLE"),
        (429, "RATE_LIMITED"),
        (503, "SERVICE_UNAVAILABLE"),
    ],
)
def test_unconfirmed_outcomes_keep_pending_request(dialog, status_code, code):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    request_id = dialog.widget._submit_context["request_id"]

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "结果尚未确认", code=code, status_code=status_code),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id


@pytest.mark.parametrize(
    "status_code, code",
    [
        (400, "UNKNOWN_400"),
        (403, "UNKNOWN_403"),
        (409, "REGISTRATION_REQUEST_UNVERIFIABLE"),
    ],
)
def test_unknown_or_unverifiable_codes_keep_pending_request(dialog, status_code, code):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    request_id = dialog.widget._submit_context["request_id"]

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "结果尚未确认", code=code, status_code=status_code),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id


def test_cross_restart_recovery_can_correct_credentials_without_new_request_id(dialog):
    registration_resume.save_pending("req-recover", "newbie", "terms-v1", "https://example.invalid")
    dialog.widget._submit_context = {
        "username": "newbie",
        "password": "wrong",
        "invite": "INVITE",
        "request_id": "req-recover",
        "resume_agreement_version": "terms-v1",
        "resumed_from_disk": True,
        "server_url": "https://example.invalid",
    }
    dialog.widget._sign_dialog = FakeSignDialog()

    # 磁盘恢复的上下文不应被当成本进程已知原始凭据；可继续使用同一 ID 核验。
    assert dialog.widget._pending_context is None
    assert dialog.widget._submit_context["request_id"] == "req-recover"
    assert dialog.widget._submit_context["resumed_from_disk"] is True

    FakeSignDialog.next_result = QDialog.DialogCode.Accepted
    dialog.widget._start_registration_submit("terms-v2")
    dialog.widget._register_with_agreement(dialog.widget._submit_context, "terms-v1")
    assert dialog.binder.calls[-1]["password"] == "wrong"
    assert dialog.binder.calls[-1]["invite_code"] == "INVITE"
    dialog.widget._active_register_token = dialog.widget._sign_dialog.submit_token
    dialog.widget._on_register_finished(
        dialog.widget._sign_dialog.submit_token,
        RegisterOutcome(
            False,
            "原注册结果无法核验",
            code="REGISTRATION_REQUEST_UNVERIFIABLE",
            status_code=409,
        ),
    )

    dialog.widget.r_password.setText("corrected")
    dialog.widget.r_confirm_password.setText("corrected")
    dialog.widget.r_invite.setText("NEW-INVITE")
    dialog.widget._submit_context.update(password="corrected", invite="NEW-INVITE", resumed_from_disk=True)
    dialog.widget._register_with_agreement(dialog.widget._submit_context, "terms-v1")
    assert dialog.widget._submit_context["request_id"] == "req-recover"
    assert dialog.binder.calls[-1]["password"] == "corrected"
    assert dialog.binder.calls[-1]["invite_code"] == "NEW-INVITE"
    assert registration_resume.load_pending()["registration_request_id"] == "req-recover"


def test_not_sent_fresh_request_releases_pending_but_recovered_request_stays(dialog):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    request_id = dialog.widget._submit_context["request_id"]
    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(
            False,
            "无法发送注册请求，请检查服务器连接后重试",
            code="REGISTRATION_NOT_SENT",
        ),
    )
    assert registration_resume.load_pending() is None

    registration_resume.save_pending("req-recovered", "newbie", "terms-v1", "https://example.invalid")
    dialog.widget._submit_context = {
        "username": "newbie",
        "password": "pw",
        "invite": "INVITE",
        "request_id": "req-recovered",
        "resume_agreement_version": "terms-v1",
        "resumed_from_disk": True,
        "server_url": "https://example.invalid",
    }
    dialog.widget._sign_dialog = FakeSignDialog()
    dialog.widget._active_register_token = dialog.widget._sign_dialog.submit_token
    dialog.widget._on_register_finished(
        dialog.widget._sign_dialog.submit_token,
        RegisterOutcome(
            False,
            "无法发送注册请求，请检查服务器连接后重试",
            code="REGISTRATION_NOT_SENT",
        ),
    )
    assert registration_resume.load_pending()["registration_request_id"] == "req-recovered"
    assert request_id != "req-recovered"


def test_unverifiable_can_be_cleared_only_by_successful_same_username_login(dialog):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(
            False,
            "原注册结果无法核验",
            code="REGISTRATION_REQUEST_UNVERIFIABLE",
            status_code=409,
        ),
    )
    request_id = registration_resume.load_pending()["registration_request_id"]
    assert registration_resume.load_pending()["confirmation_required"] == "same_user_login"
    assert "同一用户名和密码登录确认" in sign.submissions[-1][1]

    dialog.widget.l_username.setText("other")
    dialog.widget.l_password.setText("pw")
    login_and_wait(dialog.widget)
    assert registration_resume.load_pending()["registration_request_id"] == request_id

    dialog.binder.login_result = (False, "登录失败")
    dialog.widget.l_username.setText("newbie")
    dialog.widget.l_password.setText("wrong")
    login_and_wait(dialog.widget)
    assert registration_resume.load_pending()["registration_request_id"] == request_id

    dialog.binder.login_result = (True, "登录成功")
    dialog.widget.l_username.setText("newbie")
    dialog.widget.l_password.setText("pw")
    login_and_wait(dialog.widget)
    assert registration_resume.load_pending() is None


def test_pending_request_cannot_be_replayed_after_server_switch(dialog):
    registration_resume.save_pending("req-server", "newbie", "terms-v1", "https://original.example")
    dialog.widget.fill_register_form()
    dialog.binder.server_url = "https://other.example"
    register_and_wait(dialog.widget)

    assert FakeSignDialog.last_instance is None
    assert registration_resume.load_pending()["registration_request_id"] == "req-server"


def test_unverifiable_confirmation_survives_recreated_dialog(dialog):
    registration_resume.save_pending(
        "req-restart",
        "newbie",
        "terms-v1",
        "https://example.invalid",
        confirmation_required="same_user_login",
    )
    dialog.binder.login_result = (True, "登录成功")
    dialog.binder.detail_login_result = (True, "登录成功", {"user_id": "newbie"})
    dialog.widget.l_username.setText("newbie")
    dialog.widget.l_password.setText("pw")
    login_and_wait(dialog.widget)
    assert registration_resume.load_pending() is None


@pytest.mark.parametrize(
    "username, server_url, login_result",
    [
        ("other", "https://example.invalid", (True, "登录成功")),
        ("newbie", "https://other.example", (True, "登录成功")),
        ("newbie", "https://example.invalid", (False, "登录失败")),
    ],
)
def test_unverifiable_confirmation_rejects_wrong_user_server_or_failed_login(
    dialog, username, server_url, login_result
):
    registration_resume.save_pending(
        "req-keep",
        "newbie",
        "terms-v1",
        "https://example.invalid",
        confirmation_required="same_user_login",
    )
    dialog.binder.server_url = server_url
    dialog.binder.login_result = login_result
    dialog.widget.l_username.setText(username)
    dialog.widget.l_password.setText("pw")
    login_and_wait(dialog.widget)
    assert registration_resume.load_pending()["registration_request_id"] == "req-keep"


def test_unverifiable_login_on_other_server_does_not_clear_pending(dialog):
    registration_resume.save_pending("req-other-server", "newbie", "terms-v1", "https://original.example")
    dialog.widget._pending_login_confirmation_username = "newbie"
    dialog.binder.server_url = "https://other.example"
    dialog.binder.login_result = (True, "登录成功")
    dialog.widget.l_username.setText("newbie")
    dialog.widget.l_password.setText("pw")
    login_and_wait(dialog.widget)

    assert registration_resume.load_pending()["registration_request_id"] == "req-other-server"


def test_password_agreement_required_signs_then_logs_in_separately(dialog, monkeypatch):
    dialog.binder.detail_login_result = (
        False,
        "请升级到支持用户协议签署的版本，阅读并同意用户协议后再登录。",
        {"code": "AGREEMENT_REQUIRED", "agreement_version": "terms-v1"},
    )
    dialog.binder.agreement_result = (
        True,
        "协议签署成功",
        {"agreement_version": "terms-v1", "accepted_at": "2026-10-10T00:00:00+08:00"},
    )
    monkeypatch.setattr(
        login_module.AgreementSignDialog,
        "exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    # The real dialog is replaced with a small deterministic test double below.
    submitted = []

    class Sign:
        def __init__(self, *args, **kwargs):
            self.submit_requested = SimpleNamespace(connect=lambda callback: submitted.append(callback))

        def set_reject_text(self, text):
            self.reject_text = text

        def exec(self):
            submitted[0]("terms-v1")
            return QDialog.DialogCode.Accepted

        def finish_submit(self, success, message=""):
            self.finished = (success, message)

    monkeypatch.setattr(login_module, "AgreementSignDialog", Sign)
    dialog.widget.l_username.setText("newbie")
    dialog.widget.l_password.setText("pw")
    login_and_wait(dialog.widget)

    assert dialog.binder.agreement_call[2] == {"password": "pw", "token": None}
    assert dialog.binder.detail_login_result[2]["code"] == "AGREEMENT_REQUIRED"


def test_existing_user_signing_login_failure_releases_submit_for_retry(dialog, monkeypatch):
    dialog.binder.agreement_result = (True, "协议签署成功", {})
    dialog.binder.detail_login_result = (False, "登录失败", {})
    callbacks = []

    class Sign:
        def __init__(self, *args, **kwargs):
            self.submit_requested = SimpleNamespace(connect=callbacks.append)
            self.finished = []

        def set_reject_text(self, text):
            self.reject_text = text

        def exec(self):
            callbacks[0]("terms-v1")
            return QDialog.DialogCode.Rejected

        def finish_submit(self, success, message=""):
            self.finished.append((success, message))

    monkeypatch.setattr(login_module, "AgreementSignDialog", Sign)
    assert (
        dialog.widget._sign_existing_user(mode="password", username="newbie", password="pw", version="terms-v1")
        is login_module.ExistingAgreementResult.EXIT_CLIENT
    )
    assert dialog.binder.detail_login_calls == 1
    assert callbacks


@pytest.mark.parametrize(
    "login_details, expected, should_reload",
    [
        (
            (
                False,
                "用户协议已更新，请重新阅读",
                {"code": "AGREEMENT_CHANGED", "agreement_version": "v2"},
            ),
            login_module.ExistingAgreementResult.EXIT_CLIENT,
            True,
        ),
        (
            (False, "身份验证失败", {"status_code": 401}),
            login_module.ExistingAgreementResult.RETURN_TO_LOGIN,
            False,
        ),
        (
            (False, "请求过于频繁", {"status_code": 429}),
            login_module.ExistingAgreementResult.EXIT_CLIENT,
            False,
        ),
    ],
)
def test_post_sign_in_error_routes_and_later_reject_exits(dialog, monkeypatch, login_details, expected, should_reload):
    dialog.binder.agreement_result = (True, "协议签署成功", {})
    dialog.binder.detail_login_result = login_details
    callbacks = []

    class Sign:
        last = None

        def __init__(self, *args, **kwargs):
            self.submit_requested = SimpleNamespace(connect=callbacks.append)
            self.reloads = 0
            Sign.last = self

        def set_reject_text(self, text):
            self.reject_text = text

        def exec(self):
            callbacks[0]("terms-v1")
            return QDialog.DialogCode.Rejected

        def finish_submit(self, success, message="", **kwargs):
            self.finished = (success, message, kwargs)

        def reload_document(self):
            self.reloads += 1

    monkeypatch.setattr(login_module, "AgreementSignDialog", Sign)
    result = dialog.widget._sign_existing_user(mode="password", username="newbie", password="pw", version="terms-v1")
    assert result is expected
    assert Sign.last.reloads == int(should_reload)


def test_legacy_pending_without_server_identity_is_not_replayed(dialog):
    registration_resume.save_pending("req-legacy", "newbie", "terms-v1")
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)

    assert FakeSignDialog.last_instance is None
    assert registration_resume.load_pending()["registration_request_id"] == "req-legacy"


def test_late_result_from_old_dialog_does_not_complete_new_dialog(dialog):
    new = FakeSignDialog()
    new.submit_token = "new-token"
    dialog.widget._sign_dialog = new
    dialog.widget._active_register_token = "new-token"

    dialog.widget._on_register_finished("old-token", RegisterOutcome(True, "old success"))

    assert new.submissions == []
    assert new.result() != QDialog.DialogCode.Accepted


def test_version_change_prompts_reread_and_reloads(dialog):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(
            False,
            "用户协议已更新，请重新阅读",
            code="AGREEMENT_CHANGED",
            agreement_version="v2",
        ),
    )

    assert sign.submissions == [(False, "用户协议已更新，请重新阅读")]
    assert sign.reloads == 1


def test_conflict_shows_error_without_reload(dialog, monkeypatch):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(
            False,
            "该注册请求与先前提交的内容不一致，请勿盲目重试",
            code="REGISTRATION_REQUEST_CONFLICT",
        ),
    )

    assert sign.submissions == [(False, "该注册请求与先前提交的内容不一致，请勿盲目重试")]
    assert sign.reloads == 0
    assert "不一致" in sign.submissions[-1][1]


def test_conflict_offers_discard_entry_and_cancel_has_no_side_effect(dialog, monkeypatch):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    monkeypatch.setattr(login_module.QMessageBox, "exec", lambda self: None)
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    request_id = dialog.widget._submit_context["request_id"]
    monkeypatch.setattr(login_module.QMessageBox, "exec", lambda self: None)

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "冲突", code="REGISTRATION_REQUEST_CONFLICT"),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert dialog.widget.r_username.text() == "newbie"
    assert dialog.widget.r_password.text() == "pw"


def test_conflict_confirm_discard_clears_only_same_pending_and_returns_to_form(dialog, monkeypatch):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    request_id = dialog.widget._submit_context["request_id"]

    monkeypatch.setattr(login_module.QMessageBox, "exec", lambda self: None)
    monkeypatch.setattr(
        login_module.QMessageBox,
        "clickedButton",
        lambda self: self.buttons()[1],
    )
    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "冲突", code="REGISTRATION_REQUEST_CONFLICT"),
    )

    assert registration_resume.load_pending() is None
    assert dialog.widget._submit_context is None
    assert dialog.widget.tabs.currentIndex() == 1
    assert request_id


def test_conflict_stale_dialog_cannot_clear_new_pending(dialog, monkeypatch):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    old_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending("new-id", "newbie", "terms-v2", "https://example.invalid")

    class ConfirmBox:
        class Icon:
            Warning = object()

        class ButtonRole:
            RejectRole = object()
            DestructiveRole = object()

        def __init__(self, *_args, **_kwargs):
            self._buttons = [object(), object()]

        def setIcon(self, *_args):
            pass

        def setWindowTitle(self, *_args):
            pass

        def setText(self, *_args):
            pass

        def setInformativeText(self, *_args):
            pass

        def addButton(self, *_args):
            return self._buttons[len(self._buttons) - 1]

        def setDefaultButton(self, *_args):
            pass

        def buttons(self):
            return self._buttons

        def exec(self):
            return None

        def clickedButton(self):
            return object()

    monkeypatch.setattr(login_module, "QMessageBox", ConfirmBox)
    dialog.widget._offer_conflict_discard(sign, {"request_id": old_id})
    assert registration_resume.load_pending()["registration_request_id"] == "new-id"


def test_network_failure_keeps_window_open(dialog):
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token

    dialog.widget._on_register_finished(sign.submit_token, RegisterOutcome(False, "网络超时"))

    assert sign.submissions == [(False, "网络超时")]


def test_agreement_loader_uses_binder_and_reports_missing_wiring(dialog):
    assert dialog.widget._load_agreement() == (True, "", AGREEMENT)

    unwired = LoginDialog(SimpleNamespace())
    try:
        ok, detail, payload = unwired._load_agreement()
        assert ok is False and payload is None and "暂时不可用" in detail
    finally:
        unwired.close()
        unwired.deleteLater()


def login_and_wait(dialog):
    dialog.do_login()
    deadline = monotonic() + 5
    while dialog._account_operation.busy and monotonic() < deadline:
        QTest.qWait(25)
    assert not dialog._account_operation.busy


def test_lost_response_keeps_request_id_for_retry(dialog):
    """响应丢失：失败结果不得清除未决记录，重试必须复用同一 request ID。"""
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(request_id, "newbie", "terms-2026-10-v1", "https://example.invalid")

    # 服务端可能已经提交，只是响应没回来：客户端只能看到失败。
    dialog.widget._on_register_finished(sign.submit_token, RegisterOutcome(False, "read timeout"))

    assert sign.submissions == [(False, "read timeout")]
    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert registration_resume.request_id_for("newbie", resume_pending=True) == request_id


def test_transport_error_becomes_visible_failure(dialog):
    """后台任务把传输异常转成可显示结果，而不是让线程静默死掉。"""
    received: list[tuple] = []
    signals = login_module._RegisterSignals()
    signals.finished.connect(lambda token, outcome: received.append((token, outcome)))

    def boom():
        raise TimeoutError("read timeout")

    login_module._RegisterTask("tok", boom, signals).run()

    assert len(received) == 1
    token, outcome = received[0]
    assert token == "tok"
    assert outcome.ok is False
    assert "read timeout" in outcome.message


def test_version_change_starts_new_request_with_new_version(dialog):
    """换版后不能继续重放旧版本：清掉旧版本绑定并换新的请求 ID。"""
    dialog.widget.fill_register_form()
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    old_id = dialog.widget._submit_context["request_id"]
    dialog.widget._submit_context["resume_agreement_version"] = "terms-v1"
    registration_resume.save_pending(old_id, "newbie", "terms-v1", "https://example.invalid")

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "用户协议已更新，请重新阅读", code="AGREEMENT_CHANGED", agreement_version="terms-v2"),
    )

    context = dialog.widget._submit_context
    assert context["resume_agreement_version"] == ""
    assert context["request_id"] != old_id
    assert registration_resume.load_pending() is None
    outcome = dialog.widget._register_with_agreement(context, "terms-v2")
    assert outcome.ok is True
    assert dialog.binder.calls[-1]["agreement_version"] == "terms-v2"
    assert dialog.binder.calls[-1]["registration_request_id"] == context["request_id"]


def test_changing_username_before_confirming_previous_request_is_blocked(dialog):
    """旧请求结果未确认时，不允许换用户名开始新请求（否则会覆盖恢复记录）。"""
    registration_resume.save_pending("req-old", "alice", "terms-v1", "https://example.invalid")
    dialog.widget.fill_register_form(username="bob")

    register_and_wait(dialog.widget)

    assert FakeSignDialog.last_instance is None  # 没有打开协议窗口
    assert dialog.messages.warnings
    assert registration_resume.load_pending()["registration_request_id"] == "req-old"


@pytest.mark.parametrize(
    ("status_code", "message"),
    [
        (400, "注册失败，请检查邀请码或用户名"),
        (403, "需要先签署用户协议"),
        (422, "同意字段无效"),
    ],
)
def test_definitive_business_failure_allows_new_username(dialog, app, status_code, message):
    """spec 明确失败状态清除 pending，用户可修正资料继续注册（N17/N24）。

    走真实提交链路：_start_registration_submit → _RegisterTask → 线程池 → 信号 → 结果处理。
    """
    from PySide6.QtCore import QThreadPool

    dialog.widget.fill_register_form(username="taken")
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    old_request_id = dialog.widget._submit_context["request_id"]
    dialog.binder.outcome = RegisterOutcome(
        False,
        message,
        status_code=status_code,
        code={403: "AGREEMENT_REQUIRED", 422: "INVALID_AGREEMENT_INPUT"}.get(status_code, ""),
    )

    dialog.widget._start_registration_submit("terms-2026-10-v1")
    QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()
    app.processEvents()

    assert dialog.binder.calls[-1]["registration_request_id"] == old_request_id
    assert registration_resume.load_pending() is None  # 明确失败：结束未决状态
    assert dialog.messages.errors
    assert dialog.messages.errors[-1][1] == message

    FakeSignDialog.last_instance = None
    dialog.widget.fill_register_form(username="available")
    register_and_wait(dialog.widget)
    assert FakeSignDialog.last_instance is not None  # 新用户名可以继续注册
    new_request_id = dialog.widget._submit_context["request_id"]
    assert new_request_id != old_request_id  # 开始新的请求，而不是复用已失败的那次


def test_unknown_result_keeps_pending_record(dialog):
    """结果未知（传输失败）时仍保留恢复记录，不能被当成明确失败清掉。"""
    dialog.widget.fill_register_form(username="taken")
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(request_id, "taken", "terms-2026-10-v1", "https://example.invalid")

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "网络异常：read timeout", code="NETWORK_ERROR", status_code=0),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id


def test_rate_limit_keeps_pending_record_for_retry(dialog):
    """429 是暂不可用，不能清未决请求；限流解除后仍用原 request ID 恢复（spec AC-06）。"""
    dialog.widget.fill_register_form(username="taken")
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(request_id, "taken", "terms-2026-10-v1", "https://example.invalid")

    # 服务端 429 不保证带特定业务 code，按 HTTP 状态码 429 区分
    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "请求过于频繁，请稍后重试", status_code=429),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert registration_resume.request_id_for("taken", resume_pending=True) == request_id


def test_resume_flow_explains_unconfirmed_result_and_original_account(dialog):
    """N29：pending 只表示结果未确认，不能声称注册本身未完成。"""
    registration_resume.save_pending("req-old", "newbie", "terms-2026-10-v1", "https://example.invalid")
    dialog.widget.fill_register_form()

    register_and_wait(dialog.widget)

    infos = " ".join(str(item) for item in dialog.messages.infos)
    assert any(word in infos for word in ("未确认", "尚未确认", "未确定"))
    assert any(word in infos for word in ("再次提交", "重新提交", "重试"))
    for wrong in ("还没有完成", "尚未完成", "注册未完成", "注册未成功"):
        assert wrong not in infos
    assert "上次注册时的用户名和密码" in infos
    assert "已确认上次注册成功" in infos


@pytest.mark.parametrize("login_username", ["old-name"])
def test_login_success_survives_pending_cleanup_failure(dialog, monkeypatch, login_username):
    """N28：任意用户名登录成功后清理失败也只记日志，不反转登录结果。"""
    registration_resume.save_pending("req-old", "old-name", "terms-2026-10-v1", "https://example.invalid")
    warnings: list[str] = []

    def failing_clear():
        raise PermissionError("denied")

    monkeypatch.setattr(registration_resume, "clear_pending", failing_clear)
    monkeypatch.setattr(dialog.widget.logger, "warning", lambda message: warnings.append(str(message)))
    dialog.widget.l_username.setText(login_username)
    dialog.widget.l_password.setText("pw")
    dialog.binder.login_result = (True, "登录成功")

    login_and_wait(dialog.widget)

    assert dialog.widget.result() == QDialog.DialogCode.Accepted
    assert dialog.binder.detail_login_calls == 1
    assert dialog.messages.errors == []
    assert dialog.messages.warnings == []
    assert warnings and "Failed to clear pending registration" in warnings[0]
    assert registration_resume.load_pending()["registration_request_id"] == "req-old"


@pytest.mark.parametrize("login_username", ["old-name"])
def test_auto_login_success_survives_pending_cleanup_failure(dialog, monkeypatch, login_username):
    """N28：自动登录清理失败也不能把成功认证改成失败。"""
    registration_resume.save_pending("req-old", "old-name", "terms-2026-10-v1", "https://example.invalid")
    warnings: list[str] = []

    def failing_clear():
        raise PermissionError("denied")

    monkeypatch.setattr(registration_resume, "clear_pending", failing_clear)
    monkeypatch.setattr(dialog.widget.logger, "warning", lambda message: warnings.append(str(message)))
    dialog.widget.l_auto_login.setChecked(True)
    dialog.widget.saved_token = "token"
    dialog.widget.l_username.setText(login_username)
    dialog.binder.auto_login_result = True

    assert dialog.widget.try_auto_login() is True
    assert len(dialog.binder.auto_login_calls) == 1
    assert dialog.messages.errors == []
    assert dialog.messages.warnings == []
    assert warnings and "Failed to clear pending registration" in warnings[0]
    assert registration_resume.load_pending()["registration_request_id"] == "req-old"


def test_registration_success_survives_pending_cleanup_failure(dialog, monkeypatch):
    """同类本地清理失败不能阻断注册成功后的提示与回登录页。"""
    warnings: list[str] = []

    def failing_clear():
        raise PermissionError("denied")

    monkeypatch.setattr(registration_resume, "clear_pending", failing_clear)
    monkeypatch.setattr(dialog.widget.logger, "warning", lambda message: warnings.append(str(message)))
    dialog.widget.fill_register_form()

    register_and_wait(dialog.widget)

    assert any("注册成功，请登录" in str(item) for item in dialog.messages.infos)
    assert dialog.widget.l_username.text() == "newbie"
    assert dialog.widget.tabs.currentIndex() == 0
    assert dialog.messages.errors == []
    assert dialog.messages.warnings == []
    assert warnings and "Failed to clear pending registration" in warnings[0]


def test_password_decryption_failure_keeps_pending_for_key_refresh(dialog):
    """服务端仍可用 400 表示密码解密失败；此时保留 pending 以便客户端换钥重试。"""
    FakeSignDialog.next_result = QDialog.DialogCode.Rejected
    dialog.widget.fill_register_form(username="taken")
    register_and_wait(dialog.widget)
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(request_id, "taken", "terms-2026-10-v1", "https://example.invalid")

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "Encryption error", code="PASSWORD_DECRYPT_FAILED", status_code=400),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert registration_resume.request_id_for("taken", resume_pending=True) == request_id
    assert FakeSignDialog.last_instance.submissions == [(False, "Encryption error")]


@pytest.mark.parametrize("status_code", [500, 503])
def test_server_failure_retry_reuses_pending_request_id(dialog, app, status_code):
    """AC-06：5xx 后保留 pending，下一次实际提交必须复用相同 request ID。"""
    from PySide6.QtCore import QThreadPool

    FakeSignDialog.next_result = QDialog.DialogCode.Rejected
    dialog.widget.fill_register_form(username="taken")
    register_and_wait(dialog.widget)
    first_sign = FakeSignDialog.last_instance
    first_request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(first_request_id, "taken", "terms-2026-10-v1", "https://example.invalid")

    dialog.binder.outcome = RegisterOutcome(False, "服务暂不可用，请稍后重试", status_code=status_code)
    dialog.widget._sign_dialog = first_sign
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()

    assert dialog.binder.calls[-1]["registration_request_id"] == first_request_id
    assert registration_resume.load_pending()["registration_request_id"] == first_request_id

    # 再次进入流程并真正发起下一次提交；payload 仍必须带旧 ID。
    dialog.widget.fill_register_form(username="taken")
    register_and_wait(dialog.widget)
    assert dialog.widget._submit_context["request_id"] == first_request_id
    second_sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = second_sign
    dialog.binder.outcome = RegisterOutcome(True, "注册成功")
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()

    assert dialog.binder.calls[-1]["registration_request_id"] == first_request_id
    assert len(dialog.binder.calls) == 2


def test_non_resume_success_keeps_original_message(dialog):
    """没有未决记录时仍是普通注册成功文案，不误报"已确认上次注册"。"""
    dialog.widget.fill_register_form()

    register_and_wait(dialog.widget)

    assert any("注册成功，请登录" in str(item) for item in dialog.messages.infos)
    assert not any("已确认上次注册成功" in str(item) for item in dialog.messages.infos)


def test_unverifiable_closes_real_modal_and_preserves_pending(app, monkeypatch, tmp_path, messages):
    """使用真实 AgreementSignDialog 验证 UNVERIFIABLE 会退出 modal 并保留恢复 ID。"""
    monkeypatch.setattr(login_module.credential, "load_credentials", lambda: None)
    monkeypatch.setattr(registration_resume.storage, "temp_path", lambda name: str(tmp_path / name))
    binder = FakeBinder(
        outcome=RegisterOutcome(
            False, "上次注册已经完成，请用该账号登录确认", code="REGISTRATION_REQUEST_UNVERIFIABLE", status_code=409
        )
    )
    widget = LoginDialog(binder)
    sign_ref = {}
    submitting_states = []
    watchdog_fired = []

    def real_dialog(parent=None, *, load_document=None, **kwargs):
        sign = AgreementSignDialog(parent, document=AGREEMENT, load_document=load_document, **kwargs)
        sign_ref["dialog"] = sign
        # 真实 modal 事件循环内通过真实 submit_requested 信号启动异步注册 task。
        from PySide6.QtCore import QTimer

        sign.submit_token = "real-modal-token"

        def click_confirm_after_open():
            sign.begin_submit()
            submitting_states.append(sign.gate.status)
            sign.submit_requested.emit(sign.version)

        def watchdog():
            watchdog_fired.append(True)
            sign.finish_submit(False, "测试 watchdog：提交信号未完成")
            sign.reject()

        # Timer 以 dialog 为 parent，并在 modal 结束时停止，防止测试结束后访问已销毁的 PySide wrapper。
        start_timer = QTimer(sign)
        start_timer.setSingleShot(True)
        start_timer.timeout.connect(click_confirm_after_open)
        watchdog_timer = QTimer(sign)
        watchdog_timer.setSingleShot(True)
        watchdog_timer.timeout.connect(watchdog)
        sign.finished.connect(start_timer.stop)
        sign.finished.connect(watchdog_timer.stop)
        start_timer.start(0)
        watchdog_timer.start(5000)
        return sign

    monkeypatch.setattr(login_module, "AgreementSignDialog", real_dialog)
    registration_resume.save_pending("req-real-modal", "taken", "terms-2026-10-v1", "https://example.invalid")
    widget.fill_register_form = lambda username="taken", password="wrong", invite="INVITE": (
        widget.r_username.setText(username),
        widget.r_password.setText(password),
        widget.r_confirm_password.setText(password),
        widget.r_invite.setText(invite),
    )
    widget.fill_register_form()

    try:
        widget.do_register()
        sign = sign_ref["dialog"]
        assert submitting_states == ["submitting"]
        assert watchdog_fired == []
        assert sign.result() == QDialog.DialogCode.Rejected
        assert sign.gate.status != "submitting"
        assert widget._sign_dialog is None
        assert registration_resume.load_pending()["registration_request_id"] == "req-real-modal"
        assert widget.tabs.currentIndex() == 0
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def register_and_wait(dialog):
    dialog.do_register()
    deadline = monotonic() + 5
    while dialog._account_operation.busy and monotonic() < deadline:
        QTest.qWait(25)
    assert not dialog._account_operation.busy
