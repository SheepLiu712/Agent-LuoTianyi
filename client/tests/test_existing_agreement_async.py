"""真实 Qt 事件循环下，慢签署不阻塞、连点不排队重放、换版通知可见。"""

from threading import Event, get_ident
from time import monotonic
from types import SimpleNamespace

import pytest
from PySide6.QtCore import Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from src.gui import login_dialog as login_module
from src.gui.agreement_sign_dialog import AgreementSignDialog
from src.gui.login_dialog import ExistingAgreementResult, LoginDialog

DOCUMENT = {
    "version": "v1",
    "title": "用户协议",
    "format": "agreement.richtext.v1",
    "blocks": [{"font_size": 16, "runs": [{"text": "正文", "bold": False}]}],
}


@pytest.mark.parametrize("mode", ["password", "auto_login"])
def test_slow_signing_keeps_ui_responsive_and_does_not_replay_clicks(monkeypatch, mode):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setattr(login_module.credential, "load_credentials", lambda: None)
    monkeypatch.setattr(login_module.registration_resume, "load_pending", lambda: None)
    release = Event()
    calls, applied, errors = [], [], []
    main_thread = get_ident()

    def prepare(action, **values):
        def execute(cancelled):
            calls.append((get_ident(), values))
            if len(calls) == 1:
                assert release.wait(4)
                return False, "网络超时，请重试", {}
            return True, "登录成功", {"user_id": "test"}

        return SimpleNamespace(context=(), execute=execute)

    def apply(request, result):
        applied.append(get_ident())
        return result[:2]

    binder = SimpleNamespace(
        prepare_account_request=prepare,
        account_context=lambda: (),
        apply_account_result=apply,
        on_fetch_agreement=lambda: (True, "", DOCUMENT),
    )
    login = LoginDialog(binder)
    timer = QTimer()
    timer.setInterval(10)
    state = {"phase": 0, "ticks": 0, "modal": None}
    deadline = monotonic() + 8

    def drive():
        try:
            modal = app.activeModalWidget()
            if isinstance(modal, AgreementSignDialog):
                state["modal"] = modal
            assert monotonic() < deadline, "签署窗口未在限时内完成交互"
            if not isinstance(modal, AgreementSignDialog) or not modal.version:
                return
            if state["phase"] == 0:
                # 本用例聚焦请求期间的实际界面事件；阅读时长由门禁专用测试覆盖。
                modal.gate.required_seconds = 0
                modal._on_tick()
                if not modal.confirm_btn.isEnabled():
                    return  # 等待 QTextDocument 的异步布局完成。
                if mode == "auto_login":
                    assert modal.parentWidget() is None
                QTest.mouseClick(modal.confirm_btn, Qt.MouseButton.LeftButton)
                state["phase"] = 1
            elif state["phase"] == 1 and calls:
                state["ticks"] += 1
                assert modal.confirm_btn.text() == "正在提交…"
                assert not modal.confirm_btn.isEnabled()
                assert not modal.reject_btn.isEnabled()
                QTest.mouseClick(modal.confirm_btn, Qt.MouseButton.LeftButton)
                modal.close()
                assert modal.isVisible()
                if state["ticks"] >= 5:
                    release.set()
                    state["phase"] = 2
            elif state["phase"] == 2 and modal.confirm_btn.isEnabled():
                assert len(calls) == 1
                assert modal.error_label.text() == "网络超时，请重试"
                QTest.mouseClick(modal.confirm_btn, Qt.MouseButton.LeftButton)
                state["phase"] = 3
        except BaseException as error:
            errors.append(error)
            release.set()
            timer.stop()
            if state["modal"] is not None:
                state["modal"].gate.end_submit()
                state["modal"].reject()

    timer.timeout.connect(drive)
    timer.start()
    try:
        outcome = login._sign_existing_user(
            mode=mode,
            username="test",
            version="v1",
            password="pw" if mode == "password" else None,
            token="token" if mode == "auto_login" else None,
        )
        assert not errors, errors
        assert outcome is ExistingAgreementResult.LOGGED_IN
        assert len(calls) == 2
        assert all(thread != main_thread for thread, _ in calls)
        assert applied == [main_thread]
    finally:
        release.set()
        timer.stop()
        login.close()


def test_version_notice_survives_loading_and_clears_on_next_submit():
    app = QApplication.instance() or QApplication([])
    modal = AgreementSignDialog(
        document=DOCUMENT,
        load_document=lambda: (True, "", {**DOCUMENT, "version": "v2"}),
    )
    modal.show()
    try:
        notice = "用户协议已更新，请重新阅读"
        modal.reload_document(notice)
        assert modal.error_label.text() == notice
        for _ in range(100):
            if modal.version == "v2":
                break
            QTest.qWait(10)
        assert modal.version == "v2"
        assert modal.error_label.isVisible()
        assert modal.error_label.text() == notice
        assert not modal.confirm_btn.isEnabled()
        modal.begin_submit()
        assert not modal.error_label.isVisible()
        modal.finish_submit(False, "网络失败")
        assert modal.error_label.text() == "网络失败"
    finally:
        modal.close()
        app.processEvents()
