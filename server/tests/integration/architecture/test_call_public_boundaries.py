from src.stage.call_stage import CallIngressReceipt
import ast
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[3]


def test_websocket_root_contains_only_shared_contracts_and_chat_uses_public_call_protocol():
    root = SERVER_ROOT / "src/adapter/websocket"
    assert {p.name for p in root.glob("*.py")} == {"__init__.py", "connection.py"}
    for path in (root / "chat").glob("*.py"):
        module = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(module):
            if isinstance(node, ast.ImportFrom) and "call_v1" in (node.module or ""):
                assert node.module == "src.adapter.websocket.call_v1.chat_switch"
                assert all(not item.name.startswith("_") for item in node.names)


def _public_methods(path: Path, class_name: str) -> set[str]:
    module = ast.parse(path.read_text(encoding="utf-8"))
    target = next(node for node in module.body if isinstance(node, ast.ClassDef) and node.name == class_name)
    return {
        node.name
        for node in target.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_")
    }


def test_stage_manager_does_not_reexport_transitional_call_steps():
    public = _public_methods(SERVER_ROOT / "src/stage/stage_manager.py", "StageManager")

    assert {
        "stop_user_interactions",
        "take_call_claim",
        "fail_pending_call_claim",
        "create_call_stage",
        "current_call_ownership",
        "current_call_stage",
        "release_call",
    }.isdisjoint(public)
    assert {"initialize", "try_to_get_stage", "close"} <= public
    assert "start_call" not in public


def test_call_v1_package_exports_only_stable_facade_and_wire_contracts():
    init_path = SERVER_ROOT / "src/adapter/websocket/call_v1/__init__.py"
    module = ast.parse(init_path.read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in module.body
        if isinstance(node, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets)
    )
    exports = set(ast.literal_eval(assignment.value))

    assert {
        "Session",
        "Binding",
        "Delivery",
        "TransportConfig",
        "WireOutput",
        "InboundFrame",
        "_CallTransportHub",
        "_CallTransportSession",
        "_CallTransportBinding",
        "_CallStageBinding",
        "CallIngressReceipt",
        "_CallBusinessAcceptanceSink",
        "TransportConfig",
        "WireOutput",
        "InboundFrame",
    }.isdisjoint(exports)
    assert {"CallWebSocketAdapter", "CallCapabilityStatus", "CallTransportError"} <= exports


def test_web_call_entry_does_not_assemble_call_internals():
    source = (SERVER_ROOT / "src/web/websocket/call_endpoint.py").read_text(encoding="utf-8")

    for forbidden in (
        "_CallTransportHub",
        "_CallTransportSession",
        "_CallStageBinding",
        "CallStartClaim",
        "create_call_stage",
        "take_call_claim",
        "CallSettlement",
    ):
        assert forbidden not in source


def test_call_adapter_uses_only_the_complete_manager_open_facade():
    source = (SERVER_ROOT / "src/adapter/websocket/call_v1/adapter.py").read_text(encoding="utf-8")

    assert "infer_call_source_interaction" not in source
    assert "find_call_by_request" not in source
    assert "start_call" not in source


def test_stage_manager_does_not_control_adapter_binding_or_protocol_preparation():
    source = (SERVER_ROOT / "src/stage/stage_manager.py").read_text(encoding="utf-8")
    assert "src.adapter" not in source
    assert "transport.prepare(" not in source
    assert 'getattr(transport, "bind_stage"' not in source
    assert "self._adapter" not in source


def test_chat_and_call_have_the_same_network_operations_and_keep_protocol_internals_private():
    chat = _public_methods(SERVER_ROOT / "src/adapter/websocket/chat/adapter.py", "WebSocketAdapter")
    call = _public_methods(SERVER_ROOT / "src/adapter/websocket/call_v1/adapter.py", "CallWebSocketAdapter")
    network = {"open", "receive", "next_output", "complete_output", "disconnect", "close"}
    assert network <= chat & call
    assert chat - network == {"initialize", "output_sink", "detach_stage_binding"}
    assert call - network == {"capability_status", "supports_call_character", "submit_output"}
    for name in ("adapter.py", "_delivery.py", "_input.py", "_voice_upload_helper.py"):
        assert "src.web" not in (SERVER_ROOT / "src/adapter/websocket/chat" / name).read_text(encoding="utf-8")
    for name in ("session", "binding", "delivery", "protocol_translate", "input", "control", "audio_codec"):
        assert not (SERVER_ROOT / f"src/adapter/websocket/call_v1/{name}.py").exists()
        assert (SERVER_ROOT / f"src/adapter/websocket/call_v1/_{name}.py").is_file()


def test_call_adapter_keeps_delivery_inside_session_and_removes_legacy_assembly():
    root = SERVER_ROOT / "src/adapter/websocket/call_v1"
    assert not (root / "_transport.py").exists()
    assert not (root / "_stage_binding.py").exists()
    source = (root / "adapter.py").read_text(encoding="utf-8")
    assert "._delivery" not in source
    assert "_CallTransportHub" not in source
    assert "CallControl" not in (SERVER_ROOT / "src/stage/stage_manager.py").read_text(encoding="utf-8")
