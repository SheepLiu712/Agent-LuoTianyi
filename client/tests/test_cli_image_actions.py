import base64
import io
import threading

import pytest

from src.cli.actions import ActionExecutor, ExitCode
from src.cli.output import serialize_record
from src.session import HeadlessSession, SessionImageError, SessionNotReadyError, SessionState
from src.utils import image_rules


class FakeSession:
    def __init__(self):
        self.state = SessionState.READY
        self.select_ack = {"ok": True, "request_id": None, "error": None}
        self.cancel_ack = {"ok": True, "request_id": None, "error": None}
        self.send_ack = {"ok": True, "request_id": "c-1", "error": None}
        self.select_calls = 0
        self.cancel_calls = 0
        self.send_calls = []

    def select_image(self, *, ack_timeout=5.0):
        self.select_calls += 1
        return dict(self.select_ack)

    def cancel_image_selection(self, *, ack_timeout=5.0):
        self.cancel_calls += 1
        return dict(self.cancel_ack)

    def send_image(self, image_path, *, client_msg_id, ack_timeout=10.0):
        self.send_calls.append((str(image_path), client_msg_id, ack_timeout))
        return dict(self.send_ack)

    def close(self):
        self.state = SessionState.CLOSED


def _executor(session):
    executor = ActionExecutor(
        session_factory=lambda **_kwargs: session,
        session_id="session-image",
    )
    executor._session = session
    return executor


def _select(executor, path):
    return executor.execute({"action": "image.select", "params": {"path": str(path)}})


def _send(executor, path=None):
    params = {} if path is None else {"path": str(path)}
    return executor.execute({"action": "image.send", "params": params})


def _cancel(executor):
    return executor.execute({"action": "image.cancel", "params": {}})


def _png_bytes(payload=b""):
    return b"\x89PNG\r\n\x1a\n" + payload


