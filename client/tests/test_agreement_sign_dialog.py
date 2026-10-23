"""签署窗口的行为测试：门禁文案、按钮可用性、拒绝语义、提交状态与换版重置。"""

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QPoint  # noqa: E402
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
    # 提示条不再隐藏，而是保留占位（避免拖动滚动条时正文高度变化，见 N19）。
    assert dialog.hint_label.text() == ""
    assert dialog.hint_label.height() == 18


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


def test_submit_cannot_be_closed_by_reject_or_close_event(dialog, clock):
    dialog.begin_submit()
    dialog.reject()
    assert dialog.isVisible() is True
    assert dialog.result() == 0

    from PySide6.QtGui import QCloseEvent

    event = QCloseEvent()
    dialog.closeEvent(event)
    assert event.isAccepted() is False
    assert dialog.isVisible() is True


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


def test_async_loaded_document_resumes_timer_when_window_stays_active(app, clock):
    widget = AgreementSignDialog(load_document=lambda: (True, "", SHORT_DOC), clock=clock)
    widget.show()
    app.processEvents()
    widget._load_signals.finished.emit(widget._load_request_id, (True, "", SHORT_DOC))
    app.processEvents()

    clock.advance(5.0)
    widget._on_tick()

    assert widget.gate.elapsed_seconds == 5.0
    assert widget.gate.reached_bottom is True
    assert widget.confirm_btn.isEnabled() is True
    widget.close()
    widget.deleteLater()


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


def _laid_out(dialog):
    """强制排版并返回 (文档排版宽, 文档排版高, viewport 宽)。"""
    dialog._sync_scroll_state()
    size = dialog.view.document().documentLayout().documentSize()
    return size.width(), size.height(), dialog.view.viewport().width()


def _wrapping_document() -> dict:
    """长段落文档：宽度变化会改变换行数，用来验证响应式排版。"""
    return {
        "version": "terms-2026-10-v1",
        "title": "用户协议",
        "format": "agreement.richtext.v1",
        "blocks": [
            {"font_size": 16, "align": "justify", "runs": [{"text": "甲" * 400, "bold": False}]}
            for _ in range(20)
        ],
    }


def test_document_reflows_when_window_narrows(app):
    """窗口变窄时正文必须重新换行，而不是固定在初始宽度。"""
    widget = AgreementSignDialog(document=_wrapping_document())
    widget.show()
    try:
        widget.resize(900, 600)
        app.processEvents()
        _, wide_height, wide_viewport = _laid_out(widget)

        widget.resize(520, 600)
        app.processEvents()
        narrow_width, narrow_height, narrow_viewport = _laid_out(widget)

        assert narrow_viewport < wide_viewport  # 平台确实缩小了窗口
        assert narrow_width <= narrow_viewport + 2  # 不再按未换行宽度排版
        assert narrow_height > wide_height  # 换行导致行数增加
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_default_width_does_not_clip_document(app):
    """默认窗口宽度下正文不得超出可视区（此前默认 640 就裁掉约 61px）。"""
    widget = AgreementSignDialog(document=_wrapping_document())
    widget.show()
    try:
        app.processEvents()
        doc_width, _, viewport_width = _laid_out(widget)

        assert doc_width <= viewport_width + 2
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_bottom_scroll_is_stable(app, dialog):
    """滚到底后 value == maximum，且不会因为再次同步排版而多出一截。"""
    bar = dialog.view.verticalScrollBar()
    bar.setValue(bar.maximum())
    app.processEvents()
    dialog._sync_scroll_state()
    app.processEvents()

    stable_maximum = bar.maximum()
    assert bar.value() == stable_maximum

    dialog._sync_scroll_state()
    app.processEvents()
    assert bar.maximum() == stable_maximum
    assert bar.value() == bar.maximum()


def _top_block_number(dialog) -> int:
    return dialog.view.cursorForPosition(QPoint(0, 1)).block().blockNumber()


