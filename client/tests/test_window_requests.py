import base64
import json
import os
import threading
from unittest.mock import Mock

import pytest
import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from PySide6.QtCore import QCoreApplication, QEvent, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLineEdit, QPushButton
from src.gui import login_dialog as dialog_module
from src.gui.binder import AgentBinder
from src.gui.login_dialog import LoginDialog
from src.network.network_client import NetworkClient


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield QApplication.instance() or QApplication([])


def test_login_public_key_pending_keeps_ui_responsive_and_rejects_duplicate_submit(qapp, monkeypatch):
    started = threading.Event()
    release = threading.Event()
    finished = threading.Event()
    calls = []
    probes = []
    heartbeats = []

    def send(_session, request, **kwargs):
        calls.append((request.method, request.url))
        started.set()
        # 短看门狗只保证旧同步实现可结束，不作为产品时限。
        if not release.wait(1):
            release.set()
        response = requests.Response()
        response.status_code = 503
        response._content = b"{}"
        response.request = request
        finished.set()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    monkeypatch.setattr(dialog_module.credential, "load_credentials", lambda: None)
    monkeypatch.setattr(dialog_module.QMessageBox, "critical", lambda *args: None)
    network = NetworkClient("https://window-test.invalid")
    network.ws_transport.start = Mock()
    binder = AgentBinder(
        send_text_callback=Mock(),
        send_image_callback=Mock(),
        send_typing_callback=Mock(),
        send_touch_callback=Mock(),
        play_local_tts_callback=Mock(),
        stop_local_tts_callback=Mock(),
        set_volume_callback=Mock(),
        fetch_history_callback=Mock(),
        set_model_callback=Mock(),
        auto_login_callback=network.auto_login,
        login_callback=network.login,
        register_callback=network.register,
        reset_account_callback=network.reset_account,
        set_base_url_callback=network.set_base_url,
        prepare_account_callback=network.prepare_account_request,
        apply_account_callback=network.apply_account_result,
        account_context_callback=network.account_context,
    )
    window = LoginDialog(binder)
    window.l_username.setText("test-user")
    window.l_password.setText("test-password")
    window.show()
    qapp.processEvents()
    heartbeat = QTimer(window)
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: heartbeats.append(not release.is_set()))
    heartbeat.start()
    watch = QTimer(window)
    watch.setInterval(5)

    def inspect_while_request_pending():
        QTest.mouseClick(window.l_btn, Qt.MouseButton.LeftButton)
        window.l_btn.setFocus()
        QTest.keyClick(window.l_btn, Qt.Key.Key_Return)
        probes.append((not release.is_set(), any(heartbeats), window.l_btn.isEnabled(), len(calls)))

    def await_transport():
        if started.is_set():
            watch.stop()
            QTimer.singleShot(50, inspect_while_request_pending)

    watch.timeout.connect(await_transport)
    watch.start()
    QTimer.singleShot(0, lambda: QTest.mouseClick(window.l_btn, Qt.MouseButton.LeftButton))
    try:
        for _ in range(500):
            if probes:
                break
            QTest.qWait(10)

        assert probes == [(True, True, False, 1)]
        assert calls == [("GET", "https://window-test.invalid/auth/public_key")]
        network.ws_transport.start.assert_not_called()
    finally:
        release.set()
        assert finished.wait(2)
        watch.stop()
        heartbeat.stop()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def wait_for(predicate):
    for _ in range(500):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "observation exceeded the test budget"


