"""桌面 client LLM 设置对话框：单页模块列表、预检、统一校验与原子保存测试。"""

import json

import pytest
from PySide6.QtCore import QByteArray, QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QMessageBox

import src.gui.llm_settings_dialog as dlg_mod
from src.gui.llm_settings_dialog import LLMSettingsDialog, MODULE_TITLES
from src.safety import credential


PROVIDERS = [
    {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com/v1",
        "llm_models": ["deepseek-v4-flash"],
        "vlm_models": [],
    },
    {
        "name": "VlmOnly",
        "base_url": "https://v/v1",
        "llm_models": [],
        "vlm_models": ["vlm-model"],
    },
    {
        "name": "Both",
        "base_url": "https://b/v1",
        "llm_models": ["b1", "b2"],
        "vlm_models": ["vb1"],
    },
]

PROVIDERS_PAYLOAD = {
    "providers": PROVIDERS,
    "llm_model_capabilities": {
        "deepseek-v4-flash": {"can_enable_thinking": False, "can_use_json": True},
        "b1": {"can_enable_thinking": False, "can_use_json": True},
        "b2": {"can_enable_thinking": False, "can_use_json": False},
    },
    "vlm_model_capabilities": {
        "vlm-model": {"can_enable_thinking": False, "can_use_json": False},
        "vb1": {"can_enable_thinking": False, "can_use_json": True},
    },
    "llm_json_required_modules": [{"name": "memory_write", "label": "记忆写入"}],
    "vlm_json_required_modules": [],
}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeNetwork:
    base_url = "https://x"


class FakeReply(QObject):
    """模拟 QNetworkReply：单次异步发出 finished。"""

    finished = Signal()

    def __init__(
        self,
        payload: bytes,
        error=QNetworkReply.NetworkError.NoError,
        error_string="",
        status_code=200,
        parent=None,
    ):
        super().__init__(parent)
        self._payload = payload
        self._error = error
        self._error_string = error_string
        self._status_code = status_code
        self._self_ref = self
        QTimer.singleShot(0, self._emit_finished)

    def _emit_finished(self):
        self.finished.emit()
        self._self_ref = None

    def error(self):
        return self._error

    def errorString(self):
        return self._error_string

    def readAll(self):
        return QByteArray(self._payload)

    def attribute(self, code):
        if code == QNetworkRequest.Attribute.HttpStatusCodeAttribute:
            return self._status_code
        return None

    def isFinished(self):
        return True

    def isRunning(self):
        return False

    def abort(self):
        pass


class FakeHttp:
    """替代 QNetworkAccessManager：providers 与 /models 校验请求分别出队。"""

    def __init__(self, parent=None):
        self.requests = []
        self._provider_responses = []
        self._models_responses = []

    def setRedirectPolicy(self, policy):
        pass

    def setAutoDeleteReplies(self, enabled):
        pass

    def queue_provider_response(self, reply):
        self._provider_responses.append(reply)

    def queue_models_response(
        self,
        payload=b"",
        error=QNetworkReply.NetworkError.NoError,
        error_string="",
        status_code=200,
    ):
        self._models_responses.append(
            FakeReply(payload, error=error, error_string=error_string, status_code=status_code)
        )

    def get(self, request):
        self.requests.append(request)
        url = request.url().toString()
        if url.rstrip("/").endswith("/models"):
            if self._models_responses:
                return self._models_responses.pop(0)
            return FakeReply(b"{}")
        if self._provider_responses:
            return self._provider_responses.pop(0)
        return FakeReply(
            json.dumps(PROVIDERS_PAYLOAD, ensure_ascii=False).encode("utf-8")
        )


