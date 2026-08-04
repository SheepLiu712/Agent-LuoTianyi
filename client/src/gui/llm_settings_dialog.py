"""LLM 模型设置对话框 - 独立的模型配置设置页。"""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
                               QPushButton, QComboBox, QMessageBox)
from PySide6.QtCore import Qt, QTimer, QThread, Signal
from typing import TYPE_CHECKING

from ..utils.logger import get_logger
from ..safety import credential
from ..utils.llm_client import fetch_provider_models, resolve_provider_base_url

if TYPE_CHECKING:
    from ..network.network_client import NetworkClient


class _ModelsLoader(QThread):
    """后台线程：调用模型列表接口，避免阻塞 UI。"""

    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, base_url: str, api_key: str, parent=None):
        super().__init__(parent)
        self._base_url = base_url
        self._api_key = api_key

    def run(self) -> None:
        try:
            models = fetch_provider_models(self._base_url, self._api_key)
            self.loaded.emit(models)
        except Exception as exc:
            self.failed.emit(str(exc))


class _ProvidersLoader(QThread):
    """后台线程：从服务端获取 LLM 服务商预设列表，避免阻塞 UI。"""

    loaded = Signal(list)
    failed = Signal(str)

    def __init__(self, network_client, force_refresh: bool = False, parent=None):
        super().__init__(parent)
        self._network_client = network_client
        self._force_refresh = force_refresh

    def run(self) -> None:
        try:
            providers = self._network_client.get_llm_providers(
                force_refresh=self._force_refresh
            )
            self.loaded.emit(providers)
        except Exception as exc:
            self.failed.emit(str(exc))


