"""图像理解能力的模块所有权测试。"""

from importlib.util import find_spec
from pathlib import Path


def test_image_understanding_is_an_agent_skill() -> None:
    assert find_spec("src.agent.skills.cognitive.image_understanding") is not None
    server_root = Path(__file__).resolve().parents[3]
    assert not (server_root / "src/infrastructure/image_understanding").exists()
