"""SAY 的预制音频和 TTS 分支，按呈现方式组织输出。"""

from contextlib import aclosing

import src.domain.agent as d
from src.agent.processing.output_drafts import AudioChunkDraft, ExpressionDraft, MessageEndDraft, TextFinalDraft
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.skills.expression.prepared_speech import EmptyPreparedAudioError, PreparedSpeechCatalog
from src.agent.skills.expression.speaking import EmptySpeechError, SpeakingSkill, UnsupportedCallAudioError
from src.agent.skills.expression.speaking.errors import TTSStreamCancelled
from src.agent.skills.invocation import execution_invocation
from src.utils.logger import get_logger


class SayHandler:
    """角色私有的 SAY 处理器，复用共享语音技能。"""

    def __init__(self, character_id: str, speaking: SpeakingSkill, prepared_speech: PreparedSpeechCatalog) -> None:
        """绑定角色 character_id、共享 speaking 技能及预制资源 prepared_speech。"""
        self._character_id = character_id
        self._speaking = speaking
        self._prepared_speech = prepared_speech

    async def realize(
        self, action: d.Action, execution_context: d.ExecutionContext, outputs: OutputEmitter
    ) -> d.ActionResult:
        """选择音频分支并按 delivery 投递；瞬时反应不输出文字，结束不恢复表情。"""
        if not isinstance(action, d.Say):
            raise TypeError("SayHandler 只处理 Say")
        if execution_context.cancellation.is_cancelled:
            return self._result(action, d.ExecutionErrorCode.CANCELLED)
        if action.call_delivery.audio_route is d.CallAudioRoute.CALL:
            outputs.ensure_call_allowed()
            if (
                action.prepared_audio_ref is not None
                or action.sound_content is None
                or not action.sound_content.strip()
            ):
                return self._result(action, d.ExecutionErrorCode.UNSUPPORTED_ACTION)
        if action.prepared_audio_ref is not None:
            return await self._realize_prepared(action, execution_context, outputs)
        if action.sound_content is not None:
            return await self._realize_tts(action, execution_context, outputs)
        return self._result(action, d.ExecutionErrorCode.UNSUPPORTED_ACTION)

    async def _realize_prepared(
        self, action: d.Say, context: d.ExecutionContext, outputs: OutputEmitter
    ) -> d.ActionResult:
        try:
            audio = await self._prepared_speech.read_audio(
                self._character_id,
                action.prepared_audio_ref.media_id,
            )
        except Exception as error:
            get_logger(__name__).exception(
                f"SAY prepared audio failed character_id={self._character_id} action_id={action.action_id}"
            )
            code = (
                d.ExecutionErrorCode.AUDIO_EMPTY
                if isinstance(error, EmptyPreparedAudioError)
                else d.ExecutionErrorCode.AUDIO_GENERATION_FAILED
            )
            return self._result(action, code)
        if context.cancellation.is_cancelled:
            return self._result(action, d.ExecutionErrorCode.CANCELLED)
        await self._emit_presentation(action, outputs)
        await outputs.emit(
            AudioChunkDraft(delivery=action.delivery, data=audio.data, framing=d.AudioFraming.COMPLETE_FILE)
        )
        await outputs.emit(
            MessageEndDraft(delivery=action.delivery, status=d.MessageEndStatus.COMPLETED, error_code=None)
        )
        return self._result(action)

    async def _emit_presentation(self, action: d.Say, outputs: OutputEmitter) -> None:
        if (
            action.delivery is d.OutputDelivery.CONVERSATION
            or action.call_delivery.audio_route is d.CallAudioRoute.CALL
        ) and action.content.strip():
            await outputs.emit(TextFinalDraft(delivery=action.delivery, text=action.content))
        if action.expression is not None:
            await outputs.emit(ExpressionDraft(delivery=action.delivery, expression=action.expression))

    async def _realize_tts(
        self, action: d.Say, execution_context: d.ExecutionContext, outputs: OutputEmitter
    ) -> d.ActionResult:
        is_call = action.call_delivery.audio_route is d.CallAudioRoute.CALL
        await self._emit_presentation(action, outputs)
        if is_call:
            outputs.ensure_call_allowed()
        return await self._stream_tts(action, execution_context, outputs, is_call=is_call)

    # Reviewed exception: generation, cancellation, look-behind finalization, and
    # sink backpressure form one ordered stream lifecycle.
    async def _stream_tts(  # noqa: C901
        self,
        action: d.Say,
        execution_context: d.ExecutionContext,
        outputs: OutputEmitter,
        *,
        is_call: bool,
    ) -> d.ActionResult:
        async with aclosing(
            self._speaking.speak(
                execution_invocation(self._character_id, execution_context),
                text=action.sound_content,
                tone=action.tone,
                output_format=d.CALL_PCM_FORMAT if is_call else None,
            )
        ) as stream:
            pending = None
            while True:
                try:
                    if is_call:
                        outputs.ensure_call_allowed()
                    chunk = await anext(stream)
                except StopAsyncIteration:
                    break
                except TTSStreamCancelled:
                    return self._result(action, d.ExecutionErrorCode.CANCELLED)
                except Exception as error:
                    return await self._handle_tts_error(action, outputs, error)
                if execution_context.cancellation.is_cancelled:
                    return self._result(action, d.ExecutionErrorCode.CANCELLED)
                if is_call:
                    await self._emit_pending_call_chunk(action, outputs, pending)
                    pending = chunk
                else:
                    await outputs.emit(
                        AudioChunkDraft(delivery=action.delivery, data=chunk.data, framing=chunk.framing)
                    )
        if execution_context.cancellation.is_cancelled:
            return self._result(action, d.ExecutionErrorCode.CANCELLED)
        if is_call:
            outputs.ensure_call_allowed()
            if pending is None:
                await outputs.emit(
                    MessageEndDraft(
                        delivery=action.delivery,
                        status=d.MessageEndStatus.FAILED,
                        error_code=d.AudioErrorCode.EMPTY_AUDIO,
                    )
                )
                return self._result(action, d.ExecutionErrorCode.AUDIO_EMPTY)
            await outputs.emit(
                AudioChunkDraft(
                    delivery=action.delivery,
                    data=pending.data,
                    framing=d.AudioFraming.RAW_PCM,
                    audio_format=d.CALL_PCM_FORMAT,
                    final=True,
                )
            )
        await outputs.emit(
            MessageEndDraft(delivery=action.delivery, status=d.MessageEndStatus.COMPLETED, error_code=None)
        )
        return self._result(action)

    async def _handle_tts_error(self, action: d.Say, outputs: OutputEmitter, error: Exception) -> d.ActionResult:
        """将生成失败映射为稳定执行错误；交付异常仍由 Execution 接管。"""
        empty = isinstance(error, EmptySpeechError)
        if empty:
            code = d.ExecutionErrorCode.AUDIO_EMPTY
        elif isinstance(error, UnsupportedCallAudioError):
            code = d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
        elif isinstance(error, TimeoutError):
            code = d.ExecutionErrorCode.PROVIDER_TIMEOUT
        else:
            code = d.ExecutionErrorCode.AUDIO_GENERATION_FAILED
        get_logger(__name__).exception(f"SAY TTS failed character_id={self._character_id} action_id={action.action_id}")
        await outputs.emit(
            MessageEndDraft(
                delivery=action.delivery,
                status=d.MessageEndStatus.FAILED,
                error_code=d.AudioErrorCode.EMPTY_AUDIO if empty else d.AudioErrorCode.GENERATION_FAILED,
            )
        )
        return self._result(action, code)

    @staticmethod
    async def _emit_pending_call_chunk(action: d.Say, outputs: OutputEmitter, pending) -> None:
        outputs.ensure_call_allowed()
        if pending is None:
            return
        await outputs.emit(
            AudioChunkDraft(
                delivery=action.delivery,
                data=pending.data,
                framing=d.AudioFraming.RAW_PCM,
                audio_format=d.CALL_PCM_FORMAT,
            )
        )

    @staticmethod
    def _result(action: d.Say, code: d.ExecutionErrorCode | None = None) -> d.ActionResult:
        status = (
            d.ActionExecutionStatus.CANCELLED
            if code is d.ExecutionErrorCode.CANCELLED
            else d.ActionExecutionStatus.FAILED if code else d.ActionExecutionStatus.COMPLETED
        )
        return d.ActionResult(
            action_id=action.action_id,
            status=status,
            error_code=code,
            irreversible_effect_committed=False,
            effect_ref=None,
        )
