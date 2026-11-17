from __future__ import annotations

from datetime import datetime

from shiboken6 import isValid

from PySide6.QtCore import QSize, Qt, Signal, QTimer
from PySide6.QtGui import QColor, QFontMetrics, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .window_operation import WindowOperation

TIANYI_ICON_PATH = "res/gui/tianyi_icon.png"
USER_ICON_PATH = "res/gui/user_icon.png"
DYNAMIC_PAGE_SIZE = 10
SCROLLBAR_SINGLE_STEP = 12


def _source_label(source_type: str) -> str:
    labels = {
        "citywalk": "城市漫步",
        "diary": "天依日记",
        "song_learned": "学会新歌",
        "system_notice": "系统通知",
        "user_post": "生活动态",
    }
    return labels.get(source_type, source_type or "动态")


def _author_label(author_type: str) -> str:
    if author_type == "agent":
        return "天依"
    if author_type == "system":
        return "系统"
    return "你"


def _avatar_path(author_type: str) -> str | None:
    if author_type == "agent":
        return TIANYI_ICON_PATH
    if author_type == "user":
        return USER_ICON_PATH
    return None


def _format_dynamic_time(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        return "-"
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return parsed.strftime("%Y-%m-%d\n%H:%M")
    except ValueError:
        parts = raw.replace("T", " ").split()
        if len(parts) >= 2:
            return f"{parts[0]}\n{parts[1][:5]}"
        return raw


class AvatarLabel(QLabel):
    def __init__(self, author_type: str, size: int = 34, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        path = _avatar_path(author_type)
        if path:
            pixmap = QPixmap(path)
            if not pixmap.isNull():
                self.setPixmap(
                    pixmap.scaled(
                        size,
                        size,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
                self.setStyleSheet("border-radius: 17px;")
                return
        self.setText(_author_label(author_type))
        self.setStyleSheet("""
            QLabel {
                background: #EEF3F7;
                color: #667481;
                border-radius: 8px;
                font-size: 11px;
                font-weight: 700;
            }
            """)


class CommentInput(QTextEdit):
    send_requested = Signal()

    def keyPressEvent(self, event):
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        has_shift = bool(event.modifiers() & Qt.KeyboardModifier.ShiftModifier)
        if is_enter and not has_shift:
            self.send_requested.emit()
            return
        super().keyPressEvent(event)


class ElidedLabel(QLabel):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._full_text = "-"
        self.setWordWrap(False)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Fixed)

    def set_full_text(self, text: str):
        self._full_text = str(text or "-")
        self._update_elided_text()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_elided_text()

    def _update_elided_text(self):
        width = self.contentsRect().width()
        if width <= 0:
            self.setText(self._full_text)
            return
        self.setText(
            QFontMetrics(self.font()).elidedText(
                self._full_text,
                Qt.TextElideMode.ElideRight,
                width,
            )
        )


class DynamicListItemWidget(QWidget):
    def __init__(self, dynamic: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("dynamicListItem")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(AvatarLabel(str(dynamic.get("author_type", "")), 34))

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(4)
        header = QLabel(f"{dynamic.get('author_name', '-')}")
        header.setStyleSheet("font-weight: 900; font-size: 16px; color: #243447;")
        meta = QLabel(f"{_source_label(str(dynamic.get('source_type', '')))} · {dynamic.get('created_at', '-')}")
        meta.setStyleSheet("font-size: 12px; color: #667481;")
        preview = str(dynamic.get("content", "")).strip().replace("\n", " ") or "-"
        preview_label = ElidedLabel()
        preview_label.set_full_text(preview)
        preview_label.setStyleSheet("color: #334155; font-size: 14px;")
        text_box.addWidget(header)
        text_box.addWidget(meta)
        text_box.addWidget(preview_label)
        layout.addLayout(text_box, 1)


class DynamicPostWidget(QWidget):
    def __init__(self, dynamic: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("dynamicPostCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)
        layout.addWidget(
            AvatarLabel(str(dynamic.get("author_type", "")), 36),
            0,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        )

        author_name = QLabel(str(dynamic.get("author_name") or _author_label(str(dynamic.get("author_type", "")))))
        author_name.setStyleSheet("font-weight: 900; font-size: 16px; color: #243447;")
        author_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        author_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        created_at = QLabel(_format_dynamic_time(dynamic.get("created_at")))
        created_at.setStyleSheet("font-size: 12px; color: #667481;")
        created_at.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        created_at.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(author_name, 1)
        header.addWidget(created_at)
        layout.addLayout(header, 0, 1)

        content = QLabel(str(dynamic.get("content", "") or "-"))
        content.setWordWrap(True)
        content.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content.setStyleSheet("color: #243447; font-size: 14px;")
        layout.addWidget(content, 1, 1)
        layout.setColumnStretch(1, 1)


class DynamicCommentWidget(QWidget):
    def __init__(self, comment: dict, parent=None):
        super().__init__(parent)
        self.setObjectName("dynamicCommentCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        layout = QGridLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setHorizontalSpacing(10)
        layout.setVerticalSpacing(6)
        layout.addWidget(
            AvatarLabel(str(comment.get("author_type", "")), 30),
            0,
            0,
            Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignLeft,
        )

        author_name = QLabel(str(comment.get("author_name") or _author_label(str(comment.get("author_type", "")))))
        author_name.setStyleSheet("font-weight: 900; font-size: 16px; color: #243447;")
        author_name.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        author_name.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        created_at = QLabel(_format_dynamic_time(comment.get("created_at")))
        created_at.setStyleSheet("font-size: 12px; color: #667481;")
        created_at.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        created_at.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        header = QHBoxLayout()
        header.setContentsMargins(0, 0, 0, 0)
        header.setSpacing(10)
        header.addWidget(author_name, 1)
        header.addWidget(created_at)
        layout.addLayout(header, 0, 1)

        content = QLabel(str(comment.get("content", "") or "-"))
        content.setWordWrap(True)
        content.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop)
        content.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        content.setStyleSheet("color: #243447; font-size: 14px;")
        layout.addWidget(content, 1, 1)
        layout.setColumnStretch(1, 1)


class DynamicEditorDialog(QDialog):
    def __init__(self, publish_callback, parent=None):
        super().__init__(parent)
        self.publish_callback = publish_callback
        self.pending = False
        self.setWindowTitle("发一条动态")
        self.resize(560, 420)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: #F6F7F9;
            }
            QLabel#editorTitle {
                font-size: 18px;
                font-weight: 800;
                color: #243447;
            }
            QTextEdit {
                background: #FFFFFF;
                border: 1px solid #D5DEE7;
                border-radius: 6px;
                padding: 10px;
                font-size: 14px;
            }
            QPushButton {
                background: transparent;
                color: #1296DB;
                border: none;
                padding: 8px 10px;
                font-weight: 700;
                font-size: 16px;
            }
            QPushButton:hover {
                background: #E6F4FE;
                border-radius: 6px;
            }
            QPushButton:disabled {
                color: #8AA7B8;
            }
            QPushButton:focus {
                outline: none;
            }
            """)
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 14, 16, 16)
        root.setSpacing(14)

        header = QHBoxLayout()
        self.exit_button = QPushButton("退出编辑")
        self.exit_button.clicked.connect(self.reject)
        header.addWidget(self.exit_button)
        title = QLabel("发一条动态")
        title.setObjectName("editorTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        header.addWidget(title, 1)
        self.publish_button = QPushButton("发布")
        self.publish_button.clicked.connect(self._publish)
        header.addWidget(self.publish_button)
        root.addLayout(header)

        self.input = QTextEdit()
        self.input.setPlaceholderText("分享一点最近发生的事...")
        root.addWidget(self.input, 1)
        hint = QLabel("只有你、天依和管理员能够看到动态")
        hint.setStyleSheet("color: #667481; font-size: 13px;")
        root.addWidget(hint)

    def _publish(self):
        if self.pending:
            return
        content = self.input.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "提示", "先写一点内容再发布。")
            return
        if self.publish_callback(content, self):
            self.pending = True
            self.publish_button.setEnabled(False)
            self.input.setEnabled(False)

    def finish_publish(self, success, message):
        self.pending = False
        self.publish_button.setEnabled(True)
        self.input.setEnabled(True)
        if success:
            self.accept()
        else:
            QMessageBox.warning(self, "发布失败", message or "未知错误")

    def reject(self):
        box = QMessageBox(self)
        box.setWindowTitle("退出编辑")
        box.setText("退出后这条动态不会保存。")
        box.setStyleSheet("font-size: 14px;")
        keep_button = box.addButton("继续编辑", QMessageBox.ButtonRole.RejectRole)
        exit_button = box.addButton("退出", QMessageBox.ButtonRole.DestructiveRole)
        box.setDefaultButton(keep_button)
        box.exec()
        if box.clickedButton() == exit_button:
            super().reject()


class DynamicsDialog(QDialog):
    def __init__(self, network_client, on_read_callback=None, parent=None):
        super().__init__(parent)
        self.network_client = network_client
        self.on_read_callback = on_read_callback
        self.current_dynamic: dict | None = None
        self.next_cursor: str | None = None
        self.has_more = False
        self._loading_dynamics = False
        self._loading_more_dynamics = False
        self.dynamic_end_item: QListWidgetItem | None = None
        self.add_dynamic_button: QPushButton | None = None

        self.setWindowTitle("动态")
        self.resize(920, 700)
        self.setModal(False)

        self._build_ui()
        self._list_operation = WindowOperation(self)
        self._comments_operation = WindowOperation(self)
        self._write_operation = WindowOperation(self)
        self._list_operation.completed.connect(self._list_completed)
        self._list_operation.settled.connect(self._list_settled)
        self._comments_operation.completed.connect(self._comments_completed)
        self._comments_operation.settled.connect(self._comments_settled)
        self._write_operation.completed.connect(self._write_completed)
        self._write_operation.settled.connect(self._write_settled)
        self._feed_generation = 0
        self._selection_generation = 0
        self._visible_generation = 0
        self._list_ticket = None
        self._comments_ticket = None
        self._write_ticket = None
        self._list_latest = False
        self._comments_latest = None
        self._read_dirty = False
        self._hidden = False
        self._loaded = False
        self._editor = None
        self._comment_drafts = {}
        self.feed_status.setText("正在加载动态…")
        self.feed_status.show()
        QTimer.singleShot(0, self.load_dynamics)

    def _build_ui(self):
        self.setStyleSheet("""
            QDialog {
                background: #F6F7F9;
            }
            QLabel#titleLabel {
                font-size: 20px;
                font-weight: 700;
                color: #243447;
            }
            QListWidget, QTextEdit {
                background: #FFFFFF;
                border: 1px solid #D5DEE7;
                border-radius: 6px;
                padding: 4px;
            }
            QListWidget::item {
                border: none;
                padding: 0;
                margin: 3px;
            }
            QWidget#dynamicPostCard {
                background: #F0F8FF;
                border: 1px solid #B8DDF3;
                border-radius: 6px;
            }
            QWidget#dynamicCommentCard {
                background: #FFFFFF;
                border: 1px solid #D5DEE7;
                border-radius: 6px;
            }
            QPushButton#addDynamicButton,
            QPushButton#refreshButton,
            QPushButton#sendCommentButton {
                background: #66CCFF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
                font-size: 16px;
            }
            QPushButton#addDynamicButton:hover,
            QPushButton#refreshButton:hover,
            QPushButton#sendCommentButton:hover {
                background: #55BBEE;
            }
            QPushButton {
                background: #66CCFF;
                color: white;
                border: none;
                border-radius: 6px;
                padding: 8px 12px;
            }
            QPushButton:hover {
                background: #55BBEE;
            }
            QPushButton:disabled {
                background: #B8CAD6;
            }
            QPushButton:focus {
                outline: none;
            }
            """)

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("动态")
        title.setObjectName("titleLabel")
        title_box = QVBoxLayout()
        title_box.addWidget(title)
        header_row.addLayout(title_box, 1)

        self.add_dynamic_button = QPushButton("发布动态")
        self.add_dynamic_button.setObjectName("addDynamicButton")
        self.add_dynamic_button.setFixedSize(92, 38)
        self.add_dynamic_button.clicked.connect(self.open_dynamic_editor)
        header_row.addWidget(self.add_dynamic_button, 0, Qt.AlignmentFlag.AlignTop)

        self.refresh_button = QPushButton("刷新")
        self.refresh_button.setObjectName("refreshButton")
        self.refresh_button.setFixedSize(65, 38)
        self.refresh_button.clicked.connect(self.load_dynamics)
        header_row.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)
        root.addLayout(header_row)

        self.feed_status = QLabel("")
        self.feed_status.setStyleSheet("color: #A35C00;")
        self.feed_status.setWordWrap(True)
        self.feed_status.hide()
        root.addWidget(self.feed_status)

        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        left_panel = QVBoxLayout()
        left_label = QLabel("动态列表")
        left_label.setStyleSheet("font-weight: 600; font-size: 14px; color: #243447;")
        self.dynamic_list = QListWidget()
        self.dynamic_list.setObjectName("dynamicList")
        self.dynamic_list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.dynamic_list.verticalScrollBar().setSingleStep(SCROLLBAR_SINGLE_STEP)
        self.dynamic_list.currentItemChanged.connect(self.on_dynamic_selected)
        self.dynamic_list.verticalScrollBar().valueChanged.connect(self._on_dynamic_list_scroll)
        left_panel.addWidget(left_label)
        left_panel.addWidget(self.dynamic_list, 1)

        right_panel = QVBoxLayout()
        right_label = QLabel("详情与评论")
        right_label.setStyleSheet("font-weight: 600; font-size: 14px; color: #243447;")
        self.comments_text = QListWidget()
        self.comments_text.setObjectName("dynamicFeedList")
        self.comments_text.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.comments_text.verticalScrollBar().setSingleStep(SCROLLBAR_SINGLE_STEP)
        self.comments_text.setSpacing(6)
        self.comments_text.setUniformItemSizes(False)
        self.comments_text.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.comment_input = CommentInput()
        self.comment_input.setPlaceholderText("给当前动态写一条评论...")
        self.comment_input.setFixedHeight(84)
        self.comment_input.send_requested.connect(self.publish_comment)
        comment_action_row = QHBoxLayout()
        self.comment_status = QLabel("请选择一条动态")
        self.comment_status.setStyleSheet("color: #667481;")
        comment_action_row.addWidget(self.comment_status, 1)
        self.comment_button = QPushButton("发送评论")
        self.comment_button.setObjectName("sendCommentButton")
        self.comment_button.setEnabled(False)
        self.comment_button.clicked.connect(self.publish_comment)
        comment_action_row.addWidget(self.comment_button)
        right_panel.addWidget(right_label)
        right_panel.addWidget(self.comments_text, 1)
        right_panel.addWidget(self.comment_input)
        right_panel.addLayout(comment_action_row)

        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        content_row.addWidget(left_widget, 5)
        content_row.addWidget(right_widget, 6)

        root.addLayout(content_row, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_detail_item_sizes()

    def showEvent(self, event):
        super().showEvent(event)
        self._update_detail_item_sizes()
        if self._hidden:
            self._hidden = False
            self._list_latest = True
            QTimer.singleShot(0, self.load_dynamics)

    def hideEvent(self, event):
        self._hidden = True
        self._visible_generation += 1
        self._feed_generation += 1
        self._selection_generation += 1
        self._list_latest = False
        self._comments_latest = None
        self._read_dirty = False
        self._list_operation.invalidate()
        self._comments_operation.invalidate()
        self._write_operation.invalidate()
        # 隐藏仍保留 timer 回收实际终态，不能让重开绕过写在途。
        super().hideEvent(event)

    def _on_dynamic_list_scroll(self, value: int):
        if self._loading_dynamics or self._loading_more_dynamics:
            return
        scrollbar = self.dynamic_list.verticalScrollBar()
        if value >= scrollbar.maximum():
            self.load_more_dynamics()

    def _update_dynamic_end_state(self):
        if self.dynamic_end_item is not None:
            row = self.dynamic_list.row(self.dynamic_end_item)
            if row >= 0:
                self.dynamic_list.takeItem(row)
            self.dynamic_end_item = None

        if self.has_more:
            return

        item = QListWidgetItem("已经到底了")
        item.setFlags(item.flags() & ~(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(QColor("#9AA6B2"))
        item.setSizeHint(QSize(0, 32))
        self.dynamic_list.addItem(item)
        self.dynamic_end_item = item

    def _update_detail_item_sizes(self):
        width = self.comments_text.viewport().width() - 8
        if width <= 20:
            return
        for index in range(self.comments_text.count()):
            item = self.comments_text.item(index)
            widget = self.comments_text.itemWidget(item)
            if widget is None:
                continue
            widget.setFixedWidth(width)
            widget.layout().activate()
            height = widget.heightForWidth(width)
            if height <= 0:
                height = widget.sizeHint().height()
            item.setSizeHint(QSize(width, height + 6))

    def _add_detail_message(self, message: str):
        item = QListWidgetItem(message)
        item.setFlags(item.flags() & ~(Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsEnabled))
        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
        item.setForeground(QColor("#9AA6B2"))
        item.setSizeHint(QSize(0, 40))
        self.comments_text.addItem(item)

    def _add_post_item(self, dynamic: dict):
        item = QListWidgetItem()
        self.comments_text.addItem(item)
        self.comments_text.setItemWidget(item, DynamicPostWidget(dynamic))
        self._update_detail_item_sizes()

    def _valid_result(self, request, visible_generation):
        return (
            not self._hidden
            and self.isVisible()
            and visible_generation == self._visible_generation
            and request.context == self.network_client.account_context()
        )

    def load_dynamics(self):
        if self._hidden:
            return
        if self._list_operation.busy:
            return
        self._feed_generation += 1
        self._selection_generation += 1
        self._comments_operation.invalidate()
        self._comments_latest = None
        self._start_list(None)

    def _start_list(self, cursor):
        request = self.network_client.prepare_dynamic_request("list", limit=DYNAMIC_PAGE_SIZE, cursor=cursor)
        self._list_ticket = (
            self._visible_generation,
            self._feed_generation,
            cursor,
            self.dynamic_list.verticalScrollBar().value(),
            self.current_dynamic.get("id") if self.current_dynamic else None,
        )
        self._loading_dynamics = cursor is None
        self._loading_more_dynamics = cursor is not None
        self.refresh_button.setEnabled(False)
        self.feed_status.setText("正在加载动态…")
        self.feed_status.show()
        self._list_operation.start(request)

    def load_more_dynamics(self):
        if self._hidden or self._list_operation.busy or not self.has_more or not self.next_cursor:
            return
        self._start_list(self.next_cursor)

    def _list_completed(self, request, result):
        visible, generation, cursor, scroll, selected = self._list_ticket
        if not self._valid_result(request, visible) or generation != self._feed_generation:
            return
        ok, message, payload = result
        if not ok:
            self.feed_status.setText(f"动态加载失败：{message}。点击“刷新”重试。")
            return
        self.feed_status.hide()
        # 请求等待期间用户仍可切换选择或滚动，成功回写只保留完成时状态。
        selected = self.current_dynamic.get("id") if self.current_dynamic else None
        scroll = self.dynamic_list.verticalScrollBar().value()
        items = payload.get("items", [])
        if cursor is None:
            self.dynamic_list.clear()
            self.dynamic_end_item = None
            self.current_dynamic = None
            self.comments_text.clear()
        existing = {
            self.dynamic_list.item(i).data(Qt.ItemDataRole.UserRole).get("id")
            for i in range(self.dynamic_list.count())
            if isinstance(self.dynamic_list.item(i).data(Qt.ItemDataRole.UserRole), dict)
        }
        for dynamic in items:
            if dynamic.get("id") not in existing:
                self._add_dynamic_item(dynamic)
                existing.add(dynamic.get("id"))
        self.next_cursor = payload.get("next_cursor")
        self.has_more = bool(payload.get("has_more"))
        self._update_dynamic_end_state()
        row = next(
            (
                i
                for i in range(self.dynamic_list.count())
                if isinstance(self.dynamic_list.item(i).data(Qt.ItemDataRole.UserRole), dict)
                and self.dynamic_list.item(i).data(Qt.ItemDataRole.UserRole).get("id") == selected
            ),
            0,
        )
        if items:
            self.dynamic_list.setCurrentRow(row)
        if cursor is not None:
            self.dynamic_list.verticalScrollBar().setValue(scroll)
        self._loaded = True
        if cursor is None:
            self._read_dirty = True
            QTimer.singleShot(0, self.mark_read)

    def _list_settled(self):
        self._loading_dynamics = False
        self._loading_more_dynamics = False
        self.refresh_button.setEnabled(True)
        if self._list_latest and not self._hidden:
            self._list_latest = False
            self.load_dynamics()

    def _add_dynamic_item(self, dynamic: dict):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, dynamic)
        item.setSizeHint(QSize(0, 82))
        self.dynamic_list.addItem(item)
        self.dynamic_list.setItemWidget(item, DynamicListItemWidget(dynamic))

    def mark_read(self):
        if self._hidden or not self._loaded:
            return
        if self._write_operation.busy:
            self._read_dirty = True
            return
        self._read_dirty = False
        self._start_write("read")

    def on_dynamic_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None):
        if self.current_dynamic:
            self._comment_drafts[self.current_dynamic.get("id")] = self.comment_input.toPlainText()
        self._selection_generation += 1
        if current is None:
            self.current_dynamic = None
            self.comments_text.clear()
            self.comment_status.setText("请选择一条动态")
            self.comment_button.setEnabled(False)
            return

        dynamic = current.data(Qt.ItemDataRole.UserRole) or {}
        self.current_dynamic = dynamic
        self.comment_input.setPlainText(self._comment_drafts.get(dynamic.get("id"), ""))
        self.render_dynamic_detail(dynamic)
        self.load_comments(dynamic)

    def render_dynamic_detail(self, dynamic: dict):
        self.comments_text.clear()
        self._add_post_item(dynamic)
        allow_comment = bool(dynamic.get("allow_comment", False))
        self.comment_button.setEnabled(allow_comment and not self._write_operation.busy)
        self.comment_status.setText("可评论" if allow_comment else "当前动态不支持评论")

    def _clear_comment_items(self):
        while self.comments_text.count() > 1:
            self.comments_text.takeItem(1)

    def load_comments(self, dynamic: dict):
        dynamic_id = dynamic.get("id")
        if not dynamic_id or self._hidden:
            return
        if self._comments_operation.busy:
            self._comments_latest = dynamic_id
            self._comments_operation.invalidate()
            return
        request = self.network_client.prepare_dynamic_request("comments", dynamic_id=dynamic_id, limit=200)
        self._comments_ticket = (
            self._visible_generation,
            self._feed_generation,
            self._selection_generation,
            dynamic_id,
        )
        self._clear_comment_items()
        self._add_detail_message("正在加载评论…")
        self._comments_operation.start(request)

    def _comments_completed(self, request, result):
        visible, feed, selection, dynamic_id = self._comments_ticket
        if (
            not self._valid_result(request, visible)
            or feed != self._feed_generation
            or selection != self._selection_generation
            or not self.current_dynamic
            or dynamic_id != self.current_dynamic.get("id")
        ):
            return
        ok, message, payload = result
        self._clear_comment_items()
        if not ok:
            self._add_detail_message(f"评论加载失败：{message}\n再次点击这条动态，或点击“刷新”后重试。")
            return
        rows = payload.get("items", [])
        for comment in rows:
            self._add_comment_item(comment)
        self._add_detail_message("没有更多评论了。" if rows else "还没有评论。")

    def _comments_settled(self):
        target, self._comments_latest = self._comments_latest, None
        if (
            target is not None
            and not self._hidden
            and self.current_dynamic
            and self.current_dynamic.get("id") == target
        ):
            self.load_comments(self.current_dynamic)

    def _add_comment_item(self, comment: dict):
        item = QListWidgetItem()
        self.comments_text.addItem(item)
        self.comments_text.setItemWidget(item, DynamicCommentWidget(comment))
        self._update_detail_item_sizes()

    def open_dynamic_editor(self):
        editor = DynamicEditorDialog(self.publish_dynamic, self)
        editor.exec()

    def publish_dynamic(self, content: str, editor=None) -> bool:
        if self._hidden or self._write_operation.busy:
            return False
        self._editor = editor
        self._start_write("post", content=content)
        return True

    def _start_write(self, action, **values):
        request = self.network_client.prepare_dynamic_request(action, **values)
        self._write_ticket = (
            self._visible_generation,
            self._selection_generation,
            values.get("dynamic_id"),
            values.get("content"),
        )
        self.comment_button.setEnabled(False)
        self.add_dynamic_button.setEnabled(False)
        self._write_operation.start(request)

    def _write_completed(self, request, result):
        visible, selection, target, content = self._write_ticket
        if not self._valid_result(request, visible):
            return
        ok, message, payload = result
        if request.action == "read":
            if ok and self.on_read_callback:
                self.on_read_callback()
            return
        if request.action == "post":
            if self._editor is not None and isValid(self._editor) and self._editor.isVisible():
                self._editor.finish_publish(ok, message)
            if ok:
                self._feed_generation += 1
                self._list_operation.invalidate()
                self._list_latest = True
            return
        if not ok:
            QMessageBox.warning(self, "评论失败", message or "未知错误")
            return
        if self.current_dynamic and self.current_dynamic.get("id") == target:
            self._selection_generation += 1
            self._comments_operation.invalidate()
            if selection + 1 == self._selection_generation and self.comment_input.toPlainText().strip() == content:
                self.comment_input.clear()
                self._comment_drafts.pop(target, None)
            self._comments_latest = target
        elif self._comment_drafts.get(target, "").strip() == content:
            self._comment_drafts.pop(target, None)

    def _write_settled(self):
        if self._editor is not None and isValid(self._editor):
            self._editor.pending = False
            self._editor.publish_button.setEnabled(True)
            self._editor.input.setEnabled(True)
        self.add_dynamic_button.setEnabled(True)
        self.comment_button.setEnabled(bool(self.current_dynamic and self.current_dynamic.get("allow_comment")))
        if self._hidden:
            return
        if self._list_latest and not self._list_operation.busy:
            self._list_latest = False
            self.load_dynamics()
        if self._comments_latest is not None and not self._comments_operation.busy:
            self._comments_settled()
        if self._read_dirty:
            QTimer.singleShot(0, self.mark_read)

    def publish_comment(self):
        if self._hidden or self._write_operation.busy:
            return
        if not self.current_dynamic:
            QMessageBox.information(self, "提示", "请先选择一条动态。")
            return
        if not self.current_dynamic.get("allow_comment", False):
            QMessageBox.information(self, "提示", "当前动态不支持评论。")
            return
        content = self.comment_input.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "提示", "先写一点评论再发送。")
            return
        self._start_write("comment", dynamic_id=self.current_dynamic.get("id"), content=content)
