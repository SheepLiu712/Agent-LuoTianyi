import sys
from pathlib import Path

import requests

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.world.citywalk.amap_client import AMapClient
from src.world.citywalk.errors import AMapResponseError


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


def test_amap_client_retries_network_timeout(monkeypatch):
    client = AMapClient(
        {
            "amap": {
                "api_key": "test-key",
                "timeout_seconds": 20,
                "connect_timeout_seconds": 5,
                "max_retries": 2,
                "retry_backoff_seconds": 0.01,
            }
        }
    )
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        if len(calls) < 3:
            raise requests.ReadTimeout("slow amap")
        return FakeResponse({"status": "1", "pois": []})

    monkeypatch.setattr(client.session, "get", fake_get)
    monkeypatch.setattr("src.world.citywalk.amap_client.time.sleep", lambda *_: None)

    payload = client._request("/place/around", {"location": "120,30"})

    assert payload["status"] == "1"
    assert len(calls) == 3
    assert calls[0][2] == (5.0, 20.0)


def test_amap_client_does_not_retry_business_error(monkeypatch):
    client = AMapClient(
        {
            "amap": {
                "api_key": "test-key",
                "max_retries": 2,
            }
        }
    )
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url, params, timeout))
        return FakeResponse({"status": "0", "info": "INVALID_USER_KEY", "infocode": "10001"})

    monkeypatch.setattr(client.session, "get", fake_get)

    try:
        client._request("/place/around", {"location": "120,30"})
    except AMapResponseError as exc:
        assert "INVALID_USER_KEY" in str(exc)
    else:
        raise AssertionError("Expected AMapResponseError")

    assert len(calls) == 1
