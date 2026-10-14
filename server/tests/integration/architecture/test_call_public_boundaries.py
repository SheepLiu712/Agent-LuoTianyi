import ast
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[3]


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
    assert {"initialize", "open_call", "resume_call", "commit_call_resume", "close"} <= public
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
        "CallTransportHub",
        "CallTransportSession",
        "CallTransportBinding",
        "CallStageBinding",
        "CallAcceptanceReceipt",
        "CallBusinessAcceptanceSink",
        "CallTransportConfig",
        "CallWireOutput",
        "InboundCallFrame",
    }.isdisjoint(exports)
    assert {"CallWebSocketAdapter", "CallConnection", "CallCapabilityStatus", "CallTransportError"} <= exports


def test_web_call_entry_does_not_assemble_call_internals():
    source = (SERVER_ROOT / "src/web/websocket/call_endpoint.py").read_text(encoding="utf-8")

    for forbidden in (
        "CallTransportHub",
        "CallTransportSession",
        "CallStageBinding",
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
