import pytest
from PySide6.QtWidgets import QApplication

from src.gui import preferences_dialog as dialog_module
from src.gui.preferences_dialog import PreferencesDialog


class FakeNetwork:
    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.overwrite_calls = []

    def get_preferences(self):
        if self.raises is not None:
            raise self.raises
        return self.result

    def overwrite_preferences(self, preferences):
        self.overwrite_calls.append(preferences)
        return {"status": "success"}


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def silence_boxes(monkeypatch):
    monkeypatch.setattr(dialog_module.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(dialog_module.QMessageBox, "critical", staticmethod(lambda *a, **k: None))


def _make(qapp, network):
    dialog = PreferencesDialog(network)
    return dialog


def test_load_failure_disables_save_and_offers_retry(qapp, silence_boxes):
    network = FakeNetwork(raises=RuntimeError("connection reset"))
    dialog = _make(qapp, network)
    try:
        assert dialog.save_btn.isEnabled() is False
        assert dialog.retry_btn.isHidden() is False
        assert dialog.load_status_label.isHidden() is False
        assert dialog._preferences_loaded is False
    finally:
        dialog.close()


def test_missing_response_disables_save(qapp, silence_boxes):
    network = FakeNetwork(result=None)
    dialog = _make(qapp, network)
    try:
        assert dialog.save_btn.isEnabled() is False
        dialog.on_save()
        assert network.overwrite_calls == []
    finally:
        dialog.close()


def test_successful_load_enables_save(qapp, silence_boxes):
    network = FakeNetwork(result={"relationship": "家人", "custom_context": "一起听歌"})
    dialog = _make(qapp, network)
    try:
        assert dialog._preferences_loaded is True
        assert dialog.save_btn.isEnabled() is True
        assert dialog.retry_btn.isHidden() is True
        assert dialog.load_status_label.isHidden() is True

        dialog.on_save()
        assert len(network.overwrite_calls) == 1
    finally:
        dialog.close()


def test_retry_recovers_after_failure(qapp, silence_boxes):
    network = FakeNetwork(raises=RuntimeError("temporary"))
    dialog = _make(qapp, network)
    try:
        assert dialog.save_btn.isEnabled() is False
        network.raises = None
        network.result = {"relationship": "知己"}
        dialog.load_preferences()
        assert dialog._preferences_loaded is True
        assert dialog.save_btn.isEnabled() is True
        assert dialog.retry_btn.isHidden() is True
    finally:
        dialog.close()
