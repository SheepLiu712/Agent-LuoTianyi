"""客户端迁移 API、文件安全与 Qt 行为；全部使用合成数据和受控 HTTP。"""

import io
import json
import os
import stat
import threading
import zipfile
from urllib.parse import parse_qs, urlparse
from unittest.mock import Mock

import pytest
import requests
from PySide6.QtCore import QCoreApplication, QEvent, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from src.gui import data_transfer_dialog as dialog_module
from src.gui.data_transfer_dialog import DataTransferDialog
from src.network import data_transfer as transfer_module
from src.network.data_transfer import read_import_payload
from src.network.network_client import NetworkClient


def archive_bytes(entries=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in (entries or {"manifest.json": b"{}", "data.json": b"{}"}).items():
            # Windows 的 ZipInfo 构造会规范化反斜杠，显式保留恶意样本原名。
            info = zipfile.ZipInfo(name)
            info.filename = name
            archive.writestr(info, content)
    return output.getvalue()


def response_for(request, payload, status=200):
    response = requests.Response()
    response.request = request
    response.status_code = status
    response._content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    response._content_consumed = True
    return response


@pytest.fixture
def network():
    client = NetworkClient("https://transfer.invalid")
    client.user_id = "synthetic-user"
    client.message_token = "synthetic-token"
    return client


def test_preview_and_commit_use_bearer_raw_bytes_json_and_existing_tls(network, tmp_path, monkeypatch):
    source = tmp_path / "external.json"
    source.write_bytes(b'[{"role":"user","content":"synthetic"}]')
    calls = []

    def send(session, request, **kwargs):
        if hasattr(request.body, "read"):
            request.body = request.body.read()
        calls.append((request, kwargs))
        data = {"preview_id": "preview-1", "scope": "chat", "source_format": "generic", "counts": {}}
        if request.url.endswith("/commit"):
            data = {"success": True, "backup_id": "backup-1"}
        return response_for(request, data)

    monkeypatch.setattr(requests.Session, "send", send)
    request = network.prepare_data_transfer_request("preview", source_path=str(source), source_format="generic")
    assert request.execute(threading.Event())[0]
    commit = network.prepare_data_transfer_request(
        "commit", preview_id="preview-1", scope="chat", mode="replace", confirm_replace=True, extract_memories=True
    )
    assert commit.execute(threading.Event())[0]
    request, options = calls[0]
    assert request.method == "POST"
    assert parse_qs(urlparse(request.url).query) == {
        "source_format": ["generic"],
        "scope": ["all"],
        "character_id": ["luotianyi"],
    }
    assert request.body == source.read_bytes()
    assert request.headers["Content-Type"] == "application/octet-stream"
    for request, options in calls:
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        assert "username" not in request.url
        assert options["verify"] is True
    assert json.loads(calls[1][0].body) == {
        "preview_id": "preview-1",
        "mode": "replace",
        "confirm_replace": True,
        "extract_memories": True,
    }


def test_commit_requires_replace_confirmation_and_token_before_http(network, monkeypatch):
    calls = []
    monkeypatch.setattr(requests.Session, "send", lambda *args, **kwargs: calls.append(args))
    request = network.prepare_data_transfer_request("commit", preview_id="p", mode="replace")
    assert not request.execute(threading.Event())[0]
    network.message_token = None
    assert not network.prepare_data_transfer_request("export").execute(threading.Event())[0]
    assert calls == []


@pytest.mark.parametrize(
    "action,expected", [("export", "/user/data/export"), ("backup", "/user/data/backups/backup-1")]
)
def test_export_and_backup_save_real_download_with_tls(network, tmp_path, monkeypatch, action, expected):
    package = archive_bytes()
    calls = []

    def send(_session, request, **kwargs):
        calls.append(request)
        return response_for(request, package)

    monkeypatch.setattr(requests.Session, "send", send)
    target = tmp_path / "saved.zip"
    request = network.prepare_data_transfer_request(
        action, destination=str(target), backup_id="backup-1", scope="memory"
    )
    ok, _, result = request.execute(threading.Event())
    assert ok and result["path"] == str(target)
    assert target.read_bytes() == package
    assert urlparse(calls[0].url).path == expected
    assert calls[0].headers["Authorization"] == "Bearer synthetic-token"
    if action == "export":
        assert parse_qs(urlparse(calls[0].url).query) == {"scope": ["memory"], "format": ["zip"]}


@pytest.mark.parametrize("format,suffix", [("markdown", "md"), ("txt", "txt")])
def test_reading_export_saves_utf8_bytes_unchanged(network, tmp_path, monkeypatch, format, suffix):
    content = "仅用于测试的阅读副本".encode()
    monkeypatch.setattr(requests.Session, "send", lambda _s, req, **kw: response_for(req, content))
    target = tmp_path / f"reading.{suffix}"
    assert network.prepare_data_transfer_request("export", format=format, destination=str(target)).execute(
        threading.Event()
    )[0]
    assert target.read_bytes() == content


def test_directory_import_and_export_preserve_identical_relative_files(network, tmp_path, monkeypatch):
    original = tmp_path / "original"
    (original / "media" / "opaque").mkdir(parents=True)
    expected = {"manifest.json": b"{}", "data.json": b"{}", "media/opaque/content.bin": b"synthetic-media"}
    for name, content in expected.items():
        (original / name).write_bytes(content)
    package = read_import_payload(str(original), threading.Event())
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        assert {name: archive.read(name) for name in archive.namelist()} == expected
    monkeypatch.setattr(requests.Session, "send", lambda _s, req, **kw: response_for(req, package))
    target = tmp_path / "restored"
    result = network.prepare_data_transfer_request("export", destination=str(target), directory=True).execute(
        threading.Event()
    )
    assert result[0]
    assert {
        path.relative_to(target).as_posix(): path.read_bytes() for path in target.rglob("*") if path.is_file()
    } == expected


@pytest.mark.parametrize(
    "name", ["../escape", "/absolute", "C:/drive", "dir\\escape", "CON.txt", "a/../b", "a:stream", "a./b"]
)
def test_directory_download_rejects_unsafe_zip_before_publishing(network, tmp_path, monkeypatch, name):
    package = archive_bytes({name: b"unsafe"})
    monkeypatch.setattr(requests.Session, "send", lambda _s, req, **kw: response_for(req, package))
    target = tmp_path / "target"
    ok, _, _ = network.prepare_data_transfer_request("export", destination=str(target), directory=True).execute(
        threading.Event()
    )
    assert not ok and not target.exists()
    assert list(tmp_path.iterdir()) == []


def test_zip_rejects_symlinks_and_casefold_duplicates(tmp_path):
    for name, entries in (
        ("symlink.zip", None),
        ("duplicate.zip", {"data.json": b"a", "DATA.json": b"b"}),
        ("collision.zip", {"a": b"file", "a/b": b"nested"}),
    ):
        path = tmp_path / name
        if entries is not None:
            path.write_bytes(archive_bytes(entries))
        else:
            output = io.BytesIO()
            with zipfile.ZipFile(output, "w") as archive:
                info = zipfile.ZipInfo("link")
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, "../outside")
            path.write_bytes(output.getvalue())
        with pytest.raises(ValueError):
            read_import_payload(str(path), threading.Event())


