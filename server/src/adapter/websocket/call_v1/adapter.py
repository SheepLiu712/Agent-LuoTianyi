"""Complete call.v1 connection facade hiding sessions, bindings, queues, and claims."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from uuid import uuid4

from src.domain.call import CallEndReason, CallState
from src.stage.stage_manager import (
    CallControl,
    CallStartFailed,
    InteractionFinalizing,
    StageManager,
)
from src.utils.logger import get_logger
from src.utils.owned_operation import complete_owned

from ..connection import AdapterConnection, OutboundDelivery
from ._control import _ControlProtocolError, _decode_control_text, _encode_control_message
from ._stage_binding import _CallStageBinding
from ._transport import (
    CallTransportError,
    _CallTransportBackpressure,
    _CallTransportBinding,
    _CallTransportHub,
    _CallTransportSession,
    _CallWireOutput,
)


@dataclass(frozen=True, slots=True)
class CallCapabilityStatus:
    enabled: bool
    trusted_host: bool
    provider_ready: bool
    call_tts_ready: bool
    summary_ready: bool
    settlement_ready: bool
    stage_binding_ready: bool
    recovery_ready: bool
    character_ids: tuple[str, ...] = ()

    @property
    def available(self) -> bool:
        return all(
            (
                self.enabled,
                self.trusted_host,
                self.provider_ready,
                self.call_tts_ready,
                self.summary_ready,
                self.settlement_ready,
                self.stage_binding_ready,
                self.recovery_ready,
                bool(self.character_ids),
            )
        )


class _ConnectionState:
    def __init__(self, binding, control, outputs) -> None:
        self.binding, self.control, self.outputs = binding, control, outputs
        self.inflight: set[str] = set()
        self.closed = asyncio.Event()
        self.taking: set[asyncio.Task] = set()


class _PreparedTransport(_CallStageBinding):
    _MAX_RESUME_PENDING_FRAMES = 256
    _MAX_RESUME_PENDING_BYTES = 4 * 1024 * 1024

    def __init__(self, adapter: "CallWebSocketAdapter", *, user_id: str, connection_id: object) -> None:
        self._adapter = adapter
        self._user_id = user_id
        self._connection_id = connection_id
        self.outputs: asyncio.Queue[_CallWireOutput] = asyncio.Queue(maxsize=512)
        self.binding: _CallTransportBinding | None = None
        self._preparing = True
        self._business_outputs_released = asyncio.Event()
        self._resume_pending: list[_CallWireOutput] | None = None
        self._resume_pending_bytes = 0
        super().__init__(call_id="pending", deliver=self._deliver, output_queue=self.outputs)

    async def _deliver(self, output: object) -> None:
        if not isinstance(output, _CallWireOutput):
            raise TypeError("call binding emitted an invalid wire output")
        if not self._preparing:
            await self._business_outputs_released.wait()
        if self._resume_pending is not None:
            payload = output.binary if output.binary is not None else output.text.encode("utf-8")
            if (
                len(self._resume_pending) >= self._MAX_RESUME_PENDING_FRAMES
                or self._resume_pending_bytes + len(payload) > self._MAX_RESUME_PENDING_BYTES
            ):
                raise _CallTransportBackpressure("RESUME_OUTPUT_BUFFER_FULL")
            self._resume_pending.append(output)
            self._resume_pending_bytes += len(payload)
            return
        self.outputs.put_nowait(output)

    def _begin_resume_outputs(self) -> None:
        if self._resume_pending is not None:
            raise CallTransportError("CALL_CONNECTION_ACTIVE", close_code=1008)
        self._resume_pending = []
        self._resume_pending_bytes = 0

    async def _commit_resume_outputs(self) -> None:
        pending = self._resume_pending or []
        self._resume_pending = None
        self._resume_pending_bytes = 0
        for output in pending:
            self.outputs.put_nowait(output)

    def _abort_resume_outputs(self) -> None:
        self._resume_pending = None
        self._resume_pending_bytes = 0

    def _require_stage(self):
        return self._control.stage

    async def accept(self, frame, receipt) -> bool:
        if frame.control is not None and frame.control["type"] == "call.hangup":
            await self._control.terminate()
            return True
        return await super().accept(frame, receipt)

    async def _prepare(self, control: CallControl) -> None:
        self._control = control
        identity = control.identity
        self.call_id = identity.call_id
        session = _CallTransportSession(
            call_id=identity.call_id,
            user_id=self._user_id,
            character_id=identity.character_id,
            sink=self,
            call_metrics=self._adapter._call_metrics,
        )
        self.bind_session(session)
        self.binding = await self._adapter._hub.register_and_attach_start(
            session, user_id=self._user_id, connection_id=self._connection_id
        )
        await self._deliver(
            session.send_control(
                {
                    "protocol": "call.v1",
                    "type": "call.state",
                    "seq": session.next_server_seq,
                    "call_id": identity.call_id,
                    "client_request_id": identity.client_request_id,
                    "state": CallState.PREPARING.value,
                }
            )
        )
        self._preparing = False

    async def _abort_prepare(self) -> None:
        if self._session is not None:
            await self._adapter._hub.unregister(self.call_id, expected_session=self._session)
        while not self.outputs.empty():
            self.outputs.get_nowait()
            self.outputs.task_done()


class CallWebSocketAdapter:
    """Own call.v1 establishment, restore, ordered receive, and transport release."""

    def __init__(
        self,
        *,
        manager: StageManager,
        user_reset_fence=None,
        call_metrics=None,
        enabled: bool = False,
        trusted_host: bool = True,
        provider_ready: bool = True,
        call_tts_character_ids=None,
        call_summary_character_ids=None,
        supports_character=None,
    ) -> None:
        self._manager = manager
        self._start_locks: dict[str, tuple[asyncio.Lock, int]] = {}
        self._call_metrics = call_metrics
        self._hub = _CallTransportHub(user_reset_fence=user_reset_fence)
        self._connections: dict[object, _ConnectionState] = {}
        self._open_tasks: set[asyncio.Task] = set()
        self._open_cancellations: dict[asyncio.Task, asyncio.Event] = {}
        self._enabled = enabled
        self._trusted_host = trusted_host
        self._provider_ready = provider_ready
        self._call_tts_character_ids = call_tts_character_ids
        self._call_summary_character_ids = call_summary_character_ids
        self._supports_character = supports_character
        self._closed = False

    @property
    def capability_status(self) -> CallCapabilityStatus:
        tts_ids = tuple(self._call_tts_character_ids()) if self._call_tts_character_ids is not None else ()
        summary_ids = tuple(self._call_summary_character_ids()) if self._call_summary_character_ids is not None else ()
        character_ids = tuple(character_id for character_id in tts_ids if character_id in frozenset(summary_ids))
        legacy_ready = self._supports_character is not None
        if legacy_ready and not character_ids:
            character_ids = ("*",)
        return CallCapabilityStatus(
            enabled=self._enabled,
            trusted_host=self._trusted_host,
            provider_ready=self._provider_ready,
            call_tts_ready=bool(tts_ids) or legacy_ready,
            summary_ready=bool(summary_ids) or legacy_ready,
            settlement_ready=self._manager.call_settlement_ready or legacy_ready,
            stage_binding_ready=not self._closed and not self._manager.is_closed(),
            recovery_ready=self._manager.call_recovery_ready or legacy_ready,
            character_ids=character_ids,
        )

    def supports_call_character(self, character_id: str) -> bool:
        status = self.capability_status
        if self._supports_character is not None:
            return status.available and self._supports_character(character_id)
        return status.available and character_id in status.character_ids

    async def open(
        self,
        *,
        user_id: str,
        connection_id: object,
        character_id: str | None = None,
        initial_message: str | bytes | None = None,
        capabilities: frozenset[str] = frozenset(),
    ) -> AdapterConnection:
        raw = initial_message
        if not isinstance(raw, str):
            raise CallTransportError("CALL_START_REQUIRED", close_code=1002)
        if self._closed or self._manager.is_closed() or not self.capability_status.available:
            raise CallTransportError("CALL_INGRESS_UNAVAILABLE", close_code=1013)
        try:
            message = _decode_control_text(raw, sender="client", transport="call_ws")
        except _ControlProtocolError as error:
            raise CallTransportError(error.code) from error
        if message["type"] == "call.start":
            cancelled = asyncio.Event()
            operation = self._open_start(
                message, raw=raw, user_id=user_id, connection_id=connection_id, cancelled=cancelled
            )
        elif message["type"] == "call.resume":
            cancelled = asyncio.Event()
            operation = self._open_resume(raw, user_id=user_id, connection_id=connection_id, cancelled=cancelled)
        else:
            raise CallTransportError("CALL_START_REQUIRED", close_code=1002)
        task = asyncio.create_task(operation, name="call-adapter-open")
        self._open_tasks.add(task)
        self._open_cancellations[task] = cancelled

        def _open_done(done: asyncio.Task) -> None:
            self._open_tasks.discard(done)
            self._open_cancellations.pop(done, None)

        task.add_done_callback(_open_done)
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            cancelled.set()
            await complete_owned(self._discard_cancelled_open(task))
            raise

    async def _discard_cancelled_open(self, task: asyncio.Task[AdapterConnection]) -> None:
        try:
            connection = await asyncio.shield(task)
        except BaseException:
            return
        await self.disconnect(connection)

    async def _open_start(self, message, *, raw, user_id, connection_id, cancelled):
        # Only identical requests serialize identity publication and protocol registration.
        key = str(message["client_request_id"])
        lock, users = self._start_locks.get(key, (asyncio.Lock(), 0))
        self._start_locks[key] = (lock, users + 1)
        try:
            async with lock:
                return await self._open_start_owned(
                    message, raw=raw, user_id=user_id, connection_id=connection_id, cancelled=cancelled
                )
        finally:
            _, users = self._start_locks[key]
            if users == 1:
                self._start_locks.pop(key)
            else:
                self._start_locks[key] = (lock, users - 1)

    # ruff: noqa: C901
    async def _open_start_owned(
        self, message, *, raw: str, user_id: str, connection_id: object, cancelled: asyncio.Event
    ) -> AdapterConnection:
        if int(message["seq"]) != 1:
            raise CallTransportError("CALL_START_REQUIRED", close_code=1002)
        character_id = str(message["character_id"])
        request_id = str(message["client_request_id"])
        request_seq = int(message["seq"])
        if not self.supports_call_character(character_id):
            raise self._start_error("CALL_CHARACTER_UNAVAILABLE", request_id, request_seq, close_code=1008)
        prepared_here = False
        try:
            transport = _PreparedTransport(self, user_id=user_id, connection_id=connection_id)
            control = await self._manager.try_to_get_stage(
                stage_type="call",
                user_id=user_id,
                character_id=character_id,
                client_request_id=request_id,
                transport=transport,
            )
            if self._hub.session_for(control.identity.call_id) is not None:
                try:
                    return await self._attach_existing_start(control, raw, user_id, connection_id)
                except CallTransportError as error:
                    raise self._start_error(
                        error.code,
                        request_id,
                        request_seq,
                        close_code=error.close_code,
                    ) from error
            prepared_here = True
            await transport._prepare(control)
            if cancelled.is_set():
                raise asyncio.CancelledError
            await self._enqueue(transport.outputs, await transport.binding.session.receive_start(raw))
            transport._business_outputs_released.set()
            control.release()
            return self._register_connection(transport.binding, control, transport.outputs)
        except CallTransportError as error:
            if prepared_here:
                await complete_owned(self._abort_unacknowledged_open(control, transport, error))
            raise
        except BaseException as error:
            if prepared_here:
                await complete_owned(self._abort_unacknowledged_open(control, transport, error))
            if isinstance(error, asyncio.CancelledError):
                raise
            raise self._normalize_start_error(error, request_id, request_seq) from error

    async def _abort_unacknowledged_open(
        self, control: CallControl, transport: _PreparedTransport, error: BaseException
    ) -> None:
        try:
            await transport._abort_prepare()
        finally:
            await self._manager.abort_open_call(control, error)

    async def _attach_existing_start(
        self, control: CallControl, raw: str, user_id: str, connection_id: object
    ) -> AdapterConnection:
        session = self._hub.session_for(control.identity.call_id)
        if session is None:
            raise CallTransportError("CALL_NOT_FOUND", close_code=1008)
        binding = await self._hub.attach_start(session, user_id=user_id, connection_id=connection_id)
        bridge = session.business_sink
        if not isinstance(bridge, _PreparedTransport):
            raise CallTransportError("CALL_BINDING_UNAVAILABLE", close_code=1013)
        self._replace_attempts(session, bridge.outputs)
        await self._enqueue(bridge.outputs, await session.receive_start(raw))
        await self._enqueue(bridge.outputs, session.replay_after(session.server_ack_cursor))
        bridge._business_outputs_released.set()
        return self._register_connection(binding, control, bridge.outputs)

    async def _open_resume(
        self, raw: str, *, user_id: str, connection_id: object, cancelled: asyncio.Event
    ) -> AdapterConnection:
        candidate = await self._hub.reserve_resume(raw, user_id=user_id, connection_id=connection_id)
        try:
            bridge = candidate.session.business_sink
            if not isinstance(bridge, _PreparedTransport):
                raise CallTransportError("CALL_RESUME_UNAVAILABLE", close_code=1008)
            message = _decode_control_text(raw, sender="client", transport="call_ws")
            cursor = int(message["last_contiguous_server_seq"])
            if cursor > candidate.session.last_server_seq:
                raise CallTransportError("INVALID_RESUME_CURSOR")
            candidate.session.preview_resume(cursor)  # Validate before business admission; snapshot again at commit.
            control = await self._manager.try_to_get_stage(
                stage_type="call",
                call_id=candidate.session.call_id,
                user_id=user_id,
                character_id=candidate.session.character_id,
            )
        except BaseException as error:
            await self._hub.release_resume(candidate)
            raise CallTransportError(str(error), close_code=1008) from error
        binding = await complete_owned(self._commit_resume(candidate, bridge, control, cursor, cancelled))
        return self._register_connection(binding, control, bridge.outputs)

    async def _commit_resume(self, candidate, bridge, control, cursor, cancelled) -> _CallTransportBinding:
        binding = None
        business_started = False
        bridge._begin_resume_outputs()
        try:
            outputs = candidate.session.preview_resume(cursor)
            binding = await self._hub.commit_resume(candidate)
            self._replace_attempts(binding.session, bridge.outputs)
            # Manager commit may publish ACTIVE before returning, so the flag must
            # be set before the await and covers every post-binding failure.
            business_started = True
            await self._manager.commit_call_resume(control)
            self._raise_if_resume_cancelled(cancelled)
            binding.session.commit_resume(cursor)
            self._raise_if_resume_cancelled(cancelled)
            await self._enqueue(bridge.outputs, outputs)
            self._raise_if_resume_cancelled(cancelled)
            await bridge._commit_resume_outputs()
            self._raise_if_resume_cancelled(cancelled)
            return binding
        except BaseException as error:
            bridge._abort_resume_outputs()
            if binding is None:
                await self._hub.release_resume(candidate)
            else:
                if business_started:
                    try:
                        try:
                            await self._abort_started_resume(control, error)
                        except Exception:
                            # A diagnostic failure must not replace the resume
                            # error or prevent mandatory registry cleanup.
                            pass
                    finally:
                        try:
                            await self._hub.unregister(binding.session.call_id, expected_session=binding.session)
                        except BaseException as cleanup_error:
                            try:
                                self._report_resume_cleanup_failure("registry", error, cleanup_error)
                            finally:
                                if not isinstance(cleanup_error, Exception):
                                    raise cleanup_error
                else:
                    try:
                        await self._hub.rollback_resume(binding)
                    except BaseException as cleanup_error:
                        self._log_resume_cleanup_failure("binding", error, cleanup_error)
                    finally:
                        try:
                            await self._hub.unregister(binding.session.call_id, expected_session=binding.session)
                        except BaseException as cleanup_error:
                            self._log_resume_cleanup_failure("registry", error, cleanup_error)
            raise

    async def _abort_started_resume(self, control: CallControl, original_error: BaseException) -> None:
        cleanup_error: BaseException | None = None

        async def terminate_owned() -> None:
            nonlocal cleanup_error
            try:
                await control.terminate(CallEndReason.SYSTEM_FAILURE)
            except BaseException as error:
                cleanup_error = error

        try:
            await complete_owned(terminate_owned())
        except asyncio.CancelledError:
            # complete_owned has already drained the wrapper. This cancellation
            # belongs to the outer resume waiter, not the termination itself.
            pass
        if cleanup_error is not None:
            try:
                self._report_resume_cleanup_failure("termination", original_error, cleanup_error)
            finally:
                if not isinstance(cleanup_error, Exception):
                    raise cleanup_error

    def _report_resume_cleanup_failure(
        self, kind: str, original_error: BaseException, cleanup_error: BaseException
    ) -> None:
        try:
            self._log_resume_cleanup_failure(kind, original_error, cleanup_error)
        except Exception:
            pass

    @staticmethod
    def _raise_if_resume_cancelled(cancelled: asyncio.Event) -> None:
        if cancelled.is_set():
            raise asyncio.CancelledError

    @staticmethod
    def _log_resume_cleanup_failure(kind: str, original_error: BaseException, cleanup_error: BaseException) -> None:
        try:
            get_logger(__name__).error(
                "Call resume %s cleanup failed original_type=%s cleanup_type=%s",
                kind,
                type(original_error).__name__,
                type(cleanup_error).__name__,
            )
        except Exception:
            pass

    async def receive(self, connection: AdapterConnection, message: str | bytes) -> None:
        state = self._state(connection)
        self._hub.require_current(state.binding)
        if isinstance(message, bytes):
            outputs = await state.binding.session.receive_binary(message)
        elif isinstance(message, str):
            try:
                control = _decode_control_text(message, sender="client", transport="call_ws")
            except _ControlProtocolError as error:
                raise CallTransportError(error.code) from error
            if control["type"] == "ack":
                self._hub.acknowledge_bound(state.binding, int(control["ack_seq"]))
                return
            outputs = await state.binding.session.receive_text(message)
        else:
            raise CallTransportError("INVALID_WEBSOCKET_FRAME")
        await self._enqueue(state.outputs, outputs)

    async def next_output(self, connection: AdapterConnection) -> OutboundDelivery:
        state = self._state(connection)
        self._hub.require_current(state.binding)
        output = await self._take_output(state)
        delivery_id = uuid4().hex
        state.inflight.add(delivery_id)
        return OutboundDelivery(delivery_id, output.text if output.text is not None else output.binary)

    @staticmethod
    async def _take_output(state):
        taking = asyncio.create_task(state.outputs.get())
        closing = asyncio.create_task(state.closed.wait())
        state.taking.add(taking)
        try:
            try:
                await asyncio.wait((taking, closing), return_when=asyncio.FIRST_COMPLETED)
                if state.closed.is_set():
                    raise ConnectionError("call connection is closed")
                output = taking.result()
            finally:
                taking.cancel()
                closing.cancel()
                await asyncio.gather(taking, closing, return_exceptions=True)
                state.taking.discard(taking)
        except BaseException:
            if not taking.cancelled() and taking.done() and taking.exception() is None:
                state.outputs.task_done()
            raise
        return output

    def complete_output(
        self, connection: AdapterConnection, delivery_id: str, *, error: Exception | None = None
    ) -> None:
        state = self._connections.get(connection._token)
        if state is None or delivery_id not in state.inflight:
            return
        state.inflight.remove(delivery_id)
        state.outputs.task_done()
        if error is not None:
            self._fail_attempts(state)

    async def disconnect(self, connection: AdapterConnection) -> None:
        state = self._connections.pop(connection._token, None)
        if state is None:
            return
        self._fail_attempts(state)
        if self._hub.is_current(state.binding):
            await self._hub.detach_after_disconnect(state.binding, state.control.disconnect)

    @staticmethod
    def _fail_attempts(state) -> None:
        state.closed.set()
        for taking in state.taking:
            taking.cancel()
        for _ in state.inflight:
            state.outputs.task_done()
        state.inflight.clear()
        while not state.outputs.empty():
            state.outputs.get_nowait()
            state.outputs.task_done()

    def _replace_attempts(self, session, outputs) -> None:
        for token, state in tuple(self._connections.items()):
            if state.binding.session is session:
                self._fail_attempts(state)
                self._connections.pop(token, None)
        while not outputs.empty():
            outputs.get_nowait()
            outputs.task_done()

    async def close(self) -> None:
        await complete_owned(self._close())

    async def _close(self) -> None:
        self._closed = True
        open_tasks = tuple(self._open_tasks)
        for task in open_tasks:
            self._open_cancellations[task].set()
        if open_tasks:
            await asyncio.gather(*open_tasks, return_exceptions=True)
        for state in tuple(self._connections.values()):
            self._fail_attempts(state)
        await self._hub.close()
        self._connections.clear()

    def _register_connection(self, binding, control, outputs) -> AdapterConnection:
        connection = AdapterConnection()
        token = connection._token
        state = _ConnectionState(binding, control, outputs)
        self._connections[token] = state
        self._own_release(state)
        return connection

    def _state(self, connection: AdapterConnection) -> _ConnectionState:
        state = self._connections.get(connection._token)
        if state is None or state.closed.is_set():
            raise CallTransportError("STALE_CALL_CONNECTION", close_code=1008)
        return state

    def _own_release(self, connection: _ConnectionState) -> None:
        session = connection.binding.session
        if getattr(session, "_release_owned", False):
            return
        session._release_owned = True
        self._hub.own_task(self._release_terminal(connection), name="call-adapter-release")

    async def _release_terminal(self, connection: _ConnectionState) -> None:
        session = connection.binding.session
        await connection.control.wait_realtime_stopped()
        bridge = session.business_sink
        try:
            if isinstance(bridge, _CallStageBinding):
                try:
                    await asyncio.wait_for(bridge.terminal_enqueued.wait(), timeout=2.0)
                except TimeoutError:
                    pass
            try:
                await asyncio.wait_for(connection.outputs.join(), timeout=2.0)
            except TimeoutError:
                pass
        finally:
            await self._hub.unregister(session.call_id, expected_session=session)

    @staticmethod
    async def _enqueue(queue: asyncio.Queue[_CallWireOutput], outputs: list[_CallWireOutput]) -> None:
        for output in outputs:
            queue.put_nowait(output)

    @staticmethod
    def _start_error(
        code: str,
        request_id: str,
        request_seq: int,
        *,
        retryable: bool = False,
        call_id: str | None = None,
        close_code: int = 1013,
    ) -> CallTransportError:
        error = CallTransportError(code, close_code=close_code)
        error.request_id = request_id
        error.request_seq = request_seq
        error.retryable = retryable
        error.call_id = call_id
        error.initial_message = _encode_control_message(
            {
                "protocol": "call.v1",
                "type": "error",
                "code": error.code,
                "message": "call start was not accepted",
                "retryable": retryable,
                "request_type": "call.start",
                "request_seq": request_seq,
                "client_request_id": request_id,
                **({} if call_id is None else {"call_id": call_id}),
            },
            sender="server",
            transport="call_ws",
        )
        return error

    @classmethod
    def _normalize_start_error(cls, error: Exception, request_id: str, request_seq: int) -> CallTransportError:
        if isinstance(error, InteractionFinalizing):
            return cls._start_error("INTERACTION_FINALIZING", request_id, request_seq, retryable=True)
        if isinstance(error, CallStartFailed):
            return cls._start_error("CALL_START_FAILED", request_id, request_seq, call_id=error.call_id)
        if isinstance(error, TimeoutError):
            return cls._start_error("CALL_START_TIMEOUT", request_id, request_seq, retryable=True)
        if str(error) in {
            "USER_DATA_RESET_IN_PROGRESS",
            "USER_DATA_RESET_INVALIDATED_OPERATION",
            "STAGE_MANAGER_CLOSED",
        }:
            return cls._start_error("CALL_START_UNAVAILABLE", request_id, request_seq, retryable=True)
        if isinstance(error, ValueError):
            return cls._start_error("CALL_START_REJECTED", request_id, request_seq)
        return cls._start_error("CALL_START_FAILED", request_id, request_seq)
