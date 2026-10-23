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
    def __init__(self, outcome=None, agreement=(True, "", AGREEMENT)):
        self.outcome = outcome
        self.agreement = agreement
        self.calls: list[dict] = []

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
    widget.fill_register_form = lambda username="newbie", password="pw", invite="INVITE" : (
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
        RegisterOutcome(False, "该注册请求与先前提交的内容不一致，请勿盲目重试", code="REGISTRATION_REQUEST_CONFLICT"),
    )

    assert sign.submissions == [(False, "该注册请求与先前提交的内容不一致，请勿盲目重试")]
    assert sign.reloads == 0


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
        assert ok is False and payload is None and "未接线" in detail
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


def test_definitive_business_failure_allows_new_username(dialog):
    """服务端明确 4xx 拒绝后，用户可以改用户名继续注册（审查 N17）。"""
    dialog.widget.fill_register_form(username="taken")
    dialog.widget.do_register()
    sign = FakeSignDialog.last_instance
    dialog.widget._sign_dialog = sign
    dialog.widget._active_register_token = sign.submit_token
    request_id = dialog.widget._submit_context["request_id"]
    registration_resume.save_pending(request_id, "taken", "terms-2026-10-v1")

    dialog.widget._on_register_finished(
        sign.submit_token,
        RegisterOutcome(False, "注册失败，请检查邀请码或用户名", status_code=400),
    )

    assert registration_resume.load_pending() is None  # 明确失败：结束未决状态
    FakeSignDialog.last_instance = None
    dialog.widget.fill_register_form(username="available")
    dialog.widget.do_register()
    assert FakeSignDialog.last_instance is not None  # 新用户名可以继续注册


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