def test_image_select_records_valid_file(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(_png_bytes(b"\x00" * 32))
    executor = _executor(FakeSession())

    record, exit_code = _select(executor, image)

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["selected"] is True
    assert record["data"]["reference"] == "photo.png"
    assert record["data"]["mime_type"] == "image/png"
    assert record["data"]["byte_count"] == image.stat().st_size


def test_image_select_sends_signal_before_local_validation(tmp_path):
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _select(executor, tmp_path / "missing.png")

    assert session.select_calls == 1
    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "IMAGE_FILE_NOT_FOUND"


def test_image_select_rejects_unsupported_type_and_clears_selection(tmp_path):
    valid = tmp_path / "photo.png"
    valid.write_bytes(_png_bytes())
    note = tmp_path / "note.txt"
    note.write_text("hello", encoding="utf-8")
    executor = _executor(FakeSession())
    assert _select(executor, valid)[1] == ExitCode.SUCCESS

    record, exit_code = _select(executor, note)

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "IMAGE_TYPE_UNSUPPORTED"
    send_record, send_exit = _send(executor)
    assert send_exit == ExitCode.INPUT_ERROR
    assert send_record["error"]["code"] == "IMAGE_NOT_SELECTED"


def test_image_select_rejects_oversized_file(tmp_path, monkeypatch):
    image = tmp_path / "big.png"
    image.write_bytes(_png_bytes(b"\x00" * 64))
    monkeypatch.setattr(image_rules, "MAX_IMAGE_BYTES", 16)
    executor = _executor(FakeSession())

    record, exit_code = _select(executor, image)

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "IMAGE_TOO_LARGE"


def test_image_select_empty_file_is_rejected(tmp_path):
    image = tmp_path / "empty.png"
    image.write_bytes(b"")
    executor = _executor(FakeSession())

    record, exit_code = _select(executor, image)

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "IMAGE_FILE_EMPTY"


def test_image_select_ack_failure_clears_previous_selection(tmp_path):
    first = tmp_path / "first.png"
    first.write_bytes(_png_bytes())
    second = tmp_path / "second.png"
    second.write_bytes(_png_bytes())
    session = FakeSession()
    executor = _executor(session)
    assert _select(executor, first)[1] == ExitCode.SUCCESS

    session.select_ack = {"ok": False, "error": "[OVERSIZE] rejected"}
    record, exit_code = _select(executor, second)

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == "ACK_REJECTED"
    send_record, send_exit = _send(executor)
    assert send_exit == ExitCode.INPUT_ERROR
    assert send_record["error"]["code"] == "IMAGE_NOT_SELECTED"


def test_image_cancel_clears_selection(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(_png_bytes())
    session = FakeSession()
    executor = _executor(session)
    assert _select(executor, image)[1] == ExitCode.SUCCESS

    record, exit_code = _cancel(executor)

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["selected"] is False
    assert session.cancel_calls == 1
    send_record, send_exit = _send(executor)
    assert send_exit == ExitCode.INPUT_ERROR
    assert send_record["error"]["code"] == "IMAGE_NOT_SELECTED"


def test_image_cancel_ack_failure_keeps_selection(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(_png_bytes())
    session = FakeSession()
    executor = _executor(session)
    assert _select(executor, image)[1] == ExitCode.SUCCESS
    session.cancel_ack = {"ok": False, "error": "[BAD_MESSAGE] invalid event"}

    record, exit_code = _cancel(executor)

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == "ACK_REJECTED"
    send_record, send_exit = _send(executor)
    assert send_exit == ExitCode.SUCCESS
    assert send_record["data"]["ack"] is True


def test_image_send_uses_current_selection_without_leaking_absolute_path(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(_png_bytes())
    session = FakeSession()
    executor = _executor(session)
    assert _select(executor, image)[1] == ExitCode.SUCCESS

    record, exit_code = _send(executor)
    output = serialize_record(record, executor.redactor)

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["ack"] is True
    assert len(session.send_calls) == 1
    sent_path, sent_id, sent_timeout = session.send_calls[0]
    assert sent_path == str(image)
    assert sent_id
    assert sent_timeout == 10.0
    assert record["correlation_id"] == sent_id
    assert str(tmp_path) not in output


def test_image_send_accepts_explicit_path_without_selection(tmp_path):
    image = tmp_path / "direct.jpg"
    image.write_bytes(_png_bytes(b"\x01" * 8))
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _send(executor, image)

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["ack"] is True
    assert session.send_calls[0][0] == str(image)


def test_image_send_without_selection_is_rejected(tmp_path):
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _send(executor)

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "IMAGE_NOT_SELECTED"
    assert session.send_calls == []


def test_image_send_ack_rejection_does_not_retry_with_new_message_id(tmp_path):
    image = tmp_path / "photo.png"
    image.write_bytes(_png_bytes())
    session = FakeSession()
    executor = _executor(session)
    assert _select(executor, image)[1] == ExitCode.SUCCESS
    session.send_ack = {"ok": False, "error": "[BAD_MESSAGE] rejected"}

    record, exit_code = _send(executor)

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == "ACK_REJECTED"
    assert len(session.send_calls) == 1


class FakeWsTransport:
    def __init__(self, *, ready=False):
        self._ready = threading.Event()
        if ready:
            self._ready.set()
        self.listener = None
        self.state_listener = None
        self.stopped = False

    def set_agent_message_listener(self, listener, state_listener, system_listener=None):
        self.listener = listener
        self.state_listener = state_listener

    def wait_until_ready(self, timeout):
        return self._ready.wait(timeout)

    def is_ready(self):
        return self._ready.is_set()

    def stop(self):
        self.stopped = True
        self._ready.clear()


class FakeNetworkClient:
    def __init__(self, *, ready=True):
        self.ws_transport = FakeWsTransport(ready=ready)
        self.image_calls = []
        self.select_calls = []
        self.cancel_calls = []

    def login(self, username, password, request_token=False):
        return True, "ok"

    def send_image_selecting(self, ack_timeout=5.0):
        self.select_calls.append(ack_timeout)
        return {"ok": True, "request_id": None, "error": None}

    def send_image_selecting_cancel(self, ack_timeout=5.0):
        self.cancel_calls.append(ack_timeout)
        return {"ok": True, "request_id": None, "error": None}

    def send_image(
        self,
        image_base64,
        mime_type,
        image_client_path=None,
        ack_timeout=10.0,
        client_msg_id=None,
    ):
        self.image_calls.append(
            {
                "image_base64": image_base64,
                "mime_type": mime_type,
                "image_client_path": image_client_path,
                "ack_timeout": ack_timeout,
                "client_msg_id": client_msg_id,
            }
        )
        return {"ok": True, "request_id": client_msg_id, "error": None}


def test_facade_image_methods_require_ready_state():
    session = HeadlessSession(base_url="http://test", network_client=FakeNetworkClient(ready=False))

    with pytest.raises(SessionNotReadyError):
        session.select_image()
    with pytest.raises(SessionNotReadyError):
        session.cancel_image_selection()
    with pytest.raises(SessionNotReadyError):
        session.send_image("whatever.png", client_msg_id="c-1")


def test_facade_select_cancel_send_delegate_and_encode(tmp_path):
    network = FakeNetworkClient(ready=True)
    session = HeadlessSession(base_url="http://test", network_client=network)
    session.connect("user", "pass")
    image = tmp_path / "photo.png"
    raw = _png_bytes(b"\x02" * 16)
    image.write_bytes(raw)

    assert session.select_image() == {"ok": True, "request_id": None, "error": None}
    assert session.cancel_image_selection() == {"ok": True, "request_id": None, "error": None}

    ack = session.send_image(image, client_msg_id="c-1")
    assert ack == {"ok": True, "request_id": "c-1", "error": None}
    assert network.select_calls == [5.0]
    assert network.cancel_calls == [5.0]
    assert len(network.image_calls) == 1
    call = network.image_calls[0]
    assert call["image_base64"] == base64.b64encode(raw).decode("utf-8")
    assert call["mime_type"] == "image/png"
    assert call["client_msg_id"] == "c-1"
    assert call["ack_timeout"] == 10.0
    temp_path = call["image_client_path"]
    assert temp_path and temp_path.endswith(".png")


def test_facade_send_image_raises_stable_error_for_unreadable_file(tmp_path):
    session = HeadlessSession(base_url="http://test", network_client=FakeNetworkClient(ready=True))
    session.connect("user", "pass")

    with pytest.raises(SessionImageError):
        session.send_image(tmp_path / "missing.png", client_msg_id="c-1")
