"""模型基础设施公开 seam 的所有权测试。"""

from importlib.util import find_spec
from pathlib import Path


def test_model_modules_are_owned_by_infrastructure_and_websocket_adapter() -> None:
    """模型实现属于 infrastructure，客户端传输实现属于 WebSocket Adapter。"""
    assert find_spec("src.infrastructure.models.service") is not None
    assert find_spec("src.infrastructure.models.llm.module") is not None
    assert find_spec("src.infrastructure.models.vlm.module") is not None
    assert find_spec("src.adapter.websocket.client_model_executor") is not None

    server_root = Path(__file__).resolve().parents[4]
    assert not (server_root / "src/utils/llm_service.py").exists()
    assert not (server_root / "src/utils/llm").exists()
    assert not (server_root / "src/utils/vision").exists()
