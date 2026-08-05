"""LLM 模型设置对话框 - 对话模型与图片理解模型分页配置，每页独立保存。"""

import json

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QComboBox, QMessageBox, QGroupBox,
                               QPlainTextEdit, QStackedWidget, QWidget, QCheckBox,
                               QApplication)
from PySide6.QtCore import Qt, QThread, Signal
from typing import TYPE_CHECKING

from ..utils.logger import get_logger
from ..safety import credential
from ..utils.llm_client import (
    fetch_llm_json_required_modules,
    probe_llm_config,
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


class _ProvidersLoader(QThread):
    """后台线程：从服务端获取服务商预设列表，避免阻塞 UI。"""

    loaded = Signal(list)
    json_loaded = Signal(list, list)
    failed = Signal(str)

    def __init__(self, network_client, force_refresh: bool = False, parent=None):
        super().__init__(parent)
        self._network_client = network_client
        self._force_refresh = force_refresh
        self.logger = get_logger(self.__class__.__name__)

    def run(self) -> None:
        try:
            providers = self._network_client.get_llm_providers(
                force_refresh=self._force_refresh
            )
            self.loaded.emit(providers)
            try:
                llm_modules, vlm_modules = fetch_llm_json_required_modules(
                    self._network_client.base_url
                )
            except Exception as exc:
                self.logger.warning(f"获取 JSON 功能列表失败: {exc}")
                llm_modules, vlm_modules = [], []
            self.json_loaded.emit(llm_modules, vlm_modules)
        except Exception as exc:
            self.failed.emit(str(exc))


class _ProbeWorker(QThread):
    """后台线程：保存前用当前配置向服务商发探测请求。"""

    errors = Signal(list)

    def __init__(self, configs: list, parent=None):
        super().__init__(parent)
        self._configs = configs

    def run(self) -> None:
        errors = []
        for cfg in self._configs:
            try:
                probe_llm_config(
                    cfg["base_url"],
                    cfg["api_key"],
                    cfg["model"],
                    flags=cfg["flags"],
                    params=cfg["params"],
                )
            except Exception as exc:
                errors.append(_friendly_probe_error(cfg["name"], exc))
        self.errors.emit(errors)


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
        self._providers_loader: "_ProvidersLoader | None" = None
        self._probe_worker: "_ProbeWorker | None" = None
        self._pending_save: tuple | None = None

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
         self.params_editor, self.enable_thinking_check, self.use_json_check) = self._build_form(text_layout, "对话")

        vlm_tab = QWidget()
        vlm_layout = QVBoxLayout(vlm_tab)
        vlm_layout.setContentsMargins(0, 0, 0, 0)
        (self.vlm_provider_combo, self.vlm_api_key_input, self.vlm_model_combo,
         self.vlm_base_url_hint, self.vlm_params_editor,
         self.vlm_enable_thinking_check, self.vlm_use_json_check) = self._build_form(vlm_layout, "图片理解")

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

    def _go_to_page(self, index: int) -> None:
        """翻页：切换当前配置页并同步导航按钮。"""
        index = 0 if index <= 0 else 1
        self.stack.setCurrentIndex(index)
        self.page_label.setText(
            "1 / 2 · 对话模型" if index == 0 else "2 / 2 · 图片理解模型"
        )
        # 第 1 页不显示“上一步”，与 APP 一致
        self.prev_btn.setVisible(index == 1)
        self.prev_btn.setEnabled(index == 1)
        self.next_btn.setText("下一步" if index == 0 else "完成")
        self._update_page_status()
        self._update_config_hint()

    def _update_page_status(self) -> None:
        """按当前页可用项更新状态提示（与 APP 的空列表提示一致）。"""
        index = self.stack.currentIndex()
        if index == 1 and not any(
            p.get("vlm_models") for p in self._llm_providers
        ):
            self.status_label.setText("当前服务端没有支持图片理解的模型")
        else:
            self.status_label.setText("")

    def _can_advance(self) -> bool:
        """当前页下拉框有可用项时才允许继续（拉取失败/无模型时禁用）。"""
        index = self.stack.currentIndex()
        return (self.model_combo if index == 0 else self.vlm_model_combo).count() > 0

    def _next_enabled(self) -> bool:
        """下一步可用：下拉框有项，或旧配置完整且与当前填写一致。"""
        index = self.stack.currentIndex()
        return self._can_advance() or self._has_unchanged_saved_config(index)

    def _has_unchanged_saved_config(self, index: int) -> bool:
        """已保存配置完整且当前填写与之一致（任意情况下直接翻页不保存）。"""
        if index == 0:
            saved_key = credential.get_api_key()
            saved_provider = credential.get_provider()
            saved_model = credential.get_model()
            current_key = self.api_key_input.text().strip()
            current_provider = self.provider_combo.currentText().strip()
            current_model = self.model_combo.currentText().strip()
            flags_match = (
                self.enable_thinking_check.isChecked()
                == credential.get_llm_flags().get("enable_thinking", False)
                and self.use_json_check.isChecked()
                == credential.get_llm_flags().get("use_json", False)
            )
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
            flags_match = (
                self.vlm_enable_thinking_check.isChecked()
                == credential.get_vlm_flags().get("enable_thinking", False)
                and self.vlm_use_json_check.isChecked()
                == credential.get_vlm_flags().get("use_json", False)
            )
            params_match = self._params_match(
                self.vlm_params_editor, credential.get_vlm_params()
            )
        if not (saved_key and saved_provider and saved_model):
            return False
        if current_key != saved_key or not flags_match or not params_match:
            return False
        # 列表未加载时下拉框为空，无法比较服务商/模型，视为一致
        if (self.model_combo if index == 0 else self.vlm_model_combo).count() > 0:
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

        flags_hint = QLabel(
            "思考：仅模型支持思考参数时勾选；JSON：未勾选时相关功能改用服务端 API。"
        )
        flags_hint.setWordWrap(True)
        flags_hint.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(flags_hint)

        enable_thinking_check = QCheckBox("支持思考模式")
        enable_thinking_check.setStyleSheet("font-size: 13px;")
        layout.addWidget(enable_thinking_check)

        use_json_check = QCheckBox("支持 JSON 输出")
        use_json_check.setStyleSheet("font-size: 13px;")
        layout.addWidget(use_json_check)

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
            enable_thinking_check,
            use_json_check,
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
        text_flags = credential.get_llm_flags()
        self.enable_thinking_check.setChecked(text_flags.get("enable_thinking", False))
        self.use_json_check.setChecked(text_flags.get("use_json", False))
        vlm_flags = credential.get_vlm_flags()
        self.vlm_enable_thinking_check.setChecked(vlm_flags.get("enable_thinking", False))
        self.vlm_use_json_check.setChecked(vlm_flags.get("use_json", False))

        self.status_label.setText("正在获取服务商列表…")
        self._providers_loader = _ProvidersLoader(self.network_client, parent=self)
        self._providers_loader.loaded.connect(self._on_providers_loaded)
        self._providers_loader.json_loaded.connect(self._on_json_modules_loaded)
        self._providers_loader.failed.connect(self._on_providers_failed)
        self._providers_loader.start()
        self._update_config_hint()
        self.next_btn.setEnabled(self._next_enabled())

    def _on_providers_loaded(self, providers: list) -> None:
        self._llm_providers = [p for p in providers if isinstance(p, dict)]
        all_names = [p["name"] for p in self._llm_providers]
        vlm_names = [p["name"] for p in self._llm_providers if p.get("vlm_models")]
        previous_text = self.provider_combo.currentText().strip()
        previous_vlm_text = self.vlm_provider_combo.currentText().strip()
        self.provider_combo.clear()
        self.provider_combo.addItems(all_names)
        self.provider_combo.setPlaceholderText("请选择服务商")
        self.vlm_provider_combo.clear()
        self.vlm_provider_combo.addItems(vlm_names)
        self.vlm_provider_combo.setPlaceholderText("请选择服务商")
        if not all_names:
            self.status_label.setText("暂无可用的服务商（请确认服务端已配置）")
            self._update_config_hint()
            return
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
        self._update_page_status()
        self._update_config_hint()

    def _on_providers_failed(self, message: str) -> None:
        self.status_label.setText(f"获取服务商列表失败：{message}")
        self._update_config_hint()

    def _refresh_providers(self) -> None:
        self.status_label.setText("正在获取服务商列表…")
        if self._providers_loader is not None and self._providers_loader.isRunning():
            self._providers_loader.terminate()
            self._providers_loader.wait(200)
        self._providers_loader = _ProvidersLoader(
            self.network_client, force_refresh=True, parent=self
        )
        self._providers_loader.loaded.connect(self._on_providers_loaded)
        self._providers_loader.json_loaded.connect(self._on_json_modules_loaded)
        self._providers_loader.failed.connect(self._on_providers_failed)
        self._providers_loader.start()

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
                "flags": {
                    "enable_thinking": self.enable_thinking_check.isChecked(),
                    "use_json": self.use_json_check.isChecked(),
                },
                "params": params,
                "json_modules": self._llm_json_modules,
                "use_json_checked": self.use_json_check.isChecked(),
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
            "flags": {
                "enable_thinking": self.vlm_enable_thinking_check.isChecked(),
                "use_json": self.vlm_use_json_check.isChecked(),
            },
            "params": params,
            "json_modules": self._vlm_json_modules,
            "use_json_checked": self.vlm_use_json_check.isChecked(),
        }

    def _on_advance(self) -> None:
        """下一步/完成：配置未修改直接翻页；否则保存（key 未填先弹窗确认）。"""
        index = self.stack.currentIndex()
        # 旧配置完整且未修改：任意情况下直接翻页/关闭，不执行保存
        if self._has_unchanged_saved_config(index):
            self._advance_or_close(index)
            return
        if not self._can_advance():
            return
        cfg = self._build_cfg("text" if index == 0 else "vlm")
        if cfg is None:
            return
        if cfg["api_key"]:
            self._save_page(cfg, on_success=lambda: self._advance_or_close(index))
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
        self._advance_or_close(index)

    def _clear_saved_module(self, kind: str) -> bool:
        """清空该模块已保存的配置，使相关调用使用服务端 Key；返回是否清空成功。"""
        if kind == "text":
            credential.save_api_key("")
            credential.save_provider("")
            credential.save_model("")
            credential.save_provider_base_url("")
            credential.save_llm_params({})
            credential.save_llm_flags(False, False)
            return not (
                credential.get_api_key()
                or credential.get_provider()
                or credential.get_model()
            )
        credential.save_vlm_api_key("")
        credential.save_vlm_provider("")
        credential.save_vlm_model("")
        credential.save_vlm_provider_base_url("")
        credential.save_vlm_params({})
        credential.save_vlm_flags(False, False)
        return not (
            credential.get_vlm_api_key()
            or credential.get_vlm_provider()
            or credential.get_vlm_model()
        )

    def _update_config_hint(self) -> None:
        """按当前页 API Key 填写情况更新提示：未填 key 则使用服务端 Key。"""
        index = self.stack.currentIndex()
        api_key = (
            self.api_key_input.text().strip()
            if index == 0
            else self.vlm_api_key_input.text().strip()
        )
        if api_key:
            self.config_hint.setText("")
        else:
            self.config_hint.setText("未配置 API Key，相关调用将使用服务端 Key。")
        if self._probe_worker is None or not self._probe_worker.isRunning():
            self.next_btn.setEnabled(self._next_enabled())

    def _advance_or_close(self, index: int) -> None:
        """保存/跳过后的落点：第 1 页进入第 2 页，第 2 页关闭。"""
        if index == 0:
            self._go_to_page(1)
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
                        "flags": cfg["flags"],
                        "params": cfg["params"],
                    }
                )
        if not probe_configs:
            self._finish_module_save(cfg, on_success=on_success)
            return
        self._pending_save = (cfg, on_success)
        self.prev_btn.setEnabled(False)
        self.next_btn.setEnabled(False)
        self.status_label.setText("正在校验配置…")
        self._probe_worker = _ProbeWorker(probe_configs, parent=self)
        self._probe_worker.errors.connect(self._on_probe_done)
        self._probe_worker.start()

    def _on_probe_done(self, errors: list) -> None:
        index = self.stack.currentIndex()
        self.prev_btn.setEnabled(index == 1)
        self.next_btn.setEnabled(self._next_enabled())
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
        if kind == "text":
            save_key = credential.save_api_key
            save_key_plain = credential.save_api_key_plain
        else:
            save_key = credential.save_vlm_api_key
            save_key_plain = credential.save_vlm_api_key_plain
        if api_key:
            if not save_key(api_key):
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
                save_key_plain(api_key)
        else:
            # 未填 key：清空已保存的 key，与“未填项将被清空”的提示保持一致
            save_key("")

        provider = cfg["provider"]
        model = cfg["model"]
        configured = bool(api_key) and bool(provider) and bool(model)

        if kind == "text":
            credential.save_provider(provider)
            credential.save_model(model)
            credential.save_provider_base_url(
                resolve_provider_base_url(provider, presets=self._llm_providers)
            )
            credential.save_llm_params(cfg["params"])
            credential.save_llm_flags(
                cfg["flags"]["enable_thinking"],
                cfg["flags"]["use_json"],
            )
        else:
            credential.save_vlm_provider(provider)
            credential.save_vlm_model(model)
            credential.save_vlm_provider_base_url(
                resolve_provider_base_url(provider, presets=self._llm_providers)
            )
            credential.save_vlm_params(cfg["params"])
            credential.save_vlm_flags(
                cfg["flags"]["enable_thinking"],
                cfg["flags"]["use_json"],
            )

        if configured and not cfg["use_json_checked"] and cfg["json_modules"]:
            QMessageBox.information(
                self,
                "提示",
                f"{cfg['name']}未勾选“支持 JSON 输出”，以下功能将改用服务端 API 执行：\n"
                + "、".join(sorted(set(cfg["json_modules"]))),
            )

        self.status_label.setText(f"{cfg['name']}设置已保存")
        if on_success:
            on_success()
