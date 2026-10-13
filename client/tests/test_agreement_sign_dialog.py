"""签署窗口的行为测试：门禁文案、按钮可用性、拒绝语义、提交状态与换版重置。"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

from src.gui.agreement_sign_dialog import (  # noqa: E402
    COLOR_DISABLED,
    COLOR_PRIMARY,
    TEXT_REJECT,
    AgreementSignDialog,
)
from src.gui.signing_gate import (  # noqa: E402
    TEXT_BOTTOM_HINT,
    TEXT_CONFIRM,
    TEXT_CONFIRM_WAITING,
    TEXT_LOAD_FAILED,
    TEXT_SUBMITTING,
)

def long_document(version: str = "terms-2026-10-v1") -> dict:
    """足够长的正文：不滚动就看不到底部，用来验证"必须读过底部"。"""
    return {
        "version": version,
        "title": "用户协议",
        "format": "agreement.richtext.v1",
        "blocks": [
            {"font_size": 16, "align": "justify", "runs": [{"text": f"第 {index} 段正文。", "bold": False}]}
            for index in range(80)
        ],
    }


SHORT_DOC = {
    "version": "terms-2026-10-v1",
    "title": "用户协议",
    "format": "agreement.richtext.v1",
    "blocks": [{"font_size": 16, "align": "justify", "runs": [{"text": "很短的一段。", "bold": False}]}],
}

DOC = long_document()


@pytest.fixture(scope="module")
def app():
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.fixture
def clock():
    class FakeClock:
        def __init__(self) -> None:
            self.now = 1000.0

        def __call__(self) -> float:
            return self.now

        def advance(self, seconds: float) -> None:
            self.now += seconds

    return FakeClock()


@pytest.fixture
def dialog(app, clock):
    widget = AgreementSignDialog(document=DOC, clock=clock)
    widget.show()
    yield widget
    widget.close()
    widget.deleteLater()
    app.processEvents()


def confirm_color(dialog) -> str:
    for color in (COLOR_PRIMARY, COLOR_DISABLED):
        if color in dialog.confirm_btn.styleSheet():
            return color
    return "unknown"


def test_confirm_is_disabled_until_time_and_bottom_are_both_met(dialog, clock):
    assert dialog.confirm_btn.isEnabled() is False
    assert dialog.confirm_btn.text() == TEXT_CONFIRM_WAITING.format(seconds=5)
    assert confirm_color(dialog) == COLOR_DISABLED
    assert dialog.gate.reached_bottom is False  # 长正文还没读过底部
    # 未到过底部就提示（与已读秒数无关）：秒数只体现在按钮文案上。
    assert dialog.hint_label.text() == TEXT_BOTTOM_HINT
    assert dialog.hint_label.isVisible() is True

    clock.advance(5.0)
    dialog._on_tick()

    assert dialog.confirm_btn.isEnabled() is False
    assert dialog.confirm_btn.text() == TEXT_CONFIRM
    assert dialog.hint_label.text() == TEXT_BOTTOM_HINT


def test_reaching_bottom_enables_confirm(dialog, clock):
    clock.advance(5.0)
    dialog._on_tick()
    bar = dialog.view.verticalScrollBar()
    bar.setValue(bar.maximum())

    assert dialog.confirm_btn.isEnabled() is True
    assert confirm_color(dialog) == COLOR_PRIMARY
    assert dialog.hint_label.isVisible() is False


def test_confirm_emits_submit_request_with_version_and_shows_progress(dialog, clock):
    emitted: list[str] = []
    dialog.submit_requested.connect(emitted.append)
    clock.advance(5.0)
    dialog._on_tick()
    bar = dialog.view.verticalScrollBar()
    bar.setValue(bar.maximum())

    dialog.confirm_btn.click()

    assert emitted == ["terms-2026-10-v1"]
    assert dialog.confirm_btn.text() == TEXT_SUBMITTING
    assert dialog.confirm_btn.isEnabled() is False
    assert dialog.reject_btn.isEnabled() is False


def test_failed_submit_keeps_window_open_and_reading_state(dialog, clock):
    clock.advance(5.0)
    dialog._on_tick()
    dialog.view.verticalScrollBar().setValue(dialog.view.verticalScrollBar().maximum())
    dialog.begin_submit()

    dialog.finish_submit(False, "网络超时")

    assert dialog.result() != QDialog.DialogCode.Accepted
    assert dialog.isVisible() is True
    assert dialog.last_error == "网络超时"
    assert dialog.confirm_btn.isEnabled() is True
    assert dialog.confirm_btn.text() == TEXT_CONFIRM
    assert dialog.reject_btn.isEnabled() is True


def test_successful_submit_accepts_the_dialog(dialog, clock):
    clock.advance(5.0)
    dialog._on_tick()
    dialog.view.verticalScrollBar().setValue(dialog.view.verticalScrollBar().maximum())
    dialog.begin_submit()

    dialog.finish_submit(True)

    assert dialog.result() == QDialog.DialogCode.Accepted


def test_reject_returns_to_caller_without_accepting(dialog):
    dialog.reject_btn.click()

    assert dialog.result() == QDialog.DialogCode.Rejected


def test_reject_button_text_is_configurable_for_registration_flow(app, clock):
    widget = AgreementSignDialog(document=DOC, clock=clock)

    assert widget.reject_btn.text() == TEXT_REJECT
    widget.set_reject_text("关闭")
    assert widget.reject_btn.text() == "关闭"
    widget.close()
    widget.deleteLater()


def test_new_version_resets_timer_and_bottom(dialog, clock):
    clock.advance(5.0)
    dialog._on_tick()
    dialog.view.verticalScrollBar().setValue(dialog.view.verticalScrollBar().maximum())
    assert dialog.confirm_btn.isEnabled() is True

    dialog.set_document(long_document("terms-2026-10-v2"))

    assert dialog.confirm_btn.isEnabled() is False
    assert dialog.confirm_btn.text() == TEXT_CONFIRM_WAITING.format(seconds=5)
    assert dialog.version == "terms-2026-10-v2"


def test_load_failure_disables_confirm_and_offers_retry(app, clock):
    def failing_loader():
        raise RuntimeError("boom")

    widget = AgreementSignDialog(load_document=failing_loader, clock=clock)
    widget.show()
    widget.reload_document()
    widget._load_signals.finished.emit(widget._load_request_id, RuntimeError("boom"))

    assert widget.confirm_btn.isEnabled() is False
    assert widget.retry_btn.isVisible() is True

    widget.gate.mark_load_failed()
    widget._refresh_actions()
    assert widget.gate.load_failed_text == TEXT_LOAD_FAILED
    widget.close()
    widget.deleteLater()

def test_document_that_fits_on_one_screen_satisfies_bottom_after_five_seconds(app, clock):
    """正文一屏完整显示时，读满五秒即可同意，不需要真的去滚动。"""
    widget = AgreementSignDialog(document=SHORT_DOC, clock=clock)
    widget.show()
    clock.advance(5.0)
    widget._on_tick()

    assert widget.gate.reached_bottom is True
    assert widget.confirm_btn.isEnabled() is True
    widget.close()
    widget.deleteLater()
