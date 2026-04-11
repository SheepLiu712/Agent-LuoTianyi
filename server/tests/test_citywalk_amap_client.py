from unittest.mock import Mock

import pytest

from src.plugins.citywalk.amap_client import AMapClient
from src.plugins.citywalk.errors import AMapRequestError


def _build_client():
    cfg = {
        "amap": {
            "api_key": "mock_key",
            "base_url": "https://restapi.amap.com/v3",
            "timeout_seconds": 3,
            "max_retries": 0,
        }
    }
    return AMapClient(cfg)


def test_search_nearby_pois_success(monkeypatch):
    client = _build_client()
    fake_response = Mock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "status": "1",
        "pois": [
            {
                "id": "B0FFTEST",
                "name": "测试地点",
                "location": "116.3,39.9",
                "address": "测试地址",
                "distance": "120",
                "type": "餐饮",
            }
        ],
    }
    monkeypatch.setattr(client.session, "get", Mock(return_value=fake_response))

    pois = client.search_nearby_pois(location="116.3,39.9")
    assert len(pois) == 1
    assert pois[0].poi_id == "B0FFTEST"
    assert pois[0].distance_m == 120


def test_request_business_error(monkeypatch):
    client = _build_client()
    fake_response = Mock()
    fake_response.raise_for_status.return_value = None
    fake_response.json.return_value = {
        "status": "0",
        "info": "INVALID_USER_KEY",
        "infocode": "10001",
    }
    monkeypatch.setattr(client.session, "get", Mock(return_value=fake_response))

    with pytest.raises(AMapRequestError):
        client.search_nearby_pois(location="116.3,39.9")
