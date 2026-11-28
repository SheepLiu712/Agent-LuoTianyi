import base64
import json
import os
import threading
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from PIL import Image
from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication
from src.avatars import AvatarStore
from src.gui.avatar_controller import AvatarController
from src.gui.avatar_label import AvatarLabel
from src.gui.avatar_settings_dialog import AvatarCropPreview, AvatarSettingsDialog
from src.gui.binder import AgentBinder
from src.gui.chat_bubble import ChatBubble
from src.gui.dynamics_dialog import (
    DynamicCommentWidget,
    DynamicListItemWidget,
    DynamicPostWidget,
)
from src.gui.main_ui import ChatWidget
from src.network.network_client import NetworkClient
from src.types import ConversationItem


def image_uri(color, size=(256, 256)):
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="PNG")
    return "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")


def wait_for(predicate):
    for _ in range(500):
        if predicate():
            return
        QTest.qWait(10)
    assert predicate(), "头像同步未在测试时限内完成"


def pixel(label):
    image = label.pixmap().toImage()
    return image.pixelColor(image.width() // 2, image.height() // 2).name()


@pytest.fixture(scope="module")
def qapp():
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    yield QApplication.instance() or QApplication([])


class AvatarTransport:
    def __init__(self):
        self.accounts = {}
        self.calls = []
        self.offline = False
        self.gates = []
        self.rejected_tokens = set()
        self.active = 0

    def account(self, host="a.invalid", username="alice"):
        return self.accounts.setdefault(
            (host, username),
            {
                "revision": "0",
                "user": None,
                "agent": None,
                "sync_token": f"sync-{host}-{username}",
            },
        )

    def hold_next(self):
        gate = threading.Event()
        self.gates.append(gate)
        return gate

    def send(self, _session, request, **options):
        parsed = urlsplit(request.url)
        response = requests.Response()
        response.request = request
        if "/avatars" not in parsed.path:
            response.status_code, response._content = 200, b'{"unread_count": 0}'
            return response
        self.active += 1
        gate = self.gates.pop(0) if self.gates else None
        self.calls.append((request, options))
        try:
            if self.offline:
                raise requests.ConnectionError("offline")
            username = parse_qs(parsed.query)["username"][0]
            data = self.account(parsed.netloc, username)
            if request.headers["Authorization"] in self.rejected_tokens:
                response.status_code, response._content = 401, b"{}"
            elif request.method == "GET" and request.headers.get("If-None-Match") == data["revision"]:
                response.status_code, response._content = 304, b""
                response.headers["X-Avatar-Token"] = data["sync_token"]
            else:
                if request.method == "PUT":
                    data[parsed.path.rsplit("/", 1)[1]] = json.loads(request.body)["image"]
                    data["revision"] = str(int(data["revision"]) + 1)
                response.status_code, response._content = 200, json.dumps(data).encode()
            if gate and not gate.wait(5):
                raise requests.Timeout("test watchdog")
            return response
        finally:
            self.active -= 1


@pytest.fixture
def desktop(qapp, tmp_path, monkeypatch):
    transport = AvatarTransport()
    monkeypatch.setattr(
        requests.Session,
        "send",
        lambda session, request, **options: transport.send(session, request, **options),
    )
    controllers, windows = [], []
    path = str(tmp_path / "avatars.json")

    def create(username="alice", server="https://a.invalid", chat=False):
        network = NetworkClient(server)
        network.user_id, network.message_token = username, f"message-{username}"
        avatars = AvatarController(network, store=AvatarStore(path))
        controllers.append(avatars)
        if chat:
            widget = ChatWidget({}, Mock(spec=AgentBinder), network, avatars=avatars)
            windows.append(widget)
        else:
            widget = None
        return network, avatars, widget

    yield create, transport, path, windows
    for controller in controllers:
        controller.close()
    for gate in transport.gates:
        gate.set()
    wait_for(lambda: transport.active == 0)
    for window in windows:
        window.close()
        window.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    qapp.processEvents()


def test_offline_settings_update_history_and_survive_restart_then_retry(desktop, tmp_path, monkeypatch):
    create, transport, path, windows = desktop
    transport.offline = True
    _network, avatars, chat = create(chat=True)
    chat.on_history_loaded([ConversationItem("", "user", "text", "旧消息", "history")], 0)
    history = chat.history_container.findChild(ChatBubble)
    dialog = AvatarSettingsDialog(avatars, side="user")
    windows.append(dialog)
    source = tmp_path / "avatar.png"
    Image.new("RGB", (512, 128), "red").save(source)
    monkeypatch.setattr(
        "src.gui.avatar_settings_dialog.QFileDialog.getOpenFileName",
        lambda *_: (str(source), ""),
    )
    dialog.choose_image()
    assert pixel(dialog.preview) == "#ff0000"
    assert avatars.image("user") is None
    dialog.save_button.click()
    wait_for(lambda: "同步失败" in dialog.status_label.text())
    assert "自动重试" in dialog.status_label.text()
    assert pixel(history.avatar_label) == "#ff0000"
    saved = base64.b64decode(avatars.image("user").split(",", 1)[1])
    assert Image.open(BytesIO(saved)).size == (256, 256)
    avatars.close()

    cached = AvatarStore(path)
    cached.activate("alice", "https://a.invalid")
    with Image.open(BytesIO(base64.b64decode(cached.images["user"].split(",", 1)[1]))) as cached_image:
        assert cached_image.size == (256, 256)
    assert cached.server["pending"] == ["user"]
    assert "agent" not in cached.images

    transport.account()["agent"] = image_uri("blue")
    _network, resumed, _chat = create()
    wait_for(lambda: "同步失败" in resumed.status)
    assert resumed.image("user") == cached.images["user"]
    transport.offline = False
    resumed.refresh()
    wait_for(lambda: resumed.status == "头像已同步")
    writes = [request for request, _ in transport.calls if request.method == "PUT"]
    assert {urlsplit(request.url).path for request in writes} == {"/avatars/user"}
    assert transport.account()["user"] == cached.images["user"]
    assert transport.account()["agent"] == image_uri("blue")
    assert resumed.image("agent") == image_uri("blue")
    restored_dialog = AvatarSettingsDialog(resumed, side="user")
    windows.append(restored_dialog)
    restored_dialog.restore_default()
    assert resumed.image("user") == transport.account()["user"]
    restored_dialog.save_side()
    assert resumed.image("user") is None
    wait_for(lambda: resumed.status == "头像已同步")
    assert transport.account()["user"] is None
    assert transport.account()["agent"] == image_uri("blue")


def test_on_demand_refresh_updates_views_without_overwriting_edits_during_sync(desktop):
    create, transport, _path, windows = desktop
    gate = transport.hold_next()
    _network, avatars, chat = create(chat=True)
    chat.on_history_loaded([ConversationItem("", "agent", "text", "历史", "old")], 0)
    history = chat.history_container.findChild(ChatBubble)
    cards = [
        widget({"author_type": "agent"}, avatars=avatars)
        for widget in (DynamicListItemWidget, DynamicPostWidget, DynamicCommentWidget)
    ]
    windows.extend(cards)
    wait_for(lambda: len(transport.calls) == 1)
    avatars.save("user", image_uri("red"))
    avatars.save("agent", image_uri("blue"))
    put_gate = transport.hold_next()
    gate.set()
    wait_for(lambda: len(transport.calls) == 2)
    assert avatars.image("agent") == image_uri("blue")
    avatars.save("user", image_uri("green"))
    put_gate.set()
    wait_for(lambda: avatars.status == "头像已同步")
    assert transport.account()["user"] == image_uri("green")
    assert transport.account()["agent"] == image_uri("blue")
    assert pixel(history.avatar_label) == "#0000ff"

    transport.account().update(agent=image_uri("purple"), revision="99")
    avatars.refresh()
    wait_for(lambda: pixel(history.avatar_label) == "#800080")
    for card in cards:
        assert pixel(card.findChild(AvatarLabel)) == "#800080"
    avatars.refresh()
    wait_for(lambda: any(request.headers.get("If-None-Match") == "99" for request, _ in transport.calls))
    assert all(options["timeout"] == 15 and options["verify"] is True for _, options in transport.calls)


def test_account_switch_and_close_discard_late_results(desktop):
    create, transport, path, _windows = desktop
    transport.account()["user"] = image_uri("red")
    gate = transport.hold_next()
    network, avatars, _chat = create()
    old_context = network.account_context()
    wait_for(lambda: len(transport.calls) == 1)
    network.user_id, network.message_token = "bob", "message-bob"
    transport.account(username="bob")["user"] = image_uri("green")
    wait_for(lambda: avatars.image("user") == image_uri("green"))
    gate.set()
    wait_for(lambda: transport.active == 0)
    assert avatars.username == "bob"
    assert avatars.image("user") == image_uri("green")
    with pytest.raises(ValueError, match="账号已变更"):
        avatars.save("user", image_uri("red"), context=old_context)
    assert avatars.image("user") == image_uri("green")
    assert AvatarStore(path).accounts["alice"]["images"] == {}

    close_gate = transport.hold_next()
    transport.account(username="bob").update(user=image_uri("purple"), revision="2")
    previous_count = len(transport.calls)
    avatars.refresh()
    wait_for(lambda: len(transport.calls) > previous_count)
    avatars.close()
    close_gate.set()
    wait_for(lambda: transport.active == 0)
    QTest.qWait(50)
    assert avatars.image("user") == image_uri("green")
    cached = AvatarStore(path)
    cached.activate("bob", network.base_url)
    assert cached.images["user"] == image_uri("green")


def test_server_switch_migrates_known_null_and_current_images_including_return(desktop):
    create, transport, path, _windows = desktop
    transport.offline = True
    network, avatars, _chat = create()
    avatars.save("user", None)
    wait_for(lambda: "同步失败" in avatars.status)
    transport.account("b.invalid")["agent"] = image_uri("blue")
    transport.offline = False
    network.set_base_url("https://B.INVALID:443/", True)
    wait_for(lambda: avatars.status == "头像已同步" and avatars.store.server_url == "https://b.invalid")
    b_writes = [request for request, _ in transport.calls if request.method == "PUT" and "b.invalid" in request.url]
    assert [urlsplit(request.url).path for request in b_writes] == ["/avatars/user"]
    assert transport.account("b.invalid")["agent"] == image_uri("blue")
    avatars.save("agent", image_uri("purple"))
    wait_for(lambda: avatars.status == "头像已同步")
    network.set_base_url("https://a.invalid/", True)
    wait_for(lambda: avatars.status == "头像已同步" and avatars.store.server_url == "https://a.invalid")
    assert transport.account()["agent"] == image_uri("purple")
    assert transport.account()["user"] is None
    saved = AvatarStore(path).accounts["alice"]
    assert set(saved["servers"]) == {"https://a.invalid", "https://b.invalid"}
    assert saved["last_server"] == "https://a.invalid"
    before = len([request for request, _ in transport.calls if request.method == "PUT"])
    avatars.close()
    _network, resumed, _chat = create()
    wait_for(lambda: resumed.status == "头像已同步")
    assert len([request for request, _ in transport.calls if request.method == "PUT"]) == before


def test_sync_token_persists_renews_on_304_and_falls_back_once_on_401(desktop, monkeypatch):
    monkeypatch.setattr("src.avatars.encrypt_secret", lambda value: f"encrypted:{value}")
    monkeypatch.setattr(
        "src.avatars.decrypt_secret",
        lambda value: value.removeprefix("encrypted:") or None,
    )
    create, transport, path, _windows = desktop
    _network, avatars, _chat = create()
    wait_for(lambda: avatars.status == "头像已同步")
    avatars.close()
    saved = AvatarStore(path).accounts["alice"]["servers"]["https://a.invalid"]
    assert saved["sync_token"] != transport.account()["sync_token"]
    _network, resumed, _chat = create()
    wait_for(lambda: resumed.status == "头像已同步")
    assert transport.calls[-1][0].headers["Authorization"] == "Bearer sync-a.invalid-alice"
    transport.account()["sync_token"] = "renewed"
    resumed.refresh()
    wait_for(lambda: resumed.status == "头像已同步")
    assert resumed.store.request((), "message-alice").sync_token == "renewed"

    saved_at = Path(path).stat().st_mtime_ns
    resumed.refresh()
    wait_for(lambda: resumed.status == "头像已同步")
    assert Path(path).stat().st_mtime_ns == saved_at

    transport.rejected_tokens.update({"Bearer renewed", "Bearer message-alice"})
    before = len(transport.calls)
    resumed.refresh()
    wait_for(lambda: "同步失败" in resumed.status)
    assert len(transport.calls) == before + 2
    assert [request.headers["Authorization"] for request, _ in transport.calls[-2:]] == [
        "Bearer renewed",
        "Bearer message-alice",
    ]
    assert resumed.store.request((), "message-alice").sync_token is None
    assert "sync_token" not in AvatarStore(path).accounts["alice"]["servers"]["https://a.invalid"]
    transport.rejected_tokens.clear()
    resumed.refresh()
    wait_for(lambda: resumed.status == "头像已同步")
    transport.rejected_tokens.add("Bearer renewed")
    transport.account()["sync_token"] = "fresh"
    resumed.refresh()
    wait_for(lambda: resumed.status == "头像已同步")
    assert resumed.store.request((), "message-alice").sync_token == "fresh"
    assert [request.headers["Authorization"] for request, _ in transport.calls[-2:]] == [
        "Bearer renewed",
        "Bearer message-alice",
    ]


def test_avatar_crop_accepts_png_jpeg_and_rejects_unsupported_format(tmp_path, qapp):
    preview = AvatarCropPreview()
    for extension, image_format in (("png", "PNG"), ("jpg", "JPEG")):
        source = tmp_path / f"wide.{extension}"
        Image.new("RGB", (512, 128), "red").save(source, format=image_format)
        preview.set_source(str(source))
        data = base64.b64decode(preview.cropped_data().split(",", 1)[1])
        with Image.open(BytesIO(data)) as image:
            assert image.format == "PNG"
            assert image.size == (256, 256)
    source = tmp_path / "unsupported.bmp"
    Image.new("RGB", (10, 10)).save(source)
    with pytest.raises(ValueError, match="PNG 或 JPEG"):
        preview.set_source(str(source))


@pytest.mark.parametrize("side", ["user", "agent"])
def test_avatar_label_click_opens_single_side_editor(desktop, monkeypatch, side):
    create, _transport, _path, windows = desktop
    _network, avatars, chat = create(chat=True)
    bubble = chat.add_message("text", "hello", is_user=side == "user")
    windows.append(bubble)
    opened = []
    monkeypatch.setattr(
        "src.gui.chat_bubble.AvatarSettingsDialog.exec",
        lambda dialog: opened.append(dialog.side),
    )
    QTest.mouseClick(bubble.avatar_label, Qt.MouseButton.LeftButton)
    assert opened == [side]


def test_crop_preview_zoom_and_cancel_do_not_save(desktop, tmp_path, monkeypatch):
    create, _transport, _path, windows = desktop
    _network, avatars, _chat = create()
    dialog = AvatarSettingsDialog(avatars, side="agent")
    windows.append(dialog)
    source = tmp_path / "wide.png"
    Image.new("RGB", (512, 128), "blue").save(source)
    monkeypatch.setattr(
        "src.gui.avatar_settings_dialog.QFileDialog.getOpenFileName",
        lambda *_: (str(source), ""),
    )
    dialog.choose_image()
    assert avatars.image("agent") is None
    before = dialog.preview._zoom
    event = Mock()
    event.angleDelta.return_value = QPoint(0, 120)
    dialog.preview.wheelEvent(event)
    assert dialog.preview._zoom > before
    dialog.reject()
    assert avatars.image("agent") is None


@pytest.mark.parametrize("side", ["user", "agent"])
def test_choose_then_crop_enables_save_and_survives_refresh(desktop, side, tmp_path, monkeypatch):
    create, transport, _path, windows = desktop
    transport.offline = True
    _network, avatars, _chat = create()
    picture = Image.new("RGB", (256, 256), "blue")
    picture.paste("red", (0, 0, 128, 256))
    output = BytesIO()
    picture.save(output, format="PNG")
    original = "data:image/png;base64," + base64.b64encode(output.getvalue()).decode("ascii")
    avatars.save(side, original)
    dialog = AvatarSettingsDialog(avatars, side=side)
    windows.append(dialog)
    dialog.show()
    assert not dialog.save_button.isEnabled()
    assert dialog.current_avatar.isVisible()
    assert dialog.choose_button.isVisible() and dialog.choose_button.height() >= 40
    assert not dialog.preview.isVisible() and not dialog.hint_label.isVisible()
    assert not dialog.status_label.isVisible()
    source = tmp_path / "replacement.png"
    picture.save(source)
    monkeypatch.setattr("src.gui.avatar_settings_dialog.QFileDialog.getOpenFileName", lambda *_: (str(source), ""))
    QTest.mouseClick(dialog.choose_button, Qt.MouseButton.LeftButton)
    assert dialog.preview.isVisible() and dialog.hint_label.isVisible()
    preview = dialog.preview
    wheel = QWheelEvent(
        QPointF(140, 140),
        QPointF(preview.mapToGlobal(QPoint(140, 140))),
        QPoint(),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(preview, wheel)
    assert dialog.save_button.isEnabled()
    QTest.mousePress(preview, Qt.MouseButton.LeftButton, pos=QPoint(140, 140))
    QTest.mouseMove(preview, QPoint(240, 140))
    QTest.mouseRelease(preview, Qt.MouseButton.LeftButton, pos=QPoint(240, 140))
    assert preview._offset.x() > 0
    avatars.changed.emit()
    assert preview._zoom > 1 and preview._offset.x() > 0
    assert avatars.image(side) == original
    dialog.save_button.click()
    saved = Image.open(BytesIO(base64.b64decode(avatars.image(side).split(",", 1)[1])))
    assert saved.size == (256, 256)
    assert saved.getpixel((128, 128))[:3] == (255, 0, 0)
    assert avatars.image("agent" if side == "user" else "user") is None


def test_desktop_avatar_is_round_and_preview_dims_only_outside_circle(qapp):
    label = AvatarLabel("user", size=100)
    label.set_image(image_uri("red"))
    rendered = label.pixmap().toImage()
    assert rendered.pixelColor(0, 0).alpha() == 0
    assert rendered.pixelColor(50, 50).name() == "#ff0000"
    preview = AvatarCropPreview()
    preview.set_source(image_uri("red"))
    rendered = preview.grab().toImage()
    assert rendered.pixelColor(140, 140).red() == 255
    assert 0 < rendered.pixelColor(10, 10).red() < 128


def test_avatar_editor_choose_visible_at_small_size_and_restore_hides_crop(desktop, tmp_path, monkeypatch):
    create, _transport, _path, windows = desktop
    _network, avatars, _chat = create()
    dialog = AvatarSettingsDialog(avatars, side="user")
    windows.append(dialog)
    dialog.resize(400, 420)
    dialog.show()
    QApplication.processEvents()
    assert dialog.rect().contains(dialog.choose_button.mapTo(dialog, QPoint(0, 0)))
    assert dialog.rect().contains(dialog.choose_button.mapTo(dialog, dialog.choose_button.rect().bottomRight()))
    source = tmp_path / "selected.png"
    Image.new("RGB", (400, 300), "blue").save(source)
    monkeypatch.setattr("src.gui.avatar_settings_dialog.QFileDialog.getOpenFileName", lambda *_: (str(source), ""))
    QTest.mouseClick(dialog.current_avatar, Qt.MouseButton.LeftButton)
    assert dialog.preview.isVisible() and dialog.save_button.isEnabled()
    dialog.restore_button.click()
    assert dialog.current_avatar.isVisible()
    assert not dialog.preview.isVisible() and not dialog.hint_label.isVisible()
    assert dialog.save_button.isEnabled()
    assert avatars.image("user") is None


def test_chat_default_matches_mobile_while_dynamic_keeps_its_resource(desktop):
    create, _transport, _path, windows = desktop
    _network, avatars, chat = create(chat=True)
    mobile = Path("../app/assets/images/icon.png").read_bytes()
    assert Path("res/gui/chat_agent_icon.png").read_bytes() == mobile
    bubble = chat.add_message("text", "hello", is_user=False)
    expected = AvatarLabel("agent", size=34)
    expected.set_image("data:image/png;base64," + base64.b64encode(mobile).decode("ascii"))
    assert not bubble.avatar_label.pixmap().isNull()
    assert bubble.avatar_label.pixmap().toImage() == expected.pixmap().toImage()
    dialog = AvatarSettingsDialog(avatars, side="agent")
    windows.append(dialog)
    assert dialog.current_avatar.default_agent == "res/gui/chat_agent_icon.png"
    for widget_type in (DynamicListItemWidget, DynamicPostWidget, DynamicCommentWidget):
        card = widget_type({"author_type": "agent"}, avatars=avatars)
        windows.append(card)
        label = card.findChild(AvatarLabel)
        assert label.default_agent == "res/gui/tianyi_icon.png"
        assert not label.pixmap().isNull()


def test_on_demand_checks_throttle_foreground_and_do_not_poll(desktop, monkeypatch, qapp):
    clock = [0.0]
    monkeypatch.setattr("src.gui.avatar_controller.monotonic", lambda: clock[0])
    create, transport, _path, _windows = desktop
    _network, avatars, _chat = create()
    wait_for(lambda: avatars.status == "头像已同步")
    before = len(transport.calls)
    transport.account().update(agent=image_uri("blue"), revision="99")
    clock[0] = 100
    QTest.qWait(50)
    assert len(transport.calls) == before
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    QTest.qWait(50)
    assert len(transport.calls) == before
    clock[0] = 300
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationInactive)
    qapp.applicationStateChanged.emit(Qt.ApplicationState.ApplicationActive)
    wait_for(lambda: avatars.image("agent") == image_uri("blue"))
    assert len(transport.calls) == before + 1
    clock[0] = 3600
    QTest.qWait(50)
    assert len(transport.calls) == before + 1


def test_editor_check_coalesces_and_save_uses_put_snapshot_without_get(desktop):
    create, transport, _path, windows = desktop
    _network, avatars, _chat = create()
    wait_for(lambda: avatars.status == "头像已同步")
    gate = transport.hold_next()
    before = len(transport.calls)
    dialog = AvatarSettingsDialog(avatars, side="agent")
    windows.append(dialog)
    wait_for(lambda: len(transport.calls) == before + 1)
    avatars.refresh()
    assert len(transport.calls) == before + 1
    gate.set()
    wait_for(lambda: avatars.status == "头像已同步")
    before = len(transport.calls)
    avatars.save("agent", image_uri("red"))
    wait_for(lambda: avatars.status == "头像已同步")
    assert [request.method for request, _ in transport.calls[before:]] == ["PUT"]
    assert avatars.store.server["pending"] == []


def test_only_pending_uploads_retry_with_finite_backoff_and_pause_in_background(desktop):
    create, transport, _path, _windows = desktop
    transport.offline = True
    _network, avatars, _chat = create()
    wait_for(lambda: "同步失败" in avatars.status)
    assert not avatars.retry_timer.isActive()  # 纯拉取失败不定时重试。
    avatars.save("user", image_uri("red"))
    wait_for(lambda: avatars.retry_timer.isActive())
    for expected in (10_000, 30_000, 120_000):
        assert avatars.retry_timer.interval() == expected
        before = len(transport.calls)
        avatars.retry_timer.stop()
        avatars.retry_timer.timeout.emit()
        wait_for(lambda: avatars._flight is None and len(transport.calls) == before + 1)
    assert not avatars.retry_timer.isActive()
    assert "自动重试" not in avatars.status
    assert avatars.store.server["pending"] == ["user"]
    avatars.refresh()  # 显式重试恢复重试预算。
    wait_for(lambda: avatars.retry_timer.isActive())
    avatars.set_foreground(False)
    assert not avatars.retry_timer.isActive()
    before = len(transport.calls)
    avatars.retry_timer.timeout.emit()
    QTest.qWait(30)
    assert len(transport.calls) == before
    transport.offline = False
    avatars.set_foreground(True)  # 待上传修改不受五分钟门槛限制。
    wait_for(lambda: avatars.status == "头像已同步")
    assert transport.account()["user"] == image_uri("red")
    assert not avatars.retry_timer.isActive()
