"""桌面 client LLM 设置对话框：服务商/模型联动与重新选择行为测试。"""

import json

import pytest
from PySide6.QtCore import QByteArray, QObject, QTimer, Signal
from PySide6.QtNetwork import QNetworkReply
from PySide6.QtWidgets import QApplication, QMessageBox

import src.gui.llm_settings_dialog as dlg_mod
from src.gui.llm_settings_dialog import LLMSettingsDialog
from src.safety import credential


PROVIDERS = [
    {
        "name": "DeepSeek",
        "base_url": "https://d/v1",
        "models": ["deepseek-v4-flash"],
        "vlm_models": [],
    },
    {
        "name": "VlmOnly",
        "base_url": "https://v/v1",
        "models": [],
        "vlm_models": ["vlm-model", "vlm-model2"],
    },
    {
        "name": "Both",
        "base_url": "https://b/v1",
        "models": ["b1", "b2"],
        "vlm_models": ["vb1"],
    },
]


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


class FakeNetwork:
    base_url = "https://x"


class FakeReply(QObject):
    """模拟 QNetworkReply：单次异步发出 finished，sender() 可识别身份。"""

    finished = Signal()

    def __init__(
        self,
        payload: bytes,
        error=QNetworkReply.NetworkError.NoError,
        error_string="",
        parent=None,
    ):
        super().__init__(parent)
        self._payload = payload
        self._error = error
        self._error_string = error_string
        # 自持引用直到信号发出：模拟 QNetworkAccessManager 对 reply 的持有
        self._self_ref = self
        QTimer.singleShot(0, self._emit_finished)

    def _emit_finished(self):
        self.finished.emit()
        self._self_ref = None

    def error(self):
        return self._error

    def errorString(self):
        return self._error_string

    def readAll(self):
        return QByteArray(self._payload)

    def isFinished(self):
        return True

    def isRunning(self):
        return False

    def abort(self):
        pass


class FakeHttp:
    """替代 QNetworkAccessManager：get 从队列取响应，缺省返回固定 providers。"""

    def __init__(self, parent=None):
        self.requests = []
        self._responses = []
        self._post_responses = []

    def setRedirectPolicy(self, policy):
        pass

    def setAutoDeleteReplies(self, enabled):
        pass

    def queue_response(
        self,
        providers,
        error=QNetworkReply.NetworkError.NoError,
        error_string="",
    ):
        payload = json.dumps(
            {
                "providers": providers,
                "llm_json_required_modules": [],
                "vlm_json_required_modules": [],
            }
        ).encode("utf-8")
        self._responses.append(
            FakeReply(payload, error=error, error_string=error_string)
        )

    def get(self, request):
        self.requests.append(request)
        if self._responses:
            return self._responses.pop(0)
        return FakeReply(
            json.dumps(
                {
                    "providers": PROVIDERS,
                    "llm_json_required_modules": [],
                    "vlm_json_required_modules": [],
                }
            ).encode("utf-8")
        )

    def queue_post_response(self, reply):
        self._post_responses.append(reply)

    def post(self, request, data):
        if self._post_responses:
            return self._post_responses.pop(0)
        return FakeReply(b"{}")


@pytest.fixture
def make_dialog(qapp, monkeypatch, tmp_path):
    """按需创建对话框：先注入 saved 配置，再实例化，贴近真实加载流程。"""
    created = []

    def _make(saved: dict | None = None) -> LLMSettingsDialog:
        saved = saved or {}
        # 隔离真实凭据文件，避免已保存配置触发模态弹窗阻塞测试
        monkeypatch.setattr(
            credential,
            "get_credential_path",
            lambda: str(tmp_path / "user.json"),
        )
        monkeypatch.setattr(credential, "get_provider", lambda: saved.get("provider"))
        monkeypatch.setattr(credential, "get_model", lambda: saved.get("model"))
        monkeypatch.setattr(
            credential, "get_vlm_provider", lambda: saved.get("vlm_provider")
        )
        monkeypatch.setattr(credential, "get_vlm_model", lambda: saved.get("vlm_model"))
        monkeypatch.setattr(credential, "get_api_key", lambda: saved.get("key"))
        monkeypatch.setattr(
            credential, "get_vlm_api_key", lambda: saved.get("vlm_key")
        )
        monkeypatch.setattr(dlg_mod, "QNetworkAccessManager", FakeHttp)
        dlg = LLMSettingsDialog(FakeNetwork())
        for _ in range(5):
            qapp.processEvents()
        created.append(dlg)
        return dlg

    yield _make
    for dlg in created:
        dlg.close()


def _click_reselect(monkeypatch):
    """把 QMessageBox.exec 替换为自动点击“重新选择”。"""

    def fake_exec(box):
        for btn in box.buttons():
            if btn.text() == "重新选择":
                btn.click()
                return QMessageBox.DialogCode.Accepted
        return QMessageBox.DialogCode.Rejected

    monkeypatch.setattr(dlg_mod.QMessageBox, "exec", fake_exec)


