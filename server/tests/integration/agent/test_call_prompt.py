"""配置资源、角色隔离和通话语气进入语音合成的可观察行为。"""

import json
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

import src.domain.agent as d
from src.agent.context import ContextFactory, ConversationMode
from src.agent.context.memory_pool import CallMemory
from src.agent.skills.expression.speaking.skill import SpeakingAudioChunk
from src.agent_runtime.agent_runtime import AgentRuntime
from src.domain.call import CallState


class BackgroundDatabase:
    def get_user_description(self, user_id):
        return f"{user_id}的画像"

    def get_user_preferences(self, user_id):
        return {"relationship": f"{user_id}的朋友", "speaking_style": f"{user_id}偏爱简短回答"}

    def get_call_conversation_seed_state(self, user_id, *, character_id, requested_at):
        return {
            "summary": f"{user_id}的更早概括",
            "conversations": [
                {
                    "uuid": f"{user_id}-history",
                    "timestamp": "2026-10-10 12:00:00.000000",
                    "source": "user",
                    "type": "text",
                    "content": f"{user_id}的近期原文",
                    "meta_data": None,
                }
            ],
        }


class Sessions:
    is_configured = True

    def __init__(self):
        self.opened = []

    async def open(self, call_id, instructions):
        handle = object()
        self.opened.append((call_id, instructions, handle))
        return handle


async def context_for(character_id, user_id):
    call_id = uuid4()
    context = await ContextFactory(character_id=character_id, database=BackgroundDatabase()).create(
        str(call_id), mode=ConversationMode.CALL, user_id=user_id, requested_at=datetime(2026, 11, 4)
    )
    context.call_memory.remember(CallMemory(user_id, f"{user_id}的已召回记忆"))
    return call_id, context


