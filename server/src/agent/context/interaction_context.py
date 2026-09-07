"""一个交互持有的三部分上下文。"""

from typing import TYPE_CHECKING

from ._lifecycle import _Lifecycle, _complete
from ._storage import _Storage
from .conversation_context import ConversationContext
from .models import CompactionPolicy, ContextIdentity, ConversationSummarizer, ConversationSnapshot, UserContextSnapshot
from .recalled_memory_context import RecalledMemoryContext
from .user_context import UserContext

if TYPE_CHECKING:
    from src.system.database.services.conversation_service import ConversationService


class InteractionContext:
    """交互独有的用户资料、近期对话和召回记忆。"""

    def __init__(
        self, *, identity: ContextIdentity, database: "ConversationService",
        summarizer: ConversationSummarizer | None = None,
        policy: CompactionPolicy = CompactionPolicy(),
    ) -> None:
        """从 database 同步加载 identity 的资料及对话，并建立空召回缓存。

        summarizer 和 policy 控制对话压缩；异步代码应通过 ContextFactory.get 创建。
        """
        self._identity = identity
        self._state = _Lifecycle()
        storage = _Storage(database, identity)
        user_snapshot = storage.load_user()
        conversation_snapshot, _ = storage.load_conversation()
        self._user = UserContext(snapshot=user_snapshot, identity=identity, database=database)
        self._conversation = ConversationContext(
            snapshot=conversation_snapshot, identity=identity, database=database,
            summarizer=summarizer, policy=policy,
        )
        self._recalled_memory = RecalledMemoryContext()
        for part in (self._user, self._conversation, self._recalled_memory):
            part._state = self._state

    @property
    def identity(self) -> ContextIdentity:
        """返回上下文所属角色、交互和用户。"""
        return self._identity

    @property
    def user(self) -> UserContext:
        """返回用户画像与偏好上下文。"""
        return self._user

    @property
    def conversation(self) -> ConversationContext:
        """返回近期对话及总结上下文。"""
        return self._conversation

    @property
    def recalled_memory(self) -> RecalledMemoryContext:
        """返回按刺激归属管理的召回缓存。"""
        return self._recalled_memory

    async def close(self) -> None:
        """等待已开始的数据操作结束，清空内存并关闭上下文；重复调用无影响。"""
        await _complete(self._close())

    async def _close(self) -> None:
        async with self._state.lock:
            self._state.closed = True
            self._user._snapshot = UserContextSnapshot()
            self._conversation._snapshot = ConversationSnapshot()
            self._recalled_memory._entries.clear()
