"""SING 行动：渲染已确定的歌曲片段并输出音频与结束标志。"""

import src.domain.agent as d
from src.agent.processing.output_drafts import AudioChunkDraft, ExpressionDraft, MessageEndDraft
from src.agent.processing.output_emitter import OutputEmitter
from src.agent.skills.expression.singing import EmptySongAudioError, SingingSkill
from src.utils.logger import get_logger


class SingHandler:
    """角色私有的 SING 处理器，复用共享演唱技能。"""

    def __init__(self, character_id: str, singing: SingingSkill) -> None:
        """绑定角色 character_id 与共享 singing 技能。"""
        self._character_id = character_id
        self._singing = singing

    async def realize(
        self, action: d.Action, execution_context: d.ExecutionContext, outputs: OutputEmitter
    ) -> d.ActionResult:
        """渲染既定片段并按 [表情] → 音频 → 结束 输出；不可用或失败时以终止包说明原因。"""
        if not isinstance(action, d.Sing):
            raise TypeError("SingHandler 只处理 Sing")
        if execution_context.cancellation.is_cancelled:
            return self._result(action, d.ExecutionErrorCode.CANCELLED)
        delivery = d.OutputDelivery.CONVERSATION
        if action.expression is not None:
            await outputs.emit(ExpressionDraft(delivery=delivery, expression=action.expression))
        try:
            audio = await self._singing.render(
                character_id=self._character_id, song_id=action.song_id, segment_id=action.segment_id
            )
        except EmptySongAudioError:
            get_logger(__name__).warning(
                f"SING unavailable character_id={self._character_id} action_id={action.action_id}"
            )
            return await self._failed(
                action, outputs, delivery, d.AudioErrorCode.EMPTY_AUDIO, d.ExecutionErrorCode.AUDIO_EMPTY
            )
        except TimeoutError:
            get_logger(__name__).exception(
                f"SING timed out character_id={self._character_id} action_id={action.action_id}"
            )
            return await self._failed(
                action, outputs, delivery, d.AudioErrorCode.GENERATION_FAILED, d.ExecutionErrorCode.PROVIDER_TIMEOUT
            )
        except Exception:
            get_logger(__name__).exception(
                f"SING generation failed character_id={self._character_id} action_id={action.action_id}"
            )
            return await self._failed(
                action,
                outputs,
                delivery,
                d.AudioErrorCode.GENERATION_FAILED,
                d.ExecutionErrorCode.AUDIO_GENERATION_FAILED,
            )
        if execution_context.cancellation.is_cancelled:
            return self._result(action, d.ExecutionErrorCode.CANCELLED)
        await outputs.emit(AudioChunkDraft(delivery=delivery, data=audio, framing=d.AudioFraming.COMPLETE_FILE))
        await outputs.emit(MessageEndDraft(delivery=delivery, status=d.MessageEndStatus.COMPLETED, error_code=None))
        return self._result(action)

    async def _failed(
        self,
        action: d.Sing,
        outputs: OutputEmitter,
        delivery: d.OutputDelivery,
        audio_code: d.AudioErrorCode,
        error: d.ExecutionErrorCode,
    ) -> d.ActionResult:
        await outputs.emit(MessageEndDraft(delivery=delivery, status=d.MessageEndStatus.FAILED, error_code=audio_code))
        return self._result(action, error)

    @staticmethod
    def _result(action: d.Sing, code: d.ExecutionErrorCode | None = None) -> d.ActionResult:
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