@pytest.fixture
def make_dialog(qapp, monkeypatch, tmp_path):
    """按需创建对话框：隔离凭据文件并关闭 DPAPI，贴近真实加载流程。"""
    created = []
    monkeypatch.setattr(credential, "_DPAPI_AVAILABLE", False)
    monkeypatch.setattr(
        credential,
        "get_credential_path",
        lambda: str(tmp_path / "user.json"),
    )
    monkeypatch.setattr(dlg_mod, "QNetworkAccessManager", FakeHttp)

    def _make() -> LLMSettingsDialog:
        dlg = LLMSettingsDialog(FakeNetwork())
        for _ in range(8):
            qapp.processEvents()
        created.append(dlg)
        return dlg

    yield _make
    for dlg in created:
        dlg.close()


def _enable(dialog, key="llm_models"):
    info = dialog._modules[key]
    info["switch"].setChecked(True)
    return info


def _fill_module(dialog, key="llm_models", provider="DeepSeek", model="deepseek-v4-flash"):
    info = dialog._modules[key]
    info["switch"].setChecked(True)
    info["provider_combo"].setCurrentText(provider)
    info["api_key_input"].setText("sk-test")
    index = info["model_combo"].findText(model)
    info["model_combo"].setCurrentIndex(index if index >= 0 else 0)
    return info


def _models_payload(*ids):
    return json.dumps({"data": [{"id": i} for i in ids]}, ensure_ascii=False).encode(
        "utf-8"
    )


def test_modules_derived_from_providers_fields(make_dialog):
    """模块列表由 providers 中非空列表字段生成，标题取极简映射或字段名。"""
    dialog = make_dialog()
    assert dialog._module_keys == ["llm_models", "vlm_models"]
    assert MODULE_TITLES["llm_models"] == "对话模型"
    assert MODULE_TITLES["vlm_models"] == "图片理解模型"
    assert dialog.save_btn.isEnabled()

    # 模拟新增能力字段：非空列表自动出现模块，标题回退字段名
    providers = [
        {"name": "P", "base_url": "https://p/v1", "llm_models": ["m"], "audio_models": ["a"]}
    ]
    dialog._on_providers_loaded(
        providers,
        llm_caps={},
        vlm_caps={},
        llm_json=[],
        vlm_json=[],
    )
    assert "audio_models" in dialog._module_keys
    assert MODULE_TITLES.get("audio_models", "audio_models") == "audio_models"


def test_empty_storage_all_modules_disabled(make_dialog):
    """空存储时所有模块开关关闭、字段隐藏、无自动选择。"""
    dialog = make_dialog()
    for key, info in dialog._modules.items():
        assert info["switch"].isChecked() is False
        assert info["fields"].isHidden() is True
        assert info["provider_combo"].currentText() == ""
        assert info["model_combo"].currentText() == ""


def test_load_restores_switch_and_values_no_auto_select(make_dialog):
    """保存值回填表单；未保存的服务商/模型不会被自动选中。"""
    credential.save_llm_modules_config(
        {
            "llm_models": {
                "enabled": True,
                "provider": "DeepSeek",
                "model": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com/v1",
                "params": {"temperature": 0.7},
                "api_key": "sk-test",
            },
            "vlm_models": {
                "enabled": False,
                "provider": "",
                "model": "",
                "base_url": "",
                "params": {},
                "api_key": "",
            },
        },
        allow_plaintext=True,
    )
    dialog = make_dialog()
    llm = dialog._modules["llm_models"]
    assert llm["switch"].isChecked() is True
    assert llm["provider_combo"].currentText() == "DeepSeek"
    assert llm["model_combo"].currentText() == "deepseek-v4-flash"
    assert llm["api_key_input"].text() == "sk-test"
    assert '"temperature": 0.7' in llm["params_editor"].toPlainText()
    assert dialog._modules["vlm_models"]["switch"].isChecked() is False


def test_toggle_off_hides_keeps_values(make_dialog):
    """关闭开关只隐藏字段，不清空表单值；重新开启恢复。"""
    dialog = make_dialog()
    info = _fill_module(dialog)
    assert info["fields"].isHidden() is False
    info["switch"].setChecked(False)
    assert info["fields"].isHidden() is True
    assert info["api_key_input"].text() == "sk-test"
    assert info["provider_combo"].currentText() == "DeepSeek"
    info["switch"].setChecked(True)
    assert info["fields"].isHidden() is False
    assert info["api_key_input"].text() == "sk-test"


