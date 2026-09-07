"""将数据库服务的历史格式转换为上下文数据类型。"""

import json
from dataclasses import asdict
from datetime import datetime
from typing import TYPE_CHECKING

from src.domain.conversation_type import ConversationItem

from .models import (
    AudioContent, ContextIdentity, ConversationEntry, ConversationSnapshot,
    ConversationSummary, ImageContent, SongContent, TextContent,
    UserContextSnapshot, UserPreferences, UserProfile,
)

if TYPE_CHECKING:
    from src.system.database.services.conversation_service import ConversationService


class _Storage:
    def __init__(self, database: "ConversationService", identity: ContextIdentity) -> None:
        self.database = database
        self.identity = identity

    def require_user(self) -> str:
        if self.identity.user_id is None:
            raise ValueError("无用户的交互不能写入用户资料或正式对话")
        return self.identity.user_id

    def load_user(self) -> UserContextSnapshot:
        if self.identity.user_id is None:
            return UserContextSnapshot()
        user_id = self.identity.user_id
        description = self.database.get_user_description(user_id)
        if description is None:
            raise LookupError("上下文所属用户不存在")
        data = dict(self.database.get_user_preferences(user_id) or {})
        return UserContextSnapshot(UserProfile(description), UserPreferences(
            relationship=data.get("relationship", ""),
            speaking_style=data.get("speaking_style", ""),
            personality_traits=tuple(data.get("personality_traits") or ()),
            custom_context=data.get("custom_context", ""),
            personality_text=data.get("#sym:personality_text", ""),
        ))

    def save_profile(self, profile: UserProfile) -> None:
        if not self.database.update_user_description(self.require_user(), profile.description):
            raise RuntimeError("用户画像保存失败")

    def save_preferences(self, preferences: UserPreferences) -> None:
        user_id = self.require_user()
        data = dict(self.database.get_user_preferences(user_id) or {})
        data.update(asdict(preferences))
        data["personality_traits"] = list(preferences.personality_traits)
        data["#sym:personality_text"] = data.pop("personality_text")
        if not self.database.save_user_preferences(user_id, data):
            raise RuntimeError("用户偏好保存失败")

    def load_conversation(self) -> tuple[ConversationSnapshot, int]:
        if self.identity.user_id is None:
            return ConversationSnapshot(), 0
        data = self.database.get_conversation_context_state(
            self.identity.user_id, character_id=self.identity.character_id,
        )
        entries = tuple(_decode_entry(item) for item in data["conversations"])
        return ConversationSnapshot(ConversationSummary(data["summary"]), entries), data["context_count"]

    def append(self, entries: tuple[ConversationEntry, ...]) -> None:
        items = [_encode_entry(entry) for entry in entries]
        ids = self.database.add_conversations(
            self.require_user(), items, character_id=self.identity.character_id,
        )
        if ids != [entry.entry_id for entry in entries]:
            raise RuntimeError("对话记录保存失败")

    def compact(self, summary: ConversationSummary, keep_recent: int, count: int) -> None:
        if not self.database.compact_conversation_context(
            self.require_user(), summary.text, keep_recent,
            expected_context_count=count, character_id=self.identity.character_id,
        ):
            raise RuntimeError("对话总结保存失败或上下文已经改变")


def _decode_entry(item: dict) -> ConversationEntry:
    data = item.get("meta_data") or {}
    if isinstance(data, str):
        data = json.loads(data)
    kind, text = item["type"], item["content"]
    if kind == "text":
        content = TextContent(text, tuple(data.get("terms") or ()))
    elif kind == "image":
        content = ImageContent(text, data.get("image_client_path"), data.get("image_server_path"),
                               data.get("mime_type"), tuple(data.get("terms") or ()))
    elif kind == "audio":
        content = AudioContent(text)
    elif kind == "sing":
        content = SongContent(text, data["song"], data.get("segment"))
    else:
        raise ValueError(f"不支持的历史对话类型：{kind}")
    return ConversationEntry(item["uuid"], datetime.strptime(item["timestamp"], "%Y-%m-%d %H:%M:%S"),
                             item["source"], content)


def _encode_entry(entry: ConversationEntry) -> ConversationItem:
    content = entry.content
    kinds = {TextContent: "text", ImageContent: "image", AudioContent: "audio", SongContent: "sing"}
    data = asdict(content)
    text = data.pop("text")
    return ConversationItem(entry.entry_id, entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                            entry.source, kinds[type(content)], text, data or None)
