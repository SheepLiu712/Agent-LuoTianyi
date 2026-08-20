"""桌面 client LLM 设置对话框：按类型卡片、预检、统一校验与原子保存测试。"""

import json

import pytest
from PySide6.QtCore import QByteArray, QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import QApplication, QLabel, QMessageBox

import src.gui.llm_settings_dialog as dlg_mod
from src.gui.llm_settings_dialog import LLMSettingsDialog
from src.safety import credential


TYPES = [
    {
        "type": "对话模型",
        "description": "对话说明",
        "providers": [
            {
                "name": "DeepSeek",
                "base_url": "https://api.deepseek.com/v1",
                "models": [
                    {
                        "id": "deepseek-v4-flash",
                        "can_enable_thinking": False,
                        "can_use_json": True,
                    }
                ],
            }
        ],
    },
    {
        "type": "图片理解模型",
        "description": "图片说明",
        "providers": [
            {
                "name": "VlmOnly",
                "base_url": "https://v/v1",
                "models": [
                    {
                        "id": "vlm-model",
                        "can_enable_thinking": False,
                        "can_use_json": False,
                    }
                ],
            }
        ],
    },
]

TYPES_PAYLOAD = {"types": TYPES}


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
    """替代 QNetworkAccessManager：types 与 /models 校验请求分别出队。"""

    def __init__(self, parent=None):
        self.requests = []
        self._type_responses = []
        self._models_responses = []

    def setRedirectPolicy(self, policy):
        pass

    def setAutoDeleteReplies(self, enabled):
        pass

    def queue_type_response(self, reply):
        self._type_responses.append(reply)

    def queue_models_response(
        self,
        payload=b"",
        error=QNetworkReply.NetworkError.NoError,
        error_string="",
        status_code=200,
    ):
        self._models_responses.append(
            FakeReply(
                payload,
                error=error,
                error_string=error_string,
                status_code=status_code,
            )
        )

    def get(self, request):
        self.requests.append(request)
        url = request.url().toString()
        if url.rstrip("/").endswith("/models"):
            if self._models_responses:
                return self._models_responses.pop(0)
            return FakeReply(b"{}")
        if self._type_responses:
            return self._type_responses.pop(0)
        return FakeReply(json.dumps(TYPES_PAYLOAD, ensure_ascii=False).encode("utf-8"))


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


def _enable(dialog, key="对话模型"):
    info = dialog._modules[key]
    info["switch"].setChecked(True)
    return info


def _fill_module(
    dialog,
    key="对话模型",
    provider="DeepSeek",
    model="deepseek-v4-flash",
):
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


def test_cards_derived_from_types(make_dialog):
    """卡片按服务端 types 生成，标题为类型名，保存可用。"""
    dialog = make_dialog()
    assert list(dialog._modules.keys()) == ["对话模型", "图片理解模型"]
    assert dialog.save_btn.isEnabled()


def test_description_shown_in_card(make_dialog):
    dialog = make_dialog()
    card = dialog._modules["对话模型"]["card"]
    texts = [child.text() for child in card.findChildren(QLabel)]
    assert any("对话说明" in t for t in texts)


def test_empty_storage_all_types_disabled(make_dialog):
    dialog = make_dialog()
    for info in dialog._modules.values():
        assert info["switch"].isChecked() is False
        assert info["fields"].isVisible() is False


def test_load_restores_switch_and_values(make_dialog):
    credential.save_llm_modules_config(
        {
            "对话模型": {
                "enabled": True,
                "provider": "DeepSeek",
                "model": "deepseek-v4-flash",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-stored",
                "params": {"temperature": 0.3},
                "model_capabilities": {"can_enable_thinking": False, "can_use_json": True},
            }
        }
    )
    dialog = make_dialog()
    info = dialog._modules["对话模型"]
    assert info["switch"].isChecked() is True
    assert info["provider_combo"].currentText() == "DeepSeek"
    assert info["model_combo"].currentText() == "deepseek-v4-flash"
    assert info["api_key_input"].text() == "sk-stored"
    assert "0.3" in info["params_editor"].toPlainText()


def test_toggle_off_hides_fields_keeps_values(make_dialog):
    info = _fill_module(make_dialog())
    info["switch"].setChecked(False)
    assert info["fields"].isVisible() is False
    assert info["api_key_input"].text() == "sk-test"


def test_precheck_missing_field_highlights_and_blocks(make_dialog, qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: warnings.append(a[2])),
    )
    dialog = make_dialog()
    info = _enable(dialog)
    info["api_key_input"].setText("")
    dialog._on_save()
    qapp.processEvents()
    assert warnings
    assert info["api_key_input"].styleSheet().count("#E53935") > 0


def test_precheck_invalid_json_blocks(make_dialog, qapp, monkeypatch):
    warnings = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "warning",
        staticmethod(lambda *a, **k: warnings.append(a[2])),
    )
    dialog = make_dialog()
    info = _fill_module(dialog)
    info["params_editor"].setPlainText("{bad json")
    dialog._on_save()
    qapp.processEvents()
    assert warnings
    assert "JSON" in warnings[0]


