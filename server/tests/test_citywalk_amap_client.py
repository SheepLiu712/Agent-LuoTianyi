import json
from unittest.mock import Mock

import pytest

from src.plugins.citywalk.amap_client import AMapClient
from src.plugins.citywalk.config import load_citywalk_config
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


def test_citywalk_config_resolves_amap_key_from_env(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAP_KEY", "amap_key_from_env")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "citywalk": {
                    "amap": {
                        "api_key": "$AMAP_KEY",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    cfg = load_citywalk_config(str(cfg_path))

    assert cfg["amap"]["api_key"] == "amap_key_from_env"
    assert AMapClient(cfg).api_key == "amap_key_from_env"


def test_direct_json_load_keeps_placeholder_and_client_rejects_it(tmp_path, monkeypatch):
    monkeypatch.setenv("AMAP_KEY", "amap_key_from_env")
    cfg_path = tmp_path / "config.json"
    cfg_path.write_text(
        json.dumps(
            {
                "citywalk": {
                    "amap": {
                        "api_key": "$AMAP_KEY",
                    }
                }
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    # 直接 json.load 不会替换环境变量占位符。
    raw_cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
    assert raw_cfg["citywalk"]["amap"]["api_key"] == "$AMAP_KEY"

    with pytest.raises(AMapRequestError, match="AMap key is missing"):
        AMapClient(raw_cfg["citywalk"])
