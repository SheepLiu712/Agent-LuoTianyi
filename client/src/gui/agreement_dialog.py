"""用户协议只读查阅窗口（UA-1 · issue #295）。

范围（严格对齐 #295 的验收标准与「范围与 PR」）：

- 桌面设置里**只读查阅**当前协议正文与版本；失败可重试；关闭保留原会话，不写签署；
- **不启用登录或注册门禁**：本窗口没有倒计时、同意或拒绝操作；
- 正文渲染能力单独以 :func:`render_agreement_document` 提供，供后续签署流程复用。

渲染契约（#295 AC 与 spec「接口规范 1」）：

- 段落级 ``font_size``（12–32，默认 16）映射到客户端逻辑字号；
- 段落级 ``align`` 仅 ``center``（居中）/``justify``（两端对齐），缺省 ``justify``；
- ``runs`` 内 ``bold`` 局部加粗；连续普通空格与 ``\\n`` 原样保留；
- 末行与显式换行前的行不拉伸；对齐只调间距，不缩放字形；
- 不执行 HTML（HTML 会折叠连续空格，也会引入协议未允许的标记与交互）；
- 随窗口／字号变化重排。

实现要点：Qt 的 ``AlignJustify`` 会把非末行拉伸到正文宽度、末行保持自然宽度；把 ``\\n``
切成独立文本块，正好让「显式换行前的行」成为某个块的末行，从而不被拉伸。
"""

from __future__ import annotations

from typing import Any, Callable, Mapping, Sequence

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont, QTextBlockFormat, QTextCharFormat, QTextCursor, QTextDocument
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..utils.logger import get_logger

DEFAULT_BLOCK_FONT_SIZE = 16
MIN_BLOCK_FONT_SIZE = 12
MAX_BLOCK_FONT_SIZE = 32

ALIGN_CENTER = "center"
ALIGN_JUSTIFY = "justify"

BODY_SIDE_MARGIN = 32
"""正文与底部操作区共用的左右内边距：单一边距，避免嵌套累加。"""

TEXT_RIGHT_GUTTER = 12
"""正文块额外保留的右侧留白。

滚动条占用 view 自己的宽度、不会盖住正文，但正文的换行边界默认紧贴滚动条；两端对齐又会
把非末行拉到该边界，视觉上就像被滚动条压住。给块加右边距即可留出这条间隙，同时不影响
正文左缘（左缘仍由 BODY_SIDE_MARGIN 决定，与底部按钮对齐）。
"""

LINE_HEIGHT_PERCENT = 150
"""正文行距（百分比）。中文长段落按 150% 行距更易读。"""

# 配色取自设计稿标注（docs/开发进程文档/assets/用户协议签署-ui.svg）
COLOR_TEXT = "#17283d"
COLOR_MUTED = "#64748b"
COLOR_DIVIDER = "#e2e8f0"
COLOR_SURFACE = "#ffffff"
COLOR_SCROLL_HANDLE = "#cbd5e1"
COLOR_PRIMARY = "#93C5FD"
COLOR_SECONDARY_BG = "#f1f5f9"
COLOR_ERROR = "#b91c1c"

TEXT_CLOSE = "关闭"
TEXT_RETRY = "重试"
TEXT_LOAD_FAILED = "加载用户协议失败"

DocumentLoader = Callable[[], "tuple[bool, str, Mapping[str, Any]]"]
"""取协议正文：返回 ``(ok, detail, payload)``；``payload`` 为 ``GET /auth/agreement`` 的 JSON。"""


def _block_font_size(block: Mapping[str, Any]) -> int:
    """取段落字号；非法值退回默认值，不因单个字段异常中断整篇渲染。"""
    value = block.get("font_size", DEFAULT_BLOCK_FONT_SIZE)
    if isinstance(value, bool) or not isinstance(value, int):
        return DEFAULT_BLOCK_FONT_SIZE
    if not MIN_BLOCK_FONT_SIZE <= value <= MAX_BLOCK_FONT_SIZE:
        return DEFAULT_BLOCK_FONT_SIZE
    return value


