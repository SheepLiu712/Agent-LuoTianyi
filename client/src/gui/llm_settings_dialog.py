"""LLM 模型设置对话框 - 对话模型与图片理解模型分页配置，每页独立保存。"""

import json

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QComboBox, QMessageBox, QGroupBox,
                               QPlainTextEdit, QStackedWidget, QWidget,
                               QApplication, QProgressBar)
from PySide6.QtCore import Qt, QByteArray, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtGui import QCloseEvent, QResizeEvent
from typing import TYPE_CHECKING

from ..utils.logger import get_logger
from ..safety import credential
from ..utils.llm_client import (
    build_chat_completions_payload,
    resolve_provider_base_url,
)

if TYPE_CHECKING:
    from ..network.network_client import NetworkClient


def _friendly_probe_error(name: str, exc: Exception) -> str:
    """把探测失败转成面向用户的提示。"""
    text = str(exc)
    lowered = text.lower()
    if any(marker in lowered for marker in ("401", "403", "unauthorized", "invalid api key", "api key", "authentication", "access denied", "arrearage")):
        return f"{name}：API Key 无效或没有权限，请检查后重试。"
    if "400" in lowered or "unsupported" in lowered or "invalidparameter" in lowered:
        return f"{name}：模型或所选开关不受支持，请更换模型或取消不支持的选项后重试。"
    if any(marker in lowered for marker in ("connection", "timed out", "timeout", "network", "request failed", "resolve")):
        return f"{name}：无法连接服务商，请检查网络后重试。"
    return f"{name}：{text}"


def _module_labels(items: list) -> list:
    """服务端下发 [{name, label}]，提取友好标签；兼容纯字符串列表。"""
    labels = []
    for item in items:
        if isinstance(item, dict):
            label = item.get("label")
            labels.append(str(label) if label else str(item.get("name", "")))
        elif isinstance(item, str):
            labels.append(item)
    return labels


class _BlockingOverlay(QWidget):
    """校验期间覆盖整个对话框，吸收鼠标与键盘事件，保证任何操作都不可用。"""

    def keyPressEvent(self, event) -> None:
        event.accept()

    def keyReleaseEvent(self, event) -> None:
        event.accept()

    def mousePressEvent(self, event) -> None:
        event.accept()

    def mouseReleaseEvent(self, event) -> None:
        event.accept()