@pytest.fixture
def account_window(qapp, monkeypatch):
    windows = []
    states = []

    def create(post_status=503, block="POST", require_acceptance=False):
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        pem = (
            key.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )
        state = {
            "calls": [],
            "get_status": 200,
            "gate": threading.Event(),
            "complete": threading.Event(),
            "block": block,
            "status": post_status,
        }
        states.append(state)

        def send(session, request, **kwargs):
            state["calls"].append((session, request, threading.get_ident()))
            if request.method == state["block"]:
                if not state["gate"].wait(5):
                    raise requests.Timeout("test watchdog")
            response = requests.Response()
            response.status_code = state["get_status"] if request.method == "GET" else state["status"]
            payload = (
                {"public_key": pem}
                if request.method == "GET"
                else {
                    "user_id": "test-user",
                    "message_token": "test-message",
                    "login_token": "test-login",
                    "detail": "retry",
                }
            )
            if request.url.endswith("/auth/agreement/policy"):
                payload = {"require_acceptance": require_acceptance}
            response._content = json.dumps(payload).encode()
            response.request = request
            state["complete"].set()
            return response

        monkeypatch.setattr(requests.Session, "send", send)
        monkeypatch.setattr(dialog_module.credential, "load_credentials", lambda: None)
        monkeypatch.setattr(dialog_module.registration_resume, "load_pending", lambda: None)
        monkeypatch.setattr(dialog_module.QMessageBox, "critical", lambda *args: None)
        monkeypatch.setattr(dialog_module.QMessageBox, "information", lambda *args: None)
        network = NetworkClient("https://window-test.invalid")
        network.ws_transport.start = Mock()
        network.ws_transport.set_base_url = Mock()
        saves = []
        monkeypatch.setattr(
            dialog_module.credential, "save_credentials", lambda *args: saves.append(threading.get_ident())
        )
        monkeypatch.setattr(
            dialog_module.credential, "save_server_url", lambda *args, **kwargs: saves.append(threading.get_ident())
        )
        binder = AgentBinder(
            send_text_callback=Mock(),
            send_image_callback=Mock(),
            send_typing_callback=Mock(),
            send_touch_callback=Mock(),
            play_local_tts_callback=Mock(),
            stop_local_tts_callback=Mock(),
            set_volume_callback=Mock(),
            fetch_history_callback=Mock(),
            set_model_callback=Mock(),
            auto_login_callback=network.auto_login,
            login_callback=network.login,
            register_callback=network.register,
            reset_account_callback=network.reset_account,
            set_base_url_callback=network.set_base_url,
            prepare_account_callback=network.prepare_account_request,
            apply_account_callback=network.apply_account_result,
            account_context_callback=network.account_context,
        )
        window = LoginDialog(binder)
        window.show()
        windows.append(window)
        return window, network, state, saves, key

    yield create
    for state in states:
        state["gate"].set()
    QTest.qWait(100)
    for window in windows:
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


