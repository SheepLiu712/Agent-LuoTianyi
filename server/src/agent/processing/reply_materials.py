"""回复处理器使用的纯材料转换，不持有技能或执行场景规则。"""

from dataclasses import dataclass, replace

from src.agent.skills.contracts import ReplyDraft
from src.domain import MemoryHit
from src.utils.helpers import get_unified_song_name


@dataclass(frozen=True)
class ReplyGenerationResult:
    drafts: tuple[ReplyDraft, ...] = ()
    memory_hits: tuple[MemoryHit, ...] = ()
    learning_requests: tuple[str, ...] = ()


def resolve_song_selection(candidate):
    if candidate and candidate[0] and candidate[1]:
        return candidate, ()
    requests = (candidate[0],) if candidate and candidate[0] and candidate[0] != "random_song" else ()
    return None, requests


def enrich_reply_drafts(drafts, *, sing_plan, lyrics):
    enriched = []
    for draft in drafts:
        if draft.sing is None:
            enriched.append(draft)
        elif (
            sing_plan is not None
            and draft.sing[1] == sing_plan[1]
            and get_unified_song_name(draft.sing[0]) == get_unified_song_name(sing_plan[0])
        ):
            enriched.append(replace(draft, sing=sing_plan, lyrics=lyrics))
    return tuple(enriched)
