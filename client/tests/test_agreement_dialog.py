"""UA-1（issue #295）协议只读查阅窗口：正文渲染契约与只读行为。

覆盖范围严格对应 #295 的验收标准：

- 只读查阅：无倒计时、无同意／拒绝、关闭不写签署；
- 正文渲染：段落字号、局部粗体、连续空格、显式换行、居中／两端对齐，
  末行与显式换行前的行不拉伸，不执行 HTML；
- 随窗口宽度重排；加载失败可重试。
"""

import os
import threading
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QDialog, QLabel
from src.gui import agreement_dialog as dialog_module
from src.gui.agreement_dialog import AgreementDialog

DOC = {
    "version": "terms-2026-10-v1",
    "title": "用户协议",
    "format": "agreement.richtext.v1",
    "blocks": [
        {"font_size": 24, "align": "center", "runs": [{"text": "一、使用说明", "bold": True}]},
        {
            "font_size": 16,
            "align": "justify",
            "runs": [
                {"text": "请阅读", "bold": False},
                {"text": "重要内容", "bold": True},
                {"text": "。\n甲  乙    丙", "bold": False},
            ],
        },
        {"font_size": 16, "runs": [{"text": "缺省对齐段落。", "bold": False}]},
    ],
}

LEFT_DOC_PLACEHOLDER_SLACK_PX = 1.0
"""判定"左对齐首行是否留有余量"的容差（布局单位）。"""

WRAPPING_TEXT = (
    "请认真阅读本协议的全部内容与 terms of service 中的约定，凡使用本服务即视为你已充分理解并同意。"
    "本段用于撑出多行，以便检查两端对齐的拉伸行为。"
)
WRAPPING_DOC = {
    "version": "v",
    "title": "t",
    "blocks": [{"font_size": 16, "align": "justify", "runs": [{"text": WRAPPING_TEXT, "bold": False}]}],
}


@pytest.fixture(scope="module", autouse=True)
def qapp():
    """整个模块共用一个 QApplication（与 test_system_message.py 的写法一致）。"""
    app = QApplication.instance() or QApplication([])
    yield app


@pytest.fixture
def make_dialog(qapp):
    """构造协议窗口并在用例结束后关闭。"""
    dialogs = []

    def factory(document=DOC, **kwargs):
        dialog = AgreementDialog(document=document, **kwargs)
        dialogs.append(dialog)
        return dialog

    yield factory

    for dialog in dialogs:
        dialog.close()


