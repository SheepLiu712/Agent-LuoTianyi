from __future__ import annotations

from PySide6.QtCore import Qt
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


class DynamicsDialog(QDialog):
    def __init__(self, network_client, on_read_callback=None, parent=None):
        super().__init__(parent)
        self.network_client = network_client
        self.on_read_callback = on_read_callback
        self.current_dynamic: dict | None = None
        self.next_cursor: str | None = None
        self.has_more = False

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

        composer_panel = QWidget()
        composer_layout = QVBoxLayout(composer_panel)
        composer_layout.setContentsMargins(0, 0, 0, 0)
        composer_layout.setSpacing(8)
        composer_label = QLabel("发布新动态")
        composer_label.setStyleSheet("font-weight: 600; color: #243447;")
        self.post_input = QTextEdit()
        self.post_input.setPlaceholderText("分享一点最近发生的事...")
        self.post_input.setFixedHeight(90)
        publish_row = QHBoxLayout()
        hint = QLabel("只有你、天依和管理员能看到你发布的动态。")
        hint.setStyleSheet("color: #667481;")
        hint.setWordWrap(True)
        publish_row.addWidget(hint, 1)
        self.publish_button = QPushButton("发布")
        self.publish_button.clicked.connect(self.publish_dynamic)
        publish_row.addWidget(self.publish_button)
        composer_layout.addWidget(composer_label)
        composer_layout.addWidget(self.post_input)
        composer_layout.addLayout(publish_row)
        root.addWidget(composer_panel)

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
        self.comments_text = QTextEdit()
        self.comments_text.setReadOnly(True)
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
            preview = str(dynamic.get("content", "")).strip().replace("\n", " ")
            if len(preview) > 56:
                preview = preview[:56] + "..."
            title = f"[{dynamic.get('author_name', '-')}] {dynamic.get('created_at', '-')}"
            source = dynamic.get("source_type", "-")
            item = QListWidgetItem(f"{title}\n{source} · {preview}")
            item.setData(Qt.ItemDataRole.UserRole, dynamic)
            self.dynamic_list.addItem(item)

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
            preview = str(dynamic.get("content", "")).strip().replace("\n", " ")
            if len(preview) > 56:
                preview = preview[:56] + "..."
            title = f"[{dynamic.get('author_name', '-')}] {dynamic.get('created_at', '-')}"
            source = dynamic.get("source_type", "-")
            item = QListWidgetItem(f"{title}\n{source} · {preview}")
            item.setData(Qt.ItemDataRole.UserRole, dynamic)
            self.dynamic_list.addItem(item)

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
            self.comments_text.setPlainText(
                f"评论加载失败：{payload.get('message', '未知错误')}\n\n再次点击这条动态，或点击“刷新”后重试。"
            )
            return
        rows = payload.get("items", [])
        if not rows:
            self.comments_text.setPlainText("还没有评论。")
            return
        lines: list[str] = []
        for comment in rows:
            lines.append(f"[{comment.get('author_name', '-')}] {comment.get('created_at', '-')}")
            lines.append(str(comment.get("content", "") or "-"))
            lines.append(
                f"reply={comment.get('reply_status', '-')} · memory={comment.get('memory_status', '-')}"
            )
            if comment.get("reply_error"):
                lines.append(f"reply_error: {comment.get('reply_error')}")
            if comment.get("memory_error"):
                lines.append(f"memory_error: {comment.get('memory_error')}")
            lines.append("")
        self.comments_text.setPlainText("\n".join(lines).strip())

    def publish_dynamic(self):
        content = self.post_input.toPlainText().strip()
        if not content:
            QMessageBox.information(self, "提示", "先写一点内容再发布。")
            return
        result = self.network_client.create_dynamic(content)
        if not result.get("ok"):
            QMessageBox.warning(self, "发布失败", result.get("message", "未知错误"))
            return
        self.post_input.clear()
        self.load_dynamics()

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
