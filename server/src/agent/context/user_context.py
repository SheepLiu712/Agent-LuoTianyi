"""交互使用的用户画像与偏好。"""

import asyncio
from dataclasses import replace
from typing import TYPE_CHECKING

from ._lifecycle import _Lifecycle, _complete
from ._storage import _Storage
from .models import ContextIdentity, UserContextSnapshot, UserPreferences, UserProfile

if TYPE_CHECKING:
    from src.system.database.services.conversation_service import ConversationService


class UserContext:
    """由 InteractionContext 创建的用户资料视图。"""

    def __init__(self, *, snapshot: UserContextSnapshot, identity: ContextIdentity,
                 database: "ConversationService") -> None:
        """以 snapshot 初始化资料视图，使用 database 保存 identity 所属用户的资料。"""
        self._snapshot = snapshot
        self._state = _Lifecycle()
        self._storage = _Storage(database, identity)

    def read(self) -> UserContextSnapshot:
        """返回当前用户画像和偏好。"""
        self._state.check()
        return self._snapshot

    async def update_profile(self, profile: UserProfile) -> None:
        """保存 profile 后更新内存；保存失败抛异常并保留原画像。"""
        if not isinstance(profile, UserProfile):
            raise TypeError("profile 应为 UserProfile")
        async with self._state.lock:
            self._state.check()
            await _complete(self._update(profile))

    async def update_preferences(self, preferences: UserPreferences) -> None:
        """保存 preferences 后更新内存；保存失败抛异常并保留原偏好。"""
        if not isinstance(preferences, UserPreferences):
            raise TypeError("preferences 应为 UserPreferences")
        async with self._state.lock:
            self._state.check()
            await _complete(self._update(preferences))

    async def _update(self, value: UserProfile | UserPreferences) -> None:
        if isinstance(value, UserProfile):
            await asyncio.to_thread(self._storage.save_profile, value)
            self._snapshot = replace(self._snapshot, profile=value)
        else:
            await asyncio.to_thread(self._storage.save_preferences, value)
            self._snapshot = replace(self._snapshot, preferences=value)
