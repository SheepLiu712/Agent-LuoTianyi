"""Speaking Skill 对完整 TTS 实现的所有权测试。"""

from importlib.util import find_spec
from pathlib import Path


def test_speaking_skill_owns_tts_implementation() -> None:
    assert find_spec("src.agent.skills.expression.speaking.backend") is not None
    assert find_spec("src.agent.skills.expression.speaking.streaming") is not None
    assert find_spec("src.agent.skills.expression.speaking.tts_server") is not None
    server_root = Path(__file__).resolve().parents[3]
    assert not (server_root / "src/infrastructure/speech").exists()
