"""LLM 模型设置对话框 - 单页垂直模块列表，全局保存。

模块列表由服务端 /llm/providers 下发的 provider 能力字段动态生成
（值为非空列表的字段，如 llm_models / vlm_models），模块 key 即字段名。
每个模块用开关控制是否使用自己的 API Key；全局保存时先做客户端预检
（必填项 + 高级参数 JSON），再对开启模块并行发起 /v1/models 校验
（batchId 防过期响应），全部通过后一次性原子写入本地凭据。
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
from PySide6.QtCore import Qt, QUrl
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkRequest, QNetworkReply
from PySide6.QtGui import QCloseEvent
from typing import TYPE_CHECKING

from ..utils.logger import get_logger
from ..safety import credential

if TYPE_CHECKING:
    from ..network.network_client import NetworkClient


MODULE_TITLES = {
    "llm_models": "对话模型",
    "vlm_models": "图片理解模型",
}

_MODULE_DATA_SOURCES = {
    "llm_models": ("llm", "llm"),
    "vlm_models": ("vlm", "vlm"),
}

_PROVIDERS_TIMEOUT_MS = 15000
_VALIDATION_TIMEOUT_MS = 30000
_HIGHLIGHT_STYLE = "border: 2px solid #E53935;"

_FIELD_NAMES = {
    "provider": "服务商",
    "api_key": "API Key",
    "model": "模型",
    "params": "高级参数",
}


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


def _derive_module_keys(providers: list) -> list:
    """收集 providers 中值为非空列表的字段名，去重保序作为模块 key。"""
    keys = []
    for provider in providers:
        if not isinstance(provider, dict):
            continue
        for key, value in provider.items():
            if isinstance(value, list) and value and key not in keys:
                keys.append(key)
    return keys


class LLMSettingsDialog(QDialog):
    """对话/图片理解等能力模块统一在一页内配置，全局保存。"""

    def __init__(self, network_client: "NetworkClient", parent=None):
        super().__init__(parent)
        self.logger = get_logger(self.__class__.__name__)
        self.network_client = network_client
        self.setWindowTitle("LLM 模型设置")
        self.setMinimumSize(680, 720)
        self.setModal(True)

        self._http = QNetworkAccessManager(self)
        self._http.setRedirectPolicy(QNetworkRequest.RedirectPolicy.SameOriginRedirectPolicy)
        self._http.setAutoDeleteReplies(True)

        self._providers_reply: "QNetworkReply | None" = None
        self._providers_loaded = False
        self._providers: list = []
        self._module_keys: list = []
        self._modules: dict = {}
        self._module_capabilities: dict = {}
        self._module_json_labels: dict = {}

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
            "各模块可独立开启“使用自己的 API Key”；关闭时相关调用使用服务端 Key。"
            "Key 只保存在本机，不会上传服务器。"
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 13px; color: #666;")
        layout.addWidget(desc)

        header = QHBoxLayout()
        self.refresh_btn = QPushButton("刷新服务商列表")
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
        layout.addWidget(self._scroll, 1)

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
        """异步拉取服务商列表（含能力字段/能力标注/JSON 任务），取消前一个请求。"""
        if self._providers_reply is not None and not self._providers_reply.isFinished():
            self._mark_cancelled(self._providers_reply)
            self._providers_reply.abort()
        base = self.network_client.base_url
        request = QNetworkRequest(QUrl(f"{base.rstrip('/')}/llm/providers"))
        request.setTransferTimeout(_PROVIDERS_TIMEOUT_MS)
        self._providers_reply = self._http.get(request)
        self._providers_reply.finished.connect(self._on_providers_reply)
        self.status_label.setText("正在获取服务商列表…")

    def _on_providers_reply(self) -> None:
        """处理服务商列表响应；仅主动取消才静默忽略，超时按失败提示。"""
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
        providers = data.get("providers") if isinstance(data, dict) else data
        if not isinstance(providers, list):
            self._on_providers_failed("服务商列表格式错误")
            return
        self._on_providers_loaded(
            providers,
            llm_caps=data.get("llm_model_capabilities") or {},
            vlm_caps=data.get("vlm_model_capabilities") or {},
            llm_json=_module_labels(data.get("llm_json_required_modules") or []),
            vlm_json=_module_labels(data.get("vlm_json_required_modules") or []),
        )

    def _on_providers_loaded(
        self,
        providers: list,
        *,
        llm_caps: dict,
        vlm_caps: dict,
        llm_json: list,
        vlm_json: list,
    ) -> None:
        self._providers = [p for p in providers if isinstance(p, dict)]
        self._module_keys = _derive_module_keys(self._providers)
        caps_by_source = {"llm": llm_caps or {}, "vlm": vlm_caps or {}}
        labels_by_source = {"llm": llm_json or [], "vlm": vlm_json or []}
        self._module_capabilities = {
            key: caps_by_source[source[0]]
            for key, source in _MODULE_DATA_SOURCES.items()
            if key in self._module_keys
        }
        self._module_json_labels = {
            key: labels_by_source[source[1]]
            for key, source in _MODULE_DATA_SOURCES.items()
            if key in self._module_keys
        }
        self._rebuild_cards()
        self._load_modules_from_storage()
        self._providers_loaded = True
        self.save_btn.setEnabled(bool(self._module_keys))
        if not self._module_keys:
            self.status_label.setText("服务商列表为空，请刷新重试。")
        else:
            self.status_label.setText("")

    def _on_providers_failed(self, message: str) -> None:
        self._providers_loaded = False
        self.save_btn.setEnabled(False)
        self.status_label.setText(f"获取服务商列表失败：{message}")

    def _refresh_providers(self) -> None:
        self.status_label.setText("正在获取服务商列表…")
        self._start_fetch_providers()

    def _capabilities_for(self, key: str) -> dict:
        return self._module_capabilities.get(key, {})

    def _json_labels_for(self, key: str) -> list:
        return self._module_json_labels.get(key, [])

    def _providers_with_key(self, key: str) -> list:
        return [p for p in self._providers if p.get(key)]

    def _find_preset(self, name: str) -> dict | None:
        for preset in self._providers:
            if preset.get("name") == name:
                return preset
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
        for key in self._module_keys:
            self._modules[key] = self._build_module_card(key, MODULE_TITLES.get(key, key))

    def _build_module_card(self, key: str, title: str) -> dict:
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
        head_label = QLabel(title)
        head_label.setStyleSheet("font-size: 15px; font-weight: 600; color: #333;")
        switch = QCheckBox("使用自己的 API Key")
        switch.setStyleSheet("font-size: 13px;")
        head.addWidget(head_label)
        head.addStretch()
        head.addWidget(switch)
        layout.addLayout(head)

        notice = QLabel("")
        notice.setWordWrap(True)
        notice.setStyleSheet("font-size: 12px; color: #C77700;")
        notice.hide()
        layout.addWidget(notice)

        fields = QWidget()
        fl = QVBoxLayout(fields)
        fl.setContentsMargins(0, 0, 0, 0)
        fl.setSpacing(6)

        provider_combo = QComboBox()
        provider_combo.setPlaceholderText("选择服务商")
        provider_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        for preset in self._providers_with_key(key):
            provider_combo.addItem(str(preset.get("name", "")), preset.get("base_url", ""))
        fl.addWidget(provider_combo)

        api_key_input = QLineEdit()
        api_key_input.setPlaceholderText("粘贴 API Key")
        api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        api_key_input.setStyleSheet("font-size: 14px; padding: 6px;")
        fl.addWidget(api_key_input)

        model_combo = QComboBox()
        model_combo.setPlaceholderText("选择模型")
        model_combo.setStyleSheet("font-size: 14px; padding: 6px;")
        fl.addWidget(model_combo)

        badge_row = QHBoxLayout()
        badge = QLabel("")
        badge.setStyleSheet(
            "font-size: 12px; color: #B7791F; background: #FDF3DC;"
            " border-radius: 4px; padding: 2px 8px;"
        )
        badge.hide()
        info_btn = QPushButton("?")
        info_btn.setFixedSize(22, 22)
        info_btn.setStyleSheet("font-size: 12px;")
        info_btn.setToolTip("")
        info_btn.hide()
        badge_row.addWidget(badge)
        badge_row.addWidget(info_btn)
        badge_row.addStretch()
        fl.addLayout(badge_row)

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
            "key": key,
            "card": card,
            "switch": switch,
            "fields": fields,
            "provider_combo": provider_combo,
            "api_key_input": api_key_input,
            "model_combo": model_combo,
            "badge_label": badge,
            "info_btn": info_btn,
            "params_editor": params_editor,
            "notice_label": notice,
            "base_url": "",
            "stored_provider": "",
            "stored_model": "",
            "provider_style": provider_combo.styleSheet(),
            "key_style": api_key_input.styleSheet(),
            "model_style": model_combo.styleSheet(),
            "params_style": params_editor.styleSheet(),
        }

        switch.toggled.connect(
            lambda checked, w=fields: w.setVisible(checked)
        )
        provider_combo.currentTextChanged.connect(
            lambda text, k=key: self._on_module_provider_changed(k, text)
        )
        model_combo.currentTextChanged.connect(
            lambda _text, k=key: self._update_badge(k)
        )
        api_key_input.textChanged.connect(
            lambda _t, k=key: self._clear_highlight(self._modules[k]["api_key_input"])
        )
        params_editor.textChanged.connect(
            lambda _t, k=key: self._clear_highlight(self._modules[k]["params_editor"])
        )
        return info

    def _on_module_provider_changed(self, key: str, text: str) -> None:
        info = self._modules.get(key)
        if info is None:
            return
        preset = self._find_preset(text)
        info["base_url"] = str(preset.get("base_url", "")) if preset else ""
        info["stored_provider"] = ""
        info["stored_model"] = ""
        self._clear_highlight(info["provider_combo"])
        info["model_combo"].clear()
        if preset:
            for model in preset.get(key) or []:
                info["model_combo"].addItem(str(model))
        self._update_badge(key)

    def _update_badge(self, key: str) -> None:
        info = self._modules.get(key)
        if info is None:
            return
        model = info["model_combo"].currentText().strip()
        cap = self._capabilities_for(key).get(model) if model else None
        labels = self._json_labels_for(key)
        if model and cap is not None and not cap.get("can_use_json") and labels:
            info["badge_label"].setText("部分高级功能将使用服务端 Key")
            info["badge_label"].show()
            info["info_btn"].setToolTip(
                "以下功能将使用服务端 Key：\n" + "、".join(str(x) for x in labels)
            )
            info["info_btn"].show()
        else:
            info["badge_label"].hide()
            info["info_btn"].hide()

    def _load_modules_from_storage(self) -> None:
        saved = credential.get_llm_modules_config()
        for key, info in self._modules.items():
            entry = saved.get(key) or {}
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
                    info["stored_provider"] = ""
                    info["base_url"] = str(
                        self._find_preset(provider).get("base_url", "")
                        if self._find_preset(provider)
                        else info["base_url"]
                    )
                else:
                    info["stored_provider"] = provider
                    info["notice_label"].setText(
                        f"注意：服务商 ‘{provider}’ 已不在列表中（保存时仍使用已固化的地址）"
                    )
                    info["notice_label"].show()
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
            self._update_badge(key)

    # 高亮辅助
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

    # 保存：预检、校验与原子写入
    def _collect_form_modules(self) -> dict:
        modules = {}
        for key, info in self._modules.items():
            modules[key] = {
                "enabled": info["switch"].isChecked(),
                "provider": (
                    info["provider_combo"].currentText().strip()
                    or info.get("stored_provider", "")
                ),
                "api_key": info["api_key_input"].text().strip(),
                "model": (
                    info["model_combo"].currentText().strip()
                    or info.get("stored_model", "")
                ),
                "base_url": info["base_url"],
                "params_text": info["params_editor"].toPlainText().strip(),
            }
        return modules

    def _precheck(self, modules: dict) -> tuple | None:
        """客户端预检：返回首个 (key, field) 缺失项或非法 JSON；通过返回 None。"""
        for key in self._module_keys:
            info = self._modules[key]
            entry = modules[key]
            if not entry["enabled"]:
                continue
            for field in ("provider", "api_key", "model"):
                if not entry[field]:
                    return key, field
            if entry["params_text"]:
                try:
                    parsed = json.loads(entry["params_text"])
                    if not isinstance(parsed, dict):
                        return key, "params"
                except json.JSONDecodeError:
                    return key, "params"
        return None

    def _on_save(self) -> None:
        if self._validating:
            return
        modules = self._collect_form_modules()
        missing = self._precheck(modules)
        if missing is not None:
            key, field = missing
            info = self._modules[key]
            widget = {
                "provider": info["provider_combo"],
                "api_key": info["api_key_input"],
                "model": info["model_combo"],
                "params": info["params_editor"],
            }[field]
            self._highlight_widget(info, widget)
            self._scroll.ensureWidgetVisible(info["card"], 0, 120)
            widget.setFocus()
            title = MODULE_TITLES.get(key, key)
            QMessageBox.warning(
                self,
                "配置不完整",
                f"模块「{title}」缺少 {_FIELD_NAMES[field]}，请补全后重试。"
                if field != "params"
                else f"模块「{title}」的高级参数不是合法 JSON，请修正后重试。",
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
            (key, entry)
            for key, entry in modules.items()
            if entry["enabled"] and entry["base_url"]
        ]
        if not targets:
            self._finish_validation(modules)
            return
        for key, entry in targets:
            request = QNetworkRequest(
                QUrl(f"{entry['base_url'].rstrip('/')}/models")
            )
            request.setRawHeader(b"Authorization", f"Bearer {entry['api_key']}".encode())
            request.setTransferTimeout(_VALIDATION_TIMEOUT_MS)
            reply = self._http.get(request)
            self._validation_items.append(
                {"reply": reply, "key": key, "batch": batch, "done": False}
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

    def _evaluate_validation(self, reply, key: str) -> str | None:
        """校验单个 /v1/models 响应；返回 None 表示通过，否则返回失败原因。"""
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
        entry = self._save_modules.get(key) or {}
        if entry.get("model") not in model_ids:
            return "模型不可用（不在服务商模型列表中），请更换模型后重试。"
        return None

    def _finish_validation(self, modules: dict) -> None:
        self._validating = False
        self._set_validation_ui(False)
        failures = [
            (key, err)
            for key, (ok, err) in self._validation_results.items()
            if not ok
        ]
        if failures:
            lines = [
                f"模块「{MODULE_TITLES.get(key, key)}」：{err}"
                for key, err in failures
            ]
            self.status_label.setText("配置校验失败")
            QMessageBox.critical(self, "配置校验失败", "\n".join(lines))
            return
        self._write_modules(modules)

    def _write_modules(self, modules: dict) -> None:
        to_save = {}
        for key, entry in modules.items():
            params = {}
            text = (entry.get("params_text") or "").strip()
            if text:
                try:
                    parsed = json.loads(text)
                    if isinstance(parsed, dict):
                        params = parsed
                except json.JSONDecodeError:
                    params = {}
            to_save[key] = {
                "enabled": entry.get("enabled", False),
                "provider": entry.get("provider", ""),
                "model": entry.get("model", ""),
                "base_url": entry.get("base_url", ""),
                "params": params,
                "api_key": entry.get("api_key", ""),
            }
        ok = credential.save_llm_modules_config(to_save)
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
            ok = credential.save_llm_modules_config(to_save, allow_plaintext=True)
            if not ok:
                self.status_label.setText("保存失败，请重试")
                return
        self.status_label.setText("配置已保存")

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

    # 取消/关闭与超时区分
    def _mark_cancelled(self, reply) -> None:
        """标记 reply 为用户主动取消；Qt 超时与 abort() 同用 OperationCanceledError。"""
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
