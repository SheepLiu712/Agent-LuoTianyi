import json
import sys
from pathlib import Path

server_root = str(Path(__file__).resolve().parent.parent)
if server_root not in sys.path:
    sys.path.insert(0, server_root)

from src.agent.luotianyi_agent import LuoTianyiAgent
from src.system.database.database_service import DatabaseManager


class FakeLogger:
    def __init__(self):
        self.warnings = []

    def warning(self, message):
        self.warnings.append(message)


def test_database_preferences_normalize_double_encoded_json():
    payload = json.dumps(json.dumps({"relationship": "伙伴"}, ensure_ascii=False), ensure_ascii=False)

    assert DatabaseManager._normalize_preferences(payload) == {"relationship": "伙伴"}


def test_agent_preference_context_accepts_double_encoded_json_without_warning():
    agent = object.__new__(LuoTianyiAgent)
    agent.logger = FakeLogger()
    payload = json.dumps(json.dumps({"relationship": "伙伴"}, ensure_ascii=False), ensure_ascii=False)

    context = agent._build_preference_context(payload)

    assert "用户希望你是他的：伙伴" in context
    assert agent.logger.warnings == []
