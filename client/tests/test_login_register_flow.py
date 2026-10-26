"""登录窗口的注册流程：校验→协议门禁→异步提交→成功回登录页并预填用户名。"""

from types import SimpleNamespace

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Signal  # noqa: E402
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

    def finish_submit(self, success: bool, message: str = "") -> None:
        self.submissions.append((success, message))

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
    assert dialog.widget.tabs.currentIndex() == 1  # 不同意只回原注册页，不跳到登录页、不退出客户端
    assert registration_resume.load_pending() is None


def test_success_returns_to_login_tab_with_prefilled_username(dialog):
    dialog.widget.fill_register_form()
    registration_resume.save_pending("req-1", "newbie")

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
    registration_resume.save_pending("req-old", "newbie", "terms-v1")
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
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "用户协议已更新，请重新阅读", code="AGREEMENT_CHANGED", agreement_version="v2"),
    )

    assert sign.submissions == [(False, "用户协议已更新，请重新阅读")]
    assert sign.reloads == 1


def test_conflict_shows_error_without_reload(dialog):
    dialog.widget.fill_register_form()
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(
            False,
            "注册信息与之前提交的内容不一致，请核对后继续",
            code="REGISTRATION_REQUEST_CONFLICT",
            status_code=409,
        ),
    )

    assert sign.submissions == [(False, "注册信息与之前提交的内容不一致，请核对后继续")]
    assert sign.reloads == 0
    assert dialog.messages.errors
    assert "不一致" in dialog.messages.errors[-1][1]


def test_network_failure_keeps_window_open(dialog):
    dialog.widget.fill_register_form()
    dialog.widget.do_register()
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


def test_lost_response_keeps_request_id_for_retry(dialog):
    """响应丢失：失败结果不得清除未决记录，重试必须复用同一 request ID。"""
    dialog.widget.fill_register_form()
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(request_id, "newbie", "terms-2026-10-v1")

    # 服务端可能已经提交，只是响应没回来：客户端只能看到失败。
    dialog.widget._on_register_finished(sign.submit_token, RegisterOutcome(False, "read timeout"))

    assert sign.submissions == [(False, "read timeout")]
    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert registration_resume.request_id_for("newbie") == request_id


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
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    old_id = dialog.widget._submit_context["request_id"]
    dialog.widget._submit_context["resume_agreement_version"] = "terms-v1"
    registration_resume.save_pending(old_id, "newbie", "terms-v1")

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
    registration_resume.save_pending("req-old", "alice", "terms-v1")
    dialog.widget.fill_register_form(username="bob")

    dialog.widget.do_register()

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
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    old_request_id = dialog.widget._submit_context["request_id"]
    dialog.binder.outcome = RegisterOutcome(False, message, status_code=status_code)

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
    dialog.widget.do_register()
    assert FakeSignDialog.last_instance is not None  # 新用户名可以继续注册
    new_request_id = dialog.widget._submit_context["request_id"]
    assert new_request_id != old_request_id  # 开始新的请求，而不是复用已失败的那次


def test_unknown_result_keeps_pending_record(dialog):
    """结果未知（传输失败）时仍保留恢复记录，不能被当成明确失败清掉。"""
    dialog.widget.fill_register_form(username="taken")
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(request_id, "taken", "terms-2026-10-v1")

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "网络异常：read timeout", code="NETWORK_ERROR", status_code=0),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id


def test_rate_limit_keeps_pending_record_for_retry(dialog):
    """429 是暂不可用，不能清未决请求；限流解除后仍用原 request ID 恢复（spec AC-06）。"""
    dialog.widget.fill_register_form(username="taken")
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(request_id, "taken", "terms-2026-10-v1")

    # 服务端 429 不保证带特定业务 code，按 HTTP 状态码 429 区分
    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "请求过于频繁，请稍后重试", status_code=429),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert registration_resume.request_id_for("taken") == request_id


def test_resume_flow_explains_unconfirmed_result_and_original_account(dialog):
    """N29：pending 只表示结果未确认，不能声称注册本身未完成。"""
    registration_resume.save_pending("req-old", "newbie", "terms-2026-10-v1")
    dialog.widget.fill_register_form()

    dialog.widget.do_register()

    infos = " ".join(str(item) for item in dialog.messages.infos)
    assert any(word in infos for word in ("未确认", "尚未确认", "未确定"))
    assert any(word in infos for word in ("再次提交", "重新提交", "重试"))
    for wrong in ("还没有完成", "尚未完成", "注册未完成", "注册未成功"):
        assert wrong not in infos
    assert "上次注册时的用户名和密码" in infos
    assert "已确认上次注册成功" in infos


