import json
import os
import sys
import threading
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

import pytest
import requests
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget
import shiboken6
from src.gui import main_ui as ui_module
from src.gui.binder import AgentBinder
from src.gui.main_ui import ChatWidget
from src.network.network_client import NetworkClient


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QApplication.instance() or QApplication([])
    yield app


def test_slow_unread_transport_keeps_chat_input_and_qt_heartbeat_responsive(qapp, monkeypatch):
    release = threading.Event()
    completed = threading.Event()
    started = threading.Event()
    requests_seen = []

    def send(_session, request, **kwargs):
        requests_seen.append((request.url, kwargs.get("timeout")))
        started.set()
        # 旧同步实现至多阻塞本测试 15 秒；异步实现验证期间由事件保持未完成。
        if not release.wait(15):
            release.set()
        response = requests.Response()
        response.status_code = 200
        response._content = json.dumps({"unread_count": 7}).encode("utf-8")
        response.request = request
        completed.set()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    network = NetworkClient("https://unread-test.invalid")
    network.user_id = "test-user"
    network.message_token = "test-token"
    binder = Mock(spec=AgentBinder)
    window = ChatWidget({}, binder, network)
    window.show()
    qapp.processEvents()
    heartbeats = []
    probe = []
    heartbeat = QTimer(window)
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: heartbeats.append(not release.is_set()))
    heartbeat.start()

    def inspect_pending_ui():
        probe.append((started.is_set(), not release.is_set(), window.input_box.toPlainText(), any(heartbeats)))

    watch = QTimer(window)
    watch.setInterval(5)

    def inspect_after_transport_started():
        if started.is_set():
            watch.stop()
            QTimer.singleShot(40, lambda: QTest.keyClicks(window.input_box, "draft"))
            QTimer.singleShot(100, inspect_pending_ui)

    watch.timeout.connect(inspect_after_transport_started)
    watch.start()
    QTimer.singleShot(0, window.refresh_dynamic_badge)
    try:
        for _ in range(500):
            if probe:
                break
            QTest.qWait(10)

        assert probe == [(True, True, "draft", True)]
        assert requests_seen and requests_seen[0][1] == 15
        binder.on_send_typing.assert_called()
    finally:
        release.set()
        assert completed.wait(2)
        heartbeat.stop()
        window.dynamic_badge_timer.stop()
        window.close()
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def wait_for(predicate):
    for _ in range(500):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "Qt observation did not complete within the test budget"


class ControlledUnreadTransport:
    def __init__(self, payloads):
        self.payloads = payloads
        self.gates = [threading.Event() for _ in payloads]
        self.calls = []
        self.closed = []
        self.active = 0
        self.max_active = 0
        self.lock = threading.Lock()

    def send(self, session, request, **kwargs):
        with self.lock:
            index = len(self.calls)
            self.calls.append((session, request, kwargs))
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            if index >= len(self.gates) or not self.gates[index].wait(5):
                raise requests.Timeout("test transport watchdog")
            payload = self.payloads[index]
            if isinstance(payload, Exception):
                raise payload
            response = requests.Response()
            response.status_code = 200
            response._content = json.dumps(payload).encode("utf-8")
            response.request = request
            return response
        finally:
            with self.lock:
                self.active -= 1

    def release_all(self):
        for gate in self.gates:
            gate.set()