def test_directory_import_refuses_symlink_without_reading_target(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("synthetic outside")
    try:
        (source / "link").symlink_to(outside)
    except OSError:
        pytest.skip("此 Windows 环境未授予创建符号链接权限")
    with pytest.raises(ValueError, match="符号链接"):
        read_import_payload(str(source), threading.Event())


def test_upload_limits_and_cancelled_download_preserve_existing_file(network, tmp_path, monkeypatch):
    source = tmp_path / "large.json"
    source.write_bytes(b"12345")
    monkeypatch.setattr(transfer_module, "MAX_UPLOAD_BYTES", 4)
    with pytest.raises(ValueError, match="1 GiB"):
        read_import_payload(str(source), threading.Event())
    monkeypatch.setattr(transfer_module, "MAX_UPLOAD_BYTES", 64 * 1024 * 1024)
    cancelled = threading.Event()

    def send(_session, req, **kw):
        response = response_for(req, b"new")

        def chunks(**kwargs):
            cancelled.set()
            yield b"new"

        response.iter_content = chunks
        return response

    monkeypatch.setattr(requests.Session, "send", send)
    target = tmp_path / "existing.zip"
    target.write_bytes(b"original")
    assert not network.prepare_data_transfer_request("export", destination=str(target)).execute(cancelled)[0]
    assert target.read_bytes() == b"original"
    assert not list(tmp_path.glob(".agentluo-transfer-*"))


def test_archive_entry_and_expanded_limits(tmp_path, monkeypatch):
    source = tmp_path / "limited.zip"
    source.write_bytes(archive_bytes())
    monkeypatch.setattr(transfer_module, "MAX_ARCHIVE_ENTRIES", 1)
    with pytest.raises(ValueError, match="4096"):
        read_import_payload(str(source), threading.Event())
    monkeypatch.setattr(transfer_module, "MAX_ARCHIVE_ENTRIES", 4096)
    monkeypatch.setattr(transfer_module, "MAX_EXPANDED_BYTES", 1)
    with pytest.raises(ValueError, match="2 GiB"):
        read_import_payload(str(source), threading.Event())


@pytest.mark.parametrize("status", [401, 409, 503])
def test_http_failure_never_writes_download(network, tmp_path, monkeypatch, status):
    monkeypatch.setattr(
        requests.Session, "send", lambda _s, req, **kw: response_for(req, {"detail": "synthetic-error"}, status)
    )
    target = tmp_path / "not-saved.zip"
    ok, message, _ = network.prepare_data_transfer_request("export", destination=str(target)).execute(threading.Event())
    assert not ok and f"HTTP {status}" in message
    assert not target.exists()


def test_http_error_preserves_only_known_receipt_fields_and_never_reports_success(network, monkeypatch):
    receipt = {
        "backup_id": "recovery-500",
        "committed": False,
        "failed_phase": "commit",
        "code": "TRANSFER_RECEIPT_UNAVAILABLE",
        "rollback_error": None,
    }
    monkeypatch.setattr(
        requests.Session,
        "send",
        lambda _s, req, **kw: response_for(
            req, {"detail": {**receipt, "success": True, "unexpected": "must-not-be-forwarded"}}, 500
        ),
    )
    ok, message, data = network.prepare_data_transfer_request("commit", preview_id="preview-1").execute(
        threading.Event()
    )
    assert ok is False
    assert message == "HTTP 500：TRANSFER_RECEIPT_UNAVAILABLE"
    assert data == receipt


@pytest.mark.parametrize("payload", [{"success": True, "backup_id": "unexpected"}, {"detail": ["unexpected"]}, []])
def test_http_error_does_not_promote_unstructured_payload_to_receipt(network, monkeypatch, payload):
    monkeypatch.setattr(requests.Session, "send", lambda _s, req, **kw: response_for(req, payload, 500))
    assert network.prepare_data_transfer_request("commit", preview_id="preview-1").execute(threading.Event()) == (
        False,
        "HTTP 500",
        {},
    )


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield QApplication.instance() or QApplication([])


def wait_for(predicate):
    for _ in range(500):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "超过测试等待预算"


@pytest.fixture
def window(qapp, network, tmp_path, monkeypatch):
    path = tmp_path / "external.json"
    path.write_text('[{"role":"user","content":"synthetic"}]')
    state = {
        "calls": [],
        "block": None,
        "started": threading.Event(),
        "release": threading.Event(),
        "status": 200,
        "source_format": "generic",
        "commit_result": None,
    }

    def send(_session, request, **kwargs):
        action = urlparse(request.url).path.rsplit("/", 1)[-1]
        state["calls"].append((action, request, threading.get_ident()))
        if state["block"] == action:
            state["started"].set()
            if not state["release"].wait(5):
                raise requests.Timeout("test watchdog")
        if state["status"] != 200:
            return response_for(request, {"detail": "synthetic-error"}, state["status"])
        if action == "preview":
            payload = {
                "preview_id": "preview-1",
                "source_format": state["source_format"],
                "scope": "chat",
                "counts": {"conversations": 2, "memories": 0, "media": 0},
                "warnings": ["仅导入文字"],
            }
        elif action == "commit":
            payload = state["commit_result"] or {
                "success": True,
                "committed": True,
                "failed_phase": None,
                "imported": {"conversations": 2},
                "skipped": {},
                "backup_id": "backup-1",
                "extraction": {"status": "failed", "memories": 0, "error": "synthetic-model-unavailable"},
                "warnings": [],
            }
        else:
            payload = archive_bytes()
        return response_for(request, payload)

    monkeypatch.setattr(requests.Session, "send", send)
    dialog = DataTransferDialog(network)
    dialog.tabs.setCurrentIndex(1)
    dialog.source_path.setText(str(path))
    dialog.show()
    qapp.processEvents()
    yield dialog, state
    state["release"].set()
    if dialog.operation.busy:
        wait_for(lambda: not dialog.operation.busy)
    dialog.close()
    dialog.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def preview(window):
    dialog, state = window
    dialog.preview_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert dialog.commit_button.isEnabled()
    return dialog, state


def test_import_controls_remain_readable_with_preview_and_advanced_settings(window, qapp):
    dialog, _state = preview(window)
    dialog.resize(560, 620)
    for expanded in (False, True, False):
        dialog.advanced_group.setChecked(expanded)
        qapp.processEvents()
        scroll = dialog.tabs.currentWidget()
        scroll.ensureWidgetVisible(dialog.commit_button)
        qapp.processEvents()
        assert dialog.commit_button.height() >= dialog.commit_button.sizeHint().height()
        assert dialog.commit_button.visibleRegion().boundingRect().height() == dialog.commit_button.height()
        if not expanded:
            assert dialog.advanced_group.height() <= dialog.advanced_group.sizeHint().height()


def test_gui_preview_defaults_merge_then_commit_off_thread_and_backup_download(window, tmp_path, monkeypatch):
    dialog, state = preview(window)
    assert dialog.mode_combo.currentData() == "merge"
    assert not dialog.extract_checkbox.isChecked()
    assert "聊天与关联媒体" in dialog.details.toPlainText()
    assert "仅导入文字" in dialog.details.toPlainText()
    ui_thread = threading.get_ident()
    dialog.commit_button.click()
    dialog._commit()
    wait_for(lambda: not dialog.operation.busy)
    commits = [call for call in state["calls"] if call[0] == "commit"]
    assert len(commits) == 1
    assert json.loads(commits[0][1].body)["mode"] == "merge"
    assert json.loads(commits[0][1].body)["extract_memories"] is False
    assert all(call[2] != ui_thread for call in state["calls"])
    assert not dialog.commit_button.isEnabled()
    assert dialog.backup_button.isEnabled()
    assert "失败（聊天保留）" in dialog.details.toPlainText()
    assert dialog.refresh_button.isEnabled()
    refreshed = []
    dialog.refresh_requested.connect(lambda: refreshed.append(threading.get_ident()))
    dialog.refresh_button.click()
    assert refreshed == [ui_thread]
    target = tmp_path / "recovery.zip"
    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    dialog.backup_button.click()
    wait_for(lambda: not dialog.operation.busy)
    with zipfile.ZipFile(target) as archive:
        assert archive.namelist() == ["manifest.json", "data.json"]


def test_replace_cancel_sends_nothing_then_confirms_actual_preview_scope(window, monkeypatch):
    dialog, state = preview(window)
    dialog.mode_combo.setCurrentIndex(1)
    confirmations = []

    def no(_parent, _title, text, *args):
        confirmations.append(text)
        return QMessageBox.StandardButton.No

    monkeypatch.setattr(dialog_module.QMessageBox, "question", no)
    dialog.commit_button.click()
    assert [call[0] for call in state["calls"]] == ["preview"]
    assert "聊天与关联媒体" in confirmations[0]
    assert "长期记忆" not in confirmations[0]
    monkeypatch.setattr(dialog_module.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    dialog.extract_checkbox.setChecked(True)
    dialog.commit_button.click()
    wait_for(lambda: not dialog.operation.busy)
    body = json.loads(state["calls"][-1][1].body)
    assert body == {"preview_id": "preview-1", "mode": "replace", "confirm_replace": True, "extract_memories": True}


def test_pending_preview_remains_responsive_blocks_duplicates_and_cancel_discards_late_result(window):
    dialog, state = window
    state["block"] = "preview"
    beats = []
    heartbeat = QTimer(dialog)
    heartbeat.setInterval(5)
    heartbeat.timeout.connect(lambda: beats.append(True))
    heartbeat.start()
    dialog.preview_button.click()
    wait_for(state["started"].is_set)
    QTest.qWait(30)
    dialog._preview_import()
    assert beats and not dialog.preview_button.isEnabled()
    assert len(state["calls"]) == 1
    dialog.cancel_button.click()
    assert dialog.operation.busy
    state["release"].set()
    wait_for(lambda: not dialog.operation.busy)
    assert dialog._preview is None and not dialog.commit_button.isEnabled()
    assert "已取消" in dialog.status_label.text()
    heartbeat.stop()


def test_commit_cannot_be_cancelled_and_failures_require_new_preview(window):
    dialog, state = preview(window)
    state["block"] = "commit"
    state["status"] = 409
    dialog.commit_button.click()
    wait_for(state["started"].is_set)
    assert not dialog.cancel_button.isEnabled()
    dialog.reject()
    assert dialog.isVisible()
    state["release"].set()
    wait_for(lambda: not dialog.operation.busy)
    assert not dialog.commit_button.isEnabled()
    assert dialog.preview_button.isEnabled()
    assert "HTTP 409" in dialog.status_label.text()
    state["status"] = 200
    dialog.preview_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert dialog.commit_button.isEnabled()


def test_http_200_commit_failure_shows_errors_and_keeps_backup_download(window, tmp_path, monkeypatch):
    dialog, state = preview(window)
    state["commit_result"] = {
        "success": False,
        "committed": False,
        "failed_phase": "commit",
        "backup_id": "backup-1",
        "error": "synthetic-write-error",
        "rollback_error": "synthetic-rollback-error",
    }
    dialog.commit_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert "操作失败" in dialog.status_label.text()
    assert "synthetic-write-error" in dialog.details.toPlainText()
    assert "synthetic-rollback-error" in dialog.details.toPlainText()
    assert dialog.backup_button.isEnabled()
    target = tmp_path / "failed-commit-backup.zip"
    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    dialog.backup_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert target.read_bytes() == archive_bytes()


def test_http_500_commit_receipt_enables_backup_and_downloads_same_id(window, tmp_path, monkeypatch):
    dialog, _state = preview(window)
    dialog.mode_combo.setCurrentIndex(1)
    monkeypatch.setattr(dialog_module.QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    calls = []
    receipt = {
        "code": "TRANSFER_RECEIPT_UNAVAILABLE",
        "backup_id": "recovery-500",
        "committed": False,
        "failed_phase": "commit",
        "rollback_error": None,
    }
    package = archive_bytes()

    def send(_session, request, **options):
        calls.append((request, options, threading.get_ident()))
        if urlparse(request.url).path.endswith("/commit"):
            return response_for(request, {"detail": receipt}, 500)
        return response_for(request, package)

    monkeypatch.setattr(requests.Session, "send", send)
    ui_thread = threading.get_ident()
    dialog.commit_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert "操作失败：HTTP 500：TRANSFER_RECEIPT_UNAVAILABLE" in dialog.status_label.text()
    assert "数据导入完成" not in dialog.status_label.text()
    assert not dialog.commit_button.isEnabled()
    assert dialog.backup_button.isEnabled()
    assert dialog.refresh_button.isEnabled()
    assert "替换前恢复备份已生成" in dialog.details.toPlainText()

    target = tmp_path / "failed-commit-recovery.zip"
    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    dialog.backup_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert target.read_bytes() == package
    assert [(request.method, urlparse(request.url).path) for request, _options, _thread in calls] == [
        ("POST", "/user/data/import/commit"),
        ("GET", "/user/data/backups/recovery-500"),
    ]
    for request, options, thread in calls:
        assert request.headers["Authorization"] == "Bearer synthetic-token"
        assert options["verify"] is True
        assert thread != ui_thread


def test_failed_extraction_retries_same_preview_without_reupload(window):
    dialog, state = preview(window)
    dialog.extract_checkbox.setChecked(True)
    dialog.commit_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert dialog.retry_extraction_button.isEnabled()
    first = json.loads(state["calls"][-1][1].body)
    state["commit_result"] = {
        "success": True,
        "committed": True,
        "extraction": {"status": "succeeded", "memories": 1},
    }
    dialog.retry_extraction_button.click()
    dialog._retry_extraction()
    wait_for(lambda: not dialog.operation.busy)
    assert [call[0] for call in state["calls"]] == ["preview", "commit", "commit"]
    assert json.loads(state["calls"][-1][1].body) == first
    assert not dialog.retry_extraction_button.isVisible()
    assert "成功；生成 1 条" in dialog.details.toPlainText()


def test_native_preview_never_enables_extraction(window):
    dialog, state = window
    state["source_format"] = "native"
    preview(window)
    assert not dialog.extract_checkbox.isEnabled()
    assert not dialog.extract_checkbox.isChecked()


def test_account_switch_ignores_late_preview_and_changed_input_invalidates_preview(window, network):
    dialog, state = window
    state["block"] = "preview"
    dialog.preview_button.click()
    wait_for(state["started"].is_set)
    network.message_token = "different-synthetic-token"
    state["release"].set()
    wait_for(lambda: not dialog.operation.busy)
    assert dialog._preview is None
    assert "账号或服务器已变更" in dialog.status_label.text()
    state["block"] = None
    preview(window)
    dialog.character_id.setText("another-character")
    assert not dialog.commit_button.isEnabled()


def test_account_switch_after_preview_cannot_commit_old_preview(window, network):
    dialog, state = preview(window)
    network.message_token = "different-synthetic-token"
    dialog.commit_button.click()
    assert [call[0] for call in state["calls"]] == ["preview"]
    assert not dialog.commit_button.isEnabled()


def test_file_picker_cancellation_starts_no_request(window, monkeypatch):
    dialog, state = window
    monkeypatch.setattr(dialog_module.QFileDialog, "getOpenFileName", lambda *args: ("", ""))
    monkeypatch.setattr(dialog_module.QFileDialog, "getExistingDirectory", lambda *args: "")
    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", lambda *args: ("", ""))
    dialog._choose_file()
    dialog._choose_directory()
    dialog._export()
    assert state["calls"] == []


def test_settings_entry_refreshes_history_through_existing_async_binder(qapp, network, monkeypatch):
    from PySide6.QtWidgets import QLabel

    from src.gui import main_ui
    from src.gui.binder import AgentBinder

    binder = Mock(spec=AgentBinder)
    network.ws_transport.request_reconnect = Mock()
    chat = main_ui.ChatWidget({}, binder, network)
    chat.stop_dynamic_badge()
    old_message = QLabel("synthetic old message")
    chat.history_layout.insertWidget(0, old_message)
    chat.agent_bubbles["old"] = old_message
    chat.current_history_index = 100
    opened = []

    class TransferMenu(main_ui.QMenu):
        def exec(self, *_args):
            return self.actions()[-1]

    class ImmediateTransferDialog(DataTransferDialog):
        def exec(self):
            opened.append(self.windowTitle())
            self.refresh_requested.emit()
            self.reject()
            return 0

    # 用显式子类替换模态入口，避免 PySide 原生 exec 描述符绕过方法 monkeypatch。
    monkeypatch.setattr(main_ui, "QMenu", TransferMenu)
    monkeypatch.setattr(main_ui, "DataTransferDialog", ImmediateTransferDialog)
    try:
        chat.open_settings()
        assert opened == ["聊天与记忆迁移"]
        network.ws_transport.request_reconnect.assert_called_once()
        binder.on_stop_local_tts.assert_called_once()
        binder.on_load_history.assert_called_once_with(chat.load_history_num, -1)
        assert chat.agent_bubbles == {}
        assert chat.current_history_index == -1 and chat.first_load and chat.is_loading_history
        assert chat.history_layout.count() == 1  # 原有底部 stretch 仍在。
    finally:
        chat.close()
        chat.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        qapp.processEvents()


def test_preview_streams_file_above_previous_limit(network, tmp_path, monkeypatch):
    source = tmp_path / "large.json"
    size = 65 * 1024 * 1024
    with source.open("wb") as stream:
        stream.truncate(size)
    received = []

    def send(_session, request, **kwargs):
        assert hasattr(request.body, "read")
        assert int(request.headers["Content-Length"]) == size
        received.append(sum(len(chunk) for chunk in iter(lambda: request.body.read(64 * 1024), b"")))
        return response_for(request, {"preview_id": "large-preview", "scope": "chat"})

    monkeypatch.setattr(requests.Session, "send", send)
    request = network.prepare_data_transfer_request("preview", source_path=str(source))
    assert request.execute(threading.Event())[0]
    assert received == [size]
