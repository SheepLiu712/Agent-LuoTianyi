"""设置中的聊天与记忆迁移入口；界面只消费后台任务的 Qt 信号。"""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPalette, QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QLayout,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from .window_operation import WindowOperation

_SCOPE_LABELS = {"all": "聊天与记忆", "chat": "聊天与关联媒体", "memory": "长期记忆、画像与聊天偏好"}
_FORMAT_LABELS = {
    "native": "本项目恢复包",
    "chatgpt": "ChatGPT",
    "sillytavern": "SillyTavern",
    "generic": "通用文字记录",
}


def _scope_combo():
    combo = QComboBox()
    for label, value in (("全部", "all"), ("仅聊天", "chat"), ("仅记忆、画像与偏好", "memory")):
        combo.addItem(label, value)
    return combo


def _counts(value: object) -> str:
    data = value if isinstance(value, dict) else {}
    return "，".join(
        f"{label} {data.get(key, 0)}"
        for key, label in (("conversations", "记录"), ("memories", "记忆"), ("media", "媒体"))
    )


class DataTransferDialog(QDialog):
    refresh_requested = Signal()

    def __init__(self, network_client, parent=None):
        super().__init__(parent)
        self.network_client = network_client
        self._preview = None
        self._preview_context = None
        self._retry_request = None
        self._backup_id = ""
        self._backup_context = None
        self._action = ""
        self._cancelled = False
        self._refresh_available = False
        self.setWindowTitle("聊天与记忆迁移")
        self.setMinimumSize(560, 360)
        self.resize(620, 420)
        self.setModal(True)
        self.operation = WindowOperation(self)
        self.operation.completed.connect(self._completed)
        self.operation.settled.connect(self._settled)
        self.finished.connect(self.operation.close)
        self._build_ui()
        self._apply_control_styles()
        self._update_controls()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        title = QLabel("聊天与记忆迁移")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #66CCFF;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)
        help_row = QHBoxLayout()
        help_row.addStretch()
        self.usage_button = QPushButton("使用须知")
        self.usage_button.setFont(title.font())
        self.usage_button.setFlat(True)
        self.usage_button.setStyleSheet(
            "QPushButton { color: #66CCFF; font-weight: bold; border: none; padding: 2px 0; }"
        )
        self.usage_button.clicked.connect(self._show_usage)
        help_row.addWidget(self.usage_button)
        layout.addLayout(help_row)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, 1)
        self._build_export_page()
        self._build_import_page()
        self.details = QTextEdit()
        self.details.setReadOnly(True)
        self.details.setAccessibleName("迁移预览与结果")
        self.details.setMinimumHeight(130)
        self.details.setMaximumHeight(160)
        self.details.hide()
        layout.addWidget(self.details)
        self.status_label = QLabel("就绪")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        actions = QHBoxLayout()
        self.backup_button = QPushButton("下载替换前备份…")
        self.backup_button.clicked.connect(self._download_backup)
        self.refresh_button = QPushButton("刷新历史 / 重连")
        self.refresh_button.clicked.connect(self._refresh)
        self.cancel_button = QPushButton("取消操作")
        self.cancel_button.clicked.connect(self._cancel)
        self.close_button = QPushButton("关闭")
        self.close_button.clicked.connect(self.reject)
        for button in (self.backup_button, self.refresh_button, self.cancel_button, self.close_button):
            actions.addWidget(button)
        layout.addLayout(actions)
        self._editable = (
            self.tabs,
            self.export_scope,
            self.export_format,
            self.export_button,
            self.source_format,
            self.import_scope,
            self.character_id,
            self.file_button,
            self.folder_button,
            self.mode_combo,
            self.advanced_group,
        )
        for label in self.findChildren(QLabel):
            label.setTextFormat(Qt.TextFormat.PlainText)
        for button in self.findChildren(QPushButton):
            button.setAutoDefault(False)
        # 滚动区域默认使用系统窗口底色；统一两个页面及其空白区域的底色。
        for page in (
            self.tabs.widget(0),
            self.tabs.widget(1),
            self.tabs.widget(1).viewport(),
            self.tabs.widget(1).widget(),
        ):
            palette = page.palette()
            palette.setColor(QPalette.ColorRole.Window, QColor("white"))
            palette.setColor(QPalette.ColorRole.Base, QColor("white"))
            page.setPalette(palette)
            page.setAutoFillBackground(True)
        self.tabs.currentChanged.connect(self._fit_window)

    def _apply_control_styles(self):
        # 标签和说明入口在系统默认字号上增加 2 px。
        font = self.font()
        base_size = font.pixelSize() if font.pixelSize() > 0 else round(font.pointSizeF() * self.logicalDpiY() / 72)
        label_size = base_size + 2
        self.tabs.tabBar().setStyleSheet(f"QTabBar::tab {{ font-size: {label_size}px; }}")
        self.usage_button.setStyleSheet(
            self.usage_button.styleSheet() + f"QPushButton {{ font-size: {label_size}px; }}"
        )
        for label in self.findChildren(QLabel):
            if label.text() in {"数据范围：", "保存格式", "：", "导入来源："}:
                label.setStyleSheet(f"font-size: {label_size}px;")
        # 与现有相处模式设置窗口使用相同的字号、输入间距和主按钮配色。
        for control in (*self.findChildren(QComboBox), *self.findChildren(QLineEdit)):
            control.setStyleSheet("font-size: 14px; padding: 6px;")
        for button in self.findChildren(QPushButton):
            if button is not self.usage_button:
                button.setStyleSheet("font-size: 14px; padding: 8px 12px;")
        for button in (self.export_button, self.preview_button, self.commit_button):
            button.setStyleSheet("""
                QPushButton {
                    background-color: #5BB8E8; color: white; border: none;
                    padding: 12px 24px; border-radius: 8px; font-size: 14px;
                }
                QPushButton:hover { background-color: #4AA8D8; }
                QPushButton:disabled { background-color: #e0e0e0; color: #666; }
            """)

    def _build_export_page(self):
        page = QWidget()
        layout = QFormLayout(page)
        layout.setSpacing(12)
        self.export_scope = _scope_combo()
        layout.addRow("数据范围：", self.export_scope)
        self.export_format = QComboBox()
        for label, value in (
            ("ZIP 恢复包", "zip"),
            ("目录恢复包", "directory"),
            ("Markdown 阅读副本", "markdown"),
            ("TXT 阅读副本", "txt"),
        ):
            self.export_format.addItem(label, value)
        format_label = QWidget()
        format_label_layout = QHBoxLayout(format_label)
        format_label_layout.setContentsMargins(0, 0, 0, 0)
        format_label_layout.setSpacing(2)
        format_label_layout.addWidget(QLabel("保存格式"))
        self.format_help_button = QToolButton()
        self.format_help_button.setText("?")
        self.format_help_button.setAccessibleName("保存格式说明")
        self.format_help_button.setToolTip("保存格式说明")
        self.format_help_button.setStyleSheet(
            "QToolButton { color: #1296DB; text-decoration: underline; border: none; background: transparent; }"
        )
        self.format_help_button.clicked.connect(self._show_format_help)
        format_label_layout.addWidget(self.format_help_button)
        format_label_layout.addWidget(QLabel("："))
        layout.addRow(format_label, self.export_format)
        self.export_button = QPushButton("导出并保存…")
        self.export_button.clicked.connect(self._export)
        layout.addRow(self.export_button)
        self.tabs.addTab(page, "导出")

    def _build_import_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(12)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSizeConstraint(QLayout.SizeConstraint.SetMinimumSize)
        # 主区域：来源与选择
        form = QFormLayout()
        form.setSpacing(10)
        self.source_path = QLineEdit()
        self.source_path.setReadOnly(True)
        self.source_path.setPlaceholderText("选择恢复包、外部记录或桌面目录")
        form.addRow("导入来源：", self.source_path)
        choices = QHBoxLayout()
        self.file_button = QPushButton("选择文件…")
        self.folder_button = QPushButton("选择目录…")
        self.file_button.clicked.connect(self._choose_file)
        self.folder_button.clicked.connect(self._choose_directory)
        choices.addWidget(self.file_button)
        choices.addWidget(self.folder_button)
        form.addRow(choices)
        layout.addLayout(form)

        # 主操作按钮
        self.preview_button = QPushButton("预览导入")
        self.preview_button.clicked.connect(self._preview_import)
        layout.addWidget(self.preview_button)

        # 高级设置折叠区域
        self.advanced_group = QToolButton()
        self.advanced_group.setText("高级设置")
        self.advanced_group.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.advanced_group.setArrowType(Qt.ArrowType.RightArrow)
        self.advanced_group.setStyleSheet("QToolButton { border: none; background: transparent; padding: 4px 0; }")
        self.advanced_group.setCheckable(True)
        self.advanced_group.setChecked(False)
        self.advanced_content = QWidget()
        advanced_layout = QFormLayout(self.advanced_content)
        advanced_layout.setContentsMargins(0, 0, 0, 0)
        advanced_layout.setSpacing(10)
        self.advanced_group.toggled.connect(self._toggle_advanced)
        self.advanced_content.setVisible(False)
        self.source_format = QComboBox()
        for label, value in (
            ("自动识别", "auto"),
            ("本项目恢复包", "native"),
            ("ChatGPT", "chatgpt"),
            ("SillyTavern", "sillytavern"),
            ("通用 role/content JSON", "generic"),
        ):
            self.source_format.addItem(label, value)
        advanced_layout.addRow("来源格式：", self.source_format)
        self.import_scope = _scope_combo()
        advanced_layout.addRow("数据范围：", self.import_scope)
        self.character_id = QLineEdit("luotianyi")
        self.character_id.setToolTip("外部文字记录归入的已启用角色标识")
        advanced_layout.addRow("外部记录角色：", self.character_id)
        layout.addWidget(self.advanced_group)
        layout.addWidget(self.advanced_content)

        # 预览后操作区域（仅预览成功后可显示）
        self.post_preview_area = QWidget()
        post_layout = QVBoxLayout(self.post_preview_area)
        post_layout.setContentsMargins(0, 0, 0, 0)
        post_layout.setSpacing(10)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("合并并去重（默认）", "merge")
        self.mode_combo.addItem("备份后替换预览范围", "replace")
        post_layout.addWidget(self.mode_combo)
        self.extract_checkbox = QCheckBox("从本批外部聊天记录提取长期记忆（调用服务端模型）")
        self.extract_checkbox.setToolTip(
            "默认不提取，外部聊天仅进入历史。只提取用户事实，不把外部助手当当前角色；模型失败不会撤销已导入聊天。"
        )
        post_layout.addWidget(self.extract_checkbox)
        self.commit_button = QPushButton("确认导入")
        self.commit_button.clicked.connect(self._commit)
        post_layout.addWidget(self.commit_button)
        self.retry_extraction_button = QPushButton("重试本批记忆提取")
        self.retry_extraction_button.clicked.connect(self._retry_extraction)
        post_layout.addWidget(self.retry_extraction_button)
        layout.addWidget(self.post_preview_area)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setWidget(page)
        self.tabs.addTab(scroll, "导入")
        for widget in (self.source_format, self.import_scope):
            widget.currentIndexChanged.connect(self._invalidate_preview)
        self.source_path.textChanged.connect(self._invalidate_preview)
        self.character_id.textChanged.connect(self._invalidate_preview)

    def _update_controls(self):
        busy = self.operation.busy
        for widget in self._editable:
            widget.setEnabled(not busy)
        self.preview_button.setEnabled(not busy and bool(self.source_path.text()))
        self.commit_button.setEnabled(not busy and self._preview is not None)
        external = self._preview is not None and self._preview.get("source_format") != "native"
        self.extract_checkbox.setEnabled(not busy and external)
        self.retry_extraction_button.setVisible(self._retry_request is not None)
        self.retry_extraction_button.setEnabled(not busy and self._retry_request is not None)
        # 预览后操作区域仅在有预览或重试请求时显示
        self.post_preview_area.setVisible(self._preview is not None or self._retry_request is not None)
        self.backup_button.setEnabled(not busy and bool(self._backup_id))
        self.backup_button.setVisible(not busy and bool(self._backup_id))
        self.refresh_button.setEnabled(not busy and self._refresh_available)
        self.refresh_button.setVisible(not busy and self._refresh_available)
        self.cancel_button.setEnabled(busy and self._action != "commit" and not self._cancelled)
        self.cancel_button.setVisible(busy and self._action != "commit" and not self._cancelled)
        self.close_button.setEnabled(not busy or self._action != "commit")
        self._fit_window()

    def _invalidate_preview(self, *_args):
        self._preview = None
        self._preview_context = None
        self._retry_request = None
        self.extract_checkbox.setChecked(False)
        self._update_controls()

    def _choose_file(self):
        if self.operation.busy:
            return
        path, _filter = QFileDialog.getOpenFileName(
            self, "选择聊天或记忆文件", "", "数据文件 (*.zip *.json *.jsonl *.md *.txt);;所有文件 (*)"
        )
        if path:
            self.source_path.setText(path)

    def _choose_directory(self):
        if self.operation.busy:
            return
        path = QFileDialog.getExistingDirectory(self, "选择恢复包目录")
        if path:
            self.source_path.setText(path)

    def _collapse_details(self):
        self.details.hide()
        self._fit_window()

    def _expand_details(self):
        self.details.show()
        self._fit_window()

    def _start(self, action: str, message: str, **values):
        if self.operation.busy:
            return
        request = self.network_client.prepare_data_transfer_request(action, **values)
        if self.operation.start(request) is False:
            return
        self._action = action
        self._cancelled = False
        self.status_label.setText(message)
        self._collapse_details()
        self._update_controls()

    def _export(self):
        if self.operation.busy:
            return
        selected = self.export_format.currentData()
        scope = self.export_scope.currentData()
        if selected == "directory":
            parent = QFileDialog.getExistingDirectory(self, "选择目录包的保存位置")
            if not parent:
                return
            destination = str(Path(parent) / f"agentluo-{scope}-{datetime.now():%Y%m%d-%H%M%S}")
        else:
            suffix = {"zip": "zip", "markdown": "md", "txt": "txt"}[selected]
            destination, _filter = QFileDialog.getSaveFileName(
                self, "保存导出文件", f"agentluo-{scope}.{suffix}", f"导出文件 (*.{suffix})"
            )
            if not destination:
                return
        self._start(
            "export",
            "正在生成并保存导出，请暂停聊天…",
            scope=scope,
            format="zip" if selected == "directory" else selected,
            directory=selected == "directory",
            destination=destination,
        )

    def _preview_import(self):
        if self.operation.busy or not self.source_path.text():
            return
        self._invalidate_preview()
        self._start(
            "preview",
            "正在上传并预览，不会写入聊天或记忆…",
            source_path=self.source_path.text(),
            source_format=self.source_format.currentData(),
            scope=self.import_scope.currentData(),
            character_id=self.character_id.text().strip(),
        )

    def _confirm_replace(self, scope: str) -> bool:
        return (
            QMessageBox.question(
                self,
                "确认备份后替换",
                f"即将替换当前账号的【{_SCOPE_LABELS[scope]}】。\n"
                "服务器会先创建可下载的恢复 ZIP，再替换此范围；其他范围保持不变。\n"
                "提交开始后无法取消，请暂停聊天并等待结果。是否继续？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            == QMessageBox.StandardButton.Yes
        )

    def _commit(self):
        if self.operation.busy or self._preview is None:
            return
        if self._preview_context != self.network_client.account_context():
            self._invalidate_preview()
            self.status_label.setText("账号或服务器已变更，请重新预览。")
            return
        preview = self._preview
        mode = self.mode_combo.currentData()
        if mode == "replace" and not self._confirm_replace(preview["scope"]):
            return
        self._start(
            "commit",
            "正在导入；提交开始后无法撤销，请等待结果并暂停聊天…",
            preview_id=preview["preview_id"],
            scope=preview["scope"],
            mode=mode,
            confirm_replace=mode == "replace",
            extract_memories=self.extract_checkbox.isEnabled() and self.extract_checkbox.isChecked(),
        )

    def _retry_extraction(self):
        previous = self._retry_request
        if self.operation.busy or previous is None:
            return
        if previous.context != self.network_client.account_context():
            self._invalidate_preview()
            self.status_label.setText("账号或服务器已变更，不能重试原账号的提取。")
            return
        # 服务端以同一预览标识重试提取，已完成的数据提交不会再次执行。
        self._start(
            "commit",
            "正在重试本批记忆提取；不会再次替换已导入的数据…",
            preview_id=previous.preview_id,
            scope=previous.scope,
            mode=previous.mode,
            confirm_replace=previous.confirm_replace,
            extract_memories=True,
        )

    def _completed(self, request, result):
        if request.context != self.network_client.account_context():
            self._preview = None
            self._retry_request = None
            self._backup_id = ""
            self.status_label.setText("账号或服务器已变更，已忽略旧账号结果，请重新打开迁移窗口。")
            return
        success, message, data = result
        if data.get("backup_id"):
            self._backup_id = str(data["backup_id"])
            self._backup_context = request.context
        if request.action == "commit":
            # 数据重试必须重新预览；模型重试则保留原标识，由服务端避免重复替换。
            self._preview = None
            extraction = data.get("extraction") or {}
            failed_extraction = extraction.get("status") in ("failed", "unavailable")
            retryable = request.extract_memories and data.get("committed") and failed_extraction
            self._retry_request = request if retryable else None
            self._refresh_available = True
        if not success:
            self.status_label.setText(f"操作失败：{message}。可检查后重新预览或重试。")
            if request.action == "export":
                self._refresh_available = True
                self.details.setPlainText(f"导出失败：{message}\n可刷新历史并重连后继续聊天。")
                self._expand_details()
            if request.action == "commit":
                self.details.setPlainText(
                    "未确认导入成功。若请求中断，服务器可能已完成提交，请先刷新历史；重试前重新预览。\n"
                    + self._result_text(data)
                )
                self._expand_details()
            return
        if request.action == "preview":
            self._preview = data
            self._preview_context = request.context
            self.extract_checkbox.setChecked(False)
            text = (
                f"来源：{_FORMAT_LABELS.get(data.get('source_format'), data.get('source_format', '-'))}\n"
                f"实际导入范围：{_SCOPE_LABELS[data['scope']]}\n{_counts(data.get('counts'))}\n"
            )
            warnings = data.get("warnings") or []
            text += "\n警告：\n" + "\n".join(str(item) for item in warnings) if warnings else "\n未报告警告。"
            self.details.setPlainText(text)
            self._expand_details()
            self.status_label.setText("预览完成，请核对实际范围后选择合并或替换。")
        elif request.action == "commit":
            self.details.setPlainText(self._result_text(data))
            self._collapse_details()
            extraction = data.get("extraction") or {}
            if extraction.get("status") in {"failed", "unavailable"}:
                self.status_label.setText("聊天导入成功，记忆提取未完成。可重试提取。")
                self._expand_details()
            elif data.get("warnings"):
                self.status_label.setText("导入完成，请查看以下提示。")
                self._expand_details()
            else:
                self.status_label.setText("导入成功。")
        else:
            self.status_label.setText(f"已保存：{data.get('path', '')}")
            if request.action == "export":
                self._refresh_available = True

    @staticmethod
    def _result_text(data):
        lines = [f"导入：{_counts(data.get('imported'))}", f"跳过：{_counts(data.get('skipped'))}"]
        extraction = data.get("extraction") or {}
        labels = {
            "not_requested": "未请求",
            "succeeded": "成功",
            "failed": "失败（聊天保留）",
            "unavailable": "不可用（聊天保留）",
        }
        state = extraction.get("status", "not_requested")
        lines.append(f"记忆提取：{labels.get(state, state)}；生成 {extraction.get('memories', 0)} 条")
        if extraction.get("error"):
            lines.append(str(extraction["error"]))
        if data.get("backup_id"):
            lines.append("替换前恢复备份已生成，可点击“下载替换前备份”。")
        for key, label in (("error", "导入错误"), ("rollback_error", "恢复错误")):
            if data.get(key):
                lines.append(f"{label}：{data[key]}")
        lines.extend(f"警告：{item}" for item in data.get("warnings") or [])
        return "\n".join(lines)

    def _settled(self):
        if self._cancelled:
            self.status_label.setText("操作已取消。网络请求如已发出会等待结束，未提交导入。")
            if self._action == "export":
                self._refresh_available = True
        self._action = ""
        self._update_controls()

    def _download_backup(self):
        if self.operation.busy or not self._backup_id:
            return
        if self._backup_context != self.network_client.account_context():
            self.status_label.setText("账号已变更，请返回原账号下载备份。")
            return
        path, _filter = QFileDialog.getSaveFileName(
            self, "保存替换前恢复备份", "agentluo-backup.zip", "ZIP 恢复包 (*.zip)"
        )
        if path:
            self._start("backup", "正在下载替换前备份…", backup_id=self._backup_id, destination=path)

    def _refresh(self):
        if not self.operation.busy:
            self.refresh_requested.emit()
            self.status_label.setText("已请求刷新历史。聊天会自动重连；若仍离线，请重新登录。")

    def _cancel(self):
        if self.operation.busy and self._action != "commit":
            self._cancelled = True
            self.operation.invalidate()
            self.status_label.setText("正在取消，等待当前网络请求结束…")
            self._update_controls()

    def _toggle_advanced(self, expanded):
        self.advanced_content.setVisible(expanded)
        self.advanced_group.setArrowType(Qt.ArrowType.DownArrow if expanded else Qt.ArrowType.RightArrow)
        self._fit_window()

    def _fit_window(self, *_args):
        height = 420
        if self.tabs.currentIndex() == 1:
            height += 140 if self.advanced_group.isChecked() else 0
            if self._preview is not None or self._retry_request is not None:
                height += 120
        if not self.details.isHidden():
            height += 150
        self.resize(self.width(), min(height, self.screen().availableGeometry().height() - 60))

    def _show_information(self, title, text):
        # 普通说明使用对话框，不触发系统消息框的提示音。
        dialog = QDialog(self)
        dialog.setWindowTitle(title)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(16)
        content = QLabel(text)
        content.setTextFormat(Qt.TextFormat.PlainText)
        content.setWordWrap(True)
        content.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        layout.addWidget(content)
        close_button = QPushButton("确定")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, 0, Qt.AlignmentFlag.AlignRight)
        dialog.setMinimumWidth(420)
        dialog.exec()

    def _show_format_help(self):
        self._show_information("保存格式说明", "ZIP 与目录包可恢复，内部结构相同；Markdown / TXT 仅供阅读。")

    def _show_usage(self):
        text = (
            "1. 上传与下载上限 64 MiB，解压后上限 256 MiB、4096 项。\n\n"
            "2. 导入和导出时请暂停聊天，过程中服务器可能断开聊天连接。\n\n"
            "3. 外部聊天默认只进入历史，勾选提取长期记忆后才会调用模型提取。\n\n"
            "4. 完成后可点击“刷新历史 / 重连”。"
        )
        if self.details.toPlainText():
            text += "\n\n最近一次操作\n" + self.details.toPlainText()
        self._show_information("使用须知", text)

    def reject(self):
        if self.operation.busy and self._action == "commit":
            self.status_label.setText("导入提交正在执行，请等待结果；此时关闭窗口无法撤销服务器提交。")
            return
        self.operation.close()
        super().reject()