def test_resize_keeps_the_paragraph_at_viewport_top(app):
    """改宽度引起重排时，视口顶部那段正文必须留在原位（scroll anchoring）。

    此前按像素保存滚动位置：上方换行数一变，正在读的段落就被顶走。三档宽度往复切换，
    顶部段落编号都应保持不变。
    """
    widget = AgreementSignDialog(document=_wrapping_document())
    widget.show()
    try:
        widget.resize(640, 520)
        app.processEvents()
        bar = widget.view.verticalScrollBar()
        bar.setValue(int(bar.maximum() * 0.5))
        app.processEvents()
        anchor = _top_block_number(widget)

        for width in (1000, 520, 1400, 640, 900):
            widget.resize(width, 520)
            app.processEvents()
            assert _top_block_number(widget) == anchor, f"宽度 {width} 下顶部段落漂移"
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_resize_keeps_bottom_pinned(app):
    """停在底部时改宽度，仍应停在底部而不是被重排顶离。"""
    widget = AgreementSignDialog(document=_wrapping_document())
    widget.show()
    try:
        widget.resize(640, 520)
        app.processEvents()
        bar = widget.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        app.processEvents()

        for width in (1000, 520, 1400):
            widget.resize(width, 520)
            app.processEvents()
            assert bar.value() == bar.maximum(), f"宽度 {width} 下未停到底部"
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_resize_at_top_keeps_first_paragraph(app):
    """未滚动时改宽度，仍应停在第一段。"""
    widget = AgreementSignDialog(document=_wrapping_document())
    widget.show()
    try:
        widget.resize(640, 520)
        app.processEvents()
        bar = widget.view.verticalScrollBar()
        bar.setValue(0)
        app.processEvents()

        for width in (1000, 520, 1400):
            widget.resize(width, 520)
            app.processEvents()
            assert bar.value() == 0
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_resize_does_not_satisfy_bottom_gate(app):
    """改窗口宽度不得把"到过底部"标记为满足：重排的中间瞬态不能喂给门禁。"""
    widget = AgreementSignDialog(document=_wrapping_document())
    widget.show()
    try:
        widget.resize(640, 520)
        app.processEvents()
        bar = widget.view.verticalScrollBar()
        bar.setValue(int(bar.maximum() * 0.5))
        app.processEvents()
        assert widget.gate.reached_bottom is False

        for width in (1400, 520, 1000, 560):
            widget.resize(width, 520)
            app.processEvents()
            app.processEvents()
            assert widget.gate.reached_bottom is False, f"宽度 {width} 下门禁被重排误满足"
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_hint_sits_below_divider(app, dialog):
    """按草图顺序：分隔线在正文与提示之间，提示不再紧贴正文。"""
    from PySide6.QtWidgets import QFrame

    layout = dialog.hint_label.parentWidget().layout()
    widgets = [layout.itemAt(i).widget() for i in range(layout.count())]
    divider_index = next(
        i for i, widget in enumerate(widgets) if isinstance(widget, QFrame) and widget.height() == 1
    )
    assert divider_index < layout.indexOf(dialog.hint_label)


def test_reject_stops_the_ticker(app, dialog):
    """拒绝路径也要停计时器（此前只有标题栏 X 与成功路径会停）。"""
    dialog.show()
    app.processEvents()
    assert dialog._timer.isActive()

    dialog.reject()

    assert dialog._timer.isActive() is False


def test_widening_until_document_fits_satisfies_bottom(app, clock):
    """正文由"需要滚动"变为"一屏完整可见"后，应按最终尺寸满足底部条件（审查 N18）。"""
    from src.gui.agreement_sign_dialog import AgreementSignDialog as Dialog

    fits_after_widening = {
        "version": "terms-2026-10-v1",
        "title": "用户协议",
        "format": "agreement.richtext.v1",
        "blocks": [{"font_size": 16, "align": "justify", "runs": [{"text": "甲" * 400, "bold": False}]}],
    }
    widget = Dialog(document=fits_after_widening, clock=clock)
    widget.show()
    try:
        widget.resize(640, 520)
        app.processEvents()
        bar = widget.view.verticalScrollBar()
        assert bar.maximum() > 0  # 初始需要滚动

        widget.resize(1400, 520)
        app.processEvents()
        app.processEvents()

        assert bar.maximum() == 0  # 拉宽后一屏完整可见
        assert widget.gate.reached_bottom is True
        clock.advance(5.0)
        widget._on_tick()
        assert widget.confirm_btn.isEnabled() is True
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()


def test_hint_reserves_space_when_hidden(app, dialog):
    """提示条隐藏时保留占位，避免拖动滚动条时正文高度变化（审查 N19）。"""
    assert dialog.hint_label.height() == 18
    dialog.gate.observe_scroll(0, 0)  # 一屏放得下：提示文案应为空
    dialog._refresh_actions()
    assert dialog.gate.hint_text == ""
    assert dialog.hint_label.isVisible() is True
    assert dialog.hint_label.height() == 18
