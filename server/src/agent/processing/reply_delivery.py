"""把角色回复草稿转换为一致的对话记录和行动。"""

from datetime import datetime, timezone
from uuid import uuid4

import src.domain.agent as d
from src.agent.context import ConversationEntry, SongContent, TextContent
from src.agent.skills.contracts import ReplyDraft
from src.utils.enum_type import ConversationSource


def render_conversation_history(snapshot) -> str:
    """把已压缩总结与近期对话渲染成生成提示使用的历史文本。"""
    lines = []
    if snapshot.summary.text:
        lines.append(snapshot.summary.text)
    lines.extend(f"{entry.source}: {entry.content.text}" for entry in snapshot.entries)
    return "\n".join(lines)


def build_reply_delivery(
    request: d.HandleStimulusRequest,
    drafts: tuple[ReplyDraft, ...],
    *,
    prefix: str,
) -> tuple[tuple[ConversationEntry, ...], tuple[d.Action, ...]]:
    """过滤不可实现的草稿，并生成相互对齐的历史记录与 Say/Sing 行动。"""
    deliverable = tuple(
        draft
        for draft in drafts
        if (draft.sing is not None and draft.sing[0].strip() and draft.sing[1].strip())
        or (draft.sing is None and draft.content.strip() and draft.sound_content.strip())
    )
    entries = _reply_entries(deliverable)
    actions = _reply_actions(request, deliverable, tuple(entry.entry_id for entry in entries), prefix=prefix)
    return entries, actions


def _reply_text(draft: ReplyDraft) -> str:
    """返回实时呈现与历史记录共用的回复正文。"""
    return f"{draft.content}\n{draft.lyrics}".strip() if draft.lyrics else draft.content


def _reply_entries(drafts: tuple[ReplyDraft, ...]) -> tuple[ConversationEntry, ...]:
    """把可交付草稿转成 agent 侧正式对话记录。"""
    entries: list[ConversationEntry] = []
    for draft in drafts:
        content = (
            SongContent(_reply_text(draft), draft.sing[0], draft.sing[1])
            if draft.sing is not None
            else TextContent(draft.content)
        )
        entries.append(
            ConversationEntry(
                entry_id=str(uuid4()),
                timestamp=datetime.now(timezone.utc).astimezone().replace(tzinfo=None),
                source=ConversationSource.AGENT.value,
                content=content,
            )
        )
    return tuple(entries)


def _reply_actions(
    request: d.HandleStimulusRequest,
    drafts: tuple[ReplyDraft, ...],
    message_ids: tuple[str, ...],
    *,
    prefix: str,
) -> tuple[d.Action, ...]:
    """把回复草稿按序转成 Say/Sing，并保持消息标识与历史记录对齐。"""
    if len(drafts) != len(message_ids):
        raise ValueError("reply drafts and message ids must stay aligned")
    actions: list[d.Action] = []
    for index, (draft, message_id) in enumerate(zip(drafts, message_ids)):
        action_id = f"{request.request_id}-{prefix}{index}"
        expression = d.ChangeExpression(expression_id=draft.expression) if draft.expression else None
        if draft.sing is not None:
            actions.append(
                d.Sing(
                    action_id=action_id,
                    song_id=draft.sing[0],
                    segment_id=draft.sing[1],
                    expression=expression,
                    content=_reply_text(draft),
                    message_id=message_id,
                )
            )
        else:
            actions.append(
                d.Say(
                    action_id=action_id,
                    content=draft.content,
                    sound_content=draft.sound_content,
                    prepared_audio_ref=None,
                    tone=d.Tone(value=draft.tone or "normal"),
                    expression=expression,
                    delivery=d.OutputDelivery.CONVERSATION,
                    message_id=message_id,
                )
            )
    return tuple(actions)
