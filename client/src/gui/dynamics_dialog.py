from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

TIANYI_ICON_PATH = "res/gui/tianyi_icon.png"
USER_ICON_PATH = "res/gui/user_icon.png"
ADD_DYNAMIC_ICON_PATH = "res/gui/add_dynamic.png"


def _source_label(source_type: str) -> str:
    labels = {
        "citywalk": "城市漫步",
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
        self.setStyleSheet(
            """
            QLabel {
                background: #EEF3F7;
                color: #667481;
                border-radius: 8px;
                font-size: 11px;
                font-weight: 700;
            }
            """
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
        header.setStyleSheet("font-weight: 700; color: #243447;")
        meta = QLabel(f"{_source_label(str(dynamic.get('source_type', '')))} · {dynamic.get('created_at', '-')}")
        meta.setStyleSheet("font-size: 12px; color: #667481;")
        preview = str(dynamic.get("content", "")).strip().replace("\n", " ")
        if len(preview) > 72:
            preview = preview[:72] + "..."
        preview_label = QLabel(preview or "-")
        preview_label.setWordWrap(True)
        preview_label.setStyleSheet("color: #334155;")
        text_box.addWidget(header)
        text_box.addWidget(meta)
        text_box.addWidget(preview_label)
        layout.addLayout(text_box, 1)


class DynamicCommentWidget(QWidget):
    def __init__(self, comment: dict, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(AvatarLabel(str(comment.get("author_type", "")), 30))

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(4)
        header = QLabel(f"{comment.get('author_name', '-')} · {comment.get('created_at', '-')}")
        header.setStyleSheet("font-size: 12px; color: #667481;")
        content = QLabel(str(comment.get("content", "") or "-"))
        content.setWordWrap(True)
        content.setStyleSheet("color: #243447;")
        text_box.addWidget(header)
        text_box.addWidget(content)
        if comment.get("reply_error") or comment.get("memory_error"):
            error_lines = []
            if comment.get("reply_error"):
                error_lines.append(f"reply_error: {comment.get('reply_error')}")
            if comment.get("memory_error"):
                error_lines.append(f"memory_error: {comment.get('memory_error')}")
            error_label = QLabel("\n".join(error_lines))
            error_label.setWordWrap(True)
            error_label.setStyleSheet("font-size: 12px; color: #A35C00;")
            text_box.addWidget(error_label)
        layout.addLayout(text_box, 1)


class DynamicEditorDialog(QDialog):
    def __init__(self, publish_callback, parent=None):
        super().__init__(parent)
        self.publish_callback = publish_callback
        self.setWindowTitle("发一条动态")
        self.resize(560, 420)
        self.setModal(True)
        self._build_ui()

    def _build_ui(self):
        self.setStyleSheet(
            """
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
                font-size: 15px;
            }
            QPushButton {
                background: transparent;
                color: #1296DB;
                border: none;
                padding: 8px 10px;
                font-weight: 700;
            }
            QPushButton:hover {
                background: #E6F4FE;
                border-radius: 6px;
            }
            QPushButton:disabled {
                color: #8AA7B8;
            }
            """
        )
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
        content = self.input.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "提示", "先写一点内容再发布。")
            return
        self.publish_button.setEnabled(False)
        self.exit_button.setEnabled(False)
        try:
            ok, message = self.publish_callback(content)
        finally:
            self.publish_button.setEnabled(True)
            self.exit_button.setEnabled(True)
        if not ok:
            QMessageBox.warning(self, "发布失败", message or "未知错误")
            return
        self.accept()

    def reject(self):
        box = QMessageBox(self)
        box.setWindowTitle("退出编辑")
        box.setText("退出后这条动态不会保存。")
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
        self.add_dynamic_button: QPushButton | None = None

        self.setWindowTitle("动态")
        self.resize(920, 700)
        self.setModal(False)

        self._build_ui()
        if self.load_dynamics():
            self.mark_read()

    def _build_ui(self):
        self.setStyleSheet(
            """
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
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        header_row = QHBoxLayout()
        title = QLabel("动态")
        title.setObjectName("titleLabel")
        subtitle = QLabel("发布自己的动态，查看天依和系统的动态，并对选中的动态发表评论。")
        subtitle.setStyleSheet("color: #667481;")
        subtitle.setWordWrap(True)
        title_box = QVBoxLayout()
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box, 1)

        self.refresh_button = QPushButton("刷新")
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
        left_label.setStyleSheet("font-weight: 600; color: #243447;")
        self.dynamic_list = QListWidget()
        self.dynamic_list.currentItemChanged.connect(self.on_dynamic_selected)
        self.load_more_button = QPushButton("加载更多动态")
        self.load_more_button.clicked.connect(self.load_more_dynamics)
        left_panel.addWidget(left_label)
        left_panel.addWidget(self.dynamic_list, 1)
        left_panel.addWidget(self.load_more_button)

        right_panel = QVBoxLayout()
        right_label = QLabel("详情与评论")
        right_label.setStyleSheet("font-weight: 600; color: #243447;")
        self.detail_text = QTextEdit()
        self.detail_text.setReadOnly(True)
        self.detail_text.setFixedHeight(180)
        self.comments_text = QListWidget()
        self.comment_input = QTextEdit()
        self.comment_input.setPlaceholderText("给当前动态写一条评论...")
        self.comment_input.setFixedHeight(84)
        comment_action_row = QHBoxLayout()
        self.comment_status = QLabel("请选择一条动态")
        self.comment_status.setStyleSheet("color: #667481;")
        comment_action_row.addWidget(self.comment_status, 1)
        self.comment_button = QPushButton("发送评论")
        self.comment_button.setEnabled(False)
        self.comment_button.clicked.connect(self.publish_comment)
        comment_action_row.addWidget(self.comment_button)
        right_panel.addWidget(right_label)
        right_panel.addWidget(self.detail_text)
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
        self._build_add_dynamic_button()

    def _build_add_dynamic_button(self):
        self.add_dynamic_button = QPushButton(self)
        self.add_dynamic_button.setObjectName("addDynamicButton")
        self.add_dynamic_button.setFixedSize(58, 58)
        self.add_dynamic_button.setIcon(QIcon(ADD_DYNAMIC_ICON_PATH))
        self.add_dynamic_button.setIconSize(QSize(58, 58))
        self.add_dynamic_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.add_dynamic_button.setStyleSheet(
            """
            QPushButton#addDynamicButton {
                background: transparent;
                border: none;
                padding: 0;
            }
            QPushButton#addDynamicButton:hover {
                background: transparent;
            }
            """
        )
        self.add_dynamic_button.clicked.connect(self.open_dynamic_editor)
        self.add_dynamic_button.raise_()
        self._position_add_dynamic_button()

    def _position_add_dynamic_button(self):
        if self.add_dynamic_button is None:
            return
        margin = 22
        self.add_dynamic_button.move(
            max(margin, self.width() - margin - self.add_dynamic_button.width()),
            max(margin, self.height() - margin - self.add_dynamic_button.height()),
        )

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._position_add_dynamic_button()

    def load_dynamics(self):
        payload = self.network_client.get_dynamics(limit=40)
        if not payload.get("ok", False):
            self.feed_status.setText(f"动态加载失败：{payload.get('message', '未知错误')}。点击“刷新”重试。")
            self.feed_status.show()
            self.load_more_button.setEnabled(False)
            return False

        self.feed_status.hide()
        items = payload.get("items", [])
        self.dynamic_list.clear()
        self.current_dynamic = None
        self.detail_text.clear()
        self.comments_text.clear()
        self.comment_status.setText("请选择一条动态")
        self.comment_button.setEnabled(False)
        self.next_cursor = payload.get("next_cursor")
        self.has_more = bool(payload.get("has_more"))
        self.load_more_button.setEnabled(self.has_more)

        for dynamic in items:
            self._add_dynamic_item(dynamic)

        if self.dynamic_list.count() > 0:
            self.dynamic_list.setCurrentRow(0)
        return True

    def load_more_dynamics(self):
        if not self.has_more or not self.next_cursor:
            return

        payload = self.network_client.get_dynamics(limit=40, cursor=self.next_cursor)
        if not payload.get("ok", False):
            self.feed_status.setText(f"动态加载失败：{payload.get('message', '未知错误')}。点击“刷新”重试。")
            self.feed_status.show()
            return

        self.feed_status.hide()
        items = payload.get("items", [])
        self.next_cursor = payload.get("next_cursor")
        self.has_more = bool(payload.get("has_more"))
        self.load_more_button.setEnabled(self.has_more)

        for dynamic in items:
            self._add_dynamic_item(dynamic)

    def _add_dynamic_item(self, dynamic: dict):
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, dynamic)
        item.setSizeHint(QSize(0, 92))
        self.dynamic_list.addItem(item)
        self.dynamic_list.setItemWidget(item, DynamicListItemWidget(dynamic))

    def mark_read(self):
        result = self.network_client.mark_dynamics_read()
        if result.get("ok") and self.on_read_callback:
            self.on_read_callback()

    def on_dynamic_selected(self, current: QListWidgetItem | None, _previous: QListWidgetItem | None):
        if current is None:
            self.current_dynamic = None
            self.detail_text.clear()
            self.comments_text.clear()
            self.comment_status.setText("请选择一条动态")
            self.comment_button.setEnabled(False)
            return

        dynamic = current.data(Qt.ItemDataRole.UserRole) or {}
        self.current_dynamic = dynamic
        self.render_dynamic_detail(dynamic)
        self.load_comments(dynamic)

    def render_dynamic_detail(self, dynamic: dict):
        detail_lines = [
            f"id: {dynamic.get('id', '-')}",
            f"author: {dynamic.get('author_name', '-')} ({dynamic.get('author_type', '-')})",
            f"owner_user_id: {dynamic.get('owner_user_id') or '-'}",
            f"source_type: {dynamic.get('source_type', '-')}",
            f"visibility: {dynamic.get('visibility', '-')}",
            f"created_at: {dynamic.get('created_at', '-')}",
            f"reply_status: {dynamic.get('reply_status', '-')}",
            f"memory_status: {dynamic.get('memory_status', '-')}",
            "",
            str(dynamic.get("content", "") or "-"),
        ]
        if dynamic.get("reply_error"):
            detail_lines.extend(["", f"reply_error: {dynamic.get('reply_error')}"])
        if dynamic.get("memory_error"):
            detail_lines.extend(["", f"memory_error: {dynamic.get('memory_error')}"])
        self.detail_text.setPlainText("\n".join(detail_lines))
        allow_comment = bool(dynamic.get("allow_comment", False))
        self.comment_button.setEnabled(allow_comment)
        self.comment_status.setText("可评论" if allow_comment else "当前动态不支持评论")

    def load_comments(self, dynamic: dict):
        dynamic_id = dynamic.get("id")
        if not dynamic_id:
            self.comments_text.clear()
            return
        payload = self.network_client.get_dynamic_comments(dynamic_id, limit=200)
        if not payload.get("ok", False):
            self.comments_text.clear()
            item = QListWidgetItem(f"评论加载失败：{payload.get('message', '未知错误')}\n再次点击这条动态，或点击“刷新”后重试。")
            self.comments_text.addItem(item)
            return
        rows = payload.get("items", [])
        self.comments_text.clear()
        if not rows:
            self.comments_text.addItem(QListWidgetItem("还没有评论。"))
            return
        for comment in rows:
            self._add_comment_item(comment)

    def _add_comment_item(self, comment: dict):
        item = QListWidgetItem()
        item.setSizeHint(QSize(0, 74))
        self.comments_text.addItem(item)
        self.comments_text.setItemWidget(item, DynamicCommentWidget(comment))

    def open_dynamic_editor(self):
        editor = DynamicEditorDialog(self.publish_dynamic, self)
        editor.exec()

    def publish_dynamic(self, content: str) -> tuple[bool, str]:
        result = self.network_client.create_dynamic(content)
        if not result.get("ok"):
            return False, result.get("message", "未知错误")
        self.load_dynamics()
        return True, ""

    def publish_comment(self):
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
        result = self.network_client.create_dynamic_comment(self.current_dynamic.get("id"), content)
        if not result.get("ok"):
            QMessageBox.warning(self, "评论失败", result.get("message", "未知错误"))
            return
        self.comment_input.clear()
        self.load_comments(self.current_dynamic)
