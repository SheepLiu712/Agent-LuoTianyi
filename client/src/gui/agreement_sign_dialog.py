"""新用户注册前的协议签署窗口（UA-2 · issue #296）。

与只读查阅窗口（:mod:`agreement_dialog`，受 #295 守卫保护的只读范围）分开：本窗口带阅读
门禁与同意/拒绝操作，但复用它的正文渲染 ``render_agreement_document`` 与配色常量。

职责边界：本模块只管"读到满足条件 + 提交状态与文案"；真正的注册请求、请求 ID 落盘与
结果恢复由调用方（登录窗口）负责，通过 :attr:`AgreementSignDialog.submit_requested`
信号与 :meth:`begin_submit` / :meth:`finish_submit` 协作。
"""

from __future__ import annotations

import time
from typing import Any, Callable, Mapping, Optional

from PySide6.QtCore import QObject, QPoint, QRunnable, Qt, QThreadPool, QTimer, Signal
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

from .agreement_dialog import (
    BODY_SIDE_MARGIN,
    COLOR_DIVIDER,
    COLOR_MUTED,
    COLOR_PRIMARY,
    COLOR_SECONDARY_BG,
    COLOR_SCROLL_HANDLE,
    COLOR_SCROLL_HANDLE_HOVER,
    COLOR_SURFACE,
    COLOR_TEXT,
    TEXT_RETRY,
    render_agreement_document,
)
from .signing_gate import STATUS_LOAD_FAILED, STATUS_SUBMITTING, SigningGate

COLOR_DISABLED = "#D1D5DB"
TEXT_REJECT = "不同意，返回注册"
TEXT_REJECT_READONLY = "关闭"

TICK_INTERVAL_MS = 100


class _LoadSignals(QObject):
    finished = Signal(int, object)


class _LoadTask(QRunnable):
    """在后台线程拉取协议正文，避免阻塞界面。"""

    def __init__(self, request_id: int, loader: Callable[[], Mapping[str, Any]], signals: _LoadSignals) -> None:
        super().__init__()
        self._request_id = request_id
        self._loader = loader
        self._signals = signals

    def run(self) -> None:  # pragma: no cover - 由线程池调用
        try:
            payload = self._loader()
            self._signals.finished.emit(self._request_id, payload)
        except Exception as error:  # noqa: BLE001 - 任何加载失败都要转成界面提示
            self._signals.finished.emit(self._request_id, error)


