"""学会新歌事实的角色经验与动态发布决定。"""

from __future__ import annotations

from uuid import uuid4

import src.domain.agent as d
from src.agent.processing.plan_emitter import ActionPlanDraft, PlanEmitter
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill
from src.agent.skills.invocation import handling_invocation
from src.agent.skills.memory_retrieval import MemoryRetrievalSkill
from src.agent.skills.memory_write import MemoryBasis, MemoryFact, MemoryScope, MemoryWriteSkill, MemoryWriteStatus
from src.utils.logger import get_logger

SONG_LEARNED_SOURCE_TYPE = "song_learned"
SONG_LEARNED_INSTRUCTION = (
    "这是一次学会新歌后的角色动态。请以角色的第一人称视角表达学会后的开心、对这首歌或唱段的感受，"
    "以及想唱给用户听的心情；语气活泼可爱，不要复述整段歌词。"
)


class SongLearnedHandler:
    """记录学会经验并交付一个 PublishDynamic 计划。"""

    def __init__(
        self,
        character_id: str,
        experience: MemoryWriteSkill,
        publishing: DynamicPublishingSkill,
        retrieval: MemoryRetrievalSkill,
    ) -> None:
        self._character_id = character_id
        self._experience = experience
        self._publishing = publishing
        self._retrieval = retrieval
        self._logger = get_logger(__name__)

    async def handle(self, request: d.HandleStimulusRequest, plans: PlanEmitter) -> d.HandlingReport:
        """写经验（幂等、失败不回滚事实）并交付发布计划；正文生成为空时明确失败。"""
        stimulus = request.stimulus
        if not isinstance(stimulus, d.SongLearned):
            raise TypeError("SongLearnedHandler 只处理 SongLearned")
        invocation = handling_invocation(request, plans.context)
        await self._record_experience(invocation, stimulus)
        song = await self._retrieval.get_song(invocation, song_id=stimulus.song_id)
        segment_description = song.segments[0] if song.segments else ""
        lyrics = song.lyrics
        body = await self._publishing.compose(
            invocation,
            dynamic_type=SONG_LEARNED_SOURCE_TYPE,
            instruction=SONG_LEARNED_INSTRUCTION,
            structured_context="\n".join(
                (
                    f"新学会的歌曲：{stimulus.song_id}",
                    f"可唱唱段：{segment_description or '-'}",
                    f"唱段歌词：{lyrics or '-'}",
                )
            ),
        )
        if not body.strip():
            self._logger.error("学歌动态正文生成为空，未交付计划 song=%s", stimulus.song_id)
            return self._report(request, d.HandlingRequestStatus.FAILED, d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE, ())
        action = d.PublishDynamic(
            action_id=str(uuid4()),
            body=body,
            media_refs=(),
            visibility=d.Visibility.GLOBAL,
            owner_user_id=None,
            source=d.DynamicSource(source_type=SONG_LEARNED_SOURCE_TYPE, source_id=stimulus.song_id),
            allow_comment=True,
        )
        receipt = await plans.emit(
            ActionPlanDraft(
                source_stimulus_ids=(stimulus.stimulus_id,),
                actions=(action,),
            )
        )
        return self._report(
            request, d.HandlingRequestStatus.COMPLETED, None, (stimulus.stimulus_id,), plans=(receipt.plan_id,)
        )

    async def _record_experience(self, invocation, stimulus: d.SongLearned) -> None:
        """写入角色经验；失败只记录，不撤销已经成立的新学会事实。"""
        try:
            result = await self._experience.commit_fact(
                invocation,
                fact=MemoryFact(
                    source="song_learned",
                    source_id=stimulus.learning_job_id,
                    occurred_at=stimulus.completed_at,
                    content=f"学会了新歌《{stimulus.song_id}》（学习任务 {stimulus.learning_job_id}）",
                    scope=MemoryScope.CHARACTER,
                    basis=MemoryBasis.CONFIRMED_FACT,
                ),
            )
        except Exception:
            self._logger.exception("学会经验写入失败 song=%s", stimulus.song_id)
            return
        if result.status is MemoryWriteStatus.DUPLICATE:
            self._logger.info("学会经验已存在，跳过重复写入 song=%s", stimulus.song_id)

    @staticmethod
    def _report(
        request: d.HandleStimulusRequest,
        status: d.HandlingRequestStatus,
        error_code: d.HandlingErrorCode | None,
        consumed: tuple[str, ...],
        *,
        plans: tuple[str, ...] = (),
    ) -> d.HandlingReport:
        pending = tuple(item.stimulus_id for item in request.interaction.pending_stimuli)
        return d.HandlingReport(
            request_id=request.request_id,
            trigger_stimulus_id=request.stimulus.stimulus_id,
            basis_interaction_revision=request.interaction.interaction_revision,
            request_status=status,
            considered_pending_stimulus_ids=pending,
            consumed_pending_stimulus_ids=consumed,
            retained_pending_stimulus_ids=tuple(item for item in pending if item not in consumed),
            emitted_plan_ids=plans,
            error_code=error_code,
            retryable=False,
        )
