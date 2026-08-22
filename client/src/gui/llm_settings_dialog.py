"""LLM 模型设置对话框 - 按服务端下发的客户端模型类型渲染卡片，全局保存。

类型字典由服务端 /llm/providers 生成（type -> providers[base_url, models[勾选]]），
每个类型一张卡片：服务商下拉、baseURL 提示、API Key、模型下拉、高级参数。
保存时对开启的类型并行校验 /models，全部通过后一次性原子写入本地配置，
键为类型名；并把所选模型的 thinking/json 勾选复制为本地能力快照，
供运行时按服务端门控逻辑附加 enable_thinking / response_format。
"""

import json

from PySide6.QtWidgets import (
    QDialog,
    QVBoxLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QComboBox,
    QMessageBox,
    QPlainTextEdit,
    QScrollArea,
    QWidget,
    QCheckBox,
)
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtGui import QCloseEvent
from typing import TYPE_CHECKING

from ..utils.logger import get_logger
from ..utils import llm_key_storage

if TYPE_CHECKING:
    from ..network.network_client import NetworkClient


_PROVIDERS_TIMEOUT_MS = 15000
_VALIDATION_TIMEOUT_MS = 30000
_HIGHLIGHT_STYLE = "border: 2px solid #E53935;"

_FIELD_NAMES = {
    "provider": "服务商",
    "api_key": "API Key",
    "model": "模型",
    "params": "高级参数",
}


def _model_ids(models: list) -> list:
    """从模型条目中提取 id 列表（兼容纯字符串与带勾选的对象）。"""
    ids = []
    for model in models or []:
        if isinstance(model, dict):
            model_id = str(model.get("id") or "").strip()
            if model_id:
                ids.append(model_id)
        elif isinstance(model, str) and model.strip():
            ids.append(model.strip())
    return ids


def _model_capabilities(models: list, model_id: str) -> dict:
    """返回指定模型的能力勾选快照；未找到返回空字典。"""
    for model in models or []:
        if not isinstance(model, dict):
            continue
        if str(model.get("id") or "").strip() != model_id:
            continue
        return {
            "can_enable_thinking": bool(model.get("can_enable_thinking", False)),
            "can_use_json": bool(model.get("can_use_json", False)),
        }
    return {}