class AgreementSignDialog(QDialog):
    """带阅读门禁的协议签署窗口；默认拒绝文案面向"新用户返回注册表单"。"""

    submit_requested = Signal(str)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        document: Optional[Mapping[str, Any]] = None,
        load_document: Optional[Callable[[], Mapping[str, Any]]] = None,
        reject_text: str = TEXT_REJECT,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        super().__init__(parent)
        self._load_document = load_document
        self._clock = clock
        self._thread_pool = QThreadPool.globalInstance()
        self._load_signals = _LoadSignals()
        self._load_signals.finished.connect(self._on_load_finished)
        self._load_request_id = 0
        self._load_in_flight = False
        self._document_payload: Optional[Mapping[str, Any]] = None
        self.submit_token = ""
        self._allow_close = False
        self.gate = SigningGate()
        self.version: str = ""
        self.last_error: str = ""
        self._pending_anchor: Optional[tuple] = None

        self.setWindowTitle("用户协议")
        self.setModal(True)
        self.setMinimumSize(560, 460)
        self.resize(640, 520)
        self.setStyleSheet(f"QDialog {{ background-color: {COLOR_SURFACE}; }}")
        self._build_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(TICK_INTERVAL_MS)
        self._timer.timeout.connect(self._on_tick)

        # 重排补偿要等布局算完，0ms 单次定时器让同一次事件循环内连续 resize 只补偿最后结果。
        self._anchor_restore_timer = QTimer(self)
        self._anchor_restore_timer.setSingleShot(True)
        self._anchor_restore_timer.setInterval(0)
        self._anchor_restore_timer.timeout.connect(self._restore_scroll_anchor)

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
        self._refresh_actions()

    def _build_body(self) -> QWidget:
        body = QWidget()
        column = QVBoxLayout(body)
        column.setContentsMargins(BODY_SIDE_MARGIN, 14, BODY_SIDE_MARGIN, 0)
        column.setSpacing(10)

        self.version_label = QLabel("")
        self.version_label.setStyleSheet(f"font-size: 13px; color: {COLOR_MUTED};")
        column.addWidget(self.version_label)

        self.error_label = QLabel("")
        self.error_label.setWordWrap(True)
        self.error_label.setStyleSheet("font-size: 13px; color: #b91c1c;")
        self.error_label.setVisible(False)
        column.addWidget(self.error_label)

        self.view = QTextEdit()
        self.view.setReadOnly(True)
        self.view.setFrameShape(QFrame.Shape.NoFrame)
        self.view.setLineWrapMode(QTextEdit.LineWrapMode.WidgetWidth)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.NoContextMenu)
        self.view.setStyleSheet(
            f"QTextEdit {{ background: transparent; color: {COLOR_TEXT}; border: none; }}"
            "QScrollBar:vertical { background: transparent; width: 12px; margin: 0; }"
            f"QScrollBar::handle:vertical {{ background: {COLOR_SCROLL_HANDLE}; min-height: 40px;"
            " border-radius: 3px; }"
            f"QScrollBar::handle:vertical:hover {{ background: {COLOR_SCROLL_HANDLE_HOVER}; }}"
            "QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }"
        )
        self.view.verticalScrollBar().valueChanged.connect(self._on_scroll)
        self.view.verticalScrollBar().rangeChanged.connect(lambda *_: self._on_scroll())
        column.addWidget(self.view, 1)
        self.view.installEventFilter(self)
        return body

    def _build_actions(self) -> QWidget:
        actions = QWidget()
        column = QVBoxLayout(actions)
        column.setContentsMargins(BODY_SIDE_MARGIN, 0, BODY_SIDE_MARGIN, 16)
        column.setSpacing(8)

        self.hint_label = QLabel("")
        self.hint_label.setStyleSheet(f"font-size: 12px; color: {COLOR_MUTED};")
        column.addWidget(self.hint_label)

        divider = QFrame()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {COLOR_DIVIDER}; border: none;")
        column.addWidget(divider)

        row = QHBoxLayout()
        row.setSpacing(10)

        self.retry_btn = QPushButton(TEXT_RETRY)
        self.retry_btn.setMinimumHeight(44)
        self.retry_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_btn.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: 8px; font-size: 14px; padding: 10px 16px;"
            f" background-color: {COLOR_SECONDARY_BG}; color: {COLOR_TEXT}; }}"
            "QPushButton:focus { outline: none; }"
        )
        self.retry_btn.clicked.connect(self.reload_document)
        self.retry_btn.setVisible(False)

        self.reject_btn = QPushButton(TEXT_REJECT)
        self.reject_btn.setMinimumHeight(44)
        self.reject_btn.setMinimumWidth(150)
        self.reject_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.reject_btn.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: 8px; font-size: 14px; padding: 10px 16px;"
            f" background-color: {COLOR_SECONDARY_BG}; color: {COLOR_TEXT}; }}"
            "QPushButton:focus { outline: none; }"
        )
        self.reject_btn.clicked.connect(self.reject)

        self.confirm_btn = QPushButton("")
        self.confirm_btn.setMinimumHeight(44)
        self.confirm_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.confirm_btn.clicked.connect(self._on_confirm_clicked)

        row.addWidget(self.reject_btn)
        row.addWidget(self.retry_btn)
        row.addWidget(self.confirm_btn, 1)
        column.addLayout(row)
        self._reject_text = TEXT_REJECT
        return actions

    # ── 公共接口 ─────────────────────────────────────────────────
    def set_reject_text(self, text: str) -> None:
        self._reject_text = text
        self.reject_btn.setText(text)

    def set_document(self, payload: Mapping[str, Any]) -> None:
        """装载一份协议正文；换版或重新打开都会重置阅读计时与"到过底部"。"""
        self._document_payload = payload
        self.version = str(payload.get("version", "") or "")
        self.setWindowTitle(str(payload.get("title", "") or "用户协议"))
        self.version_label.setText(f"版本：{self.version}" if self.version else "")
        self.view.setDocument(render_agreement_document(payload, self.font().family()))
        self._set_error("")
        self.retry_btn.setVisible(False)
        self.gate.begin_loading()
        self.gate.mark_loaded()
        # 异步正文可能在窗口已经显示且仍处于前台时返回；加载重置门禁后要从此刻继续累计。
        if self.isVisible() and self.isActiveWindow() and not self.isMinimized():
            self.gate.resume(self._clock())
        self._sync_scroll_state()
        self._refresh_actions()

    def reload_document(self) -> bool:
        """重新拉取当前正文（加载失败后的重试，也用于协议换版重读）。"""
        if self._load_document is None or self._load_in_flight:
            return False
        self.gate.begin_loading()
        self._set_error("")
        self._refresh_actions()
        self.retry_btn.setVisible(False)
        self._load_request_id += 1
        self._load_in_flight = True
        self._thread_pool.start(_LoadTask(self._load_request_id, self._load_document, self._load_signals))
        return True

    def begin_submit(self) -> None:
        self.gate.begin_submit()
        self.last_error = ""
        self._set_error("")
        self._refresh_actions()

    def finish_submit(self, success: bool, message: str = "") -> None:
        """提交结果：成功关闭窗口；失败恢复可操作状态并保留本窗口的阅读状态。"""
        if success:
            self._timer.stop()
            self._allow_close = True
            self.accept()
            return
        self.gate.end_submit()
        self._allow_close = False
        self.last_error = message
        self._set_error(message or "提交失败，请重试")
        self._refresh_actions()

    # ── 事件与刷新 ───────────────────────────────────────────────
    def showEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().showEvent(event)
        self.gate.resume(self._clock())
        self._timer.start()

    def changeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        super().changeEvent(event)
        if event.type() == event.Type.WindowStateChange and self.isMinimized():
            self.gate.pause()
        elif event.type() == event.Type.ActivationChange:
            if self.isActiveWindow():
                self.gate.resume(self._clock())
            else:
                self.gate.pause()

    def _on_tick(self) -> None:
        self.gate.tick(self._clock())
        self._refresh_actions()

    # ── 重排时保持阅读位置（scroll anchoring）────────────────────
    #
    # 与 CSS scroll anchoring（Chrome 56+ 默认开启）同一思路：滚动位置是像素值，宽度变化
    # 引起重排后，视口上方行数变化会把正在读的段落顶走。这里把"顶部可见段落 + 段内偏移"
    # 当作锚点，重排后按锚点重新算滚动量。停在顶部/底部是用户的明确意图，保持不动。
    #
    # 锚点必须在重排**之前**取：Qt 的 resize 先到子控件、再到对话框，等对话框 resizeEvent
    # 时 QTextEdit 已按新宽度排完，读到的"顶部段落"已是漂移后的结果。所以在 view 上装
    # 事件过滤器，在它处理 Resize 之前抓锚点。

    def eventFilter(self, watched, event) -> bool:  # noqa: N802 - Qt 命名
        if watched is self.view and event.type() == event.Type.Resize:
            anchor = self._capture_scroll_anchor()
            if anchor is not None:
                self._pending_anchor = anchor
                self._anchor_restore_timer.start()
        return super().eventFilter(watched, event)

    def _capture_scroll_anchor(self) -> Optional[tuple]:
        view = self.view
        bar = view.verticalScrollBar()
        if not view.isVisible() or bar.maximum() <= 0:
            return None
        value = bar.value()
        if value <= 0:
            return ("top",)
        if value >= bar.maximum():
            return ("bottom",)
        block = view.cursorForPosition(QPoint(0, 1)).block()
        if not block.isValid():
            return None
        rect = view.document().documentLayout().blockBoundingRect(block)
        height = rect.height()
        offset = 0.0 if height <= 0 else min(max((value - rect.top()) / height, 0.0), 1.0)
        return ("block", block.blockNumber(), offset)

    def _restore_scroll_anchor(self) -> None:
        anchor = self._pending_anchor
        self._pending_anchor = None
        if anchor is None:
            return
        bar = self.view.verticalScrollBar()
        if anchor[0] == "top":
            bar.setValue(0)
        elif anchor[0] == "bottom":
            bar.setValue(bar.maximum())
        else:
            _, block_number, offset = anchor
            block = self.view.document().findBlockByNumber(block_number)
            if block.isValid():
                rect = self.view.document().documentLayout().blockBoundingRect(block)
                target = rect.top() + offset * rect.height()
                bar.setValue(max(0, min(int(round(target)), bar.maximum())))

    def _on_scroll(self, *_args) -> None:
        self._sync_scroll_state()
        self._refresh_actions()

    def _sync_scroll_state(self) -> None:
        bar = self.view.verticalScrollBar()
        # 只强制排版，不改变文档宽度。此前用 adjustSize()：它会把文档宽度设成"不换行的理想宽度"，
        # 于是窗口缩放时不再重排（右侧留白/窄窗裁切），且滚动中反复改文档尺寸会让滚动范围与真实
        # 内容高度不一致（滚到底后仍差一截、继续下滑先超出再弹回）。
        self.view.document().documentLayout().documentSize()
        self.gate.observe_scroll(bar.value(), bar.maximum())

    def _on_confirm_clicked(self) -> None:
        if not self.gate.can_confirm:
            return
        self.begin_submit()
        self.submit_requested.emit(self.version)

    def _refresh_actions(self) -> None:
        status = self.gate.status
        self.confirm_btn.setText(self.gate.confirm_text)
        self.hint_label.setText(self.gate.hint_text)
        self.hint_label.setVisible(bool(self.gate.hint_text))
        self.retry_btn.setVisible(status == STATUS_LOAD_FAILED)
        self.reject_btn.setEnabled(status != "submitting")
        self.confirm_btn.setEnabled(self.gate.can_confirm)
        enabled_color = COLOR_PRIMARY if self.gate.can_confirm else COLOR_DISABLED
        self.confirm_btn.setStyleSheet(
            f"QPushButton {{ border: none; border-radius: 8px; font-size: 14px; padding: 10px 16px;"
            f" background-color: {enabled_color}; color: {COLOR_TEXT}; }}"
            "QPushButton:focus { outline: none; }"
        )

    def _set_error(self, message: str) -> None:
        self.error_label.setText(message)
        self.error_label.setVisible(bool(message))

    def _on_load_finished(self, request_id: int, result: object) -> None:
        if request_id != self._load_request_id:
            return
        self._load_in_flight = False
        if isinstance(result, Exception):
            self._fail_load(str(result))
            return
        if isinstance(result, Mapping):
            self.set_document(result)
            return
        # 与只读窗口同一个加载契约：loader 返回 (ok, detail, payload)。
        ok, detail, payload = result if isinstance(result, tuple) and len(result) == 3 else (False, "", None)
        if not ok or not isinstance(payload, Mapping):
            self._fail_load(str(detail) if detail else "")
            return
        self.set_document(payload)

    def _fail_load(self, detail: str) -> None:
        """加载失败：显示契约文案并给出重试入口，细节只留在 last_error 里。"""
        self.gate.mark_load_failed()
        self.last_error = detail
        self._set_error(self.gate.load_failed_text)
        self._refresh_actions()

    def reject(self) -> None:  # noqa: N802 - Qt 命名
        # 提交期间禁止 Esc/代码调用 reject；否则后台结果可能串到后续注册窗口。
        if self.gate.status == STATUS_SUBMITTING and not self._allow_close:
            return
        super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt 命名
        if self.gate.status == STATUS_SUBMITTING and not self._allow_close:
            event.ignore()
            return
        self._timer.stop()
        super().closeEvent(event)


__all__ = ["AgreementSignDialog", "COLOR_DISABLED", "TEXT_REJECT", "TEXT_REJECT_READONLY"]
