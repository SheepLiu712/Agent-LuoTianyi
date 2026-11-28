"""PR #455 N2：导出失败或取消后，桌面刷新重连按钮仍不可用。"""

import io
import json
import os
import threading
import zipfile
from urllib.parse import urlparse

import pytest
import requests
from PySide6.QtCore import QCoreApplication, QEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from src.gui import data_transfer_dialog as dialog_module
from src.gui.data_transfer_dialog import DataTransferDialog
from src.network.network_client import NetworkClient


def archive_bytes(entries=None):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in (entries or {"manifest.json": b"{}", "data.json": b"{}"}).items():
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


def wait_for(predicate):
    for _ in range(500):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "超过测试等待预算"


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield QApplication.instance() or QApplication([])


@pytest.fixture
def network():
    client = NetworkClient("https://transfer.invalid")
    client.user_id = "synthetic-user"
    client.message_token = "synthetic-token"
    return client


@pytest.fixture
def export_dialog(qapp, network, tmp_path, monkeypatch):
    state = {
        "calls": [],
        "block": None,
        "started": threading.Event(),
        "release": threading.Event(),
        "status": 200,
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
        return response_for(request, archive_bytes())

    monkeypatch.setattr(requests.Session, "send", send)
    dialog = DataTransferDialog(network)
    dialog.tabs.setCurrentIndex(0)
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


def test_export_failure_enables_refresh_reconnect(export_dialog, monkeypatch, tmp_path):
    """场景(a)：export 失败后，refresh 按钮必须可见且可用。"""
    dialog, state = export_dialog
    assert not dialog.refresh_button.isVisible()
    target = tmp_path / "export-fail.zip"
    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    state["status"] = 503
    dialog.export_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert dialog.refresh_button.isVisible()
    assert dialog.refresh_button.isEnabled()
    refreshed = []
    ui_thread = threading.get_ident()
    dialog.refresh_requested.connect(lambda: refreshed.append(threading.get_ident()))
    dialog.refresh_button.click()
    assert refreshed == [ui_thread]


@pytest.fixture
def import_dialog(qapp, network, tmp_path, monkeypatch):
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


def test_advanced_group_collapsed_by_default(import_dialog):
    """导入页高级设置默认折叠，预览后区域默认隐藏。"""
    dialog, _state = import_dialog
    assert not dialog.advanced_group.isChecked()
    assert not dialog.advanced_content.isVisible()
    assert not dialog.post_preview_area.isVisible()
    dialog.advanced_group.setChecked(True)
    assert dialog.advanced_content.isVisible()


def test_import_preview_reachable_with_stage_based_ui(import_dialog):
    """正常预览流程：点击预览 → 预览后区域显示 → details 自动展开。"""
    dialog, state = import_dialog
    assert not dialog.post_preview_area.isVisible()
    assert not dialog.commit_button.isEnabled()
    dialog.preview_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert dialog.post_preview_area.isVisible()
    assert dialog.commit_button.isEnabled()
    assert "聊天与关联媒体" in dialog.details.toPlainText()
    assert dialog.details.isVisible()


def test_export_cancel_enables_refresh_reconnect(export_dialog, monkeypatch, tmp_path):
    """场景(b)：export 取消并 settled 后，refresh 按钮必须可见且可用。"""
    dialog, state = export_dialog
    assert not dialog.refresh_button.isVisible()
    target = tmp_path / "export-cancel.zip"
    monkeypatch.setattr(dialog_module.QFileDialog, "getSaveFileName", lambda *args: (str(target), ""))
    state["block"] = "export"
    dialog.export_button.click()
    wait_for(state["started"].is_set)
    assert dialog.cancel_button.isVisible()
    assert dialog.cancel_button.isEnabled()
    dialog.cancel_button.click()
    assert dialog._cancelled
    state["release"].set()
    wait_for(lambda: not dialog.operation.busy)
    assert dialog.refresh_button.isVisible()
    assert dialog.refresh_button.isEnabled()
    refreshed = []
    ui_thread = threading.get_ident()
    dialog.refresh_requested.connect(lambda: refreshed.append(threading.get_ident()))
    dialog.refresh_button.click()
    assert refreshed == [ui_thread]


@pytest.mark.parametrize("extraction", ["not_requested", "failed"])
def test_import_result_is_concise_and_usage_preserves_receipt(import_dialog, extraction, monkeypatch):
    dialog, state = import_dialog
    state["commit_result"] = {
        "success": True,
        "committed": True,
        "imported": {"conversations": 2},
        "skipped": {},
        "extraction": {"status": extraction, "memories": 0},
        "warnings": [],
    }
    dialog.preview_button.click()
    wait_for(lambda: not dialog.operation.busy)
    dialog.commit_button.click()
    wait_for(lambda: not dialog.operation.busy)
    assert dialog.details.isVisible() == (extraction == "failed")
    assert "成功" in dialog.status_label.text()
    if extraction == "failed":
        assert "记忆提取未完成" in dialog.status_label.text()
    notices = []
    monkeypatch.setattr(dialog, "_show_information", lambda title, text: notices.append((title, text)))
    dialog.usage_button.click()
    assert notices[0][0] == "使用须知"
    assert "1 GiB" in notices[0][1]
    assert "记录 2" in notices[0][1]