def test_validation_success_saves_all_types(make_dialog, qapp, monkeypatch):
    dialog = make_dialog()
    http = dialog._http
    http.queue_models_response(_models_payload("deepseek-v4-flash"))
    http.queue_models_response(_models_payload("vlm-model"))
    _fill_module(dialog, "对话模型", "DeepSeek", "deepseek-v4-flash")
    _fill_module(dialog, "图片理解模型", "VlmOnly", "vlm-model")
    dialog._on_save()
    for _ in range(16):
        qapp.processEvents()

    saved = credential.get_llm_modules_config()
    assert saved["对话模型"]["enabled"] is True
    assert saved["对话模型"]["provider"] == "DeepSeek"
    assert saved["对话模型"]["base_url"] == "https://api.deepseek.com/v1"
    assert saved["对话模型"]["model"] == "deepseek-v4-flash"
    assert saved["对话模型"]["model_capabilities"] == {
        "can_enable_thinking": False,
        "can_use_json": True,
    }
    assert saved["图片理解模型"]["enabled"] is True
    assert saved["图片理解模型"]["model_capabilities"] == {
        "can_enable_thinking": False,
        "can_use_json": False,
    }


def test_validation_success_persists_advanced_params(make_dialog, qapp):
    dialog = make_dialog()
    dialog._http.queue_models_response(_models_payload("deepseek-v4-flash"))
    info = _fill_module(dialog)
    info["params_editor"].setPlainText('{"temperature": 0.5}')
    dialog._on_save()
    for _ in range(16):
        qapp.processEvents()
    saved = credential.get_llm_modules_config()
    assert saved["对话模型"]["params"] == {"temperature": 0.5}


def test_save_updates_base_url_when_provider_exists(make_dialog, qapp):
    dialog = make_dialog()
    dialog._http.queue_models_response(_models_payload("deepseek-v4-flash"))
    _fill_module(dialog)
    dialog._on_save()
    for _ in range(16):
        qapp.processEvents()
    saved = credential.get_llm_modules_config()
    assert saved["对话模型"]["base_url"] == "https://api.deepseek.com/v1"


def test_validation_failure_no_write(make_dialog, qapp, monkeypatch):
    dialogs = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: dialogs.append(a)),
    )
    dialog = make_dialog()
    dialog._http.queue_models_response(_models_payload("other-model"))
    _fill_module(dialog)
    dialog._on_save()
    for _ in range(16):
        qapp.processEvents()
    assert dialogs
    assert credential.get_llm_modules_config() == {}


def test_validation_timeout_is_failure(make_dialog, qapp, monkeypatch):
    dialogs = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox,
        "critical",
        staticmethod(lambda *a, **k: dialogs.append(a)),
    )
    dialog = make_dialog()
    dialog._http.queue_models_response(
        error=QNetworkReply.NetworkError.OperationCanceledError,
        error_string="timeout",
    )
    _fill_module(dialog)
    dialog._on_save()
    for _ in range(16):
        qapp.processEvents()
    assert dialogs
    assert "超时" in dialogs[0][2]


def test_stale_batch_response_dropped(make_dialog, qapp):
    dialog = make_dialog()
    dialog._http.queue_models_response(_models_payload("deepseek-v4-flash"))
    _fill_module(dialog)
    dialog._on_save()
    dialog._validation_batch += 1  # 模拟取消/过期
    for _ in range(16):
        qapp.processEvents()
    assert credential.get_llm_modules_config() == {}


def test_cancel_validation_restores_editable_no_write(make_dialog, qapp):
    dialog = make_dialog()
    dialog._http.queue_models_response(_models_payload("deepseek-v4-flash"))
    _fill_module(dialog)
    dialog._on_save()
    dialog._cancel_validation()
    for _ in range(16):
        qapp.processEvents()
    assert credential.get_llm_modules_config() == {}
    assert dialog.save_btn.isEnabled()
    assert dialog._modules["对话模型"]["switch"].isEnabled()


def test_provider_missing_from_list_keeps_stored_values(make_dialog):
    credential.save_llm_modules_config(
        {
            "对话模型": {
                "enabled": True,
                "provider": "Gone",
                "model": "old-model",
                "base_url": "https://gone/v1",
                "api_key": "sk-old",
                "params": {},
                "model_capabilities": {},
            }
        }
    )
    dialog = make_dialog()
    info = dialog._modules["对话模型"]
    assert info["stored_provider"] == "Gone"
    assert info["stored_model"] == "old-model"
    assert info["base_url"] == "https://gone/v1"
    assert info["api_key_input"].text() == "sk-old"


def test_types_fetch_failure_disables_save(make_dialog, qapp):
    dialog = make_dialog()
    dialog._http.queue_type_response(
        FakeReply(
            b"",
            error=QNetworkReply.NetworkError.ConnectionRefusedError,
            error_string="refused",
        )
    )
    for _ in range(8):
        qapp.processEvents()
    assert dialog.save_btn.isEnabled() is False
    assert "失败" in dialog.status_label.text()
