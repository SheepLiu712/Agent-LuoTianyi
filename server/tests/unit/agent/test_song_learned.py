"""学会新歌事实的 Agent 侧经验写入、动态发布与学歌派发。"""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import src.domain.agent as d
from src.agent.handlers.action.song_learning import RequestSongLearningHandler
from src.agent.handlers.stimulus.song_learned import SongLearnedHandler
from src.agent.processing.plan_emitter import PlanEmitter
from src.agent.skills.cognitive.learned_song_experience import (
    LearnedSongExperienceSkill,
)
from src.agent.skills.expression.dynamic_publishing import DynamicPublishingSkill
from src.agent.skills.expression.song_learning import SongLearningDispatchSkill

BODY = "今天学会了《Song A》，好想唱给你听！"


class FakeMemory:
    def __init__(self, *, committed=True, fail=False):
        self.calls = []
        self.committed = committed
        self.fail = fail

    async def write_event_memory(self, *, user_id, content, commit=True):
        if self.fail:
            raise RuntimeError("memory unavailable")
        self.calls.append((user_id, content))
        return self.committed


class FakeDynamics:
    def __init__(self, *, body=BODY, publish_ok=True, publish_id="dynamic-song-a"):
        self.body = body
        self.publish_ok = publish_ok
        self.publish_id = publish_id
        self.composed = []
        self.published = []

    async def generate_world_dynamic_content(self, **kwargs):
        self.composed.append(kwargs)
        return self.body

    def publish_agent_dynamic(self, **kwargs):
        self.published.append(kwargs)
        if not self.publish_ok:
            return False, "failed", None
        return True, "created", {"id": self.publish_id}


class FakeSinging:
    def __init__(self, *, requested=True):
        self.requested = requested
        self.requested_songs = []

    def add_wished_song(self, song_name):
        self.requested_songs.append(song_name)
        return self.requested

    def can_i_sing_song(self, song_name):
        return song_name, ["主歌", "副歌"]

    def get_full_lyrics(self, song_name):
        return "第一句歌词\n第二句歌词"

    def get_segment_lyrics(self, song_name, segment_description):
        return f"{song_name}:{segment_description}"


class Sink:
    def __init__(self):
        self.plans = []

    async def emit(self, plan):
        self.plans.append(plan)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


def learned(song_id="Song A", learning_job_id="luotianyi:20260915120000"):
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    return d.SongLearned(
        stimulus_id="sl1", schema_version=1, occurred_at=now, source=d.StimulusSource.WORLD,
        target_character_ids=("luotianyi",), user_id=None, ephemeral=False,
        learning_job_id=learning_job_id, song_id=song_id, completed_at=now,
    )


def request_for(fact):
    now = datetime(2026, 9, 15, tzinfo=timezone.utc)
    snapshot = d.WorldInteractionSnapshot(
        interaction_id="wi", interaction_revision=1, user_id=None, pending_stimuli=(fact,),
        now=now, timezone=ZoneInfo("UTC"), supported_outputs=frozenset(), world_id="default",
        world_revision=1, activity_id=None, activity_revision=None,
        planning_cycle_id=None, schedule_revision=0,
    )
    return d.HandleStimulusRequest(
        request_id="req", stimulus=fact, interaction=snapshot, cancellation=d.CancellationToken(),
    )


def handler(memory, dynamics, singing=None):
    return SongLearnedHandler(
        "luotianyi",
        LearnedSongExperienceSkill(memory),
        DynamicPublishingSkill(dynamics),
        SongLearningDispatchSkill(singing or FakeSinging()),
    )


async def test_experience_is_written_once_per_learning_job():
    memory = FakeMemory()
    skill = LearnedSongExperienceSkill(memory)

    first = await skill.commit(character_id="luotianyi", song_id="Song A",
                               learning_job_id="luotianyi:20260915120000")
    assert first is True
    assert memory.calls[0][0] == "luotianyi"
    assert "Song A" in memory.calls[0][1]
    assert "luotianyi:20260915120000" in memory.calls[0][1]


async def test_experience_skill_rejects_invalid_arguments():
    skill = LearnedSongExperienceSkill(FakeMemory())

    for kwargs in (
        {"character_id": " ", "song_id": "Song A", "learning_job_id": "job"},
        {"character_id": "luotianyi", "song_id": "", "learning_job_id": "job"},
        {"character_id": "luotianyi", "song_id": "Song A", "learning_job_id": " "},
    ):
        try:
            await skill.commit(**kwargs)
        except ValueError:
            continue
        raise AssertionError(f"非法参数未被拒绝：{kwargs}")