@pytest.mark.parametrize("action", ["login", "register", "reset", "server"])
def test_account_actions_keep_http_off_gui_single_flight_and_allow_manual_retry(account_window, qapp, action):
    window, network, state, saves, key = account_window()
    ui_thread = threading.get_ident()
    child = None
    if action == "login":
        window.l_username.setText("test-user")
        window.l_password.setText("test-password")
        button = window.l_btn
    elif action == "register":
        window.tabs.setCurrentIndex(1)
        for field, text in (
            (window.r_username, "test-user"),
            (window.r_password, "test-password"),
            (window.r_confirm_password, "test-password"),
            (window.r_invite, "test-invite"),
        ):
            field.setText(text)
        button = window.r_btn
    else:
        opened = []

        def prepare_child():
            nonlocal child, button
            child = qapp.activeModalWidget()
            fields = child.findChildren(QLineEdit)
            values = (
                ["test-invite", "test-user", "test-password", "test-password"]
                if action == "reset"
                else ["https://candidate.invalid"]
            )
            for field, value in zip(fields, values):
                field.setText(value)
            button = child.findChild(QPushButton)
            child.setModal(False)
            child.hide()
            opened.append(True)

        # 子窗口的 exec 只用于现有入口；先获取真实控件后关闭局部 loop，再展示操作。
        QTimer.singleShot(0, prepare_child)
        QTest.mouseClick(window.reset_btn if action == "reset" else window.server_btn, Qt.MouseButton.LeftButton)
        assert opened
        child.show()
    if action == "server":
        state["block"] = "GET"
        state["get_status"] = 503
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    wait_for(lambda: any(request.method == state["block"] for _, request, _ in state["calls"]))
    heartbeat = []
    QTimer.singleShot(0, lambda: heartbeat.append(True))
    QTest.mouseClick(button, Qt.MouseButton.LeftButton)
    button.setFocus()
    QTest.keyClick(button, Qt.Key.Key_Return)
    QTest.qWait(50)
    assert heartbeat == [True]
    assert not button.isEnabled()
    requests_per_attempt = {"server": 1, "register": 3}.get(action, 2)
    assert len(state["calls"]) == requests_per_attempt
    assert all(thread != ui_thread for _, _, thread in state["calls"])
    assert all(session is not network.session for session, _, _ in state["calls"])
    if action != "server":
        account_calls = [call for call in state["calls"] if not call[1].url.endswith("/auth/agreement/policy")]
        assert account_calls[0][0] is account_calls[1][0]
        body = json.loads(account_calls[1][1].body)
        encrypted = body.get("password") or body.get("new_password")
        assert (
            key.decrypt(
                base64.b64decode(encrypted),
                padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
            )
            == b"test-password"
        )
    state["gate"].set()
    if action != "server":
        wait_for(button.isEnabled)
        assert saves == []
        state["status"] = 200
        previous = len(state["calls"])
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        wait_for(lambda: len(state["calls"]) == previous + requests_per_attempt)
        if action == "login":
            wait_for(lambda: not window.isVisible())
            assert saves == [ui_thread]
            network.ws_transport.start.assert_called_once()
        elif action == "register":
            wait_for(lambda: window.tabs.currentIndex() == 0)
            assert window.l_username.text() == "test-user"
            assert saves == []
            network.ws_transport.start.assert_not_called()
        else:
            wait_for(lambda: not child.isVisible())
            assert window.l_username.text() == "test-user"
    else:
        wait_for(button.isEnabled)
        assert saves == []
        assert child.isVisible()
        state["get_status"] = 200
        previous = len(state["calls"])
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        wait_for(lambda: len(state["calls"]) == previous + 1)
        wait_for(lambda: not child.isVisible())
        assert saves == [ui_thread]
        assert network.base_url == "https://candidate.invalid"


def test_close_login_during_post_discards_late_success_without_local_login(account_window):
    window, network, state, saves, _key = account_window(post_status=200)
    window.l_username.setText("test-user")
    window.l_password.setText("test-password")
    QTest.mouseClick(window.l_btn, Qt.MouseButton.LeftButton)
    wait_for(lambda: len(state["calls"]) == 2)
    assert window.close()
    state["gate"].set()
    QTest.qWait(100)
    assert network.user_id is None
    assert saves == []
    network.ws_transport.start.assert_not_called()


def test_close_login_during_key_fetch_prevents_later_post(account_window):
    window, network, state, saves, _key = account_window(post_status=200, block="GET")
    window.l_username.setText("test-user")
    window.l_password.setText("test-password")
    QTest.mouseClick(window.l_btn, Qt.MouseButton.LeftButton)
    wait_for(lambda: len(state["calls"]) == 1)
    assert window.close()
    state["gate"].set()
    QTest.qWait(100)
    assert len(state["calls"]) == 1
    assert saves == []
    network.ws_transport.start.assert_not_called()


