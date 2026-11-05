"""旧生命周期测试使用的受控音频端口，提供同一个 Omni 会话契约。"""

from src.domain.call import omni
from src.infrastructure.models.realtime_speech import (
    RealtimeSpeechConfig,
    SpeechStarted,
    SpeechStopped,
    TurnCompleted,
    TurnInvalid,
    ProviderFailed,
)


class CallTestSessionFactory:
    def __init__(self, speech):
        self.speech = speech

    async def open(self, call_id, instructions):
        session = await self.speech.create(call_id)
        try:
            await session.start(RealtimeSpeechConfig(instructions=instructions))
        except BaseException:
            await session.close()
            raise
        return CallTestSession(session)


class CallTestSession:
    def __init__(self, session):
        self.session = session
        self.item_id = "test-input"
        self.instructions = []
        self._turn = 0

    def __getattr__(self, name):
        return getattr(self.session, name)

    async def push(self, frame):
        if isinstance(frame, omni.AudioFrame):
            await self.session.push_audio(frame)
        else:
            self.instructions.append(frame)

    async def events(self):
        async for event in self.session.events():
            if isinstance(event, SpeechStarted):
                self.item_id = event.item_id or "test-input"
                yield omni.SpeechStarted(self.item_id)
            elif isinstance(event, SpeechStopped):
                yield omni.SpeechStopped(event.item_id or self.item_id)
            elif isinstance(event, TurnCompleted):
                self._turn += 1
                item_id = event.item_id or f"test-input-{self._turn}"
                yield omni.SpeechStopped(item_id)
                yield omni.TranscriptFinal(item_id, event.semantic.transcript or event.semantic.render())
                yield omni.ReplyStarted(f"response-{self._turn}", item_id)
                yield omni.ReplySegment(f"response-{self._turn}", 0, "正式回答")
                yield omni.ReplyFinished(f"response-{self._turn}")
            elif isinstance(event, TurnInvalid):
                yield omni.TranscriptFinal(event.item_id or self.item_id, "")
            elif isinstance(event, ProviderFailed):
                raise RuntimeError(event.error_code)
            else:
                yield event

    async def interrupt(self, response_id):
        pass

    async def submit_tool_result(self, tool_call_id, result):
        pass

    async def close(self):
        await self.session.close()


def bind_test_omni(agent, factory):
    from src.agent.facade import Agent
    from src.agent.skills.contracts import CharacterNarrative
    from src.agent.processing.omni_background import CallSessionPrompt

    if isinstance(agent, Agent) and (
        agent._omni_factory is None
        or isinstance(agent._omni_factory, CallTestSessionFactory)
        or not agent._omni_factory.is_configured
    ):
        agent._omni_factory = CallTestSessionFactory(factory)
        agent._narrative = CharacterNarrative(name="测试角色", persona="测试人格", speaking_style="自然")
        agent._omni_prompt = CallSessionPrompt("res/agent/prompts/realtime_call_prompt.json")
    elif getattr(agent, "_test_omni_bound", False) or not hasattr(agent, "open_omni_session"):

        async def open_session(context, call_id):
            return await CallTestSessionFactory(factory).open(call_id, "测试通话背景")

        agent.open_omni_session = open_session
        agent._test_omni_bound = True
    return agent

    # 生命周期测试替身也必须提供新的会话入口。


def bind_call_test_creator(**resources):
    from src.stage.call.call_stage import bind_call_stage_creator

    get_agent = resources["get_agent"]
    factory = resources["speech_factory"]
    resources["get_agent"] = lambda character_id: bind_test_omni(get_agent(character_id), factory)
    return bind_call_stage_creator(**resources)