async def test_song_learned_handler_records_experience_and_emits_publish_plan():
    memory = FakeMemory()
    dynamics = FakeDynamics()
    fact = learned()
    request = request_for(fact)
    sink = Sink()

    report = await handler(memory, dynamics).handle(request, emitter(request, sink))

    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert report.consumed_pending_stimulus_ids == ("sl1",)
    assert report.emitted_plan_ids == (sink.plans[0].plan_id,)
    assert len(memory.calls) == 1
    assert dynamics.composed[0]["dynamic_type"] == "song_learned"
    assert "Song A" in dynamics.composed[0]["structured_context"]
    assert "主歌" in dynamics.composed[0]["structured_context"]
    assert "第一句歌词" in dynamics.composed[0]["structured_context"]
    action = sink.plans[0].actions[0]
    assert isinstance(action, d.PublishDynamic)
    assert action.source == d.DynamicSource(source_type="song_learned", source_id="Song A")
    assert action.visibility is d.Visibility.GLOBAL


async def test_song_learned_handler_keeps_publishing_when_experience_fails():
    memory = FakeMemory(fail=True)
    dynamics = FakeDynamics()
    fact = learned()
    request = request_for(fact)
    sink = Sink()

    report = await handler(memory, dynamics).handle(request, emitter(request, sink))

    assert report.request_status is d.HandlingRequestStatus.COMPLETED
    assert len(sink.plans) == 1


async def test_song_learned_handler_fails_without_plan_when_body_is_empty():
    memory = FakeMemory()
    dynamics = FakeDynamics(body=" ")
    fact = learned()
    request = request_for(fact)
    sink = Sink()

    report = await handler(memory, dynamics).handle(request, emitter(request, sink))

    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.DEPENDENCY_UNAVAILABLE
    assert report.emitted_plan_ids == ()
    assert sink.plans == []


def emitter(request, sink):
    return PlanEmitter(character_id="luotianyi", request=request, sink=sink)


def action_for(song_id="Song A", dedup_key="dedup-1"):
    return d.RequestSongLearning(action_id="a1", song_id=song_id, dedup_key=dedup_key)


def execution_context(cancelled=False):
    token = d.CancellationToken()
    if cancelled:
        token.cancel(d.CancellationReason.SUPERSEDED)
    return d.ExecutionContext(
        execution_id="e", interaction_id="i", current_interaction_revision=1, cancellation=token,
    )


async def test_request_song_learning_reports_submitted_job():
    singing = FakeSinging()
    handler_ = RequestSongLearningHandler("luotianyi", SongLearningDispatchSkill(singing))

    result = await handler_.realize(action_for(), execution_context(), None)

    assert result.status is d.ActionExecutionStatus.COMPLETED
    assert result.effect_ref == d.EffectRef(kind=d.EffectKind.SONG_LEARNING_JOB, effect_id="Song A")
    assert result.irreversible_effect_committed is True
    assert singing.requested_songs == ["Song A"]


async def test_request_song_learning_marks_existing_wish_as_already_completed():
    singing = FakeSinging(requested=False)
    handler_ = RequestSongLearningHandler("luotianyi", SongLearningDispatchSkill(singing))

    result = await handler_.realize(action_for(), execution_context(), None)

    assert result.status is d.ActionExecutionStatus.ALREADY_COMPLETED
    assert result.error_code is None
    assert result.effect_ref.effect_id == "Song A"


async def test_request_song_learning_reports_missing_capability_as_dependency_failure():
    handler_ = RequestSongLearningHandler("luotianyi", SongLearningDispatchSkill(None))

    result = await handler_.realize(action_for(), execution_context(), None)

    assert result.status is d.ActionExecutionStatus.FAILED
    assert result.error_code is d.ExecutionErrorCode.DEPENDENCY_UNAVAILABLE
    assert result.effect_ref is None


async def test_request_song_learning_honours_cancellation():
    singing = FakeSinging()
    handler_ = RequestSongLearningHandler("luotianyi", SongLearningDispatchSkill(singing))

    result = await handler_.realize(action_for(), execution_context(cancelled=True), None)

    assert result.status is d.ActionExecutionStatus.CANCELLED
    assert singing.requested_songs == []


async def test_song_learning_dispatch_material_falls_back_without_capability():
    assert SongLearningDispatchSkill(None).material(song_id="Song A") == ("", "")


def test_song_learning_dispatch_rejects_malformed_capability():
    try:
        SongLearningDispatchSkill(object())
    except TypeError as error:
        assert "add_wished_song" in str(error)
        return
    raise AssertionError("缺少唱歌管理器方法的适配器未被拒绝")
