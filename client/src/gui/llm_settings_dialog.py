"""LLM 模型设置对话框 - 对话模型与图片理解模型分别配置（Tab 切换）。"""

import json

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QComboBox, QMessageBox, QGroupBox,
                               QPlainTextEdit, QTabWidget, QWidget, QCheckBox,
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
    """对话模型与图片理解模型分开配置（Tab 切换，设置项对齐）。"""

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
        self.vlm_provider_combo.currentIndexChanged.connect(self._on_vlm_provider_changed)
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

        self.tabs = QTabWidget()
        self.tabs.setStyleSheet("QTabBar::tab { font-size: 14px; padding: 8px 20px; }")

        text_tab = QWidget()
        text_layout = QVBoxLayout(text_tab)
        (self.provider_combo, self.api_key_input, self.model_combo, self.base_url_hint,
         self.params_editor, self.enable_thinking_check, self.use_json_check) = self._build_form(text_layout, "对话")

        vlm_tab = QWidget()
        vlm_layout = QVBoxLayout(vlm_tab)
        (self.vlm_provider_combo, self.vlm_api_key_input, self.vlm_model_combo,
         self.vlm_base_url_hint, self.vlm_params_editor,
         self.vlm_enable_thinking_check, self.vlm_use_json_check) = self._build_form(vlm_layout, "图片理解")

        self.tabs.addTab(text_tab, "对话模型")
        self.tabs.addTab(vlm_tab, "图片理解模型")
        layout.addWidget(self.tabs)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.status_label)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.save_btn = QPushButton("保存")
        self.save_btn.setStyleSheet("""
            QPushButton {
                background-color: #5BB8E8;
                color: white;
                border: none;
                padding: 12px 24px;
                border-radius: 8px;
                font-size: 14px;
            }
            QPushButton:hover { background-color: #4AA8D8; }
        """)
        self.save_btn.clicked.connect(self.on_save)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

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
            lambda checked=False, edit=api_key_input: edit.setText(
                QApplication.clipboard().text()
            )
        )
        key_row.addWidget(paste_btn)
        layout.addLayout(key_row)

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

    def _on_providers_loaded(self, providers: list) -> None:
        self._llm_providers = [p for p in providers if isinstance(p, dict)]
        all_names = [p["name"] for p in self._llm_providers]
        vlm_names = [p["name"] for p in self._llm_providers if p.get("vlm_models")]
        self.provider_combo.clear()
        self.provider_combo.addItems(all_names)
        self.vlm_provider_combo.clear()
        self.vlm_provider_combo.addItems(vlm_names)
        if not all_names:
            self.status_label.setText("服务端未配置 LLM 服务商")
            return
        text_index = self.provider_combo.findText(self._saved_provider or "")
        if text_index >= 0:
            self.provider_combo.setCurrentIndex(text_index)
        vlm_index = self.vlm_provider_combo.findText(self._saved_vlm_provider or "")
        if vlm_index >= 0:
            self.vlm_provider_combo.setCurrentIndex(vlm_index)
        self.status_label.setText("")
        self._on_provider_changed(self.provider_combo.currentIndex())
        self._on_vlm_provider_changed(self.vlm_provider_combo.currentIndex())

    def _on_providers_failed(self, message: str) -> None:
        self.status_label.setText(f"获取服务商列表失败：{message}")

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

    def on_save(self) -> None:
        text_params = self._parse_params(self.params_editor)
        if text_params is None:
            return
        vlm_params = self._parse_params(self.vlm_params_editor)
        if vlm_params is None:
            return

        probe_configs = []
        api_key = self.api_key_input.text().strip()
        text_provider = self.provider_combo.currentText().strip()
        if api_key and text_provider and self.model_combo.currentText().strip():
            probe_configs.append(
                {
                    "name": "对话模型",
                    "base_url": resolve_provider_base_url(
                        text_provider, presets=self._llm_providers
                    ),
                    "api_key": api_key,
                    "model": self.model_combo.currentText().strip(),
                    "flags": {
                        "enable_thinking": self.enable_thinking_check.isChecked(),
                        "use_json": self.use_json_check.isChecked(),
                    },
                    "params": text_params,
                }
            )
        vlm_api_key = self.vlm_api_key_input.text().strip()
        vlm_provider = self.vlm_provider_combo.currentText().strip()
        if vlm_api_key and vlm_provider and self.vlm_model_combo.currentText().strip():
            probe_configs.append(
                {
                    "name": "图片理解模型",
                    "base_url": resolve_provider_base_url(
                        vlm_provider, presets=self._llm_providers
                    ),
                    "api_key": vlm_api_key,
                    "model": self.vlm_model_combo.currentText().strip(),
                    "flags": {
                        "enable_thinking": self.vlm_enable_thinking_check.isChecked(),
                        "use_json": self.vlm_use_json_check.isChecked(),
                    },
                    "params": vlm_params,
                }
            )

        if not probe_configs:
            self._finish_save(text_params, vlm_params)
            return

        self._pending_save = (text_params, vlm_params)
        self.save_btn.setEnabled(False)
        self.status_label.setText("正在校验配置…")
        self._probe_worker = _ProbeWorker(probe_configs, parent=self)
        self._probe_worker.errors.connect(self._on_probe_done)
        self._probe_worker.start()

    def _on_probe_done(self, errors: list) -> None:
        self.save_btn.setEnabled(True)
        if errors:
            self.status_label.setText("配置校验失败")
            QMessageBox.critical(self, "配置校验失败", "\n".join(errors))
            return
        text_params, vlm_params = self._pending_save or ({}, {})
        self._finish_save(text_params, vlm_params)

    def _finish_save(self, text_params: dict, vlm_params: dict) -> None:
        api_key = self.api_key_input.text().strip()
        vlm_api_key = self.vlm_api_key_input.text().strip()
        text_key_failed = bool(api_key) and not credential.save_api_key(api_key)
        vlm_key_failed = bool(vlm_api_key) and not credential.save_vlm_api_key(vlm_api_key)
        if text_key_failed or vlm_key_failed:
            ret = QMessageBox.question(
                self,
                "加密失败",
                "当前环境无法加密保存部分 API Key（非 Windows 或系统加密不可用）。\n"
                "如果继续保存，对应的 key 将以明文形式存储在本机文件中。\n\n"
                "是否仍然保存？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
            if text_key_failed:
                credential.save_api_key_plain(api_key)
            if vlm_key_failed:
                credential.save_vlm_api_key_plain(vlm_api_key)

        text_provider = self.provider_combo.currentText().strip()
        vlm_provider = self.vlm_provider_combo.currentText().strip()
        text_configured = bool(api_key) and bool(text_provider) and bool(
            self.model_combo.currentText().strip()
        )
        vlm_configured = bool(vlm_api_key) and bool(vlm_provider) and bool(
            self.vlm_model_combo.currentText().strip()
        )
        # 仅校验已配置的模块，未配置的模块不要求服务商，避免一个模块影响另一个
        if text_configured and not text_provider:
            QMessageBox.warning(self, "提示", "对话服务商列表未加载，无法保存")
            return
        if vlm_configured and not vlm_provider:
            QMessageBox.warning(self, "提示", "图片理解服务商列表未加载，无法保存")
            return

        credential.save_provider(text_provider)
        credential.save_model(self.model_combo.currentText().strip())
        credential.save_provider_base_url(
            resolve_provider_base_url(text_provider, presets=self._llm_providers)
        )
        credential.save_llm_params(text_params)
        credential.save_llm_flags(
            self.enable_thinking_check.isChecked(),
            self.use_json_check.isChecked(),
        )

        credential.save_vlm_provider(vlm_provider)
        credential.save_vlm_model(self.vlm_model_combo.currentText().strip())
        credential.save_vlm_provider_base_url(
            resolve_provider_base_url(vlm_provider, presets=self._llm_providers)
        )
        credential.save_vlm_params(vlm_params)
        credential.save_vlm_flags(
            self.vlm_enable_thinking_check.isChecked(),
            self.vlm_use_json_check.isChecked(),
        )

        prompt_parts = []
        if text_configured and not self.use_json_check.isChecked() and self._llm_json_modules:
            prompt_parts.append(
                "对话模型未勾选“支持 JSON 输出”，以下功能将改用服务端 API 执行：\n"
                + "、".join(sorted(set(self._llm_json_modules)))
            )
        if vlm_configured and not self.vlm_use_json_check.isChecked() and self._vlm_json_modules:
            prompt_parts.append(
                "图片理解模型未勾选“支持 JSON 输出”，以下功能将改用服务端 API 执行：\n"
                + "、".join(sorted(set(self._vlm_json_modules)))
            )
        if prompt_parts:
            QMessageBox.information(self, "提示", "\n\n".join(prompt_parts))

        QMessageBox.information(self, "成功", "LLM 模型设置已保存")
        self.accept()