def test_precheck_missing_field_highlights_and_blocks(make_dialog, qapp, monkeypatch):
    """预检：缺少 API Key 时高亮该输入框并弹窗，不发起校验、不保存。"""
    dialog = make_dialog()
    warnings = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "warning",
        lambda parent, title, text: warnings.append((title, text)),
    )
    saved = []
    monkeypatch.setattr(
        credential,
        "save_llm_modules_config",
        lambda *a, **k: saved.append(a) or True,
    )
    http = dialog._http
    info = _enable(dialog)
    info["provider_combo"].setCurrentText("DeepSeek")
    info["model_combo"].setCurrentText("deepseek-v4-flash")
    assert info["api_key_input"].text() == ""
    dialog._on_save()
    for _ in range(5):
        qapp.processEvents()
    assert warnings and "API Key" in warnings[0][1]
    assert "E53935" in info["api_key_input"].styleSheet()
    assert saved == []
    assert http._models_responses or len(http.requests) == 1  # 仅 providers 请求


def test_precheck_invalid_json_blocks(make_dialog, qapp, monkeypatch):
    dialog = make_dialog()
    warnings = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "warning",
        lambda parent, title, text: warnings.append(text),
    )
    saved = []
    monkeypatch.setattr(
        credential,
        "save_llm_modules_config",
        lambda *a, **k: saved.append(a) or True,
    )
    info = _fill_module(dialog)
    info["params_editor"].setPlainText("{not json")
    dialog._on_save()
    for _ in range(5):
        qapp.processEvents()
    assert warnings and "JSON" in warnings[0]
    assert "E53935" in info["params_editor"].styleSheet()
    assert saved == []


def test_validation_success_saves_all_modules(make_dialog, qapp, monkeypatch):
    """校验全部通过后一次性写入整份配置（含关闭模块），成功状态提示。"""
    dialog = make_dialog()
    questions = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "question",
        lambda parent, title, text, *a, **k: (
            questions.append(title),
            QMessageBox.StandardButton.Yes,
        )[1],
    )
    http = dialog._http
    _fill_module(dialog)
    http.queue_models_response(payload=_models_payload("deepseek-v4-flash"))
    dialog._on_save()
    for _ in range(10):
        qapp.processEvents()
    saved = credential.get_llm_modules_config()
    assert saved["llm_models"]["enabled"] is True
    assert saved["llm_models"]["api_key"] == "sk-test"
    assert saved["llm_models"]["base_url"] == "https://api.deepseek.com/v1"
    assert saved["vlm_models"]["enabled"] is False
    assert dialog.status_label.text() == "配置已保存"


def test_validation_failure_no_write(make_dialog, qapp, monkeypatch):
    """任一模块校验失败：不写入任何数据并弹窗列明模块。"""
    dialog = make_dialog()
    criticals = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "critical",
        lambda parent, title, text: criticals.append((title, text)),
    )
    http = dialog._http
    _fill_module(dialog)
    http.queue_models_response(
        error=QNetworkReply.NetworkError.ContentAccessDenied,
        error_string="HTTP 401",
        status_code=401,
    )
    dialog._on_save()
    for _ in range(10):
        qapp.processEvents()
    assert criticals and "对话模型" in criticals[0][1]
    assert credential.get_llm_modules_config() == {}


def test_validation_timeout_is_failure(make_dialog, qapp, monkeypatch):
    """30 秒超时（Qt 6.9 下为 OperationCanceledError）视为校验失败，不保存。"""
    dialog = make_dialog()
    criticals = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "critical",
        lambda parent, title, text: criticals.append(text),
    )
    http = dialog._http
    _fill_module(dialog)
    http.queue_models_response(
        error=QNetworkReply.NetworkError.OperationCanceledError,
        error_string="Operation canceled",
    )
    dialog._on_save()
    for _ in range(10):
        qapp.processEvents()
    assert criticals and "超时" in criticals[0]
    assert credential.get_llm_modules_config() == {}


