"""授权记忆检索与权威歌曲资料查询。"""

from dataclasses import dataclass
from enum import Enum

from src.agent.skills.contracts import SkillInvocation
from src.domain import MemoryHit


class RetrievalScope(str, Enum):
    USER = "user"
    CHARACTER = "character"
    PUBLIC_KNOWLEDGE = "public_knowledge"


@dataclass(frozen=True)
class MemoryQuery:
    clues: tuple[str, ...]
    scopes: frozenset[RetrievalScope] = frozenset((RetrievalScope.USER, RetrievalScope.CHARACTER))
    limit: int = 3
    similarity_threshold: float = 0.8

    def __post_init__(self):
        if not self.scopes or any(not isinstance(scope, RetrievalScope) for scope in self.scopes):
            raise ValueError("检索作用域必须是已授权的用户或角色范围")
        if type(self.limit) is not int or not 1 <= self.limit <= 100:
            raise ValueError("检索结果上限必须在 1 到 100 之间")
        if any(not isinstance(clue, str) for clue in self.clues):
            raise TypeError("查询线索必须是文本")


@dataclass(frozen=True)
class MemorySearchResult:
    hits: tuple[MemoryHit, ...]

    def render_for_prompt(self) -> list[str]:
        return [hit.rendered_text for hit in self.hits]


@dataclass(frozen=True)
class SongKnowledgeResult:
    song_id: str
    found: bool
    can_sing: bool
    segments: tuple[str, ...] = ()
    lyrics: str = ""
    introduction: str = ""


@dataclass(frozen=True)
class SongPage:
    songs: tuple[SongKnowledgeResult, ...]
    next_cursor: str | None


class MemoryRetrievalSkill:
    def __init__(self, config: dict, *, memories, singing, knowledge) -> None:
        self._memories = dict(memories)
        self._singing = singing
        self._knowledge = knowledge

    async def search(self, invocation: SkillInvocation, *, query: MemoryQuery) -> MemorySearchResult:
        include_user = RetrievalScope.USER in query.scopes
        include_character = RetrievalScope.CHARACTER in query.scopes
        user_id = invocation.require_user_id() if include_user else None
        memory = self._memories[invocation.character_id]
        clues = tuple(dict.fromkeys(clue.strip() for clue in query.clues if clue.strip()))
        hits = []
        if include_user or include_character:
            context = await memory.search_memory_context_for_topic(
                user_id,
                list(clues),
                k=query.limit,
                similarity_threshold=query.similarity_threshold,
                include_user=include_user,
                include_character=include_character,
            )
            hits.extend(context.hits)
        if RetrievalScope.PUBLIC_KNOWLEDGE in query.scopes:
            for identity, content in await self._knowledge.search(clues, limit=query.limit):
                hits.append(
                    MemoryHit(content, 1.0, "；".join(clues), source="song_knowledge", source_record_id=identity)
                )
        hits.sort(key=lambda hit: hit.score, reverse=True)
        return MemorySearchResult(tuple(hits[: query.limit]))

    async def list_songs(self, invocation: SkillInvocation, *, cursor=None, limit=20) -> SongPage:
        if type(limit) is not int or not 1 <= limit <= 100:
            raise ValueError("歌曲目录页大小必须在 1 到 100 之间")
        names = sorted(
            {
                self._singing.canonical_song_id(invocation, name)
                for name in set(self._singing.catalog(invocation)) | set(await self._knowledge.song_names())
            }
        )
        if cursor is not None:
            names = [name for name in names if name > cursor]
        selected = names[:limit]
        songs = tuple([await self.get_song(invocation, song_id=name) for name in selected])
        return SongPage(songs, selected[-1] if len(names) > limit else None)

    async def get_song(self, invocation: SkillInvocation, *, song_id, segment_id=None) -> SongKnowledgeResult:
        available = self._singing.song_information(invocation, song_id=song_id, segment_id=segment_id)
        knowledge = await self._knowledge.get_song(song_id)
        if available is not None:
            canonical, segments, lyrics = available
            return SongKnowledgeResult(
                canonical, True, bool(segments), segments, lyrics, knowledge[1] if knowledge else ""
            )
        if segment_id is not None:
            return SongKnowledgeResult(song_id, False, False)
        if knowledge:
            return SongKnowledgeResult(song_id, True, False, (), knowledge[2], knowledge[1])
        return SongKnowledgeResult(song_id, False, False)