class LLMSettingsDialog(QDialog):
    """对话模型与图片理解模型分页配置，每页独立保存，避免共享保存按钮歧义。"""

    def __init__(self, network_client: "NetworkClient", parent=None):
        super().__init__(parent)
        self.logger = get_logger(self.__class__.__name__)
        self.network_client = network_client
        self.setWindowTitle("LLM 模型设置")
        self.setMinimumSize(560, 560)
        self.setModal(True)

        self._llm_providers: list = []
        self._llm_json_modules: list = []
        self._vlm_json_modules: list = []
        self._saved_provider: str | None = None
        self._saved_model: str | None = None
        self._saved_vlm_provider: str | None = None
        self._saved_vlm_model: str | None = None
        self._http = QNetworkAccessManager(self)
        self._http.setRedirectPolicy(QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        self._providers_reply: "QNetworkReply | None" = None
        self._probe_replies: list = []
        self._probe_configs: list = []
        self._pending_save: tuple | None = None
        self._page_kinds: list = ["text"]
        self._current_kind: str = "text"
        self._prompted_changes: set = set()

        self._init_ui()
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        self.provider_combo.currentIndexChanged.connect(self._update_config_hint)
        self.api_key_input.textChanged.connect(self._update_config_hint)
        self.model_combo.currentIndexChanged.connect(self._update_config_hint)
        self.vlm_provider_combo.currentIndexChanged.connect(self._on_vlm_provider_changed)
        self.vlm_provider_combo.currentIndexChanged.connect(self._update_config_hint)
        self.vlm_api_key_input.textChanged.connect(self._update_config_hint)
        self.vlm_model_combo.currentIndexChanged.connect(self._update_config_hint)
        self._load_config()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("LLM 模型设置")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #66CCFF;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "对话与图片理解可分别选择服务商和模型，各自使用独立的 API Key；"
            "key 只保存在本机，不会上传服务器。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #666;")
        layout.addWidget(desc)

        self.page_label = QLabel("1 / 2 · 对话模型")
        self.page_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.page_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #333;")
        layout.addWidget(self.page_label)

        self.config_hint = QLabel("")
        self.config_hint.setWordWrap(True)
        self.config_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.config_hint.setStyleSheet("font-size: 12px; color: #C77700;")
        layout.addWidget(self.config_hint)

        self.stack = QStackedWidget()
        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)
        text_layout.setContentsMargins(0, 0, 0, 0)
        (self.provider_combo, self.api_key_input, self.model_combo, self.base_url_hint,
         self.params_editor) = self._build_form(text_layout, "对话")
        self.text_page = text_tab

        vlm_tab = QWidget()
        vlm_layout = QVBoxLayout(vlm_tab)
        vlm_layout.setContentsMargins(0, 0, 0, 0)
        (self.vlm_provider_combo, self.vlm_api_key_input, self.vlm_model_combo,
         self.vlm_base_url_hint, self.vlm_params_editor) = self._build_form(vlm_layout, "图片理解")
        self.vlm_page = vlm_tab

        self.stack.addWidget(text_tab)
        self.stack.addWidget(vlm_tab)
        layout.addWidget(self.stack, 1)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        self.prev_btn = QPushButton("上一步")
        # 初始在第 1 页，不显示“上一步”
        self.prev_btn.setVisible(False)
        self.prev_btn.setStyleSheet("""
            QPushButton {
                background-color: #ffffff;
                color: #555555;
                border: 1px solid #cccccc;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #f2f2f2; }
            QPushButton:disabled {
                background-color: #E3E6E9;
                color: #A0A6AC;
                border-color: #D5DAE0;
            }
        """)
        self.prev_btn.clicked.connect(lambda: self._go_to_page(0))
        self.next_btn = QPushButton("下一步")
        # 列表未加载前不可继续；加载完成后按可用项重新评估
        self.next_btn.setEnabled(False)
        self.next_btn.setStyleSheet("""
            QPushButton {
                background-color: #5BB8E8;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #4AA8D8; }
            QPushButton:disabled {
                background-color: #C8CDD3;
                color: #8A9299;
            }
        """)
        self.next_btn.clicked.connect(self._on_advance)
        btn_layout.addWidget(self.prev_btn)
        btn_layout.addWidget(self.next_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

        # 校验遮罩：覆盖整个对话框，保证探测期间任何操作都不可用
        self._overlay = _BlockingOverlay(self)
        self._overlay.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._overlay.setStyleSheet("background-color: rgba(255, 255, 255, 210);")
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        overlay_layout.setSpacing(12)
        self._overlay_progress = QProgressBar(self._overlay)
        self._overlay_progress.setRange(0, 0)
        self._overlay_progress.setFixedWidth(180)
        self._overlay_progress.setTextVisible(False)
        self._overlay_label = QLabel("正在校验配置…", self._overlay)
        self._overlay_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._overlay_label.setStyleSheet(
            "font-size: 15px; font-weight: 600; color: #333333;"
            "background: transparent;"
        )
        overlay_layout.addWidget(
            self._overlay_progress, 0, Qt.AlignmentFlag.AlignHCenter
        )
        overlay_layout.addWidget(self._overlay_label)
        self._overlay.hide()

    def _go_to_page(self, index: int) -> None:
        """翻页：切换当前配置页并同步导航按钮。"""
        index = max(0, min(index, len(self._page_kinds) - 1))
        kind = self._page_kinds[index]
        self._current_kind = kind
        self.stack.setCurrentWidget(
            self.text_page if kind == "text" else self.vlm_page
        )
        self.page_label.setText(
            f"{index + 1} / {len(self._page_kinds)} · "
            + ("对话模型" if kind == "text" else "图片理解模型")
        )
        # 仅首页不显示“上一步”，与 APP 一致
        self.prev_btn.setVisible(index > 0)
        self.prev_btn.setEnabled(index > 0)
        self.next_btn.setText(
            "完成" if index == len(self._page_kinds) - 1 else "下一步"
        )
        self._update_page_status()
        self._update_config_hint()
        self._check_saved_change(kind)

    def _saved_config_stale(self, kind: str) -> bool:
        """已保存的服务商/模型是否已不在当前可用列表（视为配置变化）。"""
        if kind == "text":
            saved_provider = credential.get_provider()
            saved_model = credential.get_model()
            preset = self._find_preset(saved_provider or "")
            model_list = preset.get("models") if preset else None
        else:
            saved_provider = credential.get_vlm_provider()
            saved_model = credential.get_vlm_model()
            preset = self._find_preset(saved_provider or "")
            model_list = preset.get("vlm_models") if preset else None
        if not saved_provider:
            return False
        if preset is None:
            return True
        return bool(saved_model) and saved_model not in (model_list or [])

    def _check_saved_change(self, kind: str) -> None:
        """进入页面时检查已保存配置是否已变化；变化则提示重新选择或跳转/关闭。"""
        if kind in self._prompted_changes:
            return
        if not self._saved_config_stale(kind):
            return
        self._prompted_changes.add(kind)
        kind_name = "对话模型" if kind == "text" else "图片理解模型"
        others = [k for k in self._page_kinds if k != kind]
        box = QMessageBox(self)
        box.setWindowTitle("提示")
        if others:
            other_name = "对话模型" if others[0] == "text" else "图片理解模型"
            box.setText(
                f"已保存的{kind_name}服务商或模型已变化，是否重新选择？\n"
                f"不重新选择将跳转到{other_name}配置页。"
            )
        else:
            box.setText(
                f"已保存的{kind_name}服务商或模型已变化，是否重新选择？\n"
                "不重新选择将关闭设置页。"
            )
        reselect_btn = box.addButton("重新选择", QMessageBox.ButtonRole.AcceptRole)
        box.addButton("不重新选择", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(reselect_btn)
        box.exec()
        if box.clickedButton() is reselect_btn:
            self._select_available_config(kind)
            return
        if others:
            self._go_to_page(self._page_kinds.index(others[0]))
            self.prev_btn.setVisible(False)
        else:
            self.reject()

    def _select_available_config(self, kind: str) -> None:
        """重新选择时按失效情况自动选中可用配置。"""
        if kind == "text":
            preset = self._find_preset(credential.get_provider() or "")
            if preset is None:
                # 服务商失效：服务商与模型一起选第一个可用
                first = next(
                    (p for p in self._llm_providers if p.get("models")), None
                )
                if first is not None:
                    self.provider_combo.setCurrentIndex(
                        self.provider_combo.findText(first["name"])
                    )
            elif preset.get("models"):
                # 仅模型失效：保留服务商，选其第一个可用模型
                self.model_combo.setCurrentIndex(0)
        else:
            preset = self._find_preset(credential.get_vlm_provider() or "")
            if preset is None:
                first = next(
                    (p for p in self._llm_providers if p.get("vlm_models")), None
                )
                if first is not None:
                    self.vlm_provider_combo.setCurrentIndex(
                        self.vlm_provider_combo.findText(first["name"])
                    )
            elif preset.get("vlm_models"):
                self.vlm_model_combo.setCurrentIndex(0)

    def _update_page_status(self) -> None:
        """当前页无额外状态提示（空列表由弹窗处理）。"""
        self.status_label.setText("")

    def closeEvent(self, event: QCloseEvent) -> None:
        """校验期间禁止关闭窗口；服务商列表请求直接取消，避免残留请求/线程。"""
        if self._probe_replies and any(r.isRunning() for r in self._probe_replies):
            event.ignore()
            self.status_label.setText("正在校验配置…，请稍候")
            return
        if self._providers_reply is not None and not self._providers_reply.isFinished():
            self._providers_reply.abort()
        event.accept()

    def _can_advance(self) -> bool:
        """当前页下拉框有可用项时才允许继续（拉取失败/无模型时禁用）。"""
        return (
            self.model_combo if self._current_kind == "text" else self.vlm_model_combo
        ).count() > 0

    def _next_enabled(self) -> bool:
        """下一步可用：下拉框有项，或旧配置完整且与当前填写一致。"""
        return self._can_advance() or self._has_unchanged_saved_config(
            self._current_kind
        )

    def _has_unchanged_saved_config(self, kind: str) -> bool:
        """已保存配置完整且当前填写与之一致（任意情况下直接翻页不保存）。"""
        if kind == "text":
            saved_key = credential.get_api_key()
            saved_provider = credential.get_provider()
            saved_model = credential.get_model()
            current_key = self.api_key_input.text().strip()
            current_provider = self.provider_combo.currentText().strip()
            current_model = self.model_combo.currentText().strip()
            params_match = self._params_match(
                self.params_editor, credential.get_llm_params()
            )
        else:
            saved_key = credential.get_vlm_api_key()
            saved_provider = credential.get_vlm_provider()
            saved_model = credential.get_vlm_model()
            current_key = self.vlm_api_key_input.text().strip()
            current_provider = self.vlm_provider_combo.currentText().strip()
            current_model = self.vlm_model_combo.currentText().strip()
            params_match = self._params_match(
                self.vlm_params_editor, credential.get_vlm_params()
            )
        if not (saved_key and saved_provider and saved_model):
            return False
        if current_key != saved_key or not params_match:
            return False
        # 列表未加载时下拉框为空，无法比较服务商/模型，视为一致
        if (self.model_combo if kind == "text" else self.vlm_model_combo).count() > 0:
            if current_provider != saved_provider or current_model != saved_model:
                return False
        return True

    def _params_match(self, editor: QPlainTextEdit, saved_params: dict) -> bool:
        """当前高级参数与已保存参数是否一致（解析失败视为不一致）。"""
        text = editor.toPlainText().strip()
        if not text:
            return not saved_params
        try:
            parsed = json.loads(text)
        except Exception:
            return False
        return isinstance(parsed, dict) and parsed == saved_params

    def _build_form(self, layout: QVBoxLayout, label: str) -> tuple:
        """构建一份对齐的表单（服务商 / API Key / 模型 / 地址提示 / 高级设置）。"""
        provider_label = QLabel(f"{label}服务商：")
        provider_label.setStyleSheet("font-size: 14px; font-weight: 500; margin-top: 4px;")
        layout.addWidget(provider_label)

        provider_row = QHBoxLayout()
        provider_row.setSpacing(8)
        provider_combo = QComboBox()
        provider_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        provider_row.addWidget(provider_combo, 1)
        refresh_btn = QPushButton("刷新")
        refresh_btn.setStyleSheet("font-size: 13px; padding: 6px 12px;")
        refresh_btn.clicked.connect(self._refresh_providers)
        provider_row.addWidget(refresh_btn)
        layout.addLayout(provider_row)

        key_label = QLabel(f"{label} API Key：")
        key_label.setStyleSheet("font-size: 14px; font-weight: 500; margin-top: 4px;")
        layout.addWidget(key_label)

        api_key_input = QLineEdit()
        api_key_input.setPlaceholderText(f"粘贴{label}服务商的 API Key")
        api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_input.setStyleSheet("font-size: 14px; padding: 6px;")
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        key_row.addWidget(api_key_input, 1)
        paste_btn = QPushButton("粘贴")
        paste_btn.setStyleSheet("font-size: 13px; padding: 6px 12px;")
        paste_btn.clicked.connect(
            lambda checked=False, edit=api_key_input: self._toggle_key_input(edit)
        )
        api_key_input.textChanged.connect(
            lambda _text, btn=paste_btn, edit=api_key_input: self._update_paste_button(
                btn, edit
            )
        )
        key_row.addWidget(paste_btn)
        layout.addLayout(key_row)
        if label == "对话":
            self.paste_btn = paste_btn
        else:
            self.vlm_paste_btn = paste_btn

        model_label = QLabel(f"{label}模型：")
        model_label.setStyleSheet("font-size: 14px; font-weight: 500; margin-top: 4px;")
        layout.addWidget(model_label)

        model_combo = QComboBox()
        model_combo.setPlaceholderText(f"选择{label}模型")
        model_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        layout.addWidget(model_combo)

        base_url_hint = QLabel("")
        base_url_hint.setWordWrap(True)
        base_url_hint.setStyleSheet("font-size: 12px; color: #999;")
        layout.addWidget(base_url_hint)

        advanced_group = QGroupBox("高级设置")
        advanced_group.setCheckable(True)
        advanced_group.setChecked(False)
        advanced_group.setStyleSheet("font-size: 13px;")
        advanced_layout = QVBoxLayout(advanced_group)
        advanced_layout.setSpacing(6)
        advanced_hint = QLabel(
            "可选，以 JSON 覆盖请求参数。不同模型的参数不同，请按服务商文档填写，例如："
        )
        advanced_hint.setWordWrap(True)
        advanced_hint.setStyleSheet("font-size: 12px; color: #888;")
        advanced_layout.addWidget(advanced_hint)
        example_label = QLabel('{"temperature": 0.7, "max_tokens": 4096, "top_p": 0.9}')
        example_label.setStyleSheet("font-size: 12px; color: #666;")
        advanced_layout.addWidget(example_label)
        params_editor = QPlainTextEdit()
        params_editor.setPlaceholderText('{"temperature": 0.7}')
        params_editor.setMaximumHeight(110)
        params_editor.setStyleSheet("font-size: 13px;")
        advanced_layout.addWidget(params_editor)

        layout.addWidget(advanced_group)

        layout.addStretch()
        return (
            provider_combo,
            api_key_input,
            model_combo,
            base_url_hint,
            params_editor,
        )

    def _toggle_key_input(self, edit: QLineEdit) -> None:
        """粘贴/清空按钮：输入框有值时清空，否则粘贴剪贴板内容。"""
        if edit.text():
            edit.clear()
        else:
            edit.setText(QApplication.clipboard().text())

    def _update_paste_button(self, button: QPushButton, edit: QLineEdit) -> None:
        """按键输入值切换按钮文案：有值显示“清空”，无值显示“粘贴”。"""
        button.setText("清空" if edit.text() else "粘贴")

    def _load_config(self) -> None:
        """从本地凭据加载已保存的配置，并从服务端拉取服务商列表。"""
        self._saved_provider = credential.get_provider()
        saved_model = credential.get_model()
        if saved_model:
            self._saved_model = saved_model
        saved_vlm_provider = credential.get_vlm_provider()
        if saved_vlm_provider:
            self._saved_vlm_provider = saved_vlm_provider
        saved_vlm_model = credential.get_vlm_model()
        if saved_vlm_model:
            self._saved_vlm_model = saved_vlm_model
        saved_key = credential.get_api_key()
        if saved_key:
            self.api_key_input.setText(saved_key)
        saved_vlm_key = credential.get_vlm_api_key()
        if saved_vlm_key:
            self.vlm_api_key_input.setText(saved_vlm_key)
        text_params = credential.get_llm_params()
        if text_params:
            self.params_editor.setPlainText(json.dumps(text_params, ensure_ascii=False, indent=2))
        vlm_params = credential.get_vlm_params()
        if vlm_params:
            self.vlm_params_editor.setPlainText(json.dumps(vlm_params, ensure_ascii=False, indent=2))
        self.status_label.setText("正在获取服务商列表…")
        self._start_fetch_providers()
        self._update_config_hint()
        self.next_btn.setEnabled(self._next_enabled())

    def _start_fetch_providers(self) -> None:
        """异步拉取服务商列表（含 JSON 能力标注），取消前一个未完成的请求。"""
        if self._providers_reply is not None and not self._providers_reply.isFinished():
            self._providers_reply.abort()
        base = self.network_client.base_url
        request = QNetworkRequest(QUrl(f"{base.rstrip('/')}/llm/providers"))
        request.setTransferTimeout(15000)
        self._providers_reply = self._http.get(request)
        self._providers_reply.finished.connect(self._on_providers_reply)

    def _on_providers_reply(self) -> None:
        """处理服务商列表响应；旧请求被取消/替换后直接忽略。"""
        reply = self.sender()
        if reply is None or reply is not self._providers_reply:
            return
        self._providers_reply = None
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._on_providers_failed(reply.errorString())
            return
        try:
            data = json.loads(bytes(reply.readAll()))
        except Exception as exc:
            self._on_providers_failed(f"数据解析失败: {exc}")
            return
        providers = data.get("providers") if isinstance(data, dict) else data
        if not isinstance(providers, list):
            self._on_providers_failed("服务商列表格式错误")
            return
        self._on_providers_loaded(providers)
        if isinstance(data, dict):
            self._on_json_modules_loaded(
                _module_labels(data.get("llm_json_required_modules") or []),
                _module_labels(data.get("vlm_json_required_modules") or []),
            )

    def _on_providers_loaded(self, providers: list) -> None:
        # 全量保存，渲染/填充下拉时按能力分类（保留纯 VLM 等服务商）
        if not isinstance(providers, list):
            return
        self._llm_providers = [p for p in providers if isinstance(p, dict)]
        all_names = [
            p["name"] for p in self._llm_providers if p.get("models")
        ]
        vlm_names = [p["name"] for p in self._llm_providers if p.get("vlm_models")]
        previous_text = self.provider_combo.currentText().strip()
        previous_vlm_text = self.vlm_provider_combo.currentText().strip()
        self.provider_combo.clear()
        self.provider_combo.addItems(all_names)
        self.provider_combo.setPlaceholderText("请选择服务商")
        self.vlm_provider_combo.clear()
        self.vlm_provider_combo.addItems(vlm_names)
        self.vlm_provider_combo.setPlaceholderText("请选择服务商")
        # 服务端启动时已验证 LLM/VLM 接口存在（缺失会注册失败），
        # 下发列表必然非空，客户端不再做空列表验证
        text_index = self.provider_combo.findText(self._saved_provider or "")
        if text_index >= 0:
            self.provider_combo.setCurrentIndex(text_index)
        elif previous_text and self.provider_combo.findText(previous_text) >= 0:
            # 刷新时保留用户手动选择
            self.provider_combo.setCurrentIndex(
                self.provider_combo.findText(previous_text)
            )
        elif not credential.get_api_key():
            # key 为空（未配置）：默认展示首项，方便用户直接填入 key
            self.provider_combo.setCurrentIndex(0)
        else:
            # 已配置但保存的服务商不在列表中：保持未选择，不覆盖
            self.provider_combo.setCurrentIndex(-1)
        vlm_index = self.vlm_provider_combo.findText(self._saved_vlm_provider or "")
        if vlm_index >= 0:
            self.vlm_provider_combo.setCurrentIndex(vlm_index)
        elif previous_vlm_text and self.vlm_provider_combo.findText(previous_vlm_text) >= 0:
            self.vlm_provider_combo.setCurrentIndex(
                self.vlm_provider_combo.findText(previous_vlm_text)
            )
        elif not credential.get_vlm_api_key():
            self.vlm_provider_combo.setCurrentIndex(0)
        else:
            self.vlm_provider_combo.setCurrentIndex(-1)
        self._on_provider_changed(self.provider_combo.currentIndex())
        self._on_vlm_provider_changed(self.vlm_provider_combo.currentIndex())
        # 无可用服务商的能力页不展示：只保留有可用服务的配置页
        self._page_kinds = []
        if all_names:
            self._page_kinds.append("text")
        if vlm_names:
            self._page_kinds.append("vlm")
        if not self._page_kinds:
            self._page_kinds = ["text"]
        self._go_to_page(0)

    def _on_providers_failed(self, message: str) -> None:
        self.status_label.setText(f"获取服务商列表失败：{message}")
        self._update_config_hint()

    def _refresh_providers(self) -> None:
        self.status_label.setText("正在获取服务商列表…")
        self._start_fetch_providers()

    def _on_json_modules_loaded(self, llm_modules: list, vlm_modules: list) -> None:
        self._llm_json_modules = llm_modules or []
        self._vlm_json_modules = vlm_modules or []

    def _on_provider_changed(self, _index: int) -> None:
        preset = self._find_preset(self.provider_combo.currentText())
        self.model_combo.clear()
        if preset is None:
            return
        models = preset.get("models") or []
        self.model_combo.addItems([str(m) for m in models])
        if self._saved_model in [str(m) for m in models]:
            self.model_combo.setCurrentText(str(self._saved_model))
        elif self.model_combo.count() > 0:
            self.model_combo.setCurrentIndex(0)
        self.base_url_hint.setText(f"服务商地址：{preset.get('base_url', '')}")

    def _on_vlm_provider_changed(self, _index: int) -> None:
        preset = self._find_preset(self.vlm_provider_combo.currentText())
        self.vlm_model_combo.clear()
        if preset is None:
            return
        vlm_models = preset.get("vlm_models") or []
        self.vlm_model_combo.addItems([str(m) for m in vlm_models])
        if self._saved_vlm_model in [str(m) for m in vlm_models]:
            self.vlm_model_combo.setCurrentText(str(self._saved_vlm_model))
        elif self.vlm_model_combo.count() > 0:
            self.vlm_model_combo.setCurrentIndex(0)
        self.vlm_base_url_hint.setText(f"服务商地址：{preset.get('base_url', '')}")

    def _find_preset(self, name: str) -> dict | None:
        for preset in self._llm_providers:
            if preset.get("name") == name:
                return preset
        return None

    def _parse_params(self, editor: QPlainTextEdit) -> dict | None:
        text = editor.toPlainText().strip()
        if not text:
            return {}
        try:
            parsed = json.loads(text)
        except Exception as exc:
            QMessageBox.warning(self, "提示", f"高级参数不是合法 JSON：{exc}")
            return None
        if not isinstance(parsed, dict):
            QMessageBox.warning(self, "提示", "高级参数必须是 JSON 对象")
            return None
        return parsed

    def _build_cfg(self, kind: str) -> dict | None:
        """收集当前页配置快照；高级参数非法时返回 None。"""
        if kind == "text":
            params = self._parse_params(self.params_editor)
            if params is None:
                return None
            return {
                "kind": "text",
                "name": "对话模型",
                "api_key": self.api_key_input.text().strip(),
                "provider": self.provider_combo.currentText().strip(),
                "model": self.model_combo.currentText().strip(),
                "params": params,
                "json_modules": self._llm_json_modules,
            }
        params = self._parse_params(self.vlm_params_editor)
        if params is None:
            return None
        return {
            "kind": "vlm",
            "name": "图片理解模型",
            "api_key": self.vlm_api_key_input.text().strip(),
            "provider": self.vlm_provider_combo.currentText().strip(),
            "model": self.vlm_model_combo.currentText().strip(),
            "params": params,
            "json_modules": self._vlm_json_modules,
        }

    def _on_advance(self) -> None:
        """下一步/完成：配置未修改直接翻页；否则保存（key 未填先弹窗确认）。"""
        kind = self._current_kind
        # 旧配置完整且未修改：任意情况下直接翻页/关闭，不执行保存
        if self._has_unchanged_saved_config(kind):
            self._advance_or_close(kind)
            return
        if not self._can_advance():
            return
        cfg = self._build_cfg(kind)
        if cfg is None:
            return
        if cfg["api_key"]:
            self._save_page(cfg, on_success=lambda: self._advance_or_close(kind))
            return
        box = QMessageBox(self)
        box.setWindowTitle("提示")
        box.setText("未配置 API Key，相关调用将使用服务端 Key。是否继续？")
        continue_btn = box.addButton("继续", QMessageBox.ButtonRole.AcceptRole)
        cancel_btn = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(cancel_btn)
        box.exec()
        if box.clickedButton() is not continue_btn:
            return
        # 清除失败不继续导航：提示重试，放弃则停留并保留旧配置
        while not self._clear_saved_module(cfg["kind"]):
            ret = QMessageBox.question(
                self,
                "清除失败",
                "清除配置失败，是否重试？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
        self._advance_or_close(kind)

    def _clear_saved_module(self, kind: str) -> bool:
        """清空该模块已保存的配置，使相关调用使用服务端 Key；返回是否清空成功。"""
        if kind == "text":
            return credential.save_llm_config("", "", "", "", {})
        return credential.save_vlm_config("", "", "", "", {})

    def _update_config_hint(self) -> None:
        """按当前页 API Key 填写情况更新提示：未填 key 则使用服务端 Key。"""
        kind = self._current_kind
        api_key = (
            self.api_key_input.text().strip()
            if kind == "text"
            else self.vlm_api_key_input.text().strip()
        )
        if api_key:
            self.config_hint.setText("")
        else:
            self.config_hint.setText("未配置 API Key，相关调用将使用服务端 Key。")
        if not any(r.isRunning() for r in self._probe_replies):
            self.next_btn.setEnabled(self._next_enabled())

    def _advance_or_close(self, kind: str) -> None:
        """保存/跳过后的落点：非末页进入下一页，末页关闭。"""
        index = self._page_kinds.index(kind)
        if index < len(self._page_kinds) - 1:
            self._go_to_page(index + 1)
        else:
            self.accept()

    def _save_page(self, cfg: dict, on_success=None) -> None:
        """保存当前页配置：全部填齐先探测校验，否则直接落盘。"""
        probe_configs = []
        if cfg["api_key"] and cfg["provider"] and cfg["model"]:
            base_url = resolve_provider_base_url(
                cfg["provider"], presets=self._llm_providers
            )
            if base_url:
                probe_configs.append(
                    {
                        "name": cfg["name"],
                        "base_url": base_url,
                        "api_key": cfg["api_key"],
                        "model": cfg["model"],
                        "params": cfg["params"],
                    }
                )
        if not probe_configs:
            self._finish_module_save(cfg, on_success=on_success)
            return
        self._pending_save = (cfg, on_success)
        self._set_frozen(True)
        self.status_label.setText("正在校验配置…")
        self._probe_replies = []
        self._probe_configs = list(probe_configs)
        for probe in probe_configs:
            params = dict(probe.get("params") or {})
            params["max_tokens"] = 8
            params["temperature"] = 0
            body = build_chat_completions_payload(
                prompt="ping",
                model=probe["model"],
                params=params,
            )
            request = QNetworkRequest(
                QUrl(f"{probe['base_url'].rstrip('/')}/chat/completions")
            )
            request.setHeader(
                QNetworkRequest.KnownHeaders.ContentTypeHeader, "application/json"
            )
            request.setRawHeader(b"Authorization", f"Bearer {probe['api_key']}".encode())
            request.setTransferTimeout(30000)
            reply = self._http.post(request, QByteArray(json.dumps(body).encode()))
            self._probe_replies.append(reply)
            reply.finished.connect(self._on_probe_reply)

    def _set_frozen(self, frozen: bool) -> None:
        """校验期间整页冻结并显示遮罩，保证任何操作都不可用，完成后恢复。"""
        self.text_page.setEnabled(not frozen)
        self.vlm_page.setEnabled(not frozen)
        if frozen:
            self._overlay.setGeometry(self.rect())
            self._overlay.raise_()
            self._overlay.show()
            self._overlay.setFocus()
            self.prev_btn.setEnabled(False)
            self.next_btn.setEnabled(False)
        else:
            self._overlay.hide()
            index = self._page_kinds.index(self._current_kind)
            self.prev_btn.setVisible(index > 0)
            self.prev_btn.setEnabled(index > 0)
            self.next_btn.setEnabled(self._next_enabled())

    def resizeEvent(self, event: QResizeEvent) -> None:
        """窗口尺寸变化时让遮罩始终覆盖整个客户区。"""
        super().resizeEvent(event)
        if self._overlay.isVisible():
            self._overlay.setGeometry(self.rect())

    def _on_probe_reply(self) -> None:
        """全部探测请求结束时汇总错误；被取消的请求不视为校验失败。"""
        if not all(r.isFinished() for r in self._probe_replies):
            return
        errors = []
        for reply, probe in zip(self._probe_replies, self._probe_configs):
            if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
                continue
            if reply.error() != QNetworkReply.NetworkError.NoError:
                errors.append(
                    _friendly_probe_error(
                        probe["name"],
                        Exception(f"网络请求失败: {reply.errorString()}"),
                    )
                )
                continue
        
            status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
            if status != 200:
                errors.append(
                    _friendly_probe_error(
                        probe["name"],
                        Exception(f"非预期响应：HTTP {status} - {reply.errorString()}"),
                    )
                )
                continue

            try:
                raw_data = bytes(reply.readAll())
                if not raw_data:
                    raise ValueError("响应体为空")
                data = json.loads(raw_data)

                if not isinstance(data, dict):
                    raise ValueError("响应体不是 JSON 对象")
                if "error" in data:
                    raise ValueError(f"响应体包含错误字段: {data['error']}")
                if "choices" not in data or not isinstance(data["choices"], list) or not data["choices"]:
                    raise ValueError("响应体缺少 choices 字段或格式不正确")
            except (json.JSONDecodeError, ValueError) as exc:
                errors.append(
                    _friendly_probe_error(
                        probe["name"],
                        Exception(f"响应体解析失败: {exc}"),
                    )
                )
                continue

        self._probe_replies = []
        self._probe_configs = []
        self._set_frozen(False)
        if errors:
            self.status_label.setText("配置校验失败")
            QMessageBox.critical(self, "配置校验失败", "\n".join(errors))
            return
        cfg, on_success = self._pending_save or ({}, None)
        self._pending_save = None
        self._finish_module_save(cfg, on_success=on_success)

    def _finish_module_save(self, cfg: dict, on_success=None) -> None:
        """把当前页配置快照写入本地凭据；加密失败需二次确认明文保存。"""
        api_key = cfg["api_key"]
        kind = cfg["kind"]
        provider = cfg["provider"]
        model = cfg["model"]
        base_url = resolve_provider_base_url(provider, presets=self._llm_providers)
        params = cfg["params"]
        if kind == "text":
            ok = credential.save_llm_config(
                api_key, provider, model, base_url,
                params,
            )
        else:
            ok = credential.save_vlm_config(
                api_key, provider, model, base_url,
                params,
            )
        if not ok:
            # key 加密失败：二次确认后以明文整份重写
            ret = QMessageBox.question(
                self,
                "加密失败",
                "当前环境无法加密保存 API Key（非 Windows 或系统加密不可用）。\n"
                "如果继续保存，对应的 key 将以明文形式存储在本机文件中。\n\n"
                "是否仍然保存？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
            if kind == "text":
                credential.save_llm_config(
                    api_key, provider, model, base_url,
                    params, allow_plaintext=True,
                )
            else:
                credential.save_vlm_config(
                    api_key, provider, model, base_url,
                    params, allow_plaintext=True,
                )

        configured = bool(api_key) and bool(provider) and bool(model)

        QMessageBox.information(self, "成功", f"{cfg['name']}设置已保存")
        self.status_label.setText(f"{cfg['name']}设置已保存")
        if on_success:
            on_success()
