"""登录窗口的注册流程：校验→协议门禁→异步提交→成功回登录页并预填用户名。"""

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from src.gui import login_dialog as login_module  # noqa: E402
from src.gui.login_dialog import LoginDialog  # noqa: E402
from src.network.auth import RegisterOutcome  # noqa: E402
from src.utils import registration_resume  # noqa: E402

AGREEMENT = {
    "version": "terms-2026-10-v1",
    "title": "用户协议",
    "format": "agreement.richtext.v1",
    "blocks": [
        {"font_size": 16, "align": "justify", "runs": [{"text": "正文", "bold": False}]}
    ],
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

    def finish_submit(self, success: bool, message: str = "") -> None:
        self.submissions.append((success, message))

    def reload_document(self) -> bool:
        self.reloads += 1
        return True


class FakeBinder:
    def __init__(self, outcome=None, agreement=(True, "", AGREEMENT)):
        self.outcome = outcome
        self.agreement = agreement
        self.calls: list[dict] = []
        self.server_url = "https://example.invalid"
        self.login_result = (False, "登录失败")
        self.detail_login_result = None
        self.agreement_result = (False, "协议签署失败", {})
        self.detail_login_calls = 0

    def on_registration_server_identity(self):
        return self.server_url

    def on_login(self, username, password, do_auto_login=False):
        return self.login_result

    def on_login_with_details(self, username, password, do_auto_login=False):
        self.detail_login_calls += 1
        if self.detail_login_result is None:
            return self.login_result[0], self.login_result[1], {}
        if self.detail_login_calls > 1:
            return True, "登录成功", {"user_id": username}
        return self.detail_login_result

    def on_auto_login_with_details(self, username, token):
        return self.detail_login_result

    def on_accept_agreement(self, username, version, **kwargs):
        self.agreement_call = (username, version, kwargs)
        return self.agreement_result

    def on_fetch_agreement(self):
        return self.agreement

    def on_register_with_agreement(self, **kwargs):
        self.calls.append(kwargs)
        return self.outcome


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
    monkeypatch.setattr(
        registration_resume.storage, "temp_path", lambda name: str(tmp_path / name)
    )
    FakeSignDialog.last_instance = None
    FakeSignDialog.next_result = QDialog.DialogCode.Accepted
    binder = FakeBinder(outcome=RegisterOutcome(True, "Registration Successful"))
    widget = LoginDialog(binder)
    widget.fill_register_form = (
        lambda username="newbie", password="pw", invite="INVITE": (
            widget.r_username.setText(username),
            widget.r_password.setText(password),
            widget.r_confirm_password.setText(password),
            widget.r_invite.setText(invite),
        )
    )
    yield SimpleNamespace(widget=widget, binder=binder, messages=messages)
    widget.close()
    widget.deleteLater()
    app.processEvents()


def test_invalid_form_does_not_open_agreement(dialog):
    dialog.widget.r_username.setText("")
    dialog.widget.do_register()

    assert FakeSignDialog.last_instance is None
    assert dialog.messages.warnings


def test_mismatched_passwords_do_not_open_agreement(dialog):
    dialog.widget.fill_register_form(password="pw")
    dialog.widget.r_confirm_password.setText("other")
    dialog.widget.do_register()

    assert FakeSignDialog.last_instance is None
    assert dialog.messages.warnings


def test_reject_returns_to_form_and_keeps_input(dialog):
    FakeSignDialog.next_result = QDialog.DialogCode.Rejected
    dialog.widget.fill_register_form()
    dialog.widget.tabs.setCurrentIndex(1)  # 用户在注册页点了"注册"

    dialog.widget.do_register()

    sign = FakeSignDialog.last_instance
    assert sign is not None
    assert sign.reject_text == "不同意，返回注册"
    assert dialog.binder.calls == []
    assert dialog.widget.r_username.text() == "newbie"
    assert (
        dialog.widget.tabs.currentIndex() == 1
    )  # 不同意只回原注册页，不跳到登录页、不退出客户端
    assert registration_resume.load_pending() is None


def test_success_returns_to_login_tab_with_prefilled_username(dialog):
    dialog.widget.fill_register_form()
    registration_resume.save_pending(
        "req-1", "newbie", server_url="https://example.invalid"
    )

    dialog.widget.do_register()

    assert dialog.widget.l_username.text() == "newbie"
    assert dialog.widget.tabs.currentIndex() == 0
    assert dialog.messages.infos
    assert registration_resume.load_pending() is None  # 成功后才清除恢复记录


def test_submit_sends_request_id_version_and_acceptance(dialog):
    dialog.widget.fill_register_form()
    dialog.widget.do_register()

    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    # 线程池任务同步执行：直接调用提交函数更便于断言参数
    outcome = dialog.widget._register_with_agreement(
        dialog.widget._submit_context, "terms-2026-10-v1"
    )

    assert outcome.ok is True
    assert dialog.binder.calls[0] == {
        "username": "newbie",
        "password": "pw",
        "invite_code": "INVITE",
        "registration_request_id": dialog.widget._submit_context["request_id"],
        "agreement_version": "terms-2026-10-v1",
        "accepted": True,
    }
    assert (
        registration_resume.load_pending() is not None
    )  # 提交前先落盘请求 ID，供响应丢失后重试


def test_resume_submission_reuses_original_agreement_version(dialog):
    registration_resume.save_pending(
        "req-old", "newbie", "terms-v1", "https://example.invalid"
    )
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
    dialog.widget.do_register()
    first_id = dialog.widget._submit_context["request_id"]
    dialog.widget._sign_dialog = FakeSignDialog()
    dialog.widget._start_registration_submit("terms-2026-10-v1")

    dialog.widget.r_password.setText("changed")
    dialog.widget.r_confirm_password.setText("changed")
    dialog.widget.r_invite.setText("OTHER")
    dialog.widget.do_register()

    assert dialog.widget._submit_context["request_id"] == first_id
    assert registration_resume.load_pending()["registration_request_id"] == first_id
    assert dialog.messages.warnings


def test_version_change_clears_known_old_request_and_prepares_new_id(dialog):
    dialog.widget.fill_register_form()
    dialog.widget.do_register()
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
    dialog.widget.do_register()
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
    dialog.widget.do_register()
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
    dialog.widget.do_register()
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
    registration_resume.save_pending(
        "req-recover", "newbie", "terms-v1", "https://example.invalid"
    )
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
    dialog.widget._submit_context.update(
        password="corrected", invite="NEW-INVITE", resumed_from_disk=True
    )
    dialog.widget._register_with_agreement(dialog.widget._submit_context, "terms-v1")
    assert dialog.widget._submit_context["request_id"] == "req-recover"
    assert dialog.binder.calls[-1]["password"] == "corrected"
    assert dialog.binder.calls[-1]["invite_code"] == "NEW-INVITE"
    assert (
        registration_resume.load_pending()["registration_request_id"] == "req-recover"
    )


def test_not_sent_fresh_request_releases_pending_but_recovered_request_stays(dialog):
    dialog.widget.fill_register_form()
    dialog.widget.do_register()
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

    registration_resume.save_pending(
        "req-recovered", "newbie", "terms-v1", "https://example.invalid"
    )
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
    assert (
        registration_resume.load_pending()["registration_request_id"] == "req-recovered"
    )
    assert request_id != "req-recovered"


def test_unverifiable_can_be_cleared_only_by_successful_same_username_login(dialog):
    dialog.widget.fill_register_form()
    dialog.widget.do_register()
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
    assert (
        registration_resume.load_pending()["confirmation_required"] == "same_user_login"
    )
    assert "同一用户名和密码登录确认" in sign.submissions[-1][1]

    dialog.widget.l_username.setText("other")
    dialog.widget.l_password.setText("pw")
    dialog.widget.do_login()
    assert registration_resume.load_pending()["registration_request_id"] == request_id

    dialog.binder.login_result = (False, "登录失败")
    dialog.widget.l_username.setText("newbie")
    dialog.widget.l_password.setText("wrong")
    dialog.widget.do_login()
    assert registration_resume.load_pending()["registration_request_id"] == request_id

    dialog.binder.login_result = (True, "登录成功")
    dialog.widget.l_username.setText("newbie")
    dialog.widget.l_password.setText("pw")
    dialog.widget.do_login()
    assert registration_resume.load_pending() is None


def test_pending_request_cannot_be_replayed_after_server_switch(dialog):
    registration_resume.save_pending(
        "req-server", "newbie", "terms-v1", "https://original.example"
    )
    dialog.widget.fill_register_form()
    dialog.binder.server_url = "https://other.example"
    dialog.widget.do_register()

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
    dialog.widget.do_login()
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
    dialog.widget.do_login()
    assert registration_resume.load_pending()["registration_request_id"] == "req-keep"


def test_unverifiable_login_on_other_server_does_not_clear_pending(dialog):
    registration_resume.save_pending(
        "req-other-server", "newbie", "terms-v1", "https://original.example"
    )
    dialog.widget._pending_login_confirmation_username = "newbie"
    dialog.binder.server_url = "https://other.example"
    dialog.binder.login_result = (True, "登录成功")
    dialog.widget.l_username.setText("newbie")
    dialog.widget.l_password.setText("pw")
    dialog.widget.do_login()

    assert (
        registration_resume.load_pending()["registration_request_id"]
        == "req-other-server"
    )


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
            self.submit_requested = SimpleNamespace(
                connect=lambda callback: submitted.append(callback)
            )

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
    dialog.widget.do_login()

    assert dialog.binder.agreement_call[2] == {"password": "pw", "token": None}
    assert dialog.binder.detail_login_result[2]["code"] == "AGREEMENT_REQUIRED"


def test_existing_user_signing_login_failure_releases_submit_for_retry(
    dialog, monkeypatch
):
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
        dialog.widget._sign_existing_user(
            mode="password", username="newbie", password="pw", version="terms-v1"
        )
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
def test_post_sign_in_error_routes_and_later_reject_exits(
    dialog, monkeypatch, login_details, expected, should_reload
):
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
    result = dialog.widget._sign_existing_user(
        mode="password", username="newbie", password="pw", version="terms-v1"
    )
    assert result is expected
    assert Sign.last.reloads == int(should_reload)


def test_legacy_pending_without_server_identity_is_not_replayed(dialog):
    registration_resume.save_pending("req-legacy", "newbie", "terms-v1")
    dialog.widget.fill_register_form()
    dialog.widget.do_register()

    assert FakeSignDialog.last_instance is None
    assert registration_resume.load_pending()["registration_request_id"] == "req-legacy"


def test_late_result_from_old_dialog_does_not_complete_new_dialog(dialog):
    new = FakeSignDialog()
    new.submit_token = "new-token"
    dialog.widget._sign_dialog = new
    dialog.widget._active_register_token = "new-token"

    dialog.widget._on_register_finished(
        "old-token", RegisterOutcome(True, "old success")
    )

    assert new.submissions == []
    assert new.result() != QDialog.DialogCode.Accepted


def test_version_change_prompts_reread_and_reloads(dialog):
    dialog.widget.fill_register_form()
    dialog.widget.do_register()
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
    dialog.widget.do_register()
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

    assert sign.submissions == [
        (False, "该注册请求与先前提交的内容不一致，请勿盲目重试")
    ]
    assert sign.reloads == 0


def test_conflict_offers_discard_entry_and_cancel_has_no_side_effect(
    dialog, monkeypatch
):
    dialog.widget.fill_register_form()
    dialog.widget.do_register()
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


def test_conflict_confirm_discard_clears_only_same_pending_and_returns_to_form(
    dialog, monkeypatch
):
    dialog.widget.fill_register_form()
    dialog.widget.do_register()
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
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    old_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(
        "new-id", "newbie", "terms-v2", "https://example.invalid"
    )

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
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token

    dialog.widget._on_register_finished(
        sign.submit_token, RegisterOutcome(False, "网络超时")
    )

    assert sign.submissions == [(False, "网络超时")]


def test_agreement_loader_uses_binder_and_reports_missing_wiring(dialog):
    assert dialog.widget._load_agreement() == (True, "", AGREEMENT)

    unwired = LoginDialog(SimpleNamespace())
    try:
        ok, detail, payload = unwired._load_agreement()
        assert ok is False and payload is None and "未接线" in detail
    finally:
        unwired.close()
        unwired.deleteLater()