@pytest.fixture
def unread_window(qapp, monkeypatch):
    windows = []
    transports = []
    original_close = requests.Session.close

    def create(payloads, owner=False):
        transport = ControlledUnreadTransport(payloads)
        transports.append(transport)
        monkeypatch.setattr(
            requests.Session, "send", lambda session, request, **kwargs: transport.send(session, request, **kwargs)
        )

        def close(session):
            transport.closed.append(session)
            original_close(session)

        monkeypatch.setattr(requests.Session, "close", close)
        network = NetworkClient("https://unread-test.invalid/base")
        network.user_id = "test-user"
        network.message_token = "test-token"
        binder = Mock(spec=AgentBinder)
        if owner:
            monkeypatch.setattr(ui_module, "Live2DContainer", lambda *args: QWidget())
            window = ui_module.MainWindow({"live2d_container": {}, "chat_window": {}}, {}, binder, network)
            chat = window.chat_widget
        else:
            window = chat = ChatWidget({}, binder, network)
        windows.append(window)
        window.show()
        # 使用生产 400ms 首刷，而非替换刷新或手动调用完成回调。
        wait_for(lambda: len(transport.calls) == 1)
        chat.dynamic_badge_timer.stop()
        return window, chat, network, transport

    yield create
    for transport in transports:
        transport.release_all()
    wait_for(lambda: all(transport.active == 0 for transport in transports))
    QTest.qWait(50)
    for window in windows:
        try:
            window.close()
            window.deleteLater()
        except RuntimeError:
            pass  # 生命周期用例已显式删除。
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_refreshes_are_single_flight_and_coalesce_with_isolated_authenticated_sessions(unread_window):
    _window, chat, network, transport = unread_window([{"unread_count": 7}, {"unread_count": 150}])
    for _ in range(8):
        chat.refresh_dynamic_badge()
    QTest.qWait(50)
    assert len(transport.calls) == 1
    transport.gates[0].set()
    wait_for(lambda: len(transport.calls) == 2)
    assert chat.dynamic_btn.text() == "7"
    assert transport.calls[0][0] in transport.closed
    transport.gates[1].set()
    wait_for(lambda: chat.dynamic_btn.text() == "99+")
    QTest.qWait(50)

    assert len(transport.calls) == 2
    assert transport.max_active == 1
    first_session, first_request, options = transport.calls[0]
    assert first_session is not network.session
    assert transport.calls[1][0] is not first_session
    assert parse_qs(urlparse(first_request.url).query) == {"username": ["test-user"]}
    assert urlparse(first_request.url).path == "/base/dynamics/unread"
    assert first_request.headers["Authorization"] == "Bearer test-token"
    assert options["verify"] is True
    assert options["timeout"] == 15
    wait_for(lambda: transport.calls[1][0] in transport.closed)


def test_failed_and_malformed_results_preserve_badge_then_allow_new_refresh(unread_window):
    _window, chat, _network, transport = unread_window(
        [{"unread_count": 9}, requests.Timeout("offline"), {"unread_count": "invalid"}, {"unread_count": 0}]
    )
    transport.gates[0].set()
    wait_for(lambda: chat.dynamic_btn.text() == "9")
    for index in (1, 2):
        chat.refresh_dynamic_badge()
        wait_for(lambda: len(transport.calls) == index + 1)
        transport.gates[index].set()
        wait_for(lambda: transport.calls[index][0] in transport.closed)
        QTest.qWait(50)
        assert chat.dynamic_btn.text() == "9"
    chat.refresh_dynamic_badge()
    wait_for(lambda: len(transport.calls) == 4)
    transport.gates[3].set()
    wait_for(lambda: chat.dynamic_btn.text() == "")
    assert transport.max_active == 1


def test_successful_mark_read_invalidates_old_unread_result(unread_window, monkeypatch):
    _window, chat, network, transport = unread_window([{"unread_count": 12}, {"unread_count": 0}])
    monkeypatch.setattr(network, "get_dynamics", lambda **kwargs: {"ok": True, "items": []})
    monkeypatch.setattr(network, "mark_dynamics_read", lambda: {"ok": True})
    QTest.mouseClick(chat.dynamic_btn, ui_module.Qt.MouseButton.LeftButton)
    assert chat.dynamic_dialog is not None
    transport.gates[0].set()
    wait_for(lambda: len(transport.calls) == 2)
    assert chat.dynamic_btn.text() != "12"
    transport.gates[1].set()
    wait_for(lambda: chat.dynamic_btn.text() == "")
    assert transport.max_active == 1


