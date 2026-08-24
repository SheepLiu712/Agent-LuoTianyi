import pytest
from PySide6.QtWidgets import QApplication

from src.gui import llm_settings_dialog as dialog_module
from src.gui.llm_settings_dialog import LLMSettingsDialog


TYPES = [
    {
        "id": "main_chat",
        "name": "主对话模型",
        "description": "主回复",
        "model_kind": "llm",
        "requires_json": False,
        "requires_thinking": False,
    },
    {
        "id": "image_understanding",
        "name": "图片理解模型",
        "description": "图片理解",
        "model_kind": "vlm",
        "requires_json": True,
        "requires_thinking": False,
    },
]


class FakeNetwork:
    base_url = "https://server.example.com"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def make_dialog(qapp, monkeypatch):
    dialogs = []
    monkeypatch.setattr(LLMSettingsDialog, "_start_fetch_types", lambda self: None)
    monkeypatch.setattr(dialog_module.QMessageBox, "information", staticmethod(lambda *a, **k: None))

    def factory(saved=None):
        monkeypatch.setattr(
            dialog_module.llm_key_storage,
            "get_llm_modules_config",
            lambda: saved or {},
        )
        dialog = LLMSettingsDialog(FakeNetwork())
        dialog._types = TYPES
        dialog._rebuild_cards()
        dialog._load_modules_from_storage()
        dialog.save_btn.setEnabled(True)
        dialogs.append(dialog)
        return dialog

    yield factory
    for dialog in dialogs:
        dialog.close()


def _fill(info):
    info["switch"].setChecked(True)
    info["provider_input"].setText("Custom")
    info["base_url_input"].setText("https://custom.example/v1/")
    info["api_key_input"].setText("sk-custom")
    info["model_input"].setText("my-model")


def test_cards_use_server_requirements_without_provider_catalog(make_dialog):
    dialog = make_dialog()
    assert set(dialog._modules) == {"main_chat", "image_understanding"}
    info = dialog._modules["main_chat"]
    assert "provider_combo" not in info
    assert info["model_kind"] == "llm"
    assert info["provider_input"].placeholderText() == "服务商名称（自定义）"


def test_legacy_display_name_storage_is_loaded(make_dialog):
    dialog = make_dialog(
        {
            "主对话模型": {
                "enabled": True,
                "provider": "Legacy",
                "base_url": "https://legacy/v1",
                "api_key": "sk-old",
                "model": "old-model",
                "params": {},
                "model_capabilities": {"can_use_json": True},
            }
        }
    )
    info = dialog._modules["main_chat"]
    assert info["switch"].isChecked()
    assert info["provider_input"].text() == "Legacy"
    assert info["model_input"].text() == "old-model"
    assert info["can_json"].isChecked()


def test_save_accepts_arbitrary_openai_compatible_configuration(make_dialog, monkeypatch):
    saved = {}
    monkeypatch.setattr(
        dialog_module.llm_key_storage,
        "save_llm_modules_config",
        lambda value, allow_plaintext=False: saved.update(value) is None,
    )
    dialog = make_dialog()
    info = dialog._modules["main_chat"]
    _fill(info)
    info["can_json"].setChecked(True)
    info["can_thinking"].setChecked(True)
    info["params_editor"].setPlainText('{"temperature": 0.2}')
    dialog._on_save()

    assert saved["main_chat"]["provider"] == "Custom"
    assert saved["main_chat"]["base_url"] == "https://custom.example/v1"
    assert saved["main_chat"]["model"] == "my-model"
    assert saved["main_chat"]["model_kind"] == "llm"
    assert saved["main_chat"]["model_capabilities"] == {
        "can_use_json": True,
        "can_enable_thinking": True,
    }
    assert saved["main_chat"]["params"] == {"temperature": 0.2}


def test_precheck_requires_custom_base_url(make_dialog):
    dialog = make_dialog()
    info = dialog._modules["main_chat"]
    _fill(info)
    info["base_url_input"].clear()
    modules = dialog._collect_form_modules()
    assert dialog._precheck(modules) == ("main_chat", "base_url")


def test_invalid_advanced_params_are_rejected(make_dialog):
    dialog = make_dialog()
    info = dialog._modules["main_chat"]
    _fill(info)
    info["params_editor"].setPlainText("[]")
    assert dialog._precheck(dialog._collect_form_modules()) == ("main_chat", "params")


def test_invalid_requirement_is_filtered():
    assert LLMSettingsDialog._valid_type(TYPES[0]) is True
    assert LLMSettingsDialog._valid_type({"id": "x", "name": "X", "model_kind": "audio"}) is False
