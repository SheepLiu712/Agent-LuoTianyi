import json
import os
import sys
import threading
from urllib.parse import urlparse, parse_qs

import pytest
import requests
from PySide6.QtCore import QCoreApplication, QEvent, QTimer, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QLabel
from src.gui import dynamics_dialog as module
from src.gui.dynamics_dialog import DynamicsDialog
from src.network.network_client import NetworkClient


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield QApplication.instance() or QApplication([])


def test_slow_first_page_returns_constructor_and_keeps_window_responsive(qapp, monkeypatch):
    release = threading.Event()
    started = threading.Event()
    finished = threading.Event()
    calls = []
    windows = []
    pulses = []
    probes = []

    def send(_session, request, **kwargs):
        calls.append(request.url)
        started.set()
        if not release.wait(1):
            release.set()
        response = requests.Response()
        response.status_code = 503
        response._content = b"{}"
        response.request = request
        finished.set()
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    network = NetworkClient("https://dynamic-test.invalid")
    network.user_id = "test-user"
    network.message_token = "test-token"
    heartbeat = QTimer()
    heartbeat.setInterval(10)
    heartbeat.timeout.connect(lambda: pulses.append(not release.is_set()))
    heartbeat.start()

    def open_window():
        window = DynamicsDialog(network)
        windows.append(window)
        window.show()

    def inspect_pending():
        if windows:
            QTest.mouseClick(windows[0].refresh_button, Qt.MouseButton.LeftButton)
            probes.append((not release.is_set(), any(pulses), windows[0].isVisible(), len(calls)))
        else:
            probes.append((not release.is_set(), any(pulses), False, len(calls)))

    watch = QTimer()
    watch.setInterval(5)

    def await_transport():
        if started.is_set():
            watch.stop()
            QTimer.singleShot(50, inspect_pending)

    watch.timeout.connect(await_transport)
    watch.start()
    QTimer.singleShot(0, open_window)
    try:
        for _ in range(500):
            if probes:
                break
            QTest.qWait(10)
        assert probes == [(True, True, True, 1)]
    finally:
        release.set()
        assert finished.wait(2)
        heartbeat.stop()
        watch.stop()
        for window in windows:
            window.close()
            window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def wait_for(predicate):
    for _ in range(500):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "observation exceeded test budget"


def detail_text(window):
    return " ".join(label.text() for label in window.comments_text.findChildren(QLabel)) + " ".join(
        window.comments_text.item(i).text() for i in range(window.comments_text.count())
    )


class DynamicTransport:
    def __init__(self):
        self.calls = []
        self.pending = []
        self.comments_gate = None
        self.write_gate = None
        self.page_gate = None
        self.write_status = 200
        self.feed_status = 200
        self.comment_status = 200
        self.reads = 0
        self.active_writes = 0
        self.max_writes = 0
        self.lock = threading.Lock()

    def send(self, session, request, **kwargs):
        path = urlparse(request.url).path
        query = parse_qs(urlparse(request.url).query)
        with self.lock:
            self.calls.append((request.method, path, query, request.body, session, threading.get_ident()))
        gate = None
        code = 200
        if request.method == "GET" and path == "/dynamics":
            gate = self.page_gate
            code = self.feed_status
            items = (
                [{"id": "C", "content": "post C", "allow_comment": True}]
                if query.get("cursor")
                else [
                    {"id": "A", "content": "post A", "allow_comment": True},
                    {"id": "B", "content": "post B", "allow_comment": True},
                ]
            )
            payload = {
                "items": items,
                "has_more": not bool(query.get("cursor")),
                "next_cursor": None if query.get("cursor") else "page-2",
            }
        elif request.method == "GET":
            target = path.split("/")[2]
            gate = self.comments_gate
            code = self.comment_status
            payload = {"items": [{"content": "comment-" + target, "author_type": "user"}]}
        elif path == "/dynamics/read":
            self.reads += 1
            payload = {"ok": True}
        else:
            gate = self.write_gate
            code = self.write_status
            payload = {"item": {"id": "created"}, "detail": "test failure"}
        writing = request.method == "POST"
        if writing:
            with self.lock:
                self.active_writes += 1
                self.max_writes = max(self.max_writes, self.active_writes)
        try:
            if gate is not None:
                self.pending.append(gate)
                if not gate.wait(5):
                    raise requests.Timeout("test watchdog")
            response = requests.Response()
            response.status_code = code
            response._content = json.dumps(payload).encode()
            response.request = request
            return response
        finally:
            if writing:
                with self.lock:
                    self.active_writes -= 1