def test_validation_model_not_in_list_fails(make_dialog, qapp, monkeypatch):
    """模型不在 /v1/models 返回列表中时判定模型不可用。"""
    dialog = make_dialog()
    criticals = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "critical",
        lambda parent, title, text: criticals.append(text),
    )
    http = dialog._http
    _fill_module(dialog, model="deepseek-v4-flash")
    http.queue_models_response(payload=_models_payload("other-model"))
    dialog._on_save()
    for _ in range(10):
        qapp.processEvents()
    assert criticals and "模型不可用" in criticals[0]
    assert credential.get_llm_modules_config() == {}


def test_stale_batch_response_dropped(make_dialog, qapp, monkeypatch):
    """过期 batch 的响应被静默丢弃，不进入结果汇总。"""
    dialog = make_dialog()
    reply = FakeReply(b"{}")
    dialog._validation_items = [
        {"reply": reply, "key": "llm_models", "batch": 1, "done": False}
    ]
    dialog._validation_batch = 2  # 当前已是新批次
    reply.finished.connect(dialog._on_validation_reply)
    for _ in range(5):
        qapp.processEvents()
    assert dialog._validation_items[0]["done"] is False
    assert dialog._validation_results == {}


def test_cancel_validation_restores_editable_no_write(make_dialog, qapp, monkeypatch):
    dialog = make_dialog()
    saved = []
    monkeypatch.setattr(
        credential,
        "save_llm_modules_config",
        lambda *a, **k: saved.append(a) or True,
    )
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "critical",
        lambda parent, title, text: None,
    )
    info = _fill_module(dialog)
    dialog._on_save()
    assert dialog._validating is True
    dialog._cancel_validation()
    for _ in range(5):
        qapp.processEvents()  # 过期响应应被 batchId 丢弃
    assert dialog._validating is False
    assert info["provider_combo"].isEnabled() is True
    assert info["switch"].isEnabled() is True
    assert saved == []
    assert dialog.status_label.text().startswith("已取消")


def test_provider_missing_from_list_shows_notice_and_save_works(
    make_dialog, qapp, monkeypatch
):
    """服务商不在新列表中：显示轻量提示，保存仍用固化 base_url。"""
    credential.save_llm_modules_config(
        {
            "llm_models": {
                "enabled": True,
                "provider": "GoneProvider",
                "model": "old-model",
                "base_url": "https://cached.example.com/v1",
                "params": {},
                "api_key": "sk-cached",
            }
        },
        allow_plaintext=True,
    )
    dialog = make_dialog()
    info = dialog._modules["llm_models"]
    assert info["notice_label"].isHidden() is False
    assert "GoneProvider" in info["notice_label"].text()
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "question",
        lambda parent, title, text, *a, **k: QMessageBox.StandardButton.Yes,
    )
    http = dialog._http
    http.queue_models_response(payload=_models_payload("old-model"))
    dialog._on_save()
    for _ in range(10):
        qapp.processEvents()
    saved = credential.get_llm_modules_config()
    assert saved["llm_models"]["base_url"] == "https://cached.example.com/v1"


def test_providers_fetch_failure_disables_save(make_dialog, qapp):
    """服务商列表拉取失败：显示错误、保存按钮禁用。"""
    dialog = make_dialog()
    http = dialog._http
    http.queue_provider_response(
        FakeReply(
            b"",
            error=QNetworkReply.NetworkError.OperationCanceledError,
            error_string="Operation canceled",
        )
    )
    dialog._refresh_providers()
    for _ in range(5):
        qapp.processEvents()
    assert dialog.save_btn.isEnabled() is False
    assert "获取服务商列表失败" in dialog.status_label.text()