def test_provider_select_auto_selects_first_model(make_dialog):
    """手动选中服务商后，模型下拉框自动选中第一个可用模型。"""
    dialog = make_dialog()
    dialog.provider_combo.setCurrentIndex(
        dialog.provider_combo.findText("DeepSeek")
    )
    assert dialog.model_combo.currentText() == "deepseek-v4-flash"

    dialog.vlm_provider_combo.setCurrentIndex(
        dialog.vlm_provider_combo.findText("VlmOnly")
    )
    assert dialog.vlm_model_combo.currentText() == "vlm-model"


def test_saved_model_preserved_when_still_available(make_dialog):
    """已保存模型仍在列表中时保留原选择，不覆盖为第一个。"""
    dialog = make_dialog()
    dialog._saved_provider = "Both"
    dialog._saved_model = "b2"
    dialog.provider_combo.setCurrentIndex(
        dialog.provider_combo.findText("Both")
    )
    assert dialog.model_combo.currentText() == "b2"

    dialog._saved_vlm_provider = "Both"
    dialog._saved_vlm_model = "vb1"
    dialog.vlm_provider_combo.setCurrentIndex(
        dialog.vlm_provider_combo.findText("Both")
    )
    assert dialog.vlm_model_combo.currentText() == "vb1"


def test_stale_saved_model_falls_back_to_first(make_dialog):
    """已保存模型不在列表时，回退到该服务商第一个可用模型。"""
    dialog = make_dialog()
    dialog._saved_provider = "Both"
    dialog._saved_model = "b9"
    dialog.provider_combo.setCurrentIndex(
        dialog.provider_combo.findText("Both")
    )
    assert dialog.model_combo.currentText() == "b1"

    dialog._saved_vlm_provider = "Both"
    dialog._saved_vlm_model = "vb9"
    dialog.vlm_provider_combo.setCurrentIndex(
        dialog.vlm_provider_combo.findText("Both")
    )
    assert dialog.vlm_model_combo.currentText() == "vb1"


def test_reselect_provider_stale_selects_provider_and_model(make_dialog, monkeypatch):
    """服务商失效时重新选择：服务商与模型一起自动选第一个可用配置。"""
    _click_reselect(monkeypatch)
    dialog = make_dialog(
        {
            "provider": "OldProvider",
            "model": "old-model",
            "vlm_provider": "OldVlm",
            "vlm_model": "old-vlm",
            "key": "sk",
            "vlm_key": "skv",
        }
    )
    assert dialog.provider_combo.currentText() == "DeepSeek"
    assert dialog.model_combo.currentText() == "deepseek-v4-flash"

    dialog._go_to_page(1)
    assert dialog.vlm_provider_combo.currentText() == "VlmOnly"
    assert dialog.vlm_model_combo.currentText() == "vlm-model"


def test_reselect_model_stale_keeps_provider_selects_first_model(make_dialog, monkeypatch):
    """仅模型失效时重新选择：保留服务商，自动换成其第一个可用模型。"""
    _click_reselect(monkeypatch)
    dialog = make_dialog(
        {
            "provider": "Both",
            "model": "b9",
            "vlm_provider": "Both",
            "vlm_model": "vb9",
            "key": "sk",
            "vlm_key": "skv",
        }
    )
    assert dialog.provider_combo.currentText() == "Both"
    assert dialog.model_combo.currentText() == "b1"

    dialog._go_to_page(1)
    assert dialog.vlm_provider_combo.currentText() == "Both"
    assert dialog.vlm_model_combo.currentText() == "vb1"


def test_refresh_ignores_stale_providers_reply(make_dialog, qapp):
    """刷新竞态：旧请求晚到不覆盖新请求的结果。"""
    dialog = make_dialog()
    http = dialog._http
    old_only = [
        {
            "name": "OldOnly",
            "base_url": "https://o/v1",
            "models": ["old-model"],
            "vlm_models": [],
        }
    ]
    http.queue_response(old_only)
    http.queue_response(PROVIDERS)

    dialog._refresh_providers()
    dialog._refresh_providers()
    for _ in range(5):
        qapp.processEvents()

    # 只有第二次刷新（最新）的结果生效
    # 首次请求来自对话框初始化，后两次来自刷新
    assert len(http.requests) == 3
    assert dialog.provider_combo.currentText() == "DeepSeek"
    assert dialog.model_combo.currentText() == "deepseek-v4-flash"
    assert dialog._llm_providers[0]["name"] == "DeepSeek"