@pytest.fixture
def dynamic_window(qapp, monkeypatch):
    windows = []
    transports = []

    def create():
        transport = DynamicTransport()
        transports.append(transport)
        monkeypatch.setattr(
            requests.Session, "send", lambda session, request, **kwargs: transport.send(session, request, **kwargs)
        )
        monkeypatch.setattr(module.QMessageBox, "warning", lambda *args: None)
        monkeypatch.setattr(module.QMessageBox, "information", lambda *args: None)
        network = NetworkClient("https://dynamic-test.invalid")
        network.user_id = "test-user"
        network.message_token = "test-token"
        read_notices = []
        window = DynamicsDialog(network, on_read_callback=lambda: read_notices.append(True))
        windows.append(window)
        window.show()
        wait_for(lambda: window.dynamic_list.count() >= 2)
        wait_for(lambda: transport.reads == 1)
        wait_for(lambda: window.comment_button.isEnabled())
        return window, network, transport, read_notices

    yield create
    # 先隐藏窗口，禁止完成回调派生新请求；再释放并等待已有 worker。
    # 固定等待不能保证慢 CI 上的请求已退出，残留请求会误用下一例的全局 HTTP 替身。
    live_windows = [window for window in windows if module.isValid(window)]
    for window in live_windows:
        window.close()
    for transport in transports:
        for gate in transport.pending:
            gate.set()
        for gate in (transport.comments_gate, transport.write_gate, transport.page_gate):
            if gate is not None:
                gate.set()
    for window in live_windows:
        operations = window.findChildren(module.WindowOperation)
        wait_for(lambda: all(not operation.busy for operation in operations))
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_selection_latest_and_failed_pagination_preserve_cursor_and_selection(dynamic_window):
    window, network, transport, _notices = dynamic_window()
    wait_for(lambda: "comment-A" in detail_text(window))
    old_gate = transport.comments_gate = threading.Event()
    window.dynamic_list.setCurrentRow(1)
    wait_for(lambda: any(call[1] == "/dynamics/B/comments" for call in transport.calls))
    window.dynamic_list.setCurrentRow(0)
    transport.comments_gate = None
    old_gate.set()
    wait_for(lambda: "comment-A" in detail_text(window))
    assert "comment-B" not in detail_text(window)
    assert window.current_dynamic["id"] == "A"
    transport.feed_status = 503
    window.load_more_dynamics()
    wait_for(window.refresh_button.isEnabled)
    assert window.next_cursor == "page-2"
    assert window.current_dynamic["id"] == "A"
    transport.feed_status = 200
    page_gate = transport.page_gate = threading.Event()
    previous_pages = len([call for call in transport.calls if call[2].get("cursor") == ["page-2"]])
    window.load_more_dynamics()
    wait_for(
        lambda: len([call for call in transport.calls if call[2].get("cursor") == ["page-2"]]) == previous_pages + 1
    )
    window.dynamic_list.setCurrentRow(1)
    assert window.current_dynamic["id"] == "B"
    page_gate.set()
    wait_for(lambda: window.next_cursor is None)
    ids = [
        window.dynamic_list.item(i).data(Qt.ItemDataRole.UserRole).get("id")
        for i in range(window.dynamic_list.count())
        if isinstance(window.dynamic_list.item(i).data(Qt.ItemDataRole.UserRole), dict)
    ]
    assert ids == ["A", "B", "C"]
    assert window.current_dynamic["id"] == "B"
    assert all(call[4] is not network.session for call in transport.calls)
    assert all(call[5] != threading.get_ident() for call in transport.calls)


def test_comment_single_flight_failure_draft_and_hidden_window_terminal_recovery(dynamic_window):
    window, _network, transport, notices = dynamic_window()
    wait_for(lambda: "comment-A" in detail_text(window))
    gate = transport.write_gate = threading.Event()
    transport.write_status = 503
    window.comment_input.setPlainText("draft-A")
    QTest.mouseClick(window.comment_button, Qt.MouseButton.LeftButton)
    wait_for(lambda: any(call[0] == "POST" and call[1] == "/dynamics/A/comments" for call in transport.calls))
    QTest.mouseClick(window.comment_button, Qt.MouseButton.LeftButton)
    QTest.keyClick(window.comment_input, Qt.Key.Key_Return)
    window.mark_read()
    window.mark_read()
    QTest.qWait(50)
    assert len([call for call in transport.calls if call[0] == "POST" and call[1].endswith("/comments")]) == 1
    gate.set()
    wait_for(window.comment_button.isEnabled)
    assert window.comment_input.toPlainText() == "draft-A"
    wait_for(lambda: transport.reads == 2)
    assert transport.max_writes == 1
    # 下一次用户主动发送成功；隐藏重开不能在旧POST仍阻塞时重复发送。
    transport.write_status = 200
    gate = transport.write_gate = threading.Event()
    QTest.mouseClick(window.comment_button, Qt.MouseButton.LeftButton)
    wait_for(
        lambda: len([call for call in transport.calls if call[0] == "POST" and call[1].endswith("/comments")]) == 2
    )
    window.close()
    window.show()
    QTest.keyClick(window.comment_input, Qt.Key.Key_Return)
    QTest.qWait(50)
    assert len([call for call in transport.calls if call[0] == "POST" and call[1].endswith("/comments")]) == 2
    gate.set()
    wait_for(window.comment_button.isEnabled)
    assert window.comment_input.toPlainText() == "draft-A"
    assert transport.max_writes == 1
    assert len(notices) >= 1