class LLMSettingsDialog(QDialog):
    """独立的 LLM 模型设置窗口：服务商 / API Key / 模型。"""

    def __init__(self, network_client: "NetworkClient", parent=None):
        super().__init__(parent)
        self.logger = get_logger(self.__class__.__name__)
        self.network_client = network_client
        self.setWindowTitle("LLM 模型设置")
        self.setMinimumSize(520, 460)
        self.setModal(True)

        self._llm_providers: list = []
        self._saved_provider: str | None = None
        self._saved_model: str | None = None
        self._models_timer = QTimer(self)
        self._models_timer.setSingleShot(True)
        self._models_timer.setInterval(800)
        self._models_timer.timeout.connect(self._refresh_llm_models)
        self._models_loader: "_ModelsLoader | None" = None
        self._providers_loader: "_ProvidersLoader | None" = None

        self._init_ui()
        self._load_config()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(12)
        layout.setContentsMargins(24, 20, 24, 20)

        title = QLabel("LLM 模型设置")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #66CCFF;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "填写自己的 LLM API Key 后，聊天会由本客户端直接调用大模型。"
            "key 只保存在本机，不会上传服务器。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #666;")
        layout.addWidget(desc)

        provider_label = QLabel("服务商：")
        provider_label.setStyleSheet("font-size: 14px; font-weight: 500; margin-top: 8px;")
        layout.addWidget(provider_label)

        provider_row = QHBoxLayout()
        provider_row.setSpacing(8)
        self.provider_combo = QComboBox()
        self.provider_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_row.addWidget(self.provider_combo, 1)
        self.refresh_providers_btn = QPushButton("刷新")
        self.refresh_providers_btn.setStyleSheet("font-size: 13px; padding: 6px 12px;")
        self.refresh_providers_btn.clicked.connect(self._refresh_providers)
        provider_row.addWidget(self.refresh_providers_btn)
        layout.addLayout(provider_row)

        key_label = QLabel("LLM API Key：")
        key_label.setStyleSheet("font-size: 14px; font-weight: 500; margin-top: 8px;")
        layout.addWidget(key_label)

        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("填写后自动获取可用模型列表")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_input.setStyleSheet("font-size: 14px; padding: 6px;")
        self.api_key_input.textChanged.connect(self._on_api_key_changed)
        layout.addWidget(self.api_key_input)

        model_label = QLabel("模型：")
        model_label.setStyleSheet("font-size: 14px; font-weight: 500; margin-top: 8px;")
        layout.addWidget(model_label)

        self.model_combo = QComboBox()
        self.model_combo.setPlaceholderText("模型名称（从服务商接口获取）")
        self.model_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        layout.addWidget(self.model_combo)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.status_label)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(16)
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
            QPushButton:hover {
                background-color: #4AA8D8;
            }
        """)
        self.save_btn.clicked.connect(self.on_save)
        btn_layout.addWidget(self.save_btn)

        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _load_config(self) -> None:
        """从本地凭据加载已保存的配置，并从服务端拉取服务商列表。"""
        self._saved_provider = credential.get_provider()
        saved_model = credential.get_model()
        if saved_model:
            self._saved_model = saved_model
        saved_key = credential.get_api_key()
        if saved_key:
            self.api_key_input.setText(saved_key)
        self.status_label.setText("正在获取服务商列表…")
        self._providers_loader = _ProvidersLoader(self.network_client, parent=self)
        self._providers_loader.loaded.connect(self._on_providers_loaded)
        self._providers_loader.failed.connect(self._on_providers_failed)
        self._providers_loader.start()

    def _on_providers_loaded(self, providers: list) -> None:
        self._llm_providers = [p for p in providers if isinstance(p, dict)]
        self.provider_combo.clear()
        self.provider_combo.addItems([p["name"] for p in self._llm_providers])
        if not self._llm_providers:
            self.status_label.setText("服务端未配置 LLM 服务商")
            return
        if self._saved_provider:
            provider_index = self.provider_combo.findText(self._saved_provider)
            if provider_index >= 0:
                self.provider_combo.setCurrentIndex(provider_index)
        self.status_label.setText("")
        self._schedule_refresh_models()

    def _on_providers_failed(self, message: str) -> None:
        self.status_label.setText(f"获取服务商列表失败：{message}")

    def _refresh_providers(self) -> None:
        """强制重新拉取服务商列表。"""
        self.status_label.setText("正在获取服务商列表…")
        if self._providers_loader is not None and self._providers_loader.isRunning():
            self._providers_loader.terminate()
            self._providers_loader.wait(200)
        self._providers_loader = _ProvidersLoader(
            self.network_client,
            force_refresh=True,
            parent=self,
        )
        self._providers_loader.loaded.connect(self._on_providers_loaded)
        self._providers_loader.failed.connect(self._on_providers_failed)
        self._providers_loader.start()

    def _on_provider_changed(self, _index: int) -> None:
        self.model_combo.clear()
        self._schedule_refresh_models()

    def _on_api_key_changed(self, _text: str) -> None:
        self._schedule_refresh_models()

    def _schedule_refresh_models(self) -> None:
        self._models_timer.start()

    def _refresh_llm_models(self) -> None:
        """用当前服务商 + api-key 拉取模型列表并填充下拉框。"""
        api_key = self.api_key_input.text().strip()
        if not api_key:
            self.status_label.setText("填写 LLM API Key 后自动获取可用模型列表")
            return
        base_url = resolve_provider_base_url(
            self.provider_combo.currentText(),
            presets=self._llm_providers,
        )
        if not base_url:
            base_url = credential.get_provider_base_url() or ""
        if not base_url:
            self.status_label.setText("请先选择可用的服务商")
            return
        self.status_label.setText("正在获取模型列表…")
        if self._models_loader is not None and self._models_loader.isRunning():
            self._models_loader.terminate()
            self._models_loader.wait(200)
        self._models_loader = _ModelsLoader(base_url, api_key, self)
        self._models_loader.loaded.connect(self._on_models_loaded)
        self._models_loader.failed.connect(self._on_models_failed)
        self._models_loader.start()

    def _on_models_loaded(self, models: list) -> None:
        self.model_combo.clear()
        self.model_combo.addItems([str(m) for m in models])
        if self._saved_model and self._saved_model in [str(m) for m in models]:
            self.model_combo.setCurrentText(self._saved_model)
        elif self.model_combo.count() > 0:
            self.model_combo.setCurrentIndex(0)
        self.status_label.setText(f"已获取 {len(models)} 个可用模型")

    def _on_models_failed(self, message: str) -> None:
        self.status_label.setText(f"获取模型列表失败：请检查api-key是否正确")

    def on_save(self) -> None:
        provider = self.provider_combo.currentText().strip()
        if not provider:
            QMessageBox.warning(self, "提示", "服务商列表未加载，无法保存")
            return
        api_key = self.api_key_input.text().strip()
        if api_key and not credential.save_api_key(api_key):
            ret = QMessageBox.question(
                self,
                "加密失败",
                "当前环境无法加密保存 LLM API Key（非 Windows 或系统加密不可用）。\n"
                "如果继续保存，key 将以明文形式存储在本机文件中。\n\n"
                "是否仍然保存？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                return
            credential.save_api_key_plain(api_key)
        credential.save_provider(provider)
        credential.save_model(self.model_combo.currentText().strip())
        credential.save_provider_base_url(
            resolve_provider_base_url(provider, presets=self._llm_providers)
        )
        QMessageBox.information(self, "成功", "LLM 模型设置已保存")
        self.accept()