@pytest.mark.asyncio
async def test_configured_prompt_is_loaded_when_agent_is_created_and_uses_each_session_background(
    runtime_dependencies, tmp_path, monkeypatch
):
    kwargs, _ = runtime_dependencies
    config = kwargs["config"]
    source = Path(__file__).resolve().parents[3] / "res/agent/prompts/realtime_call_prompt.json"
    resource = json.loads(source.read_text(encoding="utf-8"))
    resource["template"].append("本模板来自配置路径。")
    prompt_file = tmp_path / "custom-call.json"
    prompt_file.write_text(json.dumps(resource, ensure_ascii=False), encoding="utf-8")
    config["omni_prompt_file"] = str(prompt_file)
    miku = tmp_path / "miku.json"
    miku.write_text(
        json.dumps(
            {"character_name": "初音未来", "character_persona": "初音的独立人设", "speaking_style": "初音的表达风格"},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    config["character_registry"]["characters"]["miku"]["static_variables_file"] = str(miku)
    sessions = Sessions()
    runtime = AgentRuntime(**kwargs, omni_factory=sessions)
    utc_times = iter(
        (datetime(2026, 11, 4, 15, 59, 59, tzinfo=timezone.utc), datetime(2026, 11, 4, 16, 0, 1, tzinfo=timezone.utc))
    )
    monkeypatch.setattr(
        "src.agent.processing.omni_background.datetime", SimpleNamespace(now=lambda tz: next(utc_times).astimezone(tz))
    )
    contexts = []
    try:
        # 正在运行的 Agent 已持有模板；创建会话不依赖再次访问该文件。
        prompt_file.unlink()
        for character_id, user_id in (("luotianyi", "甲"), ("miku", "乙")):
            call_id, context = await context_for(character_id, user_id)
            contexts.append(context)
            await runtime.get_agent(character_id).open_omni_session(context, call_id)
            assert context.conversation.read_working().entries == ()
        first, second = [entry[1] for entry in sessions.opened]
        assert "【本次通话开始时间】2026-11-04 23:59:59" in first
        assert "【本次通话开始时间】2026-11-05 00:00:01" in second
        assert "本模板来自配置路径。" in first and "本模板来自配置路径。" in second
        assert "测试角色" in first and "测试人格" in first
        assert "初音未来" in second and "初音的独立人设" in second and "初音的表达风格" in second
        assert "初音的独立人设" not in first and "测试人格" not in second
        for instructions, own, other in ((first, "甲", "乙"), (second, "乙", "甲")):
            for field in ("画像", "朋友", "偏爱简短回答", "更早概括", "近期原文", "已召回记忆"):
                assert f"{own}的{field}" in instructions or f"{own}{field}" in instructions
            assert f"{other}的画像" not in instructions
            assert "禁止输出[sing]" in instructions and "[语气]" in instructions
        assert sessions.opened[0][2] is not sessions.opened[1][2]
    finally:
        for context in contexts:
            await context.close()
        await runtime.shutdown()


class PlanSink:
    def __init__(self):
        self.plans = []

    async def emit(self, plan):
        self.plans.append(plan)
        return d.PlanReceipt(plan_id=plan.plan_id, status=d.PlanAcceptanceStatus.ACCEPTED)


class OutputSink:
    def __init__(self):
        self.outputs = []

    async def emit(self, output):
        self.outputs.append(output)
        return d.OutputReceipt(
            execution_id=output.execution_id, sequence_no=output.sequence_no, status=d.OutputAcceptanceStatus.ACCEPTED
        )


@pytest.mark.asyncio
async def test_call_tone_uses_the_current_character_mapping_and_only_speaks_clean_text(
    runtime_dependencies, tmp_path, monkeypatch
):
    kwargs, _ = runtime_dependencies
    for character_id, tone in (("luotianyi", "tender"), ("miku", "happy")):
        tones = tmp_path / f"{character_id}-tones.json"
        tones.write_text(
            json.dumps(
                {"llm_tone_to_tts_tone": {"温柔": tone}, "llm_tone_to_l2d_expression": {"温柔": "温柔脸"}},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        kwargs["config"]["character_registry"]["characters"][character_id]["llm_tone_mapping_file"] = str(tones)
    runtime = AgentRuntime(**kwargs)
    spoken = []

    async def speak(invocation, *, text, tone, output_format):
        spoken.append((invocation.character_id, text, tone.value))
        yield SpeakingAudioChunk(b"\0\0", d.AudioFraming.RAW_PCM, d.CALL_PCM_FORMAT)

    monkeypatch.setattr(runtime.skills.speaking, "speak", speak)
    try:
        for character_id in ("luotianyi", "miku"):
            call_id, context = await context_for(character_id, "用户")
            try:
                agent = runtime.get_agent(character_id)
                now = datetime.now(timezone.utc)
                stimulus = d.CallReplySegmentReady(
                    stimulus_id=str(uuid4()),
                    schema_version=1,
                    occurred_at=now,
                    source=d.StimulusSource.STAGE,
                    target_character_ids=(character_id,),
                    user_id="用户",
                    ephemeral=True,
                    call_id=call_id,
                    response_id="reply",
                    segment_index=0,
                    turn_seq=1,
                    text="别着急，我在听。",
                    tone="温柔",
                )
                plans = PlanSink()
                report = await agent.handle_stimulus(
                    d.HandleStimulusRequest(
                        request_id=str(uuid4()),
                        stimulus=stimulus,
                        cancellation=d.CancellationToken(),
                        interaction=d.CallInteractionSnapshot(
                            interaction_id=str(call_id),
                            interaction_revision=1,
                            user_id="用户",
                            pending_stimuli=(),
                            now=now,
                            timezone=ZoneInfo("Asia/Shanghai"),
                            supported_outputs=frozenset(d.AgentOutputKind),
                            call_id=call_id,
                            state=CallState.ACTIVE,
                            connection_state=d.ConnectionState.CONNECTED,
                        ),
                    ),
                    plans,
                    context=context,
                )
                assert report.request_status is d.HandlingRequestStatus.COMPLETED
                assert len(plans.plans) == 1 and all(isinstance(a, d.Say) for a in plans.plans[0].actions)
                outputs = OutputSink()
                realized = await agent.realize_action_plan(
                    plans.plans[0],
                    d.ExecutionContext(
                        execution_id=str(uuid4()),
                        interaction_id=str(call_id),
                        current_interaction_revision=1,
                        cancellation=d.CancellationToken(),
                        interaction_context=context,
                        call_output_permit=SimpleNamespace(allows=lambda _: True),
                    ),
                    outputs,
                )
                assert realized.status is d.ExecutionStatus.COMPLETED
                assert [o.text for o in outputs.outputs if isinstance(o, d.TextFinalOutput)] == ["别着急，我在听。"]
                assert any(isinstance(o, d.AudioChunkOutput) for o in outputs.outputs)
            finally:
                await context.close()
        assert spoken == [("luotianyi", "别着急，我在听。", "tender"), ("miku", "别着急，我在听。", "happy")]
    finally:
        await runtime.shutdown()
