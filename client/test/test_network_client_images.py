import sys
from pathlib import Path

import pytest


client_root = str(Path(__file__).resolve().parent.parent)
if client_root not in sys.path:
    sys.path.insert(0, client_root)

from src.network.network_client import NetworkClient
from src.types import ConversationItem


class RecordingLogger:
    def __init__(self):
        self.errors = []

    def error(self, message):
        self.errors.append(message)


class RaisingSession:
    def __init__(self, error):
        self.error = error

    def post(self, *args, **kwargs):
        raise self.error


class FatalImageDownload(BaseException):
    pass


def make_client(error):
    client = NetworkClient.__new__(NetworkClient)
    client.base_url = "https://example.invalid"
    client.verify_ssl = True
    client.user_id = "user-1"
    client.message_token = "token"
    client.logger = RecordingLogger()
    client.session = RaisingSession(error)
    return client


def make_item():
    return ConversationItem(
        timestamp="2026-08-01 00:00:00",
        source="agent",
        type="image",
        content="missing.png",
        uuid="image-1",
    )


def test_image_download_error_returns_original_item_and_logs_error():
    client = make_client(RuntimeError("network failed"))
    item = make_item()

    result = client._get_image_from_server(item)

    assert result is item
    assert len(client.logger.errors) == 1
    assert "network failed" in client.logger.errors[0]


def test_image_download_does_not_swallow_base_exception():
    client = make_client(FatalImageDownload("stop now"))

    with pytest.raises(FatalImageDownload, match="stop now"):
        client._get_image_from_server(make_item())
