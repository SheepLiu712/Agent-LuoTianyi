"""用户偏好存储兼容历史双重 JSON 编码。"""

import json

from src.infrastructure.persistence.database.services.user_store import UserStore


def test_user_store_preferences_normalize_double_encoded_json():
    payload = json.dumps(json.dumps({"relationship": "伙伴"}, ensure_ascii=False), ensure_ascii=False)

    assert UserStore.normalize_preferences(payload) == {"relationship": "伙伴"}
