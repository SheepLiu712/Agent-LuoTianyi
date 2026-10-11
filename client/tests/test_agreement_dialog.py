"""UA-1（issue #295）协议只读查阅窗口：正文渲染契约与只读行为。

覆盖范围严格对应 #295 的验收标准：

- 只读查阅：无倒计时、无同意／拒绝、关闭不写签署；
- 正文渲染：段落字号、局部粗体、连续空格、显式换行、居中／两端对齐，
  末行与显式换行前的行不拉伸，不执行 HTML；
- 随窗口宽度重排；加载失败可重试。
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import QApplication, QDialog

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
            sizes.append(char_format.font().pixelSize())
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
    assert fragment.charFormat().font().pixelSize() == dialog_module.DEFAULT_BLOCK_FONT_SIZE


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
def _left_aligned_document(text, point_size=16, width=420.0):
    """对照组：同样的文本／字号／宽度，但用 Qt 的左对齐。

    协议契约只允许 ``center`` 与 ``justify``，模块不产出左对齐文档；这里手工构造一份，
    用来判断两端对齐是否真的把非末行拉到了正文宽度（居中会整体位移，不能当对照组）。
    """
    document = QTextDocument()
    document.setDocumentMargin(0)
    cursor = QTextCursor(document)
    block_format = QTextBlockFormat()
    block_format.setAlignment(Qt.AlignmentFlag.AlignLeft)
    cursor.setBlockFormat(block_format)
    char_format = QTextCharFormat()
    font = QFont(document.defaultFont())
    font.setPixelSize(point_size)
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
    dialog.resize(640, 520)
    dialog.show()
    QApplication.processEvents()
    wide = sum(layout.lineCount() for _, layout in _blocks_of(dialog))

    dialog.resize(340, 520)
    for _ in range(6):
        QApplication.processEvents()
    narrow = sum(layout.lineCount() for _, layout in _blocks_of(dialog))

    assert narrow > wide


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


def test_window_has_a_single_title_source(make_dialog):
    """回归守卫：窗口不得再出现"系统标题栏 + 自绘标题栏"的双重标题栏。"""
    dialog = make_dialog()

    assert dialog.windowTitle() == "用户协议"
    assert not hasattr(dialog, "title_label")
    assert not hasattr(dialog, "close_btn")
    assert not hasattr(dialog, "_build_header")
    assert not hasattr(dialog_module, "COLOR_HEADER_BG")

    assert dialog.layout().count() == 2  # 正文区 + 底部操作区
    body = dialog.layout().itemAt(0).widget()
    assert dialog.version_label.parent() is body


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

    assert dialog.version == "terms-2026-10-v1"
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

    assert dialog.version is None
    assert not dialog.error_label.isHidden() and not dialog.retry_btn.isHidden()
    assert "连接超时" in dialog.error_label.text()

    dialog.reload_document()

    assert attempts["count"] == 2
    assert dialog.version == "terms-2026-10-v1"
    assert dialog.error_label.isHidden() and dialog.retry_btn.isHidden()
    dialog.close()


def test_load_exception_is_reported_not_raised(qapp):
    def boom():
        raise RuntimeError("网络不可达")

    dialog = AgreementDialog(load_document=boom)

    assert "网络不可达" in dialog.error_label.text()
    assert not dialog.retry_btn.isHidden()
    dialog.close()


def test_reload_without_loader_is_a_noop(make_dialog):
    dialog = make_dialog(document=DOC)

    assert dialog.reload_document() is False
    assert dialog.version == "terms-2026-10-v1"
