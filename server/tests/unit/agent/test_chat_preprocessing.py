"""文本和图片输入的预处理与落库：先落库再 READY，且不等于消费。"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest
from routing_support import Sink, request

import src.domain.agent as d
from src.agent import Agent
from src.agent.handlers.stimulus.chat import ChatPreprocessingHandler
from src.agent.handlers.stimulus.router import StimulusRouter
from src.agent.skills.cognitive import ImageUnderstandingSkill, TextPreprocessingSkill
from src.infrastructure.media import MediaResolutionError, ResolvedMedia


class _Understanding:
    """固定返回给定关键词的文本预处理替身。"""

    def __init__(self, terms=()):
        self.terms = tuple(terms)

    def extract_terms(self, text):
        return self.terms


class _Resolver:
    def __init__(self, media=None, error=None):
        self.media = media or ResolvedMedia(data=b"image", mime_type="image/png")
        self.error = error
        self.refs = []

    def resolve(self, media_ref, *, owner_user_id):
        self.refs.append((media_ref, owner_user_id))
        if self.error is not None:
            raise self.error
        return self.media


class _ImageUnderstanding:
    def __init__(self, description="一只白猫"):
        self.description = description
        self.calls = []

    async def generate_response(self, *, image_base64):
        self.calls.append(image_base64)
        return {"content": self.description}


class _Conversation:
    def __init__(self):
        self.entries = []

    async def append(self, entries):
        self.entries.extend(entries)


def context(interaction_id="i", user_id="u", character_id="luotianyi"):
    value = SimpleNamespace(
        identity=SimpleNamespace(interaction_id=interaction_id, user_id=user_id, character_id=character_id)
    )
    value.conversation = _Conversation()
    return value


def agent(terms=("《歌》是一首歌",)):
    return Agent(
        character_id="luotianyi",
        stimulus_router=StimulusRouter(
            [(d.StimulusKind.TEXT_MESSAGE, ChatPreprocessingHandler(_Understanding(terms), None))]
        ),
    )


def image_request(media_id="image"):
    image = d.ImageMessage(
        stimulus_id="image-stimulus",
        schema_version=1,
        occurred_at=request().stimulus.occurred_at,
        source=d.StimulusSource.USER,
        target_character_ids=("luotianyi",),
        user_id="u",
        ephemeral=False,
        media_ref=d.MediaRef(media_id=media_id),
        client_msg_id="image-client",
    )
    base = request()
    return d.HandleStimulusRequest(
        request_id="image-request",
        stimulus=image,
        interaction=replace_pending(base.interaction, image),
        cancellation=d.CancellationToken(),
    )


def replace_pending(interaction, stimulus):
    return type(interaction)(
        interaction_id=interaction.interaction_id,
        interaction_revision=interaction.interaction_revision,
        user_id=interaction.user_id,
        pending_stimuli=(stimulus,),
        now=interaction.now,
        timezone=interaction.timezone,
        supported_outputs=interaction.supported_outputs,
        response_deadline=interaction.response_deadline,
        connection_state=interaction.connection_state,
    )


@pytest.mark.asyncio
async def test_text_message_is_persisted_before_ready_and_not_consumed():
    ctx = context()
    report = await agent().handle_stimulus(request(), Sink(), context=ctx)
    assert len(ctx.conversation.entries) == 1
    entry = ctx.conversation.entries[0]
    assert entry.source == "user"
    assert entry.content.text == "你好"
    assert entry.content.terms == ("《歌》是一首歌",)
    assert isinstance(entry.timestamp, datetime) and entry.timestamp.tzinfo is None
    assert entry.timestamp == (
        request().interaction.now.replace(tzinfo=None)
        + timedelta(microseconds=request().interaction.interaction_revision * 10)
    )
    assert report.preprocessed_input.stimulus_id == "m2"
    assert report.preprocessed_input.text == "你好"
    assert report.preprocessed_input.conversation_entry_ids == (entry.entry_id,)
    assert report.consumed_pending_stimulus_ids == ()
    assert report.retained_pending_stimulus_ids == ("m2", "m1")
    assert report.emitted_plan_ids == ()
    assert report.request_status is d.HandlingRequestStatus.COMPLETED


@pytest.mark.asyncio
async def test_missing_context_fails_instead_of_silently_skipping_persistence():
    report = await agent().handle_stimulus(request(), Sink())
    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.preprocessed_input is None


@pytest.mark.asyncio
async def test_image_is_one_user_conversation_with_agent_only_description_text():
    resolver = _Resolver()
    understanding = _ImageUnderstanding()
    handler = ChatPreprocessingHandler(
        _Understanding(("白猫",)),
        ImageUnderstandingSkill({}, resolver, vlm_module=understanding),
    )
    runtime = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([(d.StimulusKind.IMAGE_MESSAGE, handler)]))
    ctx = context()

    report = await runtime.handle_stimulus(image_request(), Sink(), context=ctx)

    assert resolver.refs == [(d.MediaRef(media_id="image"), "u")]
    assert understanding.calls == ["data:image/png;base64,aW1hZ2U="]
    assert [(entry.source, type(entry.content).__name__) for entry in ctx.conversation.entries] == [
        ("user", "ImageContent"),
    ]
    media_entry = ctx.conversation.entries[0]
    assert media_entry.content.text == "[图片理解]: [一张图片]:一只白猫"
    assert media_entry.content.media_id == "image"
    assert media_entry.content.mime_type == "image/png"
    assert media_entry.content.terms == ("白猫",)
    assert report.preprocessed_input.text == "[图片理解]: [一张图片]:一只白猫"
    assert report.preprocessed_input.conversation_entry_ids == (media_entry.entry_id,)
    assert report.consumed_pending_stimulus_ids == ()
    assert report.emitted_plan_ids == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "error",
    [
        MediaResolutionError(code="MEDIA_UNKNOWN", media_id="missing"),
        MediaResolutionError(code="MEDIA_UNAUTHORIZED", media_id="private"),
        MediaResolutionError(code="MEDIA_EMPTY", media_id="empty"),
        MediaResolutionError(code="MEDIA_RESOLVER_NOT_CONFIGURED", media_id="image"),
    ],
)
async def test_illegal_media_stops_before_image_understanding(error):
    resolver = _Resolver(error=error)
    understanding = _ImageUnderstanding()
    handler = ChatPreprocessingHandler(
        _Understanding(),
        ImageUnderstandingSkill({}, resolver, vlm_module=understanding),
    )
    runtime = Agent(character_id="luotianyi", stimulus_router=StimulusRouter([(d.StimulusKind.IMAGE_MESSAGE, handler)]))
    ctx = context()

    report = await runtime.handle_stimulus(image_request(media_id=error.media_id), Sink(), context=ctx)

    assert report.request_status is d.HandlingRequestStatus.FAILED
    assert report.error_code is d.HandlingErrorCode.INTERNAL_ERROR
    assert report.preprocessed_input is None
    assert understanding.calls == []
    assert ctx.conversation.entries == []


def test_text_preprocessing_skill_returns_terms(monkeypatch):
    class _Linker:
        def __init__(self, config):
            self.config = config

        def extract_and_verify(self, text):
            return ["《歌》是一首歌"] if "歌" in text else []

    monkeypatch.setattr("src.agent.skills.cognitive.text_preprocessing.SongEntityLinker", _Linker)
    skill = TextPreprocessingSkill({"song_entity_linker": {"songname_file": "unused"}})
    assert skill.extract_terms("唱《歌》") == ("《歌》是一首歌",)
    assert skill.extract_terms("随便聊聊") == ()
    with pytest.raises(TypeError):
        skill.extract_terms(None)