class LLMSettingsDialog(QDialog):
    """按服务端类型字典渲染的一页式客户端模型设置。"""

    def __init__(self, network_client: "NetworkClient", parent=None):
        super().__init__(parent)
        self.logger = get_logger(self.__class__.__name__)
        self.network_client = network_client
        self.setWindowTitle("LLM 模型设置")
        self.setMinimumSize(680, 360)
        self.resize(720, 820)
        self.setModal(True)

        self._http = QNetworkAccessManager(self)
        self._http.setRedirectPolicy(QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        self._http.setAutoDeleteReplies(True)

        self._providers_reply: "QNetworkReply | None" = None
        self._providers_loaded = False
        self._types: list = []
        self._modules: dict = {}
        self._chrome: int | None = None

        # 校验状态：batchId 递增使旧请求响应自动失效
        self._validation_batch = 0
        self._validating = False
        self._validation_items: list = []
        self._validation_results: dict = {}
        self._save_modules: dict = {}

        self._init_ui()
        self._start_fetch_providers()

    def _init_ui(self) -> None:
        layout = QVBoxLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(20, 16, 20, 16)

        title = QLabel("LLM 模型设置")
        title.setStyleSheet("font-size: 20px; font-weight: bold; color: #66CCFF;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)

        desc = QLabel(
            "各类型可独立开启“使用自己的 API Key”；关闭时相关调用使用服务端 Key。"
            "Key 只保存在本机，不会上传服务器。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #666;")
        layout.addWidget(desc)

        header = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新类型列表")
        self.refresh_btn.setStyleSheet("font-size: 13px; padding: 6px 12px;")
        self.refresh_btn.clicked.connect(self._refresh_providers)
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

        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        btn_layout.addStretch()
        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.setVisible(False)
        self.cancel_btn.setStyleSheet(
            "QPushButton { background-color: #ffffff; color: #555555;"
            " border: 1px solid #cccccc; padding: 10px 22px; border-radius: 8px;"
            " font-size: 14px; }"
            "QPushButton:hover { background-color: #f2f2f2; }"
        )
        self.cancel_btn.clicked.connect(self._cancel_validation)
        self.save_btn = QPushButton("保存")
        self.save_btn.setEnabled(False)
        self.save_btn.setStyleSheet(
            "QPushButton { background-color: #5BB8E8; color: white; border: none;"
            " padding: 10px 30px; border-radius: 8px; font-size: 14px; }"
            "QPushButton:hover { background-color: #4AA8D8; }"
            "QPushButton:disabled { background-color: #C8CDD3; color: #8A9299; }"
        )
        self.save_btn.clicked.connect(self._on_save)
        btn_layout.addWidget(self.cancel_btn)
        btn_layout.addWidget(self.save_btn)
        layout.addLayout(btn_layout)
        self.setLayout(layout)

    def _start_fetch_providers(self) -> None:
        """异步拉取客户端模型类型字典，取消前一个请求。"""
        if self._providers_reply is not None and not self._providers_reply.isFinished():
            self._mark_cancelled(self._providers_reply)
            self._providers_reply.abort()
        base = self.network_client.base_url
        request = QNetworkRequest(QUrl(f"{base.rstrip('/')}/llm/providers"))
        request.setTransferTimeout(_PROVIDERS_TIMEOUT_MS)
        self._providers_reply = self._http.get(request)
        self._providers_reply.finished.connect(self._on_providers_reply)
        self.status_label.setText("正在获取类型列表…")

    def _on_providers_reply(self) -> None:
        reply = self.sender()
        if reply is None or reply is not self._providers_reply:
            return
        self._providers_reply = None
        if reply.error() == QNetworkReply.NetworkError.OperationCanceledError:
            if self._is_intentional_cancel(reply):
                return
            self._on_providers_failed("请求超时（15 秒无响应），请检查网络后重试。")
            return
        if reply.error() != QNetworkReply.NetworkError.NoError:
            self._on_providers_failed(reply.errorString())
            return
        try:
            data = json.loads(bytes(reply.readAll()))
        except Exception as exc:
            self._on_providers_failed(f"数据解析失败: {exc}")
            return
        types = data.get("types") if isinstance(data, dict) else data
        if not isinstance(types, list):
            self._on_providers_failed("类型列表格式错误")
            return
        self._on_providers_loaded([t for t in types if isinstance(t, dict)])

    def _on_providers_loaded(self, types: list) -> None:
        self._types = types
        self._rebuild_cards()
        QTimer.singleShot(0, self._auto_resize)
        self._load_modules_from_storage()
        self._providers_loaded = True
        self.save_btn.setEnabled(bool(self._types))
        if not self._types:
            self.status_label.setText("类型列表为空，请刷新重试。")
        else:
            self.status_label.setText("")

    def _on_providers_failed(self, message: str) -> None:
        self._providers_loaded = False
        self.save_btn.setEnabled(False)
        self.status_label.setText(f"获取类型列表失败：{message}")

    def _refresh_providers(self) -> None:
        self.status_label.setText("正在获取类型列表…")
        self._start_fetch_providers()

    def _providers_of_type(self, type_name: str) -> list:
        for type_item in self._types:
            if str(type_item.get("type") or "") == type_name:
                return [p for p in type_item.get("providers") or [] if isinstance(p, dict)]
        return []

    def _find_provider_in_type(self, type_name: str, provider_name: str) -> dict | None:
        for provider in self._providers_of_type(type_name):
            if str(provider.get("name") or "") == provider_name:
                return provider
        return None

    def _clear_cards(self) -> None:
        while self._cards_layout.count():
            item = self._cards_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._modules = {}

    def _rebuild_cards(self) -> None:
        self._clear_cards()
        for type_item in self._types:
            type_name = str(type_item.get("type") or "").strip()
            if not type_name:
                continue
            self._modules[type_name] = self._build_type_card(
                type_name,
                str(type_item.get("description") or "").strip(),
                type_item.get("providers") or [],
            )

    def _auto_resize(self) -> None:
        if self._cards_layout.count() == 0:
            return
        content_h = self._cards_layout.sizeHint().height()
        if self._chrome is None:
            self._chrome = max(0, self.height() - self._scroll.height())
        target_h = max(self._chrome + 40, min(content_h + self._chrome, 900))
        if abs(target_h - self.height()) > 8:
            self.resize(self.width(), target_h)

    def _build_type_card(self, type_name: str, description: str, providers: list) -> dict:
        card = QWidget()
        card.setStyleSheet(
            "QWidget#moduleCard { background: #F7F9FB; border: 1px solid #E0E6EC;"
            " border-radius: 8px; }"
        )
        card.setObjectName("moduleCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(16, 12, 16, 12)
        layout.setSpacing(8)

        head = QHBoxLayout()
        head_label = QLabel(type_name)
        head_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #333;")
        switch = QCheckBox("使用自己的 API Key")
        switch.setStyleSheet("font-size: 13px;")
        head.addWidget(head_label)
        head.addStretch()
        head.addWidget(switch)
        layout.addLayout(head)

        if description:
            notice = QLabel(description)
            notice.setWordWrap(True)
            notice.setStyleSheet("font-size: 12px; color: #888;")
            layout.addWidget(notice)

        fields = QWidget()
        fl = QVBoxLayout(fields)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)

        provider_combo = QComboBox()
        provider_combo.setPlaceholderText("选择服务商")
        provider_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        for provider in providers:
            provider_combo.addItem(
                str(provider.get("name", "")),
                str(provider.get("base_url", "")),
            )
        fl.addWidget(provider_combo)

        url_hint = QLabel("")
        url_hint.setWordWrap(True)
        url_hint.setStyleSheet("font-size: 12px; color: #999;")
        url_hint.hide()
        fl.addWidget(url_hint)

        api_key_input = QLineEdit()
        api_key_input.setPlaceholderText("粘贴 API Key")
        api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_input.setStyleSheet("font-size: 14px; padding: 6px;")
        fl.addWidget(api_key_input)

        model_combo = QComboBox()
        model_combo.setPlaceholderText("选择模型")
        model_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        fl.addWidget(model_combo)

        params_editor = QPlainTextEdit()
        params_editor.setPlaceholderText(
            '高级参数（JSON，可选），例如 {"temperature": 0.7}'
        )
        params_editor.setMaximumHeight(90)
        params_editor.setStyleSheet("font-size: 13px;")
        fl.addWidget(params_editor)

        layout.addWidget(fields)
        self._cards_layout.addWidget(card)

        info = {
            "key": type_name,
            "card": card,
            "switch": switch,
            "fields": fields,
            "provider_combo": provider_combo,
            "api_key_input": api_key_input,
            "model_combo": model_combo,
            "url_hint": url_hint,
            "params_editor": params_editor,
            "base_url": "",
            "stored_provider": "",
            "stored_model": "",
            "provider_style": provider_combo.styleSheet(),
            "key_style": api_key_input.styleSheet(),
            "model_style": model_combo.styleSheet(),
            "params_style": params_editor.styleSheet(),
        }

        switch.toggled.connect(lambda checked, w=fields: w.setVisible(checked))
        switch.toggled.connect(lambda: QTimer.singleShot(0, self._auto_resize))
        provider_combo.currentTextChanged.connect(
            lambda text, k=type_name: self._on_provider_changed(k, text)
        )
        api_key_input.textChanged.connect(
            lambda _t, k=type_name: self._clear_highlight(self._modules[k]["api_key_input"])
        )
        params_editor.textChanged.connect(
            lambda _t, k=type_name: self._clear_highlight(self._modules[k]["params_editor"])
        )
        return info

    def _on_provider_changed(self, type_name: str, text: str) -> None:
        info = self._modules.get(type_name)
        if info is None:
            return
        provider = self._find_provider_in_type(type_name, text)
        info["base_url"] = str(provider.get("base_url", "")) if provider else ""
        if info["base_url"]:
            info["url_hint"].setText(f"服务商地址：{info['base_url']}")
            info["url_hint"].show()
        else:
            info["url_hint"].clear()
            info["url_hint"].hide()
        info["stored_provider"] = ""
        info["stored_model"] = ""
        self._clear_highlight(info["provider_combo"])
        info["model_combo"].clear()
        if provider:
            for model_id in _model_ids(provider.get("models")):
                info["model_combo"].addItem(model_id)

    def _load_modules_from_storage(self) -> None:
        saved = llm_key_storage.get_llm_modules_config()
        for type_name, info in self._modules.items():
            entry = saved.get(type_name) or {}
            info["base_url"] = str(entry.get("base_url") or "")
            provider = str(entry.get("provider") or "")
            model = str(entry.get("model") or "")
            api_key = str(entry.get("api_key") or "")
            params = entry.get("params") or {}

            info["stored_provider"] = ""
            info["stored_model"] = ""
            info["switch"].setChecked(bool(entry.get("enabled", False)))
            if provider:
                index = info["provider_combo"].findText(provider)
                if index >= 0:
                    info["provider_combo"].setCurrentIndex(index)
                else:
                    info["stored_provider"] = provider
                    if info["base_url"]:
                        info["url_hint"].setText(f"服务商地址：{info['base_url']}")
                        info["url_hint"].show()
            if model:
                index = info["model_combo"].findText(model)
                if index >= 0:
                    info["model_combo"].setCurrentIndex(index)
                else:
                    info["stored_model"] = model
            if api_key:
                info["api_key_input"].setText(api_key)
            if params:
                info["params_editor"].setPlainText(
                    json.dumps(params, ensure_ascii=False, indent=2)
                )
            info["fields"].setVisible(info["switch"].isChecked())

    def _clear_highlight(self, widget) -> None:
        for info in self._modules.values():
            base = None
            if widget is info["provider_combo"]:
                base = info["provider_style"]
            elif widget is info["api_key_input"]:
                base = info["key_style"]
            elif widget is info["model_combo"]:
                base = info["model_style"]
            elif widget is info["params_editor"]:
                base = info["params_style"]
            if base is not None:
                widget.setStyleSheet(base)
                return

    def _highlight_widget(self, info: dict, widget) -> None:
        if widget is info["provider_combo"]:
            widget.setStyleSheet(info["provider_style"] + " " + _HIGHLIGHT_STYLE)
        elif widget is info["api_key_input"]:
            widget.setStyleSheet(info["key_style"] + " " + _HIGHLIGHT_STYLE)
        elif widget is info["model_combo"]:
            widget.setStyleSheet(info["model_style"] + " " + _HIGHLIGHT_STYLE)
        elif widget is info["params_editor"]:
            widget.setStyleSheet(info["params_style"] + " " + _HIGHLIGHT_STYLE)

    def _collect_form_modules(self) -> dict:
        modules = {}
        for type_name, info in self._modules.items():
            provider = (
                info["provider_combo"].currentText().strip()
                or info.get("stored_provider", "")
            )
            provider_cfg = self._find_provider_in_type(type_name, provider)
            model = (
                info["model_combo"].currentText().strip()
                or info.get("stored_model", "")
            )
            modules[type_name] = {
                "enabled": info["switch"].isChecked(),
                "provider": provider,
                "api_key": info["api_key_input"].text().strip(),
                "model": model,
                "base_url": (
                    str(provider_cfg.get("base_url", ""))
                    if provider_cfg
                    else info["base_url"]
                ),
                "model_capabilities": (
                    _model_capabilities(provider_cfg.get("models"), model)
                    if provider_cfg
                    else {}
                ),
                "params_text": info["params_editor"].toPlainText().strip(),
            }
        return modules

    def _precheck(self, modules: dict) -> tuple | None:
        """客户端预检：返回首个 (type, field) 缺失项或非法 JSON；通过返回 None。"""
        for type_name, info in self._modules.items():
            entry = modules[type_name]
            if not entry["enabled"]:
                continue
            for field in ("provider", "api_key", "model"):
                if not entry[field]:
                    return type_name, field
            if entry["params_text"]:
                try:
                    parsed = json.loads(entry["params_text"])
                    if not isinstance(parsed, dict):
                        return type_name, "params"
                except json.JSONDecodeError:
                    return type_name, "params"
        return None

    def _on_save(self) -> None:
        if self._validating:
            return
        modules = self._collect_form_modules()
        missing = self._precheck(modules)
        if missing is not None:
            type_name, field = missing
            info = self._modules[type_name]
            widget = {
                "provider": info["provider_combo"],
                "api_key": info["api_key_input"],
                "model": info["model_combo"],
                "params": info["params_editor"],
            }[field]
            self._highlight_widget(info, widget)
            self._scroll.ensureWidgetVisible(info["card"], 0, 120)
            widget.setFocus()
            QMessageBox.warning(
                self,
                "配置不完整",
                f"类型「{type_name}」缺少 {_FIELD_NAMES[field]}，请补全后重试。"
                if field != "params"
                else f"类型「{type_name}」的高级参数不是合法 JSON，请修正后重试。",
            )
            return
        self._save_modules = modules
        self._start_validation(modules)

    def _start_validation(self, modules: dict) -> None:
        self._validation_batch += 1
        batch = self._validation_batch
        self._validation_items = []
        self._validation_results = {}
        self._validating = True
        self._set_validation_ui(True)
        self.status_label.setText("正在校验配置…")

        targets = [
            (type_name, entry)
            for type_name, entry in modules.items()
            if entry["enabled"] and entry["base_url"]
        ]
        if not targets:
            self._finish_validation(modules)
            return
        for type_name, entry in targets:
            request = QNetworkRequest(
                QUrl(f"{entry['base_url'].rstrip('/')}/models")
            )
            request.setRawHeader(b"Authorization", f"Bearer {entry['api_key']}".encode())
            request.setTransferTimeout(_VALIDATION_TIMEOUT_MS)
            reply = self._http.get(request)
            self._validation_items.append(
                {"reply": reply, "key": type_name, "batch": batch, "done": False}
            )
            reply.finished.connect(self._on_validation_reply)

    def _on_validation_reply(self) -> None:
        reply = self.sender()
        item = next(
            (it for it in self._validation_items if it["reply"] is reply), None
        )
        if item is None or item["batch"] != self._validation_batch:
            return
        item["done"] = True
        error = self._evaluate_validation(reply, item["key"])
        self._validation_results[item["key"]] = (error is None, error)
        if all(it["done"] for it in self._validation_items):
            self._finish_validation(self._save_modules)

    def _evaluate_validation(self, reply, type_name: str) -> str | None:
        """校验单个 /models 响应；返回 None 表示通过，否则返回失败原因。"""
        error = reply.error()
        if error == QNetworkReply.NetworkError.OperationCanceledError:
            if self._is_intentional_cancel(reply):
                return None
            return "请求超时（30 秒无响应），请检查网络后重试。"
        if error != QNetworkReply.NetworkError.NoError:
            return "无法连接服务商（URL 不可达），请检查网络后重试。"
        status = reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute)
        if status in (401, 403):
            return "API Key 无效或没有权限，请检查后重试。"
        if status != 200:
            return f"服务商返回异常（HTTP {status}）。"
        try:
            data = json.loads(bytes(reply.readAll()))
        except Exception:
            return "服务商响应格式错误。"
        model_ids = []
        raw = data.get("data") if isinstance(data, dict) else data
        if isinstance(raw, list):
            model_ids = [
                str(item.get("id"))
                for item in raw
                if isinstance(item, dict) and item.get("id")
            ]
        entry = self._save_modules.get(type_name) or {}
        if entry.get("model") not in model_ids:
            return "模型不可用（不在服务商模型列表中），请更换模型后重试。"
        return None

    def _finish_validation(self, modules: dict) -> None:
        self._validating = False
        self._set_validation_ui(False)
        failures = [
            (type_name, err)
            for type_name, (ok, err) in self._validation_results.items()
            if not ok
        ]
        if failures:
            lines = [
                f"类型「{type_name}」：{err}"
                for type_name, err in failures
            ]
            self.status_label.setText("配置校验失败")
            QMessageBox.critical(self, "配置校验失败", "\n".join(lines))
            return
        self._write_modules(modules)

    def _write_modules(self, modules: dict) -> None:
        to_save = {}
        for type_name, entry in modules.items():
            params = {}
            text = (entry.get("params_text") or "").strip()
            if text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        params = parsed
                except json.JSONDecodeError:
                    params = {}
            to_save[type_name] = {
                "enabled": entry.get("enabled", False),
                "provider": entry.get("provider", ""),
                "model": entry.get("model", ""),
                "base_url": entry.get("base_url", ""),
                "params": params,
                "model_capabilities": dict(entry.get("model_capabilities") or {}),
                "api_key": entry.get("api_key", ""),
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
        self.status_label.setText("配置已保存")
        QMessageBox.information(self, "保存成功", "配置已保存")

    def _cancel_validation(self) -> None:
        self._validation_batch += 1
        for item in self._validation_items:
            self._mark_cancelled(item["reply"])
            if not item["reply"].isFinished():
                item["reply"].abort()
        self._validation_items = []
        self._validation_results = {}
        self._validating = False
        self._set_validation_ui(False)
        self.status_label.setText("已取消校验，未写入任何数据")

    def _set_validation_ui(self, active: bool) -> None:
        self.save_btn.setEnabled(not active)
        self.cancel_btn.setVisible(active)
        self.refresh_btn.setEnabled(not active)
        for info in self._modules.values():
            info["switch"].setEnabled(not active)
            info["provider_combo"].setEnabled(not active)
            info["api_key_input"].setEnabled(not active)
            info["model_combo"].setEnabled(not active)
            info["params_editor"].setEnabled(not active)

    def _mark_cancelled(self, reply) -> None:
        if reply is not None:
            reply._intentional_cancel = True

    @staticmethod
    def _is_intentional_cancel(reply) -> bool:
        return bool(getattr(reply, "_intentional_cancel", False))

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._validating:
            event.ignore()
            self.status_label.setText("校验进行中，请先取消或等待完成")
            return
        if self._providers_reply is not None and not self._providers_reply.isFinished():
            self._mark_cancelled(self._providers_reply)
            self._providers_reply.abort()
        event.accept()