def _block_alignment(block: Mapping[str, Any]) -> Qt.AlignmentFlag:
    """段落级对齐；缺省与未知取值都按契约默认的 ``justify`` 处理。"""
    return Qt.AlignmentFlag.AlignCenter if block.get("align") == ALIGN_CENTER else Qt.AlignmentFlag.AlignJustify


def split_runs_on_newline(runs: Sequence[Mapping[str, Any]]) -> list[list[tuple[str, bool]]]:
    """把一段的 runs 按 ``\\n`` 切成多个显示行，保留连续空格与空行。

    换行是段落内的显式换行：契约要求 ``\\n`` 之前的行靠左且不拉伸，因此渲染时把每个
    显示行放进独立文本块——块的末行天然不参与两端对齐的拉伸。
    """
    lines: list[list[tuple[str, bool]]] = [[]]
    for run in runs:
        text = run.get("text", "")
        if not isinstance(text, str):
            text = str(text)
        bold = bool(run.get("bold", False))
        for index, part in enumerate(text.split("\n")):
            if index:
                lines.append([])
            if part:
                lines[-1].append((part, bold))
    return lines


def render_agreement_document(payload: Mapping[str, Any], font_family: str | None = None) -> QTextDocument:
    """把服务端协议正文渲染成富文本文档（供只读查阅与后续签署流程复用）。

    逐段落套用字号与对齐、逐 run 套用粗细；这里刻意不使用 HTML：HTML 会折叠连续空格，
    也会引入协议未允许的标记与交互行为。
    """
    document = QTextDocument()
    document.setDocumentMargin(0)
    if font_family:
        document.setDefaultFont(QFont(font_family))

    cursor = QTextCursor(document)
    blocks = payload.get("blocks") or []
    started = False
    for block in blocks:
        if not isinstance(block, Mapping):
            continue
        size = _block_font_size(block)
        alignment = _block_alignment(block)
        runs = block.get("runs") or []
        if isinstance(runs, (str, bytes)) or not isinstance(runs, Sequence):
            continue
        for line in split_runs_on_newline(runs):
            if started:
                cursor.insertBlock()
            block_format = QTextBlockFormat()
            block_format.setAlignment(alignment)
            block_format.setRightMargin(TEXT_RIGHT_GUTTER)
            block_format.setLineHeight(
                float(LINE_HEIGHT_PERCENT),
                # PySide6 只接受 int：传枚举对象或 int(枚举) 都会 TypeError，必须取 .value
                int(QTextBlockFormat.LineHeightTypes.ProportionalHeight.value),
            )
            cursor.setBlockFormat(block_format)
            for text, bold in line:
                char_format = QTextCharFormat()
                font = QFont(document.defaultFont())
                font.setPixelSize(size)
                font.setBold(bold)
                char_format.setFont(font)
                cursor.insertText(text, char_format)
            started = True
    return document