def test_account_revision_rejects_aba_result_even_when_credential_save_fails(unread_window, monkeypatch):
    _window, chat, network, transport = unread_window([{"unread_count": 11}, {"unread_count": 2}])
    network.auth_api.login = Mock(
        return_value=(True, "ok", {"user_id": "test-user", "message_token": "test-token", "login_token": "other"})
    )
    from src.network import network_client as network_module

    def cannot_save(*args):
        raise OSError("test credential store unavailable")

    monkeypatch.setattr(network_module.credential, "save_credentials", cannot_save)
    assert network.login("test-user", "test-password")[0] is False
    transport.gates[0].set()
    wait_for(lambda: len(transport.calls) == 2)
    assert chat.dynamic_btn.text() != "11"
    transport.gates[1].set()
    wait_for(lambda: chat.dynamic_btn.text() == "2")


def test_main_window_close_and_delete_do_not_wait_or_restart_pending_request(unread_window, qapp):
    owner, chat, _network, transport = unread_window([{"unread_count": 17}], owner=True)
    assert owner.close()
    assert not transport.gates[0].is_set()
    assert transport.active == 1
    probe = []
    QTimer.singleShot(0, lambda: probe.append("responsive"))
    QTest.qWait(50)
    assert probe == ["responsive"]
    chat.refresh_dynamic_badge()
    owner.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()
    transport.gates[0].set()
    wait_for(lambda: transport.active == 0)
    QTest.qWait(50)
    assert len(transport.calls) == 1


@pytest.mark.parametrize("changed", ["base_url", "user_id", "message_token"])
def test_changed_request_identity_drops_old_badge_and_uses_new_snapshot(unread_window, changed):
    _window, chat, network, transport = unread_window([{"unread_count": 18}, {"unread_count": 3}])
    setattr(
        network,
        changed,
        {"base_url": "https://changed.invalid", "user_id": "new-user", "message_token": "new-token"}[changed],
    )
    transport.gates[0].set()
    wait_for(lambda: len(transport.calls) == 2)
    assert chat.dynamic_btn.text() != "18"
    _session, request, _options = transport.calls[1]
    assert urlparse(request.url).hostname == urlparse(network.base_url).hostname
    assert parse_qs(urlparse(request.url).query) == {"username": [network.user_id]}
    assert request.headers["Authorization"] == f"Bearer {network.message_token}"
    transport.gates[1].set()
    wait_for(lambda: chat.dynamic_btn.text() == "3")


def test_deleting_chat_without_close_leaves_no_qt_callback_in_worker(unread_window, qapp):
    owner, chat, _network, transport = unread_window([{"unread_count": 22}])
    failures = []
    original_hook = sys.excepthook
    try:
        sys.excepthook = lambda *args: failures.append(args)
        chat.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not shiboken6.isValid(owner)
        transport.gates[0].set()
        wait_for(lambda: transport.active == 0)
        wait_for(lambda: transport.calls[0][0] in transport.closed)
        QTest.qWait(50)
        assert failures == []
        assert len(transport.calls) == 1
    finally:
        sys.excepthook = original_hook


def test_missing_network_clears_previous_badge_without_starting_request(unread_window):
    _owner, chat, _network, transport = unread_window([{"unread_count": 4}])
    transport.gates[0].set()
    wait_for(lambda: chat.dynamic_btn.text() == "4")
    chat.network_client = None
    chat.refresh_dynamic_badge()
    assert chat.dynamic_btn.text() == "动态"
    assert len(transport.calls) == 1


def test_close_before_initial_refresh_does_not_start_http(qapp, monkeypatch):
    calls = []
    monkeypatch.setattr(requests.Session, "send", lambda *args, **kwargs: calls.append(args))
    network = NetworkClient("https://unread-test.invalid")
    network.user_id = "test-user"
    window = ChatWidget({}, Mock(spec=AgentBinder), network)
    window.show()
    assert window.close()
    QTest.qWait(450)
    assert calls == []
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
