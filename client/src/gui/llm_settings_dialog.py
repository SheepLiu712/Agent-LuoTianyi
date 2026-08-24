"""客户端 LLM/VLM 设置。

服务端只下发需求类型及能力约束；服务商、Base URL、模型和 API Key
均由用户在本机配置。保存配置时不访问服务商，实际调用失败后由服务端回退。
"""

import json
from typing import TYPE_CHECKING

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QCloseEvent
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkReply, QNetworkRequest
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..utils import llm_key_storage
from ..utils.logger import get_logger

if TYPE_CHECKING:
    from ..network.network_client import NetworkClient


_TYPES_TIMEOUT_MS = 15000
_HIGHLIGHT_STYLE = "border: 2px solid #E53935;"
_FIELD_NAMES = {
    "provider": "服务商名称",
    "base_url": "Base URL",
    "api_key": "API Key",
    "model": "模型名称",
    "params": "高级参数",
}


class LLMSettingsDialog(QDialog):
    """按服务端需求类型渲染客户端自定义模型配置。"""

    def __init__(self, network_client: "NetworkClient", parent=None):
        super().__init__(parent)
        self.logger = get_logger(self.__class__.__name__)
        self.network_client = network_client
        self.setWindowTitle("LLM 模型设置")
        self.setMinimumSize(680, 420)
        self.resize(720, 820)
        self.setModal(True)

        self._http = QNetworkAccessManager(self)
        self._http.setRedirectPolicy(QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        self._http.setAutoDeleteReplies(True)
        self._types_reply: "QNetworkReply | None" = None
        self._types: list[dict] = []
        self._modules: dict[str, dict] = {}
        self._chrome: int | None = None

        self._init_ui()
        self._start_fetch_types()

    def _init_ui(self) -> None:
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("LLM 模型设置")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #66CCFF;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "服务端只规定每类调用需要 LLM/VLM、JSON 和 thinking 中的哪些能力。"
            "服务商、Base URL、模型和 Key 完全由你配置，Key 不会上传服务器。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #666;")
        layout.addWidget(desc)

        header = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新需求列表")
        self.refresh_btn.clicked.connect(self._start_fetch_types)
        header.addStretch()
        header.addWidget(self.refresh_btn)
        layout.addLayout(header)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._cards_container = QWidget()
        self._cards_layout = QVBoxLayout(self._cards_container)
        self._cards_layout.setContentsMargins(0, 0, 0, 0)
        self._cards_layout.setSpacing(12)
        self._scroll.setWidget(self._cards_container)
        layout.addWidget(self._scroll)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        self.status_label.setStyleSheet("font-size: 12px; color: #888;")
        layout.addWidget(self.status_label)

        actions = QHBoxLayout()
        actions.addStretch()
        self.save_btn = QPushButton("保存")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._on_save)
        actions.addWidget(self.save_btn)
        layout.addLayout(actions)

    def _start_fetch_types(self) -> None:
        if self._types_reply is not None and not self._types_reply.isFinished():
            self._types_reply.abort()
        base = self.network_client.base_url.rstrip("/")
        request = QNetworkRequest(QUrl(f"{base}/llm/client-model-types"))
        request.setTransferTimeout(_TYPES_TIMEOUT_MS)
        self._types_reply = self._http.get(request)
        self._types_reply.finished.connect(self._on_types_reply)
        self.status_label.setText("正在获取模型需求…")
        self.save_btn.setEnabled(False)

    def _on_types_reply(self) -> None:
        reply = self.sender()
        if reply is None or reply is not self._types_reply:
            return
        self._types_reply = None
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self.status_label.setText(f"获取模型需求失败：{reply.errorString()}")
            return
        try:
            data = json.loads(bytes(reply.readAll()))
        except Exception as exc:
            self.status_label.setText(f"模型需求解析失败：{exc}")
            return
        raw_types = data.get("types") if isinstance(data, dict) else None
        if not isinstance(raw_types, list):
            self.status_label.setText("模型需求格式错误")
            return
        self._types = [item for item in raw_types if self._valid_type(item)]
        self._rebuild_cards()
        self._load_modules_from_storage()
        self.save_btn.setEnabled(bool(self._types))
        self.status_label.setText("" if self._types else "没有可配置的客户端模型需求")
        QTimer.singleShot(0, self._auto_resize)

    @staticmethod
    def _valid_type(item) -> bool:
        return (
            isinstance(item, dict)
            and bool(str(item.get("id") or "").strip())
            and bool(str(item.get("name") or "").strip())
            and str(item.get("model_kind") or "").lower() in {"llm", "vlm"}
        )

    def _clear_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._modules = {}

    def _rebuild_cards(self) -> None:
        self._clear_cards()
        for requirement in self._types:
            type_id = str(requirement["id"])
            self._modules[type_id] = self._build_type_card(requirement)

    def _build_type_card(self, requirement: dict) -> dict:
        name = str(requirement["name"])
        kind = str(requirement["model_kind"]).lower()
        card = QWidget()
        card.setObjectName("moduleCard")
        card.setStyleSheet(
            "QWidget#moduleCard { background: #F7F9FB; border: 1px solid #E0E6EC; border-radius: 8px; }"
        )
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(7)

        head = QHBoxLayout()
        title = QLabel(name)
        title.setStyleSheet("font-size: 15px; font-weight: 600; color: #333;")
        switch = QCheckBox("使用自己的 API Key")
        head.addWidget(title)
        head.addStretch()
        head.addWidget(switch)
        layout.addLayout(head)

        requirements = [kind.upper()]
        if requirement.get("requires_json"):
            requirements.append("需要 JSON")
        if requirement.get("requires_thinking"):
            requirements.append("需要 thinking")
        tag = QLabel("调用要求：" + " / ".join(requirements))
        tag.setStyleSheet("font-size: 12px; color: #4A789C;")
        layout.addWidget(tag)
        if requirement.get("description"):
            description = QLabel(str(requirement["description"]))
            description.setWordWrap(True)
            description.setStyleSheet("font-size: 12px; color: #888;")
            layout.addWidget(description)

        fields = QWidget()
        fields_layout = QVBoxLayout(fields)
        fields_layout.setContentsMargins(0, 0, 0, 0)
        provider_input = QLineEdit()
        provider_input.setPlaceholderText("服务商名称（自定义）")
        base_url_input = QLineEdit()
        base_url_input.setPlaceholderText("OpenAI-compatible Base URL，例如 https://example.com/v1")
        api_key_input = QLineEdit()
        api_key_input.setPlaceholderText("API Key")
        api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        model_input = QLineEdit()
        model_input.setPlaceholderText("模型名称（自定义）")
        params_editor = QPlainTextEdit()
        params_editor.setPlaceholderText('高级参数（JSON，可选），例如 {"temperature": 0.7}')
        params_editor.setMaximumHeight(90)
        for widget in (provider_input, base_url_input, api_key_input, model_input, params_editor):
            fields_layout.addWidget(widget)

        capabilities = QHBoxLayout()
        can_json = QCheckBox("此模型支持 JSON 输出")
        can_thinking = QCheckBox("此模型支持 thinking")
        capabilities.addWidget(can_json)
        capabilities.addWidget(can_thinking)
        capabilities.addStretch()
        fields_layout.addLayout(capabilities)
        layout.addWidget(fields)
        switch.toggled.connect(fields.setVisible)
        fields.hide()

        self._cards_layout.addWidget(card)
        return {
            "card": card,
            "name": name,
            "model_kind": kind,
            "switch": switch,
            "fields": fields,
            "provider_input": provider_input,
            "base_url_input": base_url_input,
            "api_key_input": api_key_input,
            "model_input": model_input,
            "params_editor": params_editor,
            "can_json": can_json,
            "can_thinking": can_thinking,
        }

    def _load_modules_from_storage(self) -> None:
        saved = llm_key_storage.get_llm_modules_config()
        for requirement in self._types:
            type_id = str(requirement["id"])
            name = str(requirement["name"])
            info = self._modules[type_id]
            entry = saved.get(type_id) or saved.get(name) or {}
            info["switch"].setChecked(bool(entry.get("enabled", False)))
            info["provider_input"].setText(str(entry.get("provider") or ""))
            info["base_url_input"].setText(str(entry.get("base_url") or ""))
            info["api_key_input"].setText(str(entry.get("api_key") or ""))
            info["model_input"].setText(str(entry.get("model") or ""))
            params = entry.get("params") or {}
            if params:
                info["params_editor"].setPlainText(json.dumps(params, ensure_ascii=False, indent=2))
            caps = entry.get("model_capabilities") or {}
            info["can_json"].setChecked(bool(caps.get("can_use_json", False)))
            info["can_thinking"].setChecked(bool(caps.get("can_enable_thinking", False)))
            info["fields"].setVisible(info["switch"].isChecked())

    def _collect_form_modules(self) -> dict:
        modules = {}
        for type_id, info in self._modules.items():
            modules[type_id] = {
                "enabled": info["switch"].isChecked(),
                "provider": info["provider_input"].text().strip(),
                "base_url": info["base_url_input"].text().strip().rstrip("/"),
                "api_key": info["api_key_input"].text().strip(),
                "model": info["model_input"].text().strip(),
                "model_kind": info["model_kind"],
                "model_capabilities": {
                    "can_use_json": info["can_json"].isChecked(),
                    "can_enable_thinking": info["can_thinking"].isChecked(),
                },
                "params_text": info["params_editor"].toPlainText().strip(),
            }
        return modules

    def _precheck(self, modules: dict) -> tuple[str, str] | None:
        for type_id, entry in modules.items():
            if not entry["enabled"]:
                continue
            for field in ("provider", "base_url", "api_key", "model"):
                if not entry[field]:
                    return type_id, field
            if entry["params_text"]:
                try:
                    if not isinstance(json.loads(entry["params_text"]), dict):
                        return type_id, "params"
                except json.JSONDecodeError:
                    return type_id, "params"
        return None

    def _on_save(self) -> None:
        modules = self._collect_form_modules()
        missing = self._precheck(modules)
        if missing:
            type_id, field = missing
            info = self._modules[type_id]
            widget = info[f"{field}_input"] if field != "params" else info["params_editor"]
            widget.setStyleSheet(_HIGHLIGHT_STYLE)
            self._scroll.ensureWidgetVisible(info["card"], 0, 120)
            message = (
                f"类型「{info['name']}」缺少 {_FIELD_NAMES[field]}，请补全后重试。"
                if field != "params"
                else f"类型「{info['name']}」的高级参数不是合法 JSON。"
            )
            QMessageBox.warning(self, "配置不完整", message)
            return
        self._write_modules(modules)

    def _write_modules(self, modules: dict) -> None:
        to_save = {}
        for type_id, entry in modules.items():
            params = json.loads(entry["params_text"]) if entry["params_text"] else {}
            to_save[type_id] = {
                **{
                    key: entry[key]
                    for key in (
                        "enabled",
                        "provider",
                        "model",
                        "base_url",
                        "model_kind",
                        "model_capabilities",
                        "api_key",
                    )
                },
                "params": params,
            }
        ok = llm_key_storage.save_llm_modules_config(to_save)
        if not ok:
            ret = QMessageBox.question(
                self,
                "加密失败",
                "API Key 无法加密保存。\n是否以明文形式保存在本机？",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if ret != QMessageBox.StandardButton.Yes:
                self.status_label.setText("保存已取消（Key 未保存）")
                return
            ok = llm_key_storage.save_llm_modules_config(to_save, allow_plaintext=True)
        if not ok:
            self.status_label.setText("保存失败，请重试")
            return
        self.status_label.setText("配置已保存；实际调用失败时会自动回退服务端模型")
        QMessageBox.information(self, "保存成功", "配置已保存")

    def _auto_resize(self) -> None:
        if not self._cards_layout.count():
            return
        content_h = self._cards_layout.sizeHint().height()
        if self._chrome is None:
            self._chrome = max(0, self.height() - self._scroll.height())
        target_h = max(self._chrome + 40, min(content_h + self._chrome, 900))
        if abs(target_h - self.height()) > 8:
            self.resize(self.width(), target_h)

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._types_reply is not None and not self._types_reply.isFinished():
            self._types_reply.abort()
        event.accept()
