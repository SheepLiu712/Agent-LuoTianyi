"""SAY 的 TTS 分支：显示文字、附带表情和流式语音。"""

from contextlib import aclosing

import src.domain.agent as d
from src.agent.skills.expression.speaking import EmptySpeechError, SpeakingSkill
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.processing.output_drafts import AudioChunkDraft, ExpressionDraft, MessageEndDraft, TextFinalDraft
from src.capabilities.speech.stream_errors import TTSStreamCancelled
from src.utils.logger import get_logger


class SayHandler:
    """角色私有的 SAY 处理器，复用共享语音技能。"""

    def __init__(self, character_id: str, speaking: SpeakingSkill) -> None:
        """绑定角色 character_id 和共享 speaking 技能。"""
        self._character_id = character_id
        self._speaking = speaking

    async def realize(self, action: d.Action, execution_context: d.ExecutionContext,
                      outputs: OutputEmitter) -> d.ActionResult:
        """执行 SAY 的 TTS 分支，返回行动结果；结束时不恢复表情。"""
        if not isinstance(action, d.Say):
            raise TypeError("SayHandler 只处理 Say")
        if action.sound_content is None or action.prepared_audio_ref is not None:
            return self._result(action, d.ExecutionErrorCode.UNSUPPORTED_ACTION)
        await outputs.emit(TextFinalDraft(delivery=action.delivery, text=action.content))
        if action.expression is not None:
            await outputs.emit(ExpressionDraft(delivery=action.delivery, expression=action.expression))
        async with aclosing(self._speaking.speak(
            character_id=self._character_id, text=action.sound_content, tone=action.tone,
            cancellation=execution_context.cancellation,
        )) as stream:
            while True:
                try:
                    chunk = await anext(stream)
                except StopAsyncIteration:
                    break
                except TTSStreamCancelled:
                    return self._result(action, d.ExecutionErrorCode.CANCELLED)
                except Exception as error:
                    # 仅捕获生成错误；交付失败直接交给执行流程，禁止追加输出。
                    empty = isinstance(error, EmptySpeechError)
                    code = (d.ExecutionErrorCode.AUDIO_EMPTY if empty
                            else d.ExecutionErrorCode.PROVIDER_TIMEOUT if isinstance(error, TimeoutError)
                            else d.ExecutionErrorCode.AUDIO_GENERATION_FAILED)
                    get_logger(__name__).exception(
                        f"SAY TTS failed character_id={self._character_id} action_id={action.action_id}")
                    await outputs.emit(MessageEndDraft(
                        delivery=action.delivery, status=d.MessageEndStatus.FAILED,
                        error_code=d.AudioErrorCode.EMPTY_AUDIO if empty else d.AudioErrorCode.GENERATION_FAILED,
                    ))
                    return self._result(action, code)
                await outputs.emit(AudioChunkDraft(delivery=action.delivery, data=chunk.data, framing=chunk.framing))
        await outputs.emit(MessageEndDraft(delivery=action.delivery, status=d.MessageEndStatus.COMPLETED,
                                           error_code=None))
        return self._result(action)

    @staticmethod
    def _result(action: d.Say, code: d.ExecutionErrorCode | None = None) -> d.ActionResult:
        status = (d.ActionExecutionStatus.CANCELLED if code is d.ExecutionErrorCode.CANCELLED
                  else d.ActionExecutionStatus.FAILED if code else d.ActionExecutionStatus.COMPLETED)
        return d.ActionResult(action_id=action.action_id, status=status, error_code=code,
                              irreversible_effect_committed=False, effect_ref=None)
