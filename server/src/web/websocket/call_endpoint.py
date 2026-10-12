"""Authenticated physical ``call_ws`` ingress and CallStage transport binding."""

# ruff: noqa: C901

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from src.adapter.websocket.call_v1 import (
    CallStageBinding,
    CallTransportBinding,
    CallTransportError,
    CallTransportHub,
    CallTransportSession,
    CallWireOutput,
    ControlProtocolError,
    decode_control_text,
)
from src.application.admin import get_admin_shell
from src.domain.call import CallEndReason
from src.stage.stage_manager import CallStartFailed
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned

from .service import WebSocketConnection

if TYPE_CHECKING:
    from src.server_runtime import ServerRuntime

logger = get_logger(__name__)
router = APIRouter()


@router.websocket("/call_ws")
async def call_ws(websocket: WebSocket) -> None:  # noqa: C901 - lifecycle boundary has explicit cleanup paths
    try:
        await websocket.accept()
    except WebSocketDisconnect:
        return
    runtime: "ServerRuntime | None" = get_admin_shell().runtime_supervisor.runtime
    if runtime is None:
        await websocket.close(code=1013, reason="runtime not ready")
        return
    if not runtime.call_capability.available or runtime.call_transport_hub is None:
        await websocket.close(code=1013, reason="call transport unavailable")
        return
    connection = WebSocketConnection(websocket=websocket, user_uuid=None, user_name=None)
    binding: CallTransportBinding | None = None
    send_task: asyncio.Task[None] | None = None
    receive_task: asyncio.Task[None] | None = None
    output_queue: asyncio.Queue[CallWireOutput] | None = None
    stage = None
    try:
        binding, stage, output_queue = await _authenticate_and_attach(websocket, runtime, connection)
        if binding is not None:
            send_task = asyncio.create_task(
                _send_pump(websocket, runtime.call_transport_hub, binding, output_queue), name="call-ws-send-pump"
            )
            if stage is not None and output_queue is not None:
                runtime.call_transport_hub.own_task(
                    _release_terminal_session(runtime.call_transport_hub, binding.session, stage, output_queue),
                    name="call-transport-release",
                )
            receive_task = asyncio.create_task(
                _receive_call_frames(websocket, runtime.call_transport_hub, binding), name="call-ws-receive"
            )
            done, _ = await asyncio.wait((send_task, receive_task), return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected from /call_ws")
    except CallTransportError as error:
        logger.warning("Call WebSocket protocol failure code=%s", error.code)
        await _close_protocol_error(websocket, error)
    except Exception as error:  # noqa: BLE001 - physical connection boundary normalizes unexpected failures
        logger.error("Call WebSocket failed type=%s", type(error).__name__)
        await websocket.close(code=1011, reason="internal call transport error")
    finally:
        tasks = tuple(task for task in (send_task, receive_task) if task is not None)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if binding is not None:
            if stage is not None:
                await runtime.call_transport_hub.detach_after_disconnect(binding, stage.disconnect)
            else:
                await runtime.call_transport_hub.detach(binding)


async def _authenticate_and_attach(
    websocket: WebSocket,
    runtime: "ServerRuntime",
    connection: WebSocketConnection,
) -> tuple[CallTransportBinding | None, object | None, asyncio.Queue[CallWireOutput] | None]:  # noqa: C901
    await runtime.websocket_service.send_system_ready_event(websocket)
    authenticated = await connection.auth(runtime.websocket_service, runtime.database_manager)
    if not authenticated:
        return None, None, None
    first = await websocket.receive()
    if first.get("type") == "websocket.disconnect":
        return None, None, None
    raw = first.get("text")
    if not isinstance(raw, str):
        await websocket.close(code=1002, reason="first call control text frame required")
        return None, None, None
    try:
        message = decode_control_text(raw, sender="client", transport="call_ws")
    except ControlProtocolError as error:
        raise CallTransportError(error.code) from error
    if message["type"] == "call.resume":
        binding = await runtime.call_transport_hub.attach_resume(
            raw, user_id=connection.user_uuid or "", connection_id=connection
        )
        manager = getattr(runtime, "stage_manager", None)
        stage = manager.current_call_stage(binding.session.call_id) if manager is not None else None
        bridge = binding.session.business_sink
        output_queue = bridge.output_queue if isinstance(bridge, CallStageBinding) else None
        async with _handshake_ownership(runtime.call_transport_hub, binding, stage, output_queue):
            _require_current(runtime.call_transport_hub, binding)
            await _send_bound_outputs(
                websocket, runtime.call_transport_hub, binding, await binding.session.receive_text(raw)
            )
            if stage is not None and not await stage.resume():
                raise CallTransportError("CALL_RESUME_UNAVAILABLE", close_code=1008)
            return binding, stage, output_queue or asyncio.Queue()
    if message["type"] != "call.start" or int(message["seq"]) != 1:
        raise CallTransportError("CALL_START_REQUIRED", close_code=1002)
    stage_manager = getattr(runtime, "stage_manager", None)
    if stage_manager is None or runtime.realtime_speech_factory is None or runtime.call_settlement_coordinator is None:
        raise CallTransportError("CALL_INGRESS_UNAVAILABLE", close_code=1013)
    user_id, character_id = connection.user_uuid or "", str(message["character_id"])
    supports_character = getattr(runtime, "supports_call_character", None)
    if supports_character is not None and not supports_character(character_id):
        await websocket.send_text(
            _call_start_error(
                request_id=str(message["client_request_id"]),
                request_seq=int(message["seq"]),
                code="CALL_CHARACTER_UNAVAILABLE",
            )
        )
        raise CallTransportError("CALL_CHARACTER_UNAVAILABLE", close_code=1008)
    request_id = str(message["client_request_id"])
    source = await stage_manager.infer_call_source_interaction(user_id=user_id, character_id=character_id)
    binding = None
    try:
        claim = await stage_manager.start_call(
            user_id=user_id, character_id=character_id, source_interaction_id=source, client_request_id=request_id
        )
    except Exception as error:
        await websocket.send_text(
            _call_start_error(
                request_id=request_id,
                request_seq=int(message["seq"]),
                code=_call_start_error_code(error),
                call_id=error.call_id if isinstance(error, CallStartFailed) else None,
            )
        )
        raise CallTransportError("CALL_START_FAILED", close_code=1013) from error
    call_id = str(claim.record.call_id)
    existing = stage_manager.current_call_stage(call_id)
    if existing is not None:
        session = runtime.call_transport_hub.session_for(call_id)
        if session is None:
            raise CallTransportError("CALL_TRANSPORT_MISSING")
        binding = await runtime.call_transport_hub.attach_start(session, user_id=user_id, connection_id=connection)
        bridge = session.business_sink
        output_queue = bridge.output_queue if isinstance(bridge, CallStageBinding) else None
        async with _handshake_ownership(runtime.call_transport_hub, binding, existing, output_queue):
            await _send_bound_outputs(websocket, runtime.call_transport_hub, binding, await session.receive_start(raw))
            if output_queue is None:
                raise CallTransportError("CALL_BINDING_UNAVAILABLE", close_code=1013)
            return binding, existing, output_queue
    outputs: asyncio.Queue[CallWireOutput] = asyncio.Queue()

    async def deliver(output: object) -> None:
        if not isinstance(output, CallWireOutput):
            raise TypeError("call binding emitted an invalid wire output")
        await outputs.put(output)

    bridge = CallStageBinding(call_id=call_id, deliver=deliver, output_queue=outputs)
    session = CallTransportSession(
        call_id=call_id,
        user_id=user_id,
        character_id=character_id,
        sink=bridge,
        call_metrics=runtime.call_metrics,
    )
    bridge.bind_session(session)
    create_started = False
    try:
        binding = await runtime.call_transport_hub.register_and_attach_start(
            session, user_id=user_id, connection_id=connection
        )
        await _send_bound_outputs(
            websocket,
            runtime.call_transport_hub,
            binding,
            [
                session.send_control(
                    {
                        "protocol": "call.v1",
                        "type": "call.state",
                        "seq": session.next_server_seq,
                        "call_id": call_id,
                        "client_request_id": request_id,
                        "state": "preparing",
                    }
                )
            ],
        )
        create_started = True
        stage = await stage_manager.create_call_stage(
            claim,
            user_id=user_id,
            character_id=character_id,
            client_request_id=request_id,
            speech_factory=runtime.realtime_speech_factory,
            transport=bridge,
            settlement_sink=runtime.call_settlement_coordinator,
            call_metrics=runtime.call_metrics,
        )
    except BaseException as original_error:
        await complete_owned(
            _cleanup_failed_start(
                websocket=websocket,
                runtime=runtime,
                stage_manager=stage_manager,
                claim=claim,
                bridge=bridge,
                session=session,
                binding=binding,
                outputs=outputs,
                create_started=create_started,
                original_error=original_error,
            )
        )
        raise
    async with _handshake_ownership(runtime.call_transport_hub, binding, stage, outputs):
        _require_current(runtime.call_transport_hub, binding)
        await _send_bound_outputs(
            websocket, runtime.call_transport_hub, binding, await binding.session.receive_start(raw)
        )
        return binding, stage, outputs


@asynccontextmanager
async def _handshake_ownership(hub, binding, stage, outputs):
    """Release an attachment if the handshake never transfers it to call_ws."""
    try:
        yield
    except BaseException:
        if stage is not None:
            # A newly created Stage must also release its session after recovery
            # expires, even when its first ACK never reached the physical socket.
            if outputs is not None:
                hub.own_task(
                    _release_terminal_session(hub, binding.session, stage, outputs),
                    name="call-handshake-release",
                )
            await complete_owned(_disconnect_failed_handshake(hub, binding, stage))
        else:
            await complete_owned(hub.detach(binding))
        raise


async def _disconnect_failed_handshake(hub, binding, stage):
    try:
        if hub.is_current(binding):
            await stage.disconnect()
    finally:
        # detach checks generation again, including if Stage cleanup failed.
        await hub.detach(binding)


async def _send_pump(
    websocket: WebSocket, hub: CallTransportHub, binding: CallTransportBinding, outputs: asyncio.Queue[CallWireOutput]
) -> None:
    while True:
        output = await outputs.get()
        try:
            await _send_bound_outputs(websocket, hub, binding, [output])
        finally:
            outputs.task_done()


async def _release_terminal_session(
    hub: CallTransportHub,
    session: CallTransportSession,
    stage: object,
    outputs: asyncio.Queue[CallWireOutput],
) -> None:
    await stage.wait_closed()
    try:
        bridge = session.business_sink
        if isinstance(bridge, CallStageBinding):
            try:
                await asyncio.wait_for(bridge.terminal_delivered.wait(), timeout=2.0)
            except (TimeoutError, asyncio.TimeoutError):
                pass
        try:
            await asyncio.wait_for(outputs.join(), timeout=2.0)
        except (TimeoutError, asyncio.TimeoutError):
            pass
    finally:
        await hub.unregister(session.call_id, expected_session=session)


async def _cleanup_failed_start(
    *,
    websocket: WebSocket,
    runtime: "ServerRuntime",
    stage_manager,
    claim,
    bridge: CallStageBinding,
    session: CallTransportSession,
    binding: CallTransportBinding | None,
    outputs: asyncio.Queue[CallWireOutput],
    create_started: bool,
    original_error: BaseException,
) -> None:
    try:
        if not create_started:
            try:
                await stage_manager.fail_pending_call_claim(claim, original_error)
            except BaseException as cleanup_error:
                logger.error("Pending call cleanup failed type=%s", type(cleanup_error).__name__)
        if not bridge.terminal_delivered.is_set():
            try:
                reason = (
                    CallEndReason.SETUP_TIMEOUT
                    if isinstance(original_error, TimeoutError)
                    else CallEndReason.SYSTEM_FAILURE
                )
                await bridge.send_failed(reason)
            except BaseException as cleanup_error:
                logger.error("Call setup error delivery failed type=%s", type(cleanup_error).__name__)
        while binding is not None and not outputs.empty():
            output = outputs.get_nowait()
            try:
                await _send_bound_outputs(websocket, runtime.call_transport_hub, binding, [output])
            except BaseException as cleanup_error:
                logger.error("Call setup output drain failed type=%s", type(cleanup_error).__name__)
            finally:
                outputs.task_done()
    finally:
        await runtime.call_transport_hub.unregister(session.call_id, expected_session=session)


async def _receive_call_frames(
    websocket: WebSocket,
    hub: CallTransportHub,
    binding: CallTransportBinding,
) -> None:
    while True:
        _require_current(hub, binding)
        event = await websocket.receive()
        if event.get("type") == "websocket.disconnect":
            return
        text = event.get("text")
        binary = event.get("bytes")
        if isinstance(text, str):
            outputs = await _receive_bound_text(hub, binding, text)
        elif isinstance(binary, bytes):
            outputs = await binding.session.receive_binary(binary)
        else:
            raise CallTransportError("INVALID_WEBSOCKET_FRAME")
        _require_current(hub, binding)
        await _send_bound_outputs(websocket, hub, binding, outputs)


async def _receive_bound_text(
    hub: CallTransportHub,
    binding: CallTransportBinding,
    raw: str,
) -> list[CallWireOutput]:
    try:
        message = decode_control_text(raw, sender="client", transport="call_ws")
    except ControlProtocolError as error:
        raise CallTransportError(error.code) from error
    if message["type"] == "ack":
        hub.acknowledge_bound(binding, int(message["ack_seq"]))
        return []
    return await binding.session.receive_text(raw)


def _require_current(hub: CallTransportHub, binding: CallTransportBinding) -> None:
    if not hub.is_current(binding):
        raise CallTransportError("STALE_CALL_CONNECTION", close_code=1008)


async def _send_bound_outputs(
    websocket: WebSocket,
    hub: CallTransportHub,
    binding: CallTransportBinding,
    outputs: list[CallWireOutput],
) -> None:
    for output in outputs:
        _require_current(hub, binding)
        if output.text is not None:
            await websocket.send_text(output.text)
        else:
            await websocket.send_bytes(output.binary or b"")


async def _close_protocol_error(websocket: WebSocket, error: CallTransportError) -> None:
    try:
        await websocket.close(code=error.close_code, reason=error.code[:123])
    except WebSocketDisconnect:
        pass


def _call_start_error(*, request_id: str, request_seq: int, code: str, call_id: str | None = None) -> str:
    from src.adapter.websocket.call_v1 import encode_control_message

    message = {
        "protocol": "call.v1",
        "type": "error",
        "code": code,
        "message": "call start was not accepted",
        "retryable": code in {"CALL_START_TIMEOUT", "CALL_START_UNAVAILABLE"},
        "request_type": "call.start",
        "request_seq": request_seq,
        "client_request_id": request_id,
    }
    if call_id is not None:
        message["call_id"] = call_id
    return encode_control_message(
        message,
        sender="server",
        transport="call_ws",
    )


def _call_start_error_code(error: Exception) -> str:
    if isinstance(error, CallStartFailed):
        return "CALL_START_FAILED"
    if isinstance(error, TimeoutError):
        return "CALL_START_TIMEOUT"
    if str(error) in {"USER_DATA_RESET_IN_PROGRESS", "USER_DATA_RESET_INVALIDATED_OPERATION"}:
        return "CALL_START_UNAVAILABLE"
    if isinstance(error, ValueError):
        return "CALL_START_REJECTED"
    return "CALL_START_FAILED"