@pytest.mark.parametrize("login_username", ["old-name", "new-name"])
def test_login_success_clears_pending_record_of_any_username(dialog, login_username):
    """N28：本机只有一个恢复记录，成功登录即结束恢复状态，不再要求用户名相同。"""
    registration_resume.save_pending("req-old", "old-name", "terms-2026-10-v1")
    dialog.widget.l_username.setText(login_username)
    dialog.widget.l_password.setText("pw")
    dialog.binder.login_result = (True, "登录成功")

    dialog.widget.do_login()

    assert registration_resume.load_pending() is None


@pytest.mark.parametrize("login_username", ["old-name", "new-name"])
def test_login_success_survives_pending_cleanup_failure(dialog, monkeypatch, login_username):
    """N28：任意用户名登录成功后清理失败也只记日志，不反转登录结果。"""
    registration_resume.save_pending("req-old", "old-name", "terms-2026-10-v1")
    warnings: list[str] = []

    def failing_clear():
        raise PermissionError("denied")

    monkeypatch.setattr(registration_resume, "clear_pending", failing_clear)
    monkeypatch.setattr(dialog.widget.logger, "warning", lambda message: warnings.append(str(message)))
    dialog.widget.l_username.setText(login_username)
    dialog.widget.l_password.setText("pw")
    dialog.binder.login_result = (True, "登录成功")

    dialog.widget.do_login()

    assert dialog.widget.result() == QDialog.DialogCode.Accepted
    assert len(dialog.binder.login_calls) == 1
    assert dialog.messages.errors == []
    assert dialog.messages.warnings == []
    assert warnings and "Failed to clear pending registration record" in warnings[0]
    assert registration_resume.load_pending()["registration_request_id"] == "req-old"


@pytest.mark.parametrize("login_username", ["old-name", "new-name"])
def test_auto_login_success_clears_pending_of_any_username(dialog, login_username):
    """N28：自动登录成功同样结束本机恢复状态。"""
    registration_resume.save_pending("req-old", "old-name", "terms-2026-10-v1")
    dialog.widget.l_auto_login.setChecked(True)
    dialog.widget.saved_token = "token"
    dialog.widget.l_username.setText(login_username)
    dialog.binder.auto_login_result = True

    assert dialog.widget.try_auto_login() is True
    assert registration_resume.load_pending() is None


@pytest.mark.parametrize("login_username", ["old-name", "new-name"])
def test_auto_login_success_survives_pending_cleanup_failure(dialog, monkeypatch, login_username):
    """N28：自动登录清理失败也不能把成功认证改成失败。"""
    registration_resume.save_pending("req-old", "old-name", "terms-2026-10-v1")
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
    assert warnings and "Failed to clear pending registration record" in warnings[0]
    assert registration_resume.load_pending()["registration_request_id"] == "req-old"


def test_registration_success_survives_pending_cleanup_failure(dialog, monkeypatch):
    """同类本地清理失败不能阻断注册成功后的提示与回登录页。"""
    warnings: list[str] = []

    def failing_clear():
        raise PermissionError("denied")

    monkeypatch.setattr(registration_resume, "clear_pending", failing_clear)
    monkeypatch.setattr(dialog.widget.logger, "warning", lambda message: warnings.append(str(message)))
    dialog.widget.fill_register_form()

    dialog.widget.do_register()

    assert any("注册成功，请登录" in str(item) for item in dialog.messages.infos)
    assert dialog.widget.l_username.text() == "newbie"
    assert dialog.widget.tabs.currentIndex() == 0
    assert dialog.messages.errors == []
    assert dialog.messages.warnings == []
    assert warnings and "Failed to clear pending registration record" in warnings[0]


def test_password_decryption_failure_keeps_pending_for_key_refresh(dialog):
    """服务端仍可用 400 表示密码解密失败；此时保留 pending 以便客户端换钥重试。"""
    FakeSignDialog.next_result = QDialog.DialogCode.Rejected
    dialog.widget.fill_register_form(username="taken")
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(request_id, "taken", "terms-2026-10-v1")

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "Encryption error", code="PASSWORD_DECRYPT_FAILED", status_code=400),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert registration_resume.request_id_for("taken") == request_id
    assert FakeSignDialog.last_instance.submissions == [(False, "Encryption error")]