def _wait_until(predicate, timeout=2.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if predicate():
            return
        time.sleep(0.01)
    QApplication.processEvents()
    assert predicate()


def _layout_document(payload, width=420.0):
    """渲染并按给定宽度排版，返回 (document, [(对齐, 行) ...])。"""
    document = dialog_module.render_agreement_document(payload)
    document.setTextWidth(width)
    document.documentLayout().documentSize()  # 强制排版
    blocks = []
    block = document.begin()
    while block.isValid():
        blocks.append((block.blockFormat().alignment(), block.layout()))
        block = block.next()
    return document, blocks


def _line_ink(line):
    """本行实际绘制的最大 x（取自字形位置，而非布局宽度）。"""
    best = 0.0
    for run in line.glyphRuns():
        for point in run.positions():
            best = max(best, point.x())
    return best


# ── 换行切分 ─────────────────────────────────────────────────────
def test_split_runs_on_newline_keeps_bold_and_consecutive_spaces():
    lines = dialog_module.split_runs_on_newline(DOC["blocks"][1]["runs"])

    assert len(lines) == 2
    assert lines[0] == [("请阅读", False), ("重要内容", True), ("。", False)]
    assert lines[1] == [("甲  乙    丙", False)]


def test_split_runs_on_newline_keeps_blank_lines():
    lines = dialog_module.split_runs_on_newline([{"text": "上\n\n下", "bold": False}])

    assert lines == [[("上", False)], [], [("下", False)]]


# ── 渲染契约 ─────────────────────────────────────────────────────
def test_render_splits_explicit_newline_into_its_own_block():
    document, blocks = _layout_document(DOC)

    # 3 个段落中有 1 个含显式换行 → 4 个文本块；换行前的行因此成为某个块的末行
    assert document.blockCount() == 4
    assert [int(alignment) for alignment, _ in blocks] == [
        int(Qt.AlignmentFlag.AlignCenter),
        int(Qt.AlignmentFlag.AlignJustify),
        int(Qt.AlignmentFlag.AlignJustify),
        int(Qt.AlignmentFlag.AlignJustify),
    ]


def test_render_maps_block_font_size_and_partial_bold():
    document, _ = _layout_document(DOC)

    sizes, bolds = [], []
    block = document.begin()
    while block.isValid():
        fragment = block.begin()
        while not fragment.atEnd():
            char_format = fragment.fragment().charFormat()
            sizes.append(char_format.font().pointSizeF())
            bolds.append(char_format.font().bold())
            fragment += 1
        block = block.next()

    assert set(sizes) == {24, 16}
    assert True in bolds and False in bolds


def test_render_defaults_to_justify_when_align_is_absent():
    _, blocks = _layout_document(DOC)

    # 第 3 段没有 align 字段 → 契约默认 justify
    assert int(blocks[3][0]) == int(Qt.AlignmentFlag.AlignJustify)


@pytest.mark.parametrize("bad_size", [999, 0, "16", True, None])
def test_render_falls_back_to_default_font_size(bad_size):
    payload = {"version": "v", "title": "t", "blocks": [{"font_size": bad_size, "runs": [{"text": "正文"}]}]}

    document, _ = _layout_document(payload)

    fragment = document.begin().begin().fragment()
    assert fragment.charFormat().font().pointSizeF() == pytest.approx(16.0)


def test_render_does_not_execute_html():
    payload = {
        "version": "v",
        "title": "t",
        "blocks": [{"runs": [{"text": "含 <b>标记</b> 与 <script>x</script>", "bold": False}]}],
    }

    document, _ = _layout_document(payload)

    assert "<b>标记</b>" in document.toPlainText()
    assert "<script>x</script>" in document.toPlainText()
    fragment = document.begin().begin().fragment()
    assert not fragment.charFormat().font().bold()


def test_render_skips_malformed_blocks_without_failing():
    payload = {
        "version": "v",
        "title": "t",
        "blocks": [
            "不是对象",
            {"runs": "不是数组"},
            {"font_size": 16, "runs": [{"text": "唯一有效段落"}]},
        ],
    }

    document, _ = _layout_document(payload)

    assert document.blockCount() == 1
    assert document.toPlainText() == "唯一有效段落"


# ── 两端对齐：不得静默降级为左对齐 ───────────────────────────────
def _left_aligned_document(text, point_size=16.0, width=420.0):
    """对照组：同样的文本／字号／宽度／块格式，但用 Qt 的左对齐。

    协议契约只允许 ``center`` 与 ``justify``，模块不产出左对齐文档；这里手工构造一份，
    用来判断两端对齐是否真的把非末行拉到了正文宽度（居中会整体位移，不能当对照组）。

    右边距必须与生产块一致：它决定折行宽度，缺了它对照组的折行落点会和正文不同，
    末行就不是同一段文字，末行行宽的对比也就失去意义。
    """
    document = QTextDocument()
    document.setDocumentMargin(0)
    cursor = QTextCursor(document)
    block_format = QTextBlockFormat()
    block_format.setAlignment(Qt.AlignmentFlag.AlignLeft)
    block_format.setRightMargin(dialog_module.TEXT_RIGHT_GUTTER)
    cursor.setBlockFormat(block_format)
    char_format = QTextCharFormat()
    font = QFont(document.defaultFont())
    font.setPointSizeF(point_size)
    char_format.setFont(font)
    cursor.insertText(text, char_format)
    document.setTextWidth(width)
    document.documentLayout().documentSize()
    return document


def test_justify_stretches_non_last_line_and_leaves_last_line_natural():
    _, justify_blocks = _layout_document(WRAPPING_DOC, width=420.0)
    control = _left_aligned_document(WRAPPING_TEXT)

    justify_layout = justify_blocks[0][1]
    left_layout = control.begin().layout()
    assert justify_layout.lineCount() == left_layout.lineCount() > 1

    # 末行不拉伸：与左对齐对照组的绘制范围一致
    last = justify_layout.lineCount() - 1
    assert _line_ink(justify_layout.lineAt(last)) == pytest.approx(
        _line_ink(left_layout.lineAt(last)), abs=1.0
    )

    # 非末行：左对齐留有余量时，两端对齐必须把它吃掉（证明未静默降级）
    first_justify = _line_ink(justify_layout.lineAt(0))
    first_left = _line_ink(left_layout.lineAt(0))
    assert first_justify >= first_left
    if first_left < 420.0 - LEFT_DOC_PLACEHOLDER_SLACK_PX:
        assert first_justify > first_left


def test_reflow_adds_lines_when_window_narrows(make_dialog):
    payload = {
        "version": "v",
        "title": "t",
        "blocks": [{"font_size": 16, "runs": [{"text": WRAPPING_TEXT * 3, "bold": False}]}],
    }
    dialog = make_dialog(document=payload)
    dialog.resize(900, 520)
    dialog.show()
    QApplication.processEvents()
    wide = sum(layout.lineCount() for _, layout in _blocks_of(dialog))

    dialog.resize(560, 520)
    for _ in range(6):
        QApplication.processEvents()
    narrow = sum(layout.lineCount() for _, layout in _blocks_of(dialog))

    assert narrow > wide


def test_text_size_comes_from_protocol_number(make_dialog):
    """协议 ``font_size`` 数值直接作为点字号：24 → 24pt、16 → 16pt。

    应用字体从 9pt 调到 24pt 后字号不变；字号只由协议里的数值决定。
    """
    payload = {
        "version": "v",
        "title": "t",
        "blocks": [
            {"font_size": 24, "runs": [{"text": "标题"}]},
            {"font_size": 16, "runs": [{"text": WRAPPING_TEXT * 3}]},
        ],
    }
    dialog = make_dialog(document=payload)
    dialog.resize(420, 520)
    small_font = QFont(dialog.font())
    small_font.setPointSizeF(9.0)
    dialog.setFont(small_font)
    dialog.show()
    QApplication.processEvents()

    document = dialog.view.document()
    small_title = document.begin().begin().fragment().charFormat().font().pointSizeF()
    small_body = document.begin().next().begin().fragment().charFormat().font().pointSizeF()

    large_font = QFont(dialog.font())
    large_font.setPointSizeF(24.0)
    dialog.setFont(large_font)
    for _ in range(6):
        QApplication.processEvents()

    document = dialog.view.document()
    large_title = document.begin().begin().fragment().charFormat().font().pointSizeF()
    large_body = document.begin().next().begin().fragment().charFormat().font().pointSizeF()

    assert (small_title, small_body) == (24.0, 16.0)
    assert (large_title, large_body) == (small_title, small_body)


def _blocks_of(dialog):
    document = dialog.view.document()
    blocks = []
    block = document.begin()
    while block.isValid():
        blocks.append((block.blockFormat().alignment(), block.layout()))
        block = block.next()
    return blocks


# ── 只读范围（#295 守卫） ────────────────────────────────────────
@pytest.mark.parametrize(
    "absent",
    ["SubmitOutcome", "ForegroundReadingClock", "READING_SECONDS", "MODE_SIGN", "MODE_READ_ONLY"],
)
def test_module_exposes_no_signing_or_countdown_api(absent):
    assert not hasattr(dialog_module, absent)


@pytest.mark.parametrize(
    "absent",
    ["accept_btn", "refuse_btn", "on_accept", "reached_bottom", "remaining_seconds", "accepted_version"],
)
def test_dialog_exposes_no_signing_or_countdown_state(make_dialog, absent):
    assert not hasattr(make_dialog(), absent)


def test_title_is_carried_by_the_window_frame_only(make_dialog):
    """回归守卫：标题只由系统标题栏承载，窗口内容里不再重复出现（曾出现双重标题栏）。

    只断言"标题不重复"这个结果，不检查内部控件名——换实现方式不必改测试。
    """
    dialog = make_dialog()

    assert dialog.windowTitle() == "用户协议"
    repeated = [label.text() for label in dialog.findChildren(QLabel) if label.text() == dialog.windowTitle()]
    assert repeated == []


def test_version_body_and_actions_share_one_left_edge(make_dialog):
    """回归守卫：版本号、正文、底部按钮左缘对齐。

    曾出现"外层边距 + 内层卡片内边距"累加，使正文比按钮多缩进 18px。这里只断言渲染后的
    左缘一致，不钉具体数值、也不检查控件名——改边距、改配色、换实现方式都不必改测试。
    """
    dialog = make_dialog()
    dialog.resize(640, 520)
    dialog.show()
    for _ in range(4):
        QApplication.processEvents()

    body = dialog.layout().itemAt(0).widget()
    actions = dialog.layout().itemAt(1).widget()
    left_edges = {
        body.x() + dialog.version_label.x(),
        body.x() + dialog.view.x(),
        actions.x() + dialog.close_action_btn.x(),
    }

    assert len(left_edges) == 1
    dialog.close()


def test_view_does_not_offer_a_context_menu(make_dialog):
    """只读查阅窗口不提供右键菜单（QTextEdit 默认会弹 Qt 自带的复制/全选）。

    这里断言策略而不是"发一个右键事件看是否弹窗"：万一有人把菜单放回来，菜单的 exec() 会
    阻塞测试进程（挂死，而不是干脆失败）。
    """
    assert make_dialog().view.contextMenuPolicy() == Qt.ContextMenuPolicy.NoContextMenu


def test_version_label_and_close_action(make_dialog):
    dialog = make_dialog()

    assert dialog.version_label.text() == "版本：terms-2026-10-v1"
    assert dialog.close_action_btn.text() == dialog_module.TEXT_CLOSE
    assert dialog.retry_btn.isHidden() and dialog.error_label.isHidden()

    dialog.close_action_btn.click()

    assert dialog.result() == int(QDialog.DialogCode.Rejected)


# ── 加载与失败重试 ───────────────────────────────────────────────
def test_load_success_sets_version_and_clears_error(qapp):
    dialog = AgreementDialog(load_document=lambda: (True, "", DOC))

    _wait_until(lambda: dialog.version == "terms-2026-10-v1")
    assert dialog.error_label.isHidden() and dialog.retry_btn.isHidden()
    dialog.close()


def test_load_failure_shows_error_and_retry_then_recovers(qapp):
    attempts = {"count": 0}

    def flaky():
        attempts["count"] += 1
        if attempts["count"] == 1:
            return False, "连接超时", {}
        return True, "", DOC

    dialog = AgreementDialog(load_document=flaky)

    _wait_until(lambda: "连接超时" in dialog.error_label.text())
    assert dialog.version is None
    assert not dialog.error_label.isHidden() and not dialog.retry_btn.isHidden()

    dialog.reload_document()

    _wait_until(lambda: dialog.version == "terms-2026-10-v1")
    assert attempts["count"] == 2
    assert dialog.error_label.isHidden() and dialog.retry_btn.isHidden()
    dialog.close()


def test_load_exception_is_reported_not_raised(qapp):
    def boom():
        raise RuntimeError("网络不可达")

    dialog = AgreementDialog(load_document=boom)

    _wait_until(lambda: "网络不可达" in dialog.error_label.text())
    assert not dialog.retry_btn.isHidden()
    dialog.close()


def test_failure_message_sits_in_the_content_area(qapp):
    """回归守卫：失败提示落在正文区，不被压到底部操作区。

    曾把 error_label 建在底部操作区（分隔线与按钮之间），失败时正文区只剩一个空 view
    占满高度，提示就贴着按钮出现在窗口最底下。用窗口坐标比较，不依赖提示挂在哪个容器下。
    """
    dialog = AgreementDialog(load_document=lambda: (False, "连接超时", {}))
    dialog.resize(640, 520)
    dialog.show()
    _wait_until(lambda: "连接超时" in dialog.error_label.text())

    actions_top = dialog.layout().itemAt(1).widget().mapTo(dialog, QPoint(0, 0)).y()
    message_bottom = (
        dialog.error_label.mapTo(dialog, QPoint(0, 0)).y() + dialog.error_label.height()
    )

    assert not dialog.error_label.isHidden()
    assert message_bottom < actions_top
    dialog.close()


def test_slow_loader_does_not_block_gui_event_loop(qapp):
    release = threading.Event()
    timer_fired = []

    def slow_loader():
        release.wait(timeout=2)
        return True, "", DOC

    started = time.monotonic()
    dialog = AgreementDialog(load_document=slow_loader)
    constructor_seconds = time.monotonic() - started
    QTimer.singleShot(0, lambda: timer_fired.append(True))

    _wait_until(lambda: bool(timer_fired))
    assert constructor_seconds < 0.2
    assert dialog.version is None
    assert dialog.error_label.text() == dialog_module.TEXT_LOADING

    release.set()
    _wait_until(lambda: dialog.version == "terms-2026-10-v1")
    dialog.close()


def test_close_ignores_late_loader_result(qapp):
    release = threading.Event()
    completed = threading.Event()

    def slow_loader():
        release.wait(timeout=2)
        completed.set()
        return True, "", DOC

    dialog = AgreementDialog(load_document=slow_loader)
    dialog.reject()
    release.set()
    _wait_until(completed.is_set)
    for _ in range(4):
        QApplication.processEvents()

    assert dialog.version is None
    assert dialog._closed is True


def test_reload_without_loader_is_a_noop(make_dialog):
    dialog = make_dialog(document=DOC)

    assert dialog.reload_document() is False
    assert dialog.version == "terms-2026-10-v1"