def test_first_page_failure_does_not_mark_read_and_manual_refresh_recovers(qapp, monkeypatch):
    transport = DynamicTransport()
    transport.feed_status = 503
    monkeypatch.setattr(
        requests.Session, "send", lambda session, request, **kwargs: transport.send(session, request, **kwargs)
    )
    network = NetworkClient("https://dynamic-test.invalid")
    network.user_id = "test-user"
    network.message_token = "test-token"
    window = DynamicsDialog(network)
    window.show()
    try:
        wait_for(lambda: "失败" in window.feed_status.text())
        assert transport.reads == 0
        transport.feed_status = 200
        QTest.mouseClick(window.refresh_button, Qt.MouseButton.LeftButton)
        wait_for(lambda: transport.reads == 1)
        assert window.dynamic_list.count() >= 2
    finally:
        window.close()
        operations = window.findChildren(module.WindowOperation)
        wait_for(lambda: all(not operation.busy for operation in operations))
        window.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def test_publish_editor_is_single_flight_and_preserves_failed_draft(dynamic_window, qapp):
    window, _network, transport, _notices = dynamic_window()
    opened = []

    def prepare_editor():
        editor = qapp.activeModalWidget()
        editor.setModal(False)
        editor.hide()
        opened.append(editor)

    QTimer.singleShot(0, prepare_editor)
    QTest.mouseClick(window.add_dynamic_button, Qt.MouseButton.LeftButton)
    editor = opened[0]
    editor.show()
    editor.input.setPlainText("draft-post")
    gate = transport.write_gate = threading.Event()
    transport.write_status = 503
    QTest.mouseClick(editor.publish_button, Qt.MouseButton.LeftButton)
    wait_for(lambda: any(call[0] == "POST" and call[1] == "/dynamics" for call in transport.calls))
    QTest.mouseClick(editor.publish_button, Qt.MouseButton.LeftButton)
    QTest.qWait(30)
    assert len([call for call in transport.calls if call[0] == "POST" and call[1] == "/dynamics"]) == 1
    gate.set()
    wait_for(editor.publish_button.isEnabled)
    assert editor.isVisible()
    assert editor.input.toPlainText() == "draft-post"
    transport.write_status = 200
    QTest.mouseClick(editor.publish_button, Qt.MouseButton.LeftButton)
    wait_for(lambda: not editor.isVisible())
    assert len([call for call in transport.calls if call[0] == "POST" and call[1] == "/dynamics"]) == 2
    assert transport.max_writes == 1


def test_identity_change_discards_old_comments_and_deleted_window_is_safe(dynamic_window, qapp):
    window, network, transport, _notices = dynamic_window()
    wait_for(lambda: "comment-A" in detail_text(window))
    gate = transport.comments_gate = threading.Event()
    window.dynamic_list.setCurrentRow(1)
    wait_for(lambda: any(call[1] == "/dynamics/B/comments" for call in transport.calls))
    network.set_base_url("https://changed.invalid", True)
    gate.set()
    QTest.qWait(100)
    assert "comment-B" not in detail_text(window)
    window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_deleted_editor_during_post_leaves_no_deleted_qt_callback(dynamic_window, qapp):
    window, _network, transport, _notices = dynamic_window()
    opened = []

    def prepare_editor():
        editor = qapp.activeModalWidget()
        editor.setModal(False)
        editor.hide()
        opened.append(editor)

    QTimer.singleShot(0, prepare_editor)
    QTest.mouseClick(window.add_dynamic_button, Qt.MouseButton.LeftButton)
    editor = opened[0]
    editor.show()
    editor.input.setPlainText("delete-during-post")
    gate = transport.write_gate = threading.Event()
    QTest.mouseClick(editor.publish_button, Qt.MouseButton.LeftButton)
    wait_for(lambda: any(call[0] == "POST" and call[1] == "/dynamics" for call in transport.calls))
    failures = []
    hook = sys.excepthook
    try:
        sys.excepthook = lambda *args: failures.append(args)
        editor.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        assert not module.isValid(editor)
        gate.set()
        wait_for(window.add_dynamic_button.isEnabled)
        assert failures == []
        assert len([call for call in transport.calls if call[0] == "POST" and call[1] == "/dynamics"]) == 1
    finally:
        sys.excepthook = hook
