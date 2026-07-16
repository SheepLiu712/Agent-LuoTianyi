"""
动态对话框：查看/发布动态和评论。

v0.3.x-diary 版本：
  - 左侧动态列表（单行预览 + 省略号）
  - 右侧详情（头像 + 名称 + 时间 + 正文）+ 评论列表 + 评论输入
  - 发布动态按钮在顶部
  - 修复了 FAB 与评论按钮重叠的问题
"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPixmap
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


def _source_label(source_type: str) -> str:
    labels = {
        "citywalk": "城市漫步",
        "song_learned": "学会新歌",
        "system_notice": "系统通知",
        "user_post": "生活动态",
        "diary": "日记",
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
                # 圆形头像裁切
                self.setStyleSheet(
                    f"border-radius: {size // 2}px; border: 1px solid #E2E8F0;"
                )
                return
        # 无头像时显示文字首字母
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
    """左侧动态列表的条目组件，头像 + 名称 + 来源 + 时间 + 单行预览。"""

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

        # 第一行：名称（加粗）
        header = QLabel(f"{dynamic.get('author_name', '-')}")
        header.setStyleSheet("font-weight: 700; color: #243447;")
        text_box.addWidget(header)

        # 第二行：来源 · 时间（小字灰色）
        meta = QLabel(
            f"{_source_label(str(dynamic.get('source_type', '')))} · {dynamic.get('created_at', '-')}"
        )
        meta.setStyleSheet("font-size: 12px; color: #667481;")
        text_box.addWidget(meta)

        # 第三行：单行预览（截断 + 省略号）
        preview = str(dynamic.get("content", "")).strip().replace("\n", " ")
        # 取前 50 个字符 + ...，保证一行能显示完整
        preview = (preview[:48] + "…") if len(preview) > 48 else preview
        preview_label = QLabel(preview or "-")
        preview_label.setFixedHeight(18)  # 固定单行高度
        preview_label.setStyleSheet("color: #334155; font-size: 13px;")
        text_box.addWidget(preview_label)

        layout.addLayout(text_box, 1)


class DynamicCommentWidget(QWidget):
    """评论条目组件：头像 + 名称·时间 + 正文（+错误信息）。"""

    def __init__(self, comment: dict, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(10)
        layout.addWidget(AvatarLabel(str(comment.get("author_type", "")), 30))

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 0, 0, 0)
        text_box.setSpacing(4)

        # 头部：名称 · 时间
        header = QLabel(
            f"{comment.get('author_name', '-')} · {comment.get('created_at', '-')}"
        )
        header.setStyleSheet("font-size: 12px; color: #667481;")
        text_box.addWidget(header)

        # 正文
        content = QLabel(str(comment.get("content", "") or "-"))
        content.setWordWrap(True)
        content.setStyleSheet("color: #243447;")
        text_box.addWidget(content)

        # 错误信息（如有）
        errors = []
        if comment.get("reply_error"):
            errors.append(f"回复失败: {comment.get('reply_error')}")
        if comment.get("memory_error"):
            errors.append(f"记忆失败: {comment.get('memory_error')}")
        if errors:
            error_label = QLabel("\n".join(errors))
            error_label.setWordWrap(True)
            error_label.setStyleSheet("font-size: 12px; color: #A35C00;")
            text_box.addWidget(error_label)

        layout.addLayout(text_box, 1)


class DynamicEditorDialog(QDialog):
    """发布新动态的编辑弹窗。"""

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
    """
    动态对话框。

    ┌──────────────────────────────────────────┐
    │ 动态    ××× ×××  [刷新] [发动态]         │  ← 顶部栏（含发布按钮）
    ├──────────────────┬───────────────────────┤
    │  动态列表         │  ▸ 头像 · 名称 · 时间  │
    │  [头像] 名称      │   正文内容             │
    │  来源 · 时间      │   错误信息（如有）      │
    │  预览文字…        │  ────────────────     │
    │                  │  评论列表              │
    │                  │  [头像] 名称 · 时间     │
    │                  │   评论正文             │
    │                  │  ────────────────     │
    │  [加载更多]       │  [输入框] [发送]       │
    └──────────────────┴───────────────────────┘
    """

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
        """构建完整 UI 布局。"""
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
            QPushButton#publishBtn {
                background: #66CCFF;
                color: white;
                font-weight: 700;
                padding: 8px 16px;
            }
            QPushButton#publishBtn:hover {
                background: #55BBEE;
            }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # ── 顶部栏：标题 + 刷新 + 发动态 ──
        header_row = QHBoxLayout()
        title = QLabel("动态")
        title.setObjectName("titleLabel")
        subtitle = QLabel("查看天依的动态，分享自己的生活。")
        subtitle.setStyleSheet("color: #667481;")
        subtitle.setWordWrap(True)
        title_box = QVBoxLayout()
        title_box.addWidget(title)
        title_box.addWidget(subtitle)
        header_row.addLayout(title_box, 1)

        # 刷新按钮
        self.refresh_button = QPushButton("刷新")
        self.refresh_button.clicked.connect(self.load_dynamics)
        header_row.addWidget(self.refresh_button, 0, Qt.AlignmentFlag.AlignTop)

        # 【修复 4】发布动态按钮从右下角 FAB 移到顶部，改为方形文字按钮
        self.publish_button = QPushButton("发动态")
        self.publish_button.setObjectName("publishBtn")
        self.publish_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.publish_button.clicked.connect(self.open_dynamic_editor)
        header_row.addWidget(self.publish_button, 0, Qt.AlignmentFlag.AlignTop)

        root.addLayout(header_row)

        # 状态提示
        self.feed_status = QLabel("")
        self.feed_status.setStyleSheet("color: #A35C00;")
        self.feed_status.setWordWrap(True)
        self.feed_status.hide()
        root.addWidget(self.feed_status)

        # ── 主内容区：左侧列表 + 右侧详情/评论 ──
        content_row = QHBoxLayout()
        content_row.setSpacing(12)

        # ── 左侧：动态列表 ──
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

        # ── 右侧：详情 + 评论 ──
        right_panel = QVBoxLayout()
        right_label = QLabel("详情与评论")
        right_label.setStyleSheet("font-weight: 600; color: #243447;")

        # 【修复 2】详情区域：用 QWidget 替代 QTextEdit，干净地展示头像 + 名称 + 时间 + 正文
        self.detail_widget = QWidget()
        self.detail_widget.setObjectName("detailWidget")
        self.detail_widget.setStyleSheet(
            """
            QWidget#detailWidget {
                background: #FFFFFF;
                border: 1px solid #D5DEE7;
                border-radius: 6px;
            }
            """
        )
        self.detail_layout = QVBoxLayout(self.detail_widget)
        self.detail_layout.setContentsMargins(12, 12, 12, 12)
        self.detail_layout.setSpacing(8)

        # 详情的头部行：头像 + 名称
        self.detail_header_layout = QHBoxLayout()
        self.detail_header_layout.setSpacing(8)
        self.detail_avatar = QLabel()
        self.detail_avatar.setFixedSize(28, 28)
        self.detail_name = QLabel("")
        self.detail_name.setStyleSheet("font-weight: 600; color: #243447; font-size: 14px;")
        self.detail_time = QLabel("")
        self.detail_time.setStyleSheet("color: #94A3B8; font-size: 12px;")
        self.detail_header_layout.addWidget(self.detail_avatar)
        self.detail_header_layout.addWidget(self.detail_name)
        self.detail_header_layout.addWidget(self.detail_time)
        self.detail_header_layout.addStretch()
        self.detail_layout.addLayout(self.detail_header_layout)

        # 分割线
        sep = QLabel()
        sep.setFixedHeight(1)
        sep.setStyleSheet("background: #E2E8F0;")
        self.detail_layout.addWidget(sep)

        # 正文
        self.detail_content = QLabel("")
        self.detail_content.setWordWrap(True)
        self.detail_content.setStyleSheet("color: #334155; font-size: 14px; line-height: 1.6;")
        self.detail_layout.addWidget(self.detail_content)

        # 错误信息（后台错误/回复错误）
        self.detail_error = QLabel("")
        self.detail_error.setWordWrap(True)
        self.detail_error.setStyleSheet("color: #A35C00; font-size: 12px;")
        self.detail_error.hide()
        self.detail_layout.addWidget(self.detail_error)

        # 缺省提示（未选择动态时）
        self.detail_placeholder = QLabel("请从左侧选择一条动态查看详情")
        self.detail_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_placeholder.setStyleSheet("color: #94A3B8; font-size: 13px; padding: 20px;")
        self.detail_layout.addWidget(self.detail_placeholder)

        self.detail_widget.hide()  # 初始隐藏

        # 【修复 3】评论区：统一放在详情下方
        self.comments_text = QListWidget()
        self.comment_input = QTextEdit()
        self.comment_input.setPlaceholderText("写一条评论...")
        self.comment_input.setFixedHeight(80)
        comment_action_row = QHBoxLayout()
        self.comment_status = QLabel("请选择一条动态")
        self.comment_status.setStyleSheet("color: #667481;")
        comment_action_row.addWidget(self.comment_status, 1)
        self.comment_button = QPushButton("发送评论")
        self.comment_button.setEnabled(False)
        self.comment_button.clicked.connect(self.publish_comment)
        comment_action_row.addWidget(self.comment_button)

        right_panel.addWidget(right_label)
        right_panel.addWidget(self.detail_widget)
        right_panel.addWidget(self.comments_text, 1)
        right_panel.addWidget(self.comment_input)
        right_panel.addLayout(comment_action_row)

        # 左右分栏
        left_widget = QWidget()
        left_widget.setLayout(left_panel)
        right_widget = QWidget()
        right_widget.setLayout(right_panel)
        content_row.addWidget(left_widget, 5)
        content_row.addWidget(right_widget, 6)

        root.addLayout(content_row, 1)

        # 【修复 4】不再创建 FAB 按钮，不需要 _build_add_dynamic_button / _position_add_dynamic_button

    # ────────────────────── 动态加载 ──────────────────────

    def load_dynamics(self):
        payload = self.network_client.get_dynamics(limit=40)
        if not payload.get("ok", False):
            self.feed_status.setText(
                f"动态加载失败：{payload.get('message', '未知错误')}。点击“刷新”重试。"
            )
            self.feed_status.show()
            self.load_more_button.setEnabled(False)
            return False

        self.feed_status.hide()
        items = payload.get("items", [])
        self.dynamic_list.clear()
        self.current_dynamic = None
        self._clear_detail()
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
            self.feed_status.setText(
                f"动态加载失败：{payload.get('message', '未知错误')}。点击“刷新”重试。"
            )
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
        item.setSizeHint(QSize(0, 80))  # 单行预览，高度可以稍小
        self.dynamic_list.addItem(item)
        self.dynamic_list.setItemWidget(item, DynamicListItemWidget(dynamic))

    def mark_read(self):
        result = self.network_client.mark_dynamics_read()
        if result.get("ok") and self.on_read_callback:
            self.on_read_callback()

    # ────────────────────── 动态详情 ──────────────────────

    def on_dynamic_selected(
        self, current: QListWidgetItem | None, _previous: QListWidgetItem | None
    ):
        if current is None:
            self.current_dynamic = None
            self._clear_detail()
            self.comments_text.clear()
            self.comment_status.setText("请选择一条动态")
            self.comment_button.setEnabled(False)
            return

        dynamic = current.data(Qt.ItemDataRole.UserRole) or {}
        self.current_dynamic = dynamic
        self.render_dynamic_detail(dynamic)
        self.load_comments(dynamic)

    def _clear_detail(self):
        """清空详情区域，显示缺省提示。"""
        self.detail_widget.hide()
        self.detail_placeholder.show()

    def render_dynamic_detail(self, dynamic: dict):
        """【修复 2】渲染动态详情：只展示头像、名称、时间、正文。"""
        # 设置头像
        author_type = str(dynamic.get("author_type", ""))
        avatar_path = _avatar_path(author_type)
        if avatar_path:
            pixmap = QPixmap(avatar_path)
            if not pixmap.isNull():
                self.detail_avatar.setPixmap(
                    pixmap.scaled(
                        28, 28,
                        Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )
            else:
                self.detail_avatar.setText(_author_label(author_type))
        else:
            self.detail_avatar.setText(_author_label(author_type))
        self.detail_avatar.setStyleSheet(
            "border-radius: 14px; border: 1px solid #E2E8F0;"
        )

        # 名称 · 时间
        author_name = dynamic.get("author_name", "-")
        created_at = dynamic.get("created_at", "-")
        self.detail_name.setText(author_name)
        self.detail_time.setText(created_at)

        # 正文
        content = str(dynamic.get("content", "") or "-")
        self.detail_content.setText(content)

        # 错误信息
        errors = []
        if dynamic.get("reply_error"):
            errors.append(f"回复失败: {dynamic.get('reply_error')}")
        if dynamic.get("memory_error"):
            errors.append(f"记忆存储失败: {dynamic.get('memory_error')}")
        if errors:
            self.detail_error.setText("\n".join(errors))
            self.detail_error.show()
        else:
            self.detail_error.hide()

        # 切换显示
        self.detail_placeholder.hide()
        self.detail_widget.show()

        # 评论权限
        allow_comment = bool(dynamic.get("allow_comment", False))
        self.comment_button.setEnabled(allow_comment)
        self.comment_status.setText("可评论" if allow_comment else "当前动态不支持评论")

    # ────────────────────── 评论 ──────────────────────

    def load_comments(self, dynamic: dict):
        dynamic_id = dynamic.get("id")
        if not dynamic_id:
            self.comments_text.clear()
            return
        payload = self.network_client.get_dynamic_comments(dynamic_id, limit=200)
        if not payload.get("ok", False):
            self.comments_text.clear()
            item = QListWidgetItem(
                f"评论加载失败：{payload.get('message', '未知错误')}\n再次点击这条动态，或点击“刷新”后重试。"
            )
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

    # ────────────────────── 发布 ──────────────────────

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
        result = self.network_client.create_dynamic_comment(
            self.current_dynamic.get("id"), content
        )
        if not result.get("ok"):
            QMessageBox.warning(self, "评论失败", result.get("message", "未知错误"))
            return
        self.comment_input.clear()
        self.load_comments(self.current_dynamic)