def test_providers_timeout_is_reported(make_dialog, qapp):
    """服务商列表 15 秒传输超时（Qt 6.9 下为 OperationCanceledError）应提示失败，而非静默忽略。"""
    dialog = make_dialog()
    http = dialog._http
    http.queue_response(
        PROVIDERS,
        error=QNetworkReply.NetworkError.OperationCanceledError,
        error_string="Operation canceled",
    )
    dialog._refresh_providers()
    for _ in range(5):
        qapp.processEvents()
    assert "获取服务商列表失败" in dialog.status_label.text()
    assert "超时" in dialog.status_label.text()


def test_providers_intentional_cancel_is_ignored(make_dialog, qapp):
    """用户主动 abort 服务商列表请求（关闭/刷新）时保持静默忽略。"""
    dialog = make_dialog()
    reply = FakeReply(
        b"",
        error=QNetworkReply.NetworkError.OperationCanceledError,
        error_string="Operation canceled",
    )
    dialog._mark_cancelled(reply)
    dialog._providers_reply = reply
    reply.finished.connect(dialog._on_providers_reply)
    for _ in range(5):
        qapp.processEvents()
    assert dialog._providers_reply is None
    assert "获取服务商列表失败" not in dialog.status_label.text()


def _probe_cfg():
    return {
        "name": "DeepSeek",
        "kind": "text",
        "api_key": "sk-test",
        "provider": "DeepSeek",
        "model": "deepseek-v4-flash",
        "params": {},
    }


def test_probe_timeout_fails_validation(make_dialog, qapp, monkeypatch):
    """探测请求 30 秒超时（OperationCanceledError）必须判定校验失败，不能保存配置。"""
    dialog = make_dialog()
    saved = []
    monkeypatch.setattr(
        credential, "save_llm_config", lambda *a, **k: saved.append(a) or True
    )
    errors_box = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox, "critical", lambda parent, title, text: errors_box.append(text)
    )

    reply = FakeReply(
        b"",
        error=QNetworkReply.NetworkError.OperationCanceledError,
        error_string="Operation canceled",
    )
    dialog._probe_replies = [reply]
    dialog._probe_configs = [
        {
            "name": "DeepSeek",
            "base_url": "https://d/v1",
            "api_key": "sk-test",
            "model": "deepseek-v4-flash",
            "params": {},
        }
    ]
    cfg = _probe_cfg()
    dialog._pending_save = (cfg, None)
    dialog._set_frozen(True)
    reply.finished.connect(dialog._on_probe_reply)
    for _ in range(5):
        qapp.processEvents()

    assert errors_box, "超时应当弹窗报错"
    assert dialog.status_label.text() == "配置校验失败"
    assert saved == [], "超时不应保存配置"
    assert dialog._pending_save == (cfg, None)


def test_probe_intentional_cancel_is_skipped(make_dialog, qapp, monkeypatch):
    """主动取消的探测请求跳过不算失败，其余请求正常时允许保存。"""
    dialog = make_dialog()
    saved = []
    monkeypatch.setattr(
        credential, "save_llm_config", lambda *a, **k: saved.append(a) or True
    )
    monkeypatch.setattr(dlg_mod.QMessageBox, "information", lambda *a, **k: None)

    reply = FakeReply(
        b"",
        error=QNetworkReply.NetworkError.OperationCanceledError,
        error_string="Operation canceled",
    )
    dialog._mark_cancelled(reply)
    dialog._probe_replies = [reply]
    dialog._probe_configs = [
        {
            "name": "DeepSeek",
            "base_url": "https://d/v1",
            "api_key": "sk-test",
            "model": "deepseek-v4-flash",
            "params": {},
        }
    ]
    dialog._pending_save = (_probe_cfg(), None)
    dialog._set_frozen(True)
    reply.finished.connect(dialog._on_probe_reply)
    for _ in range(5):
        qapp.processEvents()

    assert saved, "主动取消应被跳过并继续保存"
    assert dialog._pending_save is None


def test_save_with_timed_out_probe_is_rejected(make_dialog, qapp, monkeypatch):
    """端到端：_save_page 发起探测，30 秒超时后弹窗报错且不落盘。"""
    dialog = make_dialog()
    saved = []
    monkeypatch.setattr(
        credential, "save_llm_config", lambda *a, **k: saved.append(a) or True
    )
    errors_box = []
    monkeypatch.setattr(
        dlg_mod.QMessageBox, "critical", lambda parent, title, text: errors_box.append(text)
    )

    http = dialog._http
    http.queue_post_response(
        FakeReply(
            b"",
            error=QNetworkReply.NetworkError.OperationCanceledError,
            error_string="Operation canceled",
        )
    )
    dialog._save_page(_probe_cfg())
    for _ in range(5):
        qapp.processEvents()

    assert errors_box, "超时应弹窗报错"
    assert saved == [], "超时不应保存配置"
    assert dialog.status_label.text() == "配置校验失败"
