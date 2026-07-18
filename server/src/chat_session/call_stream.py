from __future__ import annotations

import asyncio
import json
import time
import uuid
from dataclasses import replace
from datetime import datetime
from typing import Any

from src.chat_session.call_context_builder import CallContextBuilder
from src.chat_session.call_memory_pool import CallMemoryPool
from src.chat_session.call_models import CallExitCode, CallResponseState, CallState, CallTTSLine, CallTurnDraft
from src.chat_session.call_response_parser import CallResponseParser
from src.chat_session.call_settlement import CallSettlementCoordinator
from src.chat_session.dependency.global_speaking_worker import GlobalSpeakingWorker, SpeakingJob
from src.system.user_interface.types import WSEventType, WSMessage
from src.utils.realtime_dialogue import RealtimeToolDefinition
from src.utils.realtime_dialogue.models import RealtimeEvent, RealtimeEventType
from src.utils.logger import get_logger


class CallStream:
    def __init__(
        self,
        *,
        call_id: str,
        user_id: str,
        user_name: str,
        character_id: str,
        ws_connection,
        config: dict[str, Any],
        realtime_dialogue_service,
        conversation_service,
        global_speaking_worker: GlobalSpeakingWorker,
        agent_runtime,
        call_store,
        llm_service=None,
        observability=None,
    ) -> None:
        self.call_id = call_id
        self.user_id = user_id
        self.user_name = user_name
        self.character_id = character_id
        self.ws_connection = ws_connection
        self.config = config or {}
        self.realtime_dialogue_service = realtime_dialogue_service
        self.conversation_service = conversation_service
        self.global_speaking_worker = global_speaking_worker
        self.agent_runtime = agent_runtime
        self.call_store = call_store
        self.observability = observability
        self.logger = get_logger("CallStream")

        self.state = CallState.REQUESTING
        self.requested_at = datetime.now()
        self.connected_at: datetime | None = None
        self.ended_at: datetime | None = None
        self.exit_code: int | None = None
        self.session = None
        self.provider_task: asyncio.Task | None = None
        self._prepare_task: asyncio.Task | None = None
        self._state_lock = asyncio.Lock()
        self._end_lock = asyncio.Lock()
        self._send_lock = asyncio.Lock()
        self._hangup_event = asyncio.Event()
        self._end_event = asyncio.Event()
        self._current_response_id: str | None = None
        self._responses: dict[str, CallResponseState] = {}
        self._audio_lines: dict[str, CallTTSLine] = {}
        self._turn_seq = 0
        self._next_tts_seq = 0
        self._next_audio_seq = 0
        self._last_speech_stopped_at: float | None = None
        self._interrupt_started_at: dict[str, float] = {}
        self._playback_ack_tasks: dict[str, asyncio.Task] = {}
        self._sent_audio_ids: set[str] = set()
        self._reconnect_deadline: float | None = None
        self._audio_tasks: set[asyncio.Task] = set()
        self._parser = CallResponseParser(call_id)
        self._context_builder = CallContextBuilder(
            agent_runtime=agent_runtime,
            conversation_service=conversation_service,
            config=self.config.get("context", {}),
        )
        self._memory_pool: CallMemoryPool | None = None
        self._turns: list[dict[str, Any]] = []
        self._settlement = CallSettlementCoordinator(
            config=self.config.get("settlement", {}),
            llm_service=llm_service,
            call_store=call_store,
            agent_runtime=agent_runtime,
            character_id=character_id,
            observability=observability,
        )
        self._postprocess_task: asyncio.Task | None = None
        self._proactive_task: asyncio.Task | None = None
        self._pending_function_calls: set[str] = set()

    @property
    def stream_id(self) -> str:
        return f"call:{self.call_id}"

    @property
    def is_blocking_chat(self) -> bool:
        return self.state in {CallState.REQUESTING, CallState.ACTIVE, CallState.RECONNECTING}

    async def start(self) -> None:
        await self._send_event(
            WSEventType.CALL_REQUESTED,
            {
                "call_id": self.call_id,
                "requested_at": self.requested_at.isoformat(),
                "accept_after_ms": int(float(self.config.get("request_delay_seconds", 2)) * 1000),
            },
        )
        self._record_call_event(
            "call.requested",
            metadata={"accept_after_ms": int(float(self.config.get("request_delay_seconds", 2)) * 1000)},
        )
        delay_task = asyncio.create_task(asyncio.sleep(float(self.config.get("request_delay_seconds", 2))))
        self._prepare_task = asyncio.create_task(self._prepare_provider())
        hangup_task = asyncio.create_task(self._hangup_event.wait())
        try:
            while True:
                done, _ = await asyncio.wait(
                    {delay_task, self._prepare_task, hangup_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if hangup_task in done:
                    await self._cancel_task(self._prepare_task)
                    await self.end(CallExitCode.HANGUP_BEFORE_CONNECTED, "user_hangup_before_connected")
                    return
                if self._prepare_task in done:
                    try:
                        await self._prepare_task
                    except Exception as exc:
                        self.logger.exception("call provider preparation failed: call_id=%s", self.call_id)
                        if self._hangup_event.is_set():
                            await self.end(CallExitCode.HANGUP_BEFORE_CONNECTED, "user_hangup_before_connected")
                        else:
                            await self.end(CallExitCode.REALTIME_PROVIDER_FAILED, str(exc))
                        return
                    if delay_task in done:
                        break
                if delay_task in done:
                    if self._prepare_task.done():
                        await self._prepare_task
                        break
        finally:
            if not delay_task.done():
                delay_task.cancel()
            if not hangup_task.done():
                hangup_task.cancel()

        async with self._state_lock:
            if self.state != CallState.REQUESTING:
                return
            self.connected_at = datetime.now()
            created = await asyncio.to_thread(
                self.call_store.create_active_session,
                call_id=self.call_id,
                user_id=self.user_id,
                character_id=self.character_id,
                requested_at=self.requested_at,
                connected_at=self.connected_at,
            )
            if not created:
                await self.end(CallExitCode.INTERNAL_ERROR, "call_session_create_failed")
                return
            self._transition(CallState.ACTIVE, expected={CallState.REQUESTING})
            self._memory_pool = CallMemoryPool(
                session=self.session,
                limit=int(self.config.get("memory_pool_limit", 10)),
            )
        await self._send_event(
            WSEventType.CALL_CONNECTED,
            {"call_id": self.call_id, "connected_at": self.connected_at.isoformat()},
        )
        self._record_call_event(
            "call.connected",
            duration_ms=(self.connected_at - self.requested_at).total_seconds() * 1000,
        )
        self.provider_task = asyncio.create_task(self._read_provider_events())

    async def _prepare_provider(self) -> None:
        context = await self._context_builder.build(user_id=self.user_id, character_id=self.character_id)
        tools = [
            RealtimeToolDefinition(
                name="search_memory",
                description="检索洛天依与当前用户相关的长期记忆。",
                parameters={
                    "type": "object",
                    "properties": {"queries": {"type": "array", "items": {"type": "string"}, "maxItems": 5}},
                    "required": ["queries"],
                },
            )
        ]
        self.session = await self.realtime_dialogue_service.create_session(
            trace_id=f"call-{self.call_id}",
            call_id=self.call_id,
            instructions=context.system_prompt,
            tools=tools,
        )
        await self.session.connect()
        await self.session.append_context_item(role="user", text=context.recent_history_item, item_id=f"call-history-{self.call_id}")
        await self.session.append_context_item(role="user", text=context.start_request_item, item_id=f"call-start-{self.call_id}")

    async def handle_client_event(self, event: WSMessage) -> None:
        payload = event.payload or {}
        if event.event_type == WSEventType.CALL_AUDIO_APPEND.value:
            if self.state != CallState.ACTIVE:
                return
            audio = payload.get("audio")
            if isinstance(audio, str) and audio:
                task = asyncio.create_task(self._append_audio(int(payload.get("seq", 0)), audio))
                self._audio_tasks.add(task)
                task.add_done_callback(self._audio_tasks.discard)
            return
        if event.event_type == WSEventType.CALL_HANGUP.value:
            await self.hangup()
            return
        if event.event_type == WSEventType.CALL_PLAYBACK_COMPLETED.value:
            await self._playback_completed(payload)
            return
        if event.event_type == WSEventType.CALL_PLAYBACK_STOPPED.value:
            await self._playback_stopped(payload)
            return

    async def _append_audio(self, seq: int, audio: str) -> None:
        if self.state != CallState.ACTIVE or self.session is None:
            return
        if seq < self._next_audio_seq:
            return
        if seq > self._next_audio_seq:
            self.logger.warning(
                "call audio sequence gap: call_id=%s expected=%s got=%s",
                self.call_id,
                self._next_audio_seq,
                seq,
            )
        self._next_audio_seq = seq + 1
        try:
            await self.session.append_audio(audio)
        except Exception as exc:
            await self.end(CallExitCode.REALTIME_PROVIDER_FAILED, f"append_audio_failed:{exc}")

    async def _read_provider_events(self) -> None:
        try:
            async for event in self.session.events():
                if self.state in {CallState.ENDING, CallState.ENDED}:
                    return
                await self._handle_provider_event(event)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            await self.end(CallExitCode.REALTIME_PROVIDER_FAILED, str(exc))

    async def _handle_provider_event(self, event: RealtimeEvent) -> None:
        event_type = event.type
        if event.response_id:
            response = self._responses.setdefault(
                event.response_id,
                CallResponseState(response_id=event.response_id),
            )
        response.raw_events.append(event.raw)
        if event_type == RealtimeEventType.SPEECH_STARTED:
            await self._handle_speech_started(event)
        elif event_type == RealtimeEventType.SPEECH_STOPPED:
            self._last_speech_stopped_at = time.perf_counter()
            self._record_call_event(
                "qwen.speech_stopped",
                metadata={"qwen_event_id": event.event_id, "qwen_item_id": event.item_id},
            )
        elif event_type == RealtimeEventType.INPUT_TRANSCRIPTION_COMPLETED:
            await self._append_turn("user", event.transcript, raw_events=[event.raw])
        elif event_type == RealtimeEventType.RESPONSE_CREATED:
            await self._cancel_proactive_task()
            response_id = event.response_id or f"response-{uuid.uuid4().hex}"
            self._current_response_id = response_id
            self._responses[response_id] = CallResponseState(response_id=response_id)
        elif event_type in {
            RealtimeEventType.TEXT_DELTA,
            RealtimeEventType.OUTPUT_TEXT_DELTA,
            RealtimeEventType.AUDIO_TRANSCRIPT_DELTA,
            RealtimeEventType.OUTPUT_AUDIO_TRANSCRIPT_DELTA,
        }:
            response_id = event.response_id or self._current_response_id
            if response_id:
                for line in self._parser.feed_text_delta(response_id, event.delta):
                    await self._enqueue_tts_line(line)
        elif event_type == RealtimeEventType.FUNCTION_ARGUMENTS_DONE:
            await self._handle_function_call(event)
        elif event_type in {
            RealtimeEventType.OUTPUT_ITEM_DONE,
            RealtimeEventType.CONTENT_PART_DONE,
        }:
            response_id = event.response_id or self._current_response_id
            if response_id:
                for line in self._parser.flush_response(response_id):
                    await self._enqueue_tts_line(line)
        elif event_type == RealtimeEventType.RESPONSE_DONE:
            response_id = event.response_id or self._current_response_id
            if response_id:
                for line in self._parser.flush_response(response_id):
                    await self._enqueue_tts_line(line)
                response = self._responses.setdefault(response_id, CallResponseState(response_id=response_id))
                response.completed = True
                self._current_response_id = None
                self._record_provider_usage(event)
                self._record_call_event(
                    "qwen.response_done",
                    usage=event.usage,
                    metadata={"qwen_event_id": event.event_id, "response_id": response_id},
                )
                self._schedule_proactive_check(response_id)
        elif event_type == RealtimeEventType.ERROR:
            await self.end(CallExitCode.REALTIME_PROVIDER_FAILED, self._safe_error(event.error))

    async def _handle_function_call(self, event: RealtimeEvent) -> None:
        if event.call_id:
            self._pending_function_calls.add(event.call_id)
        if not event.call_id or event.name != "search_memory":
            if self.session:
                await self.session.submit_tool_result(call_id=event.call_id or "", output="不支持的工具调用")
                await self.session.request_response()
            if event.call_id:
                self._pending_function_calls.discard(event.call_id)
            return
        try:
            args = json.loads(event.arguments or "{}")
            queries = args.get("queries", [])
            if isinstance(queries, str):
                queries = [queries]
            if not isinstance(queries, list):
                raise ValueError("queries must be an array")
            runtime = self.agent_runtime.get_character_runtime(self.character_id)
            memory_context = await runtime.mind.search_memory_context_for_topic(
                user_id=self.user_id,
                queries=[str(item) for item in queries[:5]],
                similarity_threshold=0.8,
                k=10,
            )
            result = await self._memory_pool.add_hits(memory_context.hits) if self._memory_pool else None
            output = "没有更多记忆" if not result or result.status == "no_more_memory" else f"新增记忆{result.added_count}条"
        except Exception:
            self.logger.exception("call memory search failed: call_id=%s", self.call_id)
            output = "记忆搜索失败"
        if self.session:
            await self.session.submit_tool_result(call_id=event.call_id, output=output)
            await self.session.request_response()
        self._pending_function_calls.discard(event.call_id)

    async def _enqueue_tts_line(self, line: CallTTSLine) -> None:
        if self.state != CallState.ACTIVE:
            return
        response = self._responses.setdefault(line.response_id, CallResponseState(response_id=line.response_id))
        if response.cancelled:
            return
        audio_id = f"audio-{self.call_id}-{self._next_tts_seq}"
        self._next_tts_seq += 1
        line = replace(line, audio_id=audio_id)
        response.pending_audio_ids.append(audio_id)
        self._audio_lines[audio_id] = line
        cancellation_event = asyncio.Event()
        await self.global_speaking_worker.enqueue(
            SpeakingJob(
                send_reply_callback=self._send_tts_packet,
                job_content=line,
                character_id=self.character_id,
                stream_id=self.stream_id,
                stream_seq=line.seq,
                user_id=self.user_id,
                response_id=line.response_id,
                cancellation_event=cancellation_event,
                on_error=self._on_tts_error,
            )
        )

    async def _send_tts_packet(self, response) -> None:
        audio_id = response.uuid
        line = self._audio_lines.get(audio_id)
        call_response = self._responses.get(line.response_id) if line is not None else None
        if (
            line is None
            or (call_response is not None and call_response.cancelled)
            or self.state in {CallState.ENDING, CallState.ENDED}
            or self.ws_connection is None
        ):
            return
        if audio_id not in self._sent_audio_ids and response.audio:
            self._sent_audio_ids.add(audio_id)
            duration_ms = None
            if self._last_speech_stopped_at is not None:
                duration_ms = (time.perf_counter() - self._last_speech_stopped_at) * 1000
                self._last_speech_stopped_at = None
            self._record_call_event(
                "call.speech_to_tts_first_chunk",
                duration_ms=duration_ms,
                metadata={"response_id": line.response_id, "audio_id": audio_id},
            )
        await self._send_event(
            WSEventType.CALL_AUDIO_CHUNK,
            {
                "call_id": self.call_id,
                "response_id": line.response_id,
                "audio_id": audio_id,
                "seq": self._audio_packet_seq(audio_id, response.audio),
                "audio": response.audio or "",
                "is_final": bool(response.is_final_package),
                "expression": response.expression or line.expression,
            },
        )

    def _audio_packet_seq(self, audio_id: str, audio: str | None) -> int:
        key = f"_packet_seq_{audio_id}"
        value = getattr(self, key, 0)
        setattr(self, key, value + 1)
        return value

    async def _on_tts_error(self, exc: Exception) -> None:
        await self.end(CallExitCode.TTS_FAILED, str(exc))

    async def _handle_speech_started(self, event: RealtimeEvent) -> None:
        response_id = self._current_response_id
        if response_id is None:
            for candidate_id, candidate in reversed(list(self._responses.items())):
                if candidate.pending_audio_ids and not candidate.cancelled:
                    response_id = candidate_id
                    break
        if not response_id:
            return
        response = self._responses.setdefault(response_id, CallResponseState(response_id=response_id))
        response.cancelled = True
        self._interrupt_started_at[response_id] = time.perf_counter()
        previous_ack_task = self._playback_ack_tasks.pop(response_id, None)
        if previous_ack_task and not previous_ack_task.done():
            previous_ack_task.cancel()
        self._playback_ack_tasks[response_id] = asyncio.create_task(self._wait_playback_stop_ack(response_id))
        self._record_call_event(
            "qwen.speech_started",
            metadata={"qwen_event_id": event.event_id, "response_id": response_id},
        )
        self._parser.cancel_response(response_id)
        if self.session:
            try:
                await self.session.cancel_response()
            except Exception:
                self.logger.debug("response.cancel failed", exc_info=True)
        await self.global_speaking_worker.cancel_pending(stream_id=self.stream_id, response_id=response_id, reason="barge_in")
        await self._send_event(
            WSEventType.CALL_STOP_PLAYBACK,
            {
                "call_id": self.call_id,
                "response_id": response_id,
                "audio_ids": list(response.pending_audio_ids),
                "reason": "user_barge_in",
            },
        )

    async def _playback_completed(self, payload: dict[str, Any]) -> None:
        audio_id = str(payload.get("audio_id") or "")
        line = self._audio_lines.get(audio_id)
        if not line:
            return
        response_id = str(payload.get("response_id") or "")
        if response_id and response_id != line.response_id:
            self.logger.warning("call playback response mismatch: call_id=%s audio_id=%s", self.call_id, audio_id)
            return
        response = self._responses.setdefault(line.response_id, CallResponseState(response_id=line.response_id))
        if audio_id in response.completed_audio_ids:
            return
        response.completed_audio_ids.add(audio_id)
        raw_events = self._responses.get(line.response_id).raw_events if self._responses.get(line.response_id) else []
        await self._append_turn("assistant", line.content, raw_events=raw_events)
        self._record_call_event(
            "client.playback_completed",
            metadata={
                "response_id": line.response_id,
                "audio_id": audio_id,
                "text_length": len(line.content),
            },
        )
        self._schedule_proactive_check(line.response_id)

    async def _playback_stopped(self, payload: dict[str, Any]) -> None:
        audio_id = str(payload.get("audio_id") or "")
        line = self._audio_lines.get(audio_id)
        if line:
            response_id = str(payload.get("response_id") or "")
            if response_id and response_id != line.response_id:
                return
            response = self._responses.setdefault(line.response_id, CallResponseState(response_id=line.response_id))
            response.cancelled = True
            started_at = self._interrupt_started_at.pop(line.response_id, None)
            ack_task = self._playback_ack_tasks.pop(line.response_id, None)
            if ack_task and not ack_task.done():
                ack_task.cancel()
            self._record_call_event(
                "client.playback_stopped",
                duration_ms=((time.perf_counter() - started_at) * 1000 if started_at is not None else None),
                metadata={"response_id": line.response_id, "audio_id": audio_id},
            )

    async def _append_turn(self, speaker: str, text: str, raw_events: list[dict[str, Any]] | None = None) -> None:
        if not text or not text.strip() or self.state in {CallState.ENDING, CallState.ENDED}:
            return
        seq = self._turn_seq
        self._turn_seq += 1
        turn = {"seq": seq, "speaker": speaker, "text": text.strip()}
        self._turns.append(turn)
        await asyncio.to_thread(
            self.call_store.append_turn,
            CallTurnDraft(
                call_id=self.call_id,
                seq=seq,
                speaker=speaker,
                text=text.strip(),
                ended_at=datetime.now(),
                raw_events=raw_events or [],
            ),
        )
        if len(self._turns) >= 10 and len(self._turns) % 10 == 0:
            asyncio.create_task(
                self._settlement.write_memory_incremental(
                    call_id=self.call_id,
                    user_id=self.user_id,
                    turns=list(self._turns),
                )
            )

    async def reconnect(self, ws_connection) -> bool:
        if self.state != CallState.RECONNECTING or (self._reconnect_deadline and time.monotonic() > self._reconnect_deadline):
            return False
        self.ws_connection = ws_connection
        self._reconnect_deadline = None
        self._transition(CallState.ACTIVE, expected={CallState.RECONNECTING})
        await self._send_event(WSEventType.CALL_RESUMED, {"call_id": self.call_id, "resumed_at": datetime.now().isoformat()})
        return True

    async def lost_connection(self) -> None:
        if self.state in {CallState.ENDING, CallState.ENDED}:
            return
        self.ws_connection = None
        await self._cancel_proactive_task()
        if self.state in {CallState.REQUESTING, CallState.ACTIVE}:
            self._transition(CallState.RECONNECTING, expected={CallState.REQUESTING, CallState.ACTIVE})
        self._reconnect_deadline = time.monotonic() + float(self.config.get("reconnect_grace_seconds", 5))
        if self.session:
            try:
                await self.session.cancel_response()
            except Exception:
                pass
        await self.global_speaking_worker.cancel_pending(stream_id=self.stream_id, reason="websocket_disconnect")

    async def hangup(self) -> None:
        self._hangup_event.set()
        if self.state == CallState.REQUESTING:
            await self.end(CallExitCode.HANGUP_BEFORE_CONNECTED, "user_hangup_before_connected")
        elif self.state in {CallState.ACTIVE, CallState.RECONNECTING}:
            await self.end(CallExitCode.NORMAL, "user_hangup")

    async def end(self, exit_code: CallExitCode | int, reason: str) -> None:
        async with self._end_lock:
            if self.state == CallState.ENDED:
                return
            self._transition(CallState.ENDING, expected={
                CallState.REQUESTING,
                CallState.ACTIVE,
                CallState.RECONNECTING,
            })
            await self._cancel_proactive_task()
            self.exit_code = int(exit_code)
            self.ended_at = datetime.now()
            if self._prepare_task and not self._prepare_task.done() and self._prepare_task is not asyncio.current_task():
                self._prepare_task.cancel()
            if self.provider_task and self.provider_task is not asyncio.current_task():
                self.provider_task.cancel()
            for task in self._audio_tasks:
                task.cancel()
            self._audio_tasks.clear()
            for task in self._playback_ack_tasks.values():
                task.cancel()
            self._playback_ack_tasks.clear()
            await self.global_speaking_worker.cancel_pending(stream_id=self.stream_id, reason=reason)
            if self.session:
                await self.session.close()
            if self.connected_at is None and self.exit_code == int(CallExitCode.REALTIME_PROVIDER_FAILED):
                # Qwen 建连失败不生成 call_sessions/call_history；错误只进入日志和协议事件。
                await self._send_event(
                    WSEventType.CALL_ERROR,
                    {"call_id": self.call_id, "code": "REALTIME_PROVIDER_FAILED", "message": reason},
                )
                duration = 0
            elif self.connected_at is None:
                await asyncio.to_thread(
                    self.call_store.create_preconnect_hangup,
                    call_id=self.call_id,
                    user_id=self.user_id,
                    character_id=self.character_id,
                    requested_at=self.requested_at,
                    ended_at=self.ended_at,
                    exit_code=self.exit_code,
                    summary=("网络断联结束" if self.exit_code == int(CallExitCode.RECONNECT_TIMEOUT) else "未接通就挂断"),
                )
                duration = 0
            else:
                duration = max(0, int((self.ended_at - self.connected_at).total_seconds()))
                await asyncio.to_thread(
                    self.call_store.settle_call_and_conversation,
                    call_id=self.call_id,
                    ended_at=self.ended_at,
                    exit_code=self.exit_code,
                    duration_seconds=duration,
                )
            self._transition(CallState.ENDED, expected={CallState.ENDING})
            await self._send_event(
                WSEventType.CALL_ENDED,
                {"call_id": self.call_id, "exit_code": self.exit_code, "duration_seconds": duration, "ended_at": self.ended_at.isoformat()},
            )
            self._record_call_event(
                "call.ended",
                error=(None if self.exit_code == int(CallExitCode.NORMAL) else {"code": self.exit_code, "reason": reason}),
                metadata={"exit_code": self.exit_code, "duration_seconds": duration},
            )
            if self.connected_at is not None:
                self._postprocess_task = asyncio.create_task(
                    self._settlement.process_after_end(
                        call_id=self.call_id,
                        user_id=self.user_id,
                        exit_code=self.exit_code,
                        duration_seconds=duration,
                        turns=list(self._turns),
                    )
                )
            self._end_event.set()

    async def _send_event(self, event_type: WSEventType, payload: dict[str, Any]) -> bool:
        if self.ws_connection is None or self.ws_connection.websocket is None:
            return False
        async with self._send_lock:
            try:
                await self.ws_connection.websocket.send_json(
                    {"type": event_type.value, "ts": int(time.time() * 1000), "payload": payload}
                )
                return True
            except Exception:
                return False

    def _schedule_proactive_check(self, response_id: str) -> None:
        if self._proactive_task is None or self._proactive_task.done():
            self._proactive_task = asyncio.create_task(self._wait_and_start_proactive(response_id))

    async def _wait_and_start_proactive(self, response_id: str) -> None:
        try:
            while self.state == CallState.ACTIVE:
                response = self._responses.get(response_id)
                if response is None or response.cancelled:
                    return
                all_played = set(response.pending_audio_ids) <= response.completed_audio_ids
                if all_played and not self._pending_function_calls and not self.global_speaking_worker.has_work(self.stream_id):
                    break
                await asyncio.sleep(0.05)
            await asyncio.sleep(float(self.config.get("proactive_delay_seconds", 2)))
            if self.state != CallState.ACTIVE or self._current_response_id is not None:
                return
            if self._pending_function_calls or self.global_speaking_worker.has_work(self.stream_id):
                return
            await self._generate_proactive_topic()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.logger.exception("call proactive topic failed: call_id=%s", self.call_id)

    async def _generate_proactive_topic(self) -> None:
        if self.session is None or self.state != CallState.ACTIVE:
            return
        transcript = "\n".join(f"[{item['speaker']}] {item['text']}" for item in self._turns[-20:])
        agent = self.agent_runtime.get_agent(self.character_id)
        lines = await agent.generate_topic_reply_for_pipeline(
            self.user_id,
            "用户暂时没有继续说话，请主动发起一个自然、简短、与最近通话内容相关的话题。",
            conversation_history=transcript,
        )
        if self.state != CallState.ACTIVE or self.session is None:
            return
        for line in lines:
            content = getattr(line, "content", "") or line.get_content()
            if content:
                await self.session.append_context_item(
                    role="user",
                    text=f"洛天依主动找话题：{content}",
                    item_id=f"call-proactive-{self.call_id}-{uuid.uuid4().hex}",
                )
                await self.session.request_response()
                return

    async def _cancel_proactive_task(self) -> None:
        if self._proactive_task and not self._proactive_task.done() and self._proactive_task is not asyncio.current_task():
            self._proactive_task.cancel()
            try:
                await self._proactive_task
            except asyncio.CancelledError:
                pass
        self._proactive_task = None

    async def _wait_playback_stop_ack(self, response_id: str) -> None:
        try:
            await asyncio.sleep(float(self.config.get("playback_stop_ack_timeout_seconds", 3)))
            if response_id in self._interrupt_started_at and self.state not in {CallState.ENDING, CallState.ENDED}:
                self._interrupt_started_at.pop(response_id, None)
                self._record_call_event(
                    "playback_stop_ack_timeout",
                    error={"message": "client did not acknowledge playback stop"},
                    metadata={"response_id": response_id},
                )
        except asyncio.CancelledError:
            raise

    @staticmethod
    async def _cancel_task(task: asyncio.Task | None) -> None:
        if task and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    @staticmethod
    def _safe_error(error: dict[str, Any] | None) -> str:
        if not error:
            return "realtime_provider_error"
        return str(error.get("message") or error.get("code") or "realtime_provider_error")[:500]

    def _record_provider_usage(self, event: RealtimeEvent) -> None:
        if self.observability is None or not event.usage:
            return
        qwen = getattr(self.realtime_dialogue_service, "config", {}).get("qwen", {})
        try:
            self.observability.record_llm_call(
                module_name="call_realtime",
                interface_name="qwen_realtime",
                model_name=qwen.get("model"),
                latency_ms=0,
                success=True,
                prompt_tokens=event.usage.get("input_tokens", event.usage.get("prompt_tokens", 0)),
                completion_tokens=event.usage.get("output_tokens", event.usage.get("completion_tokens", 0)),
                total_tokens=event.usage.get("total_tokens", 0),
                trace_id=f"call-{self.call_id}",
                user_id=self.user_id,
                metadata={"call_id": self.call_id, "response_id": event.response_id, "usage": event.usage},
            )
        except Exception:
            self.logger.debug("record realtime usage failed", exc_info=True)

    def _record_call_event(
        self,
        event_name: str,
        *,
        duration_ms: float | None = None,
        error: dict[str, Any] | None = None,
        usage: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        if self.observability is None:
            return
        try:
            self.observability.record_call_event(
                event_name=event_name,
                trace_id=f"call-{self.call_id}",
                call_id=self.call_id,
                user_id=self.user_id,
                duration_ms=duration_ms,
                error=error,
                usage=usage,
                metadata={"character_id": self.character_id, **(metadata or {})},
            )
        except Exception:
            self.logger.debug("record call event failed: call_id=%s event=%s", self.call_id, event_name, exc_info=True)

    def _transition(self, target: CallState, *, expected: set[CallState]) -> None:
        if self.state not in expected:
            raise RuntimeError(f"invalid call state transition: {self.state.value} -> {target.value}")
        self.state = target