@pytest.mark.parametrize("status_code", [500, 503])
def test_server_failure_retry_reuses_pending_request_id(dialog, app, status_code):
    """AC-06：5xx 后保留 pending，下一次实际提交必须复用相同 request ID。"""
    from PySide6.QtCore import QThreadPool

    FakeSignDialog.next_result = QDialog.DialogCode.Rejected
    dialog.widget.fill_register_form(username="taken")
    dialog.widget.do_register()
    first_sign = FakeSignDialog.last_instance
    first_request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(first_request_id, "taken", "terms-2026-10-v1")

    dialog.binder.outcome = RegisterOutcome(False, "服务暂不可用，请稍后重试", status_code=status_code)
    dialog.widget._sign_dialog = first_sign
    dialog.widget._start_registration_submit("terms-2026-10-v1")
    QThreadPool.globalInstance().waitForDone(5000)
    app.processEvents()

    assert dialog.binder.calls[-1]["registration_request_id"] == first_request_id
    assert registration_resume.load_pending()["registration_request_id"] == first_request_id

    # 再次进入流程并真正发起下一次提交；payload 仍必须带旧 ID。
    dialog.widget.fill_register_form(username="taken")
    dialog.widget.do_register()
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

    dialog.widget.do_register()

    assert any("注册成功，请登录" in str(item) for item in dialog.messages.infos)
    assert not any("已确认上次注册成功" in str(item) for item in dialog.messages.infos)


def test_unverifiable_recovery_preserves_pending_until_login_confirms(dialog):
    """N20: UNVERIFIABLE 按 spec 提示登录确认，并保留原 ID，登录成功后才清理。"""
    request_id = "req-unverifiable"
    registration_resume.save_pending(request_id, "taken", "terms-2026-10-v1")
    FakeSignDialog.next_result = QDialog.DialogCode.Rejected
    dialog.widget.fill_register_form(username="taken")
    dialog.widget.do_register()

    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(
            False,
            "上次注册已经完成，请用该账号登录确认",
            code="REGISTRATION_REQUEST_UNVERIFIABLE",
            status_code=409,
        ),
    )

    # 错误结果不能丢掉唯一恢复凭据；UI 路由与 spec:297 一致，是登录确认而非新注册。
    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert registration_resume.request_id_for("taken") == request_id
    assert dialog.widget.tabs.currentIndex() == 0
    assert dialog.widget.l_username.text() == "taken"
    assert dialog.messages.infos
    message = dialog.messages.infos[-1][1]
    assert "上次注册已经完成" in message
    assert "请用该账号当前的密码登录" in message
    # 提示面向用户，不应泄露实现术语。
    for jargon in ("未决请求", "替代账号", "request ID", "pending"):
        assert jargon not in message
    assert not dialog.messages.errors

    # 如用户返回注册流程并补上原凭据，仍沿用原 request ID，而不是创建新请求。
    FakeSignDialog.next_result = QDialog.DialogCode.Rejected
    dialog.widget.r_password.setText("original-password")
    dialog.widget.r_confirm_password.setText("original-password")
    dialog.widget.tabs.setCurrentIndex(1)
    dialog.widget.do_register()
    assert dialog.widget._submit_context["request_id"] == request_id
    assert registration_resume.load_pending()["registration_request_id"] == request_id

    # 登录失败不清记录；任意用户名成功登录后清除该 pending。
    dialog.widget.l_password.setText("wrong")
    dialog.binder.login_result = (False, "登录失败")
    dialog.widget.do_login()
    assert registration_resume.load_pending()["registration_request_id"] == request_id

    dialog.widget.l_password.setText("valid-current-password")
    dialog.binder.login_result = (True, "登录成功")
    dialog.widget.do_login()
    assert registration_resume.load_pending() is None


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
    registration_resume.save_pending("req-real-modal", "taken", "terms-2026-10-v1")
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


def test_registration_request_conflict_preserves_pending_and_form(dialog):
    """N22: 同 ID 内容冲突时不清恢复记录，提示保留输入且不盲目重试。"""
    request_id = "req-conflict"
    registration_resume.save_pending(request_id, "taken", "terms-2026-10-v1")
    FakeSignDialog.next_result = QDialog.DialogCode.Rejected
    dialog.widget.fill_register_form(username="taken", invite="changed-invite")
    dialog.widget.tabs.setCurrentIndex(1)
    dialog.widget.do_register()

    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(
            False,
            "注册信息与之前提交的内容不一致，请核对后继续",
            code="REGISTRATION_REQUEST_CONFLICT",
            status_code=409,
        ),
    )

    assert registration_resume.load_pending()["registration_request_id"] == request_id
    assert registration_resume.request_id_for("taken") == request_id
    assert dialog.widget.tabs.currentIndex() == 1
    assert dialog.widget.r_username.text() == "taken"
    assert dialog.widget.r_invite.text() == "changed-invite"
    assert dialog.messages.errors
    assert "不一致" in dialog.messages.errors[-1][1]
