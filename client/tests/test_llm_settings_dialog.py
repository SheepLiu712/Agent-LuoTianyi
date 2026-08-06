"""桌面 client LLM 设置对话框：服务商/模型联动与重新选择行为测试。"""

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox

import src.gui.llm_settings_dialog as dlg_mod
from src.gui.llm_settings_dialog import LLMSettingsDialog
from src.safety import credential


PROVIDERS = [
    {
        "name": "DeepSeek",
        "base_url": "https://d/v1",
        "models": ["deepseek-v4-flash"],
        "vlm_models": [],
    },
    {
        "name": "VlmOnly",
        "base_url": "https://v/v1",
        "models": [],
        "vlm_models": ["vlm-model", "vlm-model2"],
    },
    {
        "name": "Both",
        "base_url": "https://b/v1",
        "models": ["b1", "b2"],
        "vlm_models": ["vb1"],
    },
]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeNetwork:
    base_url = "https://x"

    def get_llm_providers(self, force_refresh=False):
        return [dict(p) for p in PROVIDERS]


@pytest.fixture
def make_dialog(qapp, monkeypatch, tmp_path):
    """按需创建对话框：先注入 saved 配置，再实例化，贴近真实加载流程。"""
    created = []

    def _make(saved: dict | None = None) -> LLMSettingsDialog:
        saved = saved or {}
        # 隔离真实凭据文件，避免已保存配置触发模态弹窗阻塞测试
        monkeypatch.setattr(
            credential,
            "get_credential_path",
            lambda: str(tmp_path / "user.json"),
        )
        monkeypatch.setattr(credential, "get_provider", lambda: saved.get("provider"))
        monkeypatch.setattr(credential, "get_model", lambda: saved.get("model"))
        monkeypatch.setattr(
            credential, "get_vlm_provider", lambda: saved.get("vlm_provider")
        )
        monkeypatch.setattr(credential, "get_vlm_model", lambda: saved.get("vlm_model"))
        monkeypatch.setattr(credential, "get_api_key", lambda: saved.get("key"))
        monkeypatch.setattr(
            credential, "get_vlm_api_key", lambda: saved.get("vlm_key")
        )
        monkeypatch.setattr(
            dlg_mod, "fetch_llm_json_required_modules", lambda *a, **k: ([], [])
        )
        dlg = LLMSettingsDialog(FakeNetwork())
        dlg._providers_loader.wait(3000)
        for _ in range(3):
            qapp.processEvents()
        created.append(dlg)
        return dlg

    yield _make
    for dlg in created:
        dlg.close()


def _click_reselect(monkeypatch):
    """把 QMessageBox.exec 替换为自动点击“重新选择”。"""

    def fake_exec(box):
        for btn in box.buttons():
            if btn.text() == "重新选择":
                btn.click()
                return QMessageBox.DialogCode.Accepted
        return QMessageBox.DialogCode.Rejected

    monkeypatch.setattr(dlg_mod.QMessageBox, "exec", fake_exec)


def test_provider_select_auto_selects_first_model(make_dialog):
    """手动选中服务商后，模型下拉框自动选中第一个可用模型。"""
    dialog = make_dialog()
    dialog.provider_combo.setCurrentIndex(
        dialog.provider_combo.findText("DeepSeek")
    )
    assert dialog.model_combo.currentText() == "deepseek-v4-flash"

    dialog.vlm_provider_combo.setCurrentIndex(
        dialog.vlm_provider_combo.findText("VlmOnly")
    )
    assert dialog.vlm_model_combo.currentText() == "vlm-model"


def test_saved_model_preserved_when_still_available(make_dialog):
    """已保存模型仍在列表中时保留原选择，不覆盖为第一个。"""
    dialog = make_dialog()
    dialog._saved_provider = "Both"
    dialog._saved_model = "b2"
    dialog.provider_combo.setCurrentIndex(
        dialog.provider_combo.findText("Both")
    )
    assert dialog.model_combo.currentText() == "b2"

    dialog._saved_vlm_provider = "Both"
    dialog._saved_vlm_model = "vb1"
    dialog.vlm_provider_combo.setCurrentIndex(
        dialog.vlm_provider_combo.findText("Both")
    )
    assert dialog.vlm_model_combo.currentText() == "vb1"


def test_stale_saved_model_falls_back_to_first(make_dialog):
    """已保存模型不在列表时，回退到该服务商第一个可用模型。"""
    dialog = make_dialog()
    dialog._saved_provider = "Both"
    dialog._saved_model = "b9"
    dialog.provider_combo.setCurrentIndex(
        dialog.provider_combo.findText("Both")
    )
    assert dialog.model_combo.currentText() == "b1"

    dialog._saved_vlm_provider = "Both"
    dialog._saved_vlm_model = "vb9"
    dialog.vlm_provider_combo.setCurrentIndex(
        dialog.vlm_provider_combo.findText("Both")
    )
    assert dialog.vlm_model_combo.currentText() == "vb1"


def test_reselect_provider_stale_selects_provider_and_model(make_dialog, monkeypatch):
    """服务商失效时重新选择：服务商与模型一起自动选第一个可用配置。"""
    _click_reselect(monkeypatch)
    dialog = make_dialog(
        {
            "provider": "OldProvider",
            "model": "old-model",
            "vlm_provider": "OldVlm",
            "vlm_model": "old-vlm",
            "key": "sk",
            "vlm_key": "skv",
        }
    )
    assert dialog.provider_combo.currentText() == "DeepSeek"
    assert dialog.model_combo.currentText() == "deepseek-v4-flash"

    dialog._go_to_page(1)
    assert dialog.vlm_provider_combo.currentText() == "VlmOnly"
    assert dialog.vlm_model_combo.currentText() == "vlm-model"


def test_reselect_model_stale_keeps_provider_selects_first_model(make_dialog, monkeypatch):
    """仅模型失效时重新选择：保留服务商，自动换成其第一个可用模型。"""
    _click_reselect(monkeypatch)
    dialog = make_dialog(
        {
            "provider": "Both",
            "model": "b9",
            "vlm_provider": "Both",
            "vlm_model": "vb9",
            "key": "sk",
            "vlm_key": "skv",
        }
    )
    assert dialog.provider_combo.currentText() == "Both"
    assert dialog.model_combo.currentText() == "b1"

    dialog._go_to_page(1)
    assert dialog.vlm_provider_combo.currentText() == "Both"
    assert dialog.vlm_model_combo.currentText() == "vb1"