class AgreementDialog(QDialog):
    """只读的协议查阅窗口；底部只有「关闭」，加载失败时额外出现「重试」。"""

    def __init__(
        self,
        parent: QWidget | None = None,
        *,
        document: Mapping[str, Any] | None = None,
        load_document: DocumentLoader | None = None,
    ) -> None:
        super().__init__(parent)
        self.logger = get_logger(self.__class__.__name__)
        self._load_document = load_document
        self.version: str | None = None
        self.last_error: str = ""

        self.setWindowTitle("用户协议")
        self.setModal(True)
        self.setMinimumSize(560, 460)
        self.resize(640, 520)
        # 窗口整体白底（设计稿 §04：白卡即窗口本身），正文与按钮共用同一个左右边距
        self.setStyleSheet(f"QDialog {{ background-color: {COLOR_SURFACE}; }}")
        self._build_ui()

        if document is not None:
            self.set_document(document)
        elif self._load_document is not None:
            self.reload_document()

    # ── 构建界面 ─────────────────────────────────────────────────
    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(self._build_body())
        outer.addWidget(self._build_actions())

    def _build_body(self) -> QWidget:
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(BODY_SIDE_MARGIN, 14, BODY_SIDE_MARGIN, 0)
        column.setSpacing(10)

        self.version_label = QLabel("")
        self.version_label.setStyleSheet(f"font-size: 13px; color: {COLOR_MUTED};")
        column.addWidget(self.version_label)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        # 只读查阅窗口不提供右键菜单（QTextEdit 默认会弹复制/全选）
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.setStyleSheet(
            f"QTextEdit {{ background: transparent; color: {COLOR_TEXT}; border: none; }}"
            "QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }"
            f"QScrollBar::handle:vertical {{ background: {COLOR_SCROLL_HANDLE}; min-height: 40px; border-radius: 2px; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        column.addWidget(self.view, 1)
        return body

    def _build_actions(self) -> QWidget:
        actions = QWidget()
        column = QVBoxLayout(actions)
        column.setContentsMargins(BODY_SIDE_MARGIN, 0, BODY_SIDE_MARGIN, 16)
        column.setSpacing(8)

        self.divider = QFrame()
        self.divider.setFixedHeight(1)
        self.divider.setStyleSheet(f"background-color: {COLOR_DIVIDER}; border: none;")
        column.addWidget(self.divider)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet(f"font-size: 13px; color: {COLOR_ERROR};")
        self.error_label.setVisible(False)
        column.addWidget(self.error_label)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.retry_btn = QPushButton(TEXT_RETRY)
        self.retry_btn.setMinimumHeight(44)
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: 8px; font-size: 14px; padding: 10px 16px;"
            f" background-color: {COLOR_SECONDARY_BG}; color: {COLOR_TEXT}; }}"
            f"QPushButton:hover {{ background-color: {COLOR_DIVIDER}; }}"
        )
        self.retry_btn.clicked.connect(self.reload_document)
        self.retry_btn.setVisible(False)

        self.close_action_btn = QPushButton(TEXT_CLOSE)
        self.close_action_btn.setMinimumHeight(44)
        self.close_action_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_action_btn.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: 8px; font-size: 14px; padding: 10px 16px;"
            f" background-color: {COLOR_PRIMARY}; color: {COLOR_TEXT}; }}"
            f"QPushButton:hover {{ background-color: {COLOR_PRIMARY}; }}"
        )
        self.close_action_btn.clicked.connect(self.reject)

        row.addWidget(self.retry_btn)
        row.addWidget(self.close_action_btn, 1)
        column.addLayout(row)
        return actions

    # ── 正文 ─────────────────────────────────────────────────────
    def set_document(self, payload: Mapping[str, Any]) -> None:
        """装载一份协议正文；只读窗口不含任何签署或计时状态。"""
        self.version = str(payload.get("version", "") or "")
        self.setWindowTitle(str(payload.get("title", "") or "用户协议"))
        self.version_label.setText(f"版本：{self.version}" if self.version else "")
        self.view.setDocument(render_agreement_document(payload, self.font().family()))
        self._set_failure(None)

    def reload_document(self) -> bool:
        """按注入的 ``load_document`` 取正文；失败时提示并可重试，不写任何签署。"""
        if self._load_document is None:
            return False
        try:
            ok, detail, payload = self._load_document()
        except Exception as error:  # noqa: BLE001 - 网络层异常统一转成界面提示
            self.logger.error(f"加载用户协议失败: {error}")
            self._set_failure(f"{TEXT_LOAD_FAILED}：{error}")
            return False
        if not ok or not payload:
            self._set_failure(f"{TEXT_LOAD_FAILED}：{detail}")
            return False
        self.last_error = ""
        self.set_document(payload)
        return True

    def _set_failure(self, message: str | None) -> None:
        """切换失败态：显示错误与「重试」，成功态恢复设计稿的单一「关闭」。"""
        self.last_error = message or ""
        self.error_label.setText(message or "")
        self.error_label.setVisible(bool(message))
        self.retry_btn.setVisible(bool(message))

    # ── 生命周期 ─────────────────────────────────────────────────
    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        """关闭查阅窗口只结束本次查阅：不写签署、不影响既有会话。"""
        super().closeEvent(event)
