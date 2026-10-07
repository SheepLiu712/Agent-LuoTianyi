"""Exercise the real UI/binder/queue methods without loading Qt or audio devices."""

import ast
import threading
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from src.utils import image_encoding

ROOT = Path(__file__).resolve().parents[1]


def load_method(path, name, namespace):
    tree = ast.parse((ROOT / path).read_text(encoding="utf-8"))
    method = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == name)
    exec(compile(ast.Module(body=[method], type_ignores=[]), path, "exec"), namespace)
    return namespace[name]


def test_ui_failure_warns_and_cancels_without_bubble(tmp_path):
    path = tmp_path / "missing.jpg"
    warning = Mock()
    ui = SimpleNamespace(agent=Mock(), add_message=Mock(), can_send_pic=True)
    method = load_method(
        "src/gui/main_ui.py",
        "on_picture_clicked",
        {
            "QFileDialog": SimpleNamespace(getOpenFileName=lambda *args: (str(path), "")),
            "QMessageBox": SimpleNamespace(warning=warning),
            "prepare_image_payload": image_encoding.prepare_image_payload,
        },
    )
    method(ui)
    warning.assert_called_once()
    ui.agent.on_image_selecting_cancel.assert_called_once()
    ui.add_message.assert_not_called()
    ui.agent.on_send_image.assert_not_called()
    assert ui.can_send_pic


def test_ui_to_binder_to_queue_uses_prepared_payload_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    path = tmp_path / "image.jpg"
    path.write_bytes(b"original")
    processor = SimpleNamespace(
        _send_cond=threading.Condition(),
        _send_queue=[],
        _next_local_id=lambda kind: "image-1",
        _next_client_msg_id=lambda: "client-1",
        _prepare_image_payload=Mock(side_effect=AssertionError("must not read/compress twice")),
    )
    send = load_method(
        "src/message_process/message_processor.py",
        "send_image",
        {
            "OutgoingMessage": SimpleNamespace,
            "threading": threading,
        },
    )
    binder = SimpleNamespace(send_image_callback=lambda *a, **kw: send(processor, *a, **kw), msg_to_bubble={})
    on_send = load_method("src/gui/binder.py", "on_send_image", {})
    agent = Mock()
    agent.on_send_image = lambda *a, **kw: on_send(binder, *a, **kw)
    bubble = object()
    ui = SimpleNamespace(agent=agent, add_message=Mock(return_value=bubble), can_send_pic=True)
    prepare = Mock(wraps=image_encoding.prepare_image_payload)
    method = load_method(
        "src/gui/main_ui.py",
        "on_picture_clicked",
        {
            "QFileDialog": SimpleNamespace(getOpenFileName=lambda *args: (str(path), "")),
            "QMessageBox": SimpleNamespace(warning=Mock()),
            "prepare_image_payload": prepare,
        },
    )
    method(ui)
    prepare.assert_called_once()
    assert len(processor._send_queue) == 1
    payload = processor._send_queue[0].payload
    assert payload["image_base64"] == "b3JpZ2luYWw="
    assert payload["mime_type"] == "image/jpeg"
    ui.add_message.assert_called_once_with("image", payload["image_client_path"], is_user=True)
    assert binder.msg_to_bubble == {"image-1": bubble}
    assert not ui.can_send_pic
