"""回复交付测试的具名能力替身，不保留旧场景编排接口。"""

from types import SimpleNamespace

from src.agent.handlers.reply_skills import ReplySkills
from src.agent.skills.contracts import TopicExtraction
from src.agent.skills.memory_retrieval import MemorySearchResult


def scripted_reply_skills(producer):
    state = {}

    async def extract(message, *, conversation_history=""):
        state.update(reply_topic=message, conversation_history=conversation_history)
        return TopicExtraction(memory_queries=("test",), sing_attempts=("test",))

    async def search(invocation, *, query):
        state["invocation"] = invocation
        return MemorySearchResult(tuple(getattr(producer, "hits", ())))

    async def select(invocation, *, attempts, excluded_segments=None, emotion_context=""):
        state["excluded_segments"] = excluded_segments
        drafts = getattr(producer, "drafts", getattr(producer, "formal_drafts", ()))
        return next((draft.sing for draft in drafts if draft.sing and draft.sing[1]), None)

    async def generate(character_id, **kwargs):
        result = await producer.generate_drafts(
            state["invocation"],
            user_context=kwargs["user_context"],
            reply_topic=state["reply_topic"],
            conversation_history=state["conversation_history"],
            excluded_segments=state.get("excluded_segments"),
        )
        for draft in getattr(result, "drafts", result):
            yield draft

    return ReplySkills(
        topic_extraction=SimpleNamespace(extract=extract),
        retrieval=SimpleNamespace(search=search),
        singing=SimpleNamespace(
            select=select,
            song_information=lambda invocation, **kwargs: (kwargs["song_id"], (kwargs["segment_id"],), ""),
        ),
        reply=SimpleNamespace(generate=generate),
    )
