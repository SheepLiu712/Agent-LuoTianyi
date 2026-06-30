import sys
from pathlib import Path
from types import SimpleNamespace

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.chat_session.chat_pipeline.chat_stream import ChatStream


def test_set_system_runtime_does_not_require_live_websocket_after_disconnect():
    ws_connection = SimpleNamespace(user_name="tester", user_uuid="user-1", websocket=object())
    stream = ChatStream({}, ws_connection, character_id="luotianyi")
    stream.lost_connection()

    stream.set_system_runtime(SimpleNamespace())

    assert stream.system_runtime is not None
    assert stream.ws_connection is None
