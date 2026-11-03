"""既有处理器测试的能力替身；不替代正式装配测试。"""

from types import SimpleNamespace


def stub_retrieval(memories):
    async def search(invocation, *, query):
        return await memories[invocation.character_id].search_memory_context_for_topic(
            invocation.require_user_id(), list(query.clues)
        )
    return SimpleNamespace(search=search)


def stub_singing(backend):
    async def select(invocation, *, attempts, excluded_segments=None):
        return await backend.build_sing_plan(invocation.character_id, list(attempts),
                                             excluded_segments=excluded_segments, confirmed_intent=True)
    def information(invocation, *, song_id, segment_id=None):
        return song_id, (segment_id,), backend.get_segment_lyrics(invocation.character_id, song_id, segment_id)
    return SimpleNamespace(select=select, song_information=information)


def song_material(manager):
    async def get_song(invocation, *, song_id, segment_id=None):
        canonical, segments = manager.can_i_sing_song(song_id)
        return SimpleNamespace(song_id=canonical, segments=tuple(segments), lyrics=manager.get_full_lyrics(song_id))
    return SimpleNamespace(get_song=get_song)
