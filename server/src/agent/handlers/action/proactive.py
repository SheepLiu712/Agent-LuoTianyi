"""主动话题的执行结果和事件分享记录。"""

from dataclasses import replace

import src.domain.agent as d
from src.agent.handlers.action.call import _completed


class RequestCallSpeechHandler:
    async def realize(self, action, execution_context, outputs):
        if not isinstance(action, d.RequestCallSpeech):
            raise TypeError("expected RequestCallSpeech")
        return _completed(action)


class MarkTopicSharedHandler:
    def __init__(self, events):
        self._events = events

    async def realize(self, action, execution_context, outputs):
        if not isinstance(action, d.MarkTopicShared):
            raise TypeError("expected MarkTopicShared")
        identity = execution_context.interaction_context.identity
        self._events.claim(
            action.event_id,
            user_id=identity.user_id,
            character_id=identity.character_id,
            trigger_key=action.trigger_key,
        )
        return replace(_completed(action), irreversible_effect_committed=True)