def test_child_close_keeps_parent_slot_until_request_finishes(account_window, qapp):
    window, network, state, saves, _key = account_window(post_status=200)
    snapshots = []

    def submit_reset():
        child = qapp.activeModalWidget()
        for field, value in zip(child.findChildren(QLineEdit), ["invite", "new-user", "new-password", "new-password"]):
            field.setText(value)
        QTest.mouseClick(child.findChild(QPushButton), Qt.MouseButton.LeftButton)
        wait_for(lambda: len(state["calls"]) == 2)
        child.reject()
        window.l_username.setText("test-user")
        window.l_password.setText("test-password")
        QTest.mouseClick(window.l_btn, Qt.MouseButton.LeftButton)
        window.l_btn.setFocus()
        QTest.keyClick(window.l_btn, Qt.Key.Key_Return)
        QTest.qWait(50)
        snapshots.append((len(state["calls"]), window.l_btn.isEnabled()))
        state["gate"].set()

    QTimer.singleShot(0, submit_reset)
    QTest.mouseClick(window.reset_btn, Qt.MouseButton.LeftButton)
    wait_for(window.l_btn.isEnabled)
    assert snapshots == [(2, False)]
    assert window.l_username.text() == "test-user"
    assert saves == []
    network.ws_transport.start.assert_not_called()
    # 旧子窗口真正删除也只会设置旧 ticket，不能取消后来的父请求。
    for child in window.findChildren(dialog_module.QDialog):
        child.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    QTest.mouseClick(window.l_btn, Qt.MouseButton.LeftButton)
    wait_for(lambda: not window.isVisible())
    network.ws_transport.start.assert_called_once()


def test_changed_identity_rejects_late_login_success(account_window):
    window, network, state, saves, _key = account_window(post_status=200)
    window.l_username.setText("test-user")
    window.l_password.setText("test-password")
    QTest.mouseClick(window.l_btn, Qt.MouseButton.LeftButton)
    wait_for(lambda: len(state["calls"]) == 2)
    network.set_base_url("https://changed.invalid", True)
    state["gate"].set()
    wait_for(window.l_btn.isEnabled)
    assert network.user_id is None
    assert saves == []
    assert window.isVisible()
    network.ws_transport.start.assert_not_called()


def test_synchronous_account_interfaces_keep_original_result_contract(account_window):
    _window, network, state, saves, _key = account_window(post_status=200)
    state["gate"].set()
    assert network.register("test-user", "test-password", "test-invite")[0] is True
    assert network.reset_account("test-invite", "test-user", "test-password")[0] is True
    assert network.login("test-user", "test-password") == (True, "Login Successful")
    assert network.user_id == "test-user"
    assert len(saves) == 1
    network.ws_transport.start.assert_called_once()


def test_disabled_policy_registers_without_opening_agreement(account_window, monkeypatch):
    window, network, state, saves, _key = account_window(post_status=200)
    state["gate"].set()
    monkeypatch.setattr(dialog_module.registration_resume, "load_pending", lambda: None)
    sign = Mock(side_effect=AssertionError("disabled policy must not open signing dialog"))
    monkeypatch.setattr(dialog_module, "AgreementSignDialog", sign)
    window.tabs.setCurrentIndex(1)
    window.r_username.setText("test-user")
    window.r_password.setText("test-password")
    window.r_confirm_password.setText("test-password")
    window.r_invite.setText("test-invite")
    window.do_register()
    wait_for(lambda: not window._account_operation.busy)
    assert window.tabs.currentIndex() == 0
    assert window.l_username.text() == "test-user"
    posts = [request for _, request, _ in state["calls"] if request.method == "POST"]
    assert len(posts) == 1
    payload = json.loads(posts[0].body)
    assert payload["username"] == "test-user"
    assert "accepted" not in payload
    sign.assert_not_called()


@pytest.mark.parametrize("policy", [True, "false"])
def test_registration_policy_requires_signing_or_rejects_invalid_policy_without_post(account_window, policy):
    window, network, state, _, _key = account_window(require_acceptance=policy)
    state["gate"].set()
    request = network.prepare_account_request("register", username="test-user", password="pw", invite="invite")
    ok, message, details = request.execute(threading.Event())
    assert not ok
    assert message
    assert details.get("code") == ("AGREEMENT_REQUIRED" if policy is True else None)
    assert not any(req.method == "POST" for _, req, _ in state["calls"])
