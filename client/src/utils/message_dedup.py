"""历史消息去重工具。

与 app 端 app/utils/message_dedup.ts 对齐：
- deduplicate_by_uuid：按 uuid 过滤与已有消息重复及批次内重复，保持原顺序；
- build_fallback_uuid：服务端缺失 uuid 时生成确定性、文件名安全的 ID。
"""

import hashlib
from typing import Iterable, List, Sequence, TypeVar

T = TypeVar("T")


def deduplicate_by_uuid(existing_uuids: Iterable[str], incoming: Sequence[T]) -> List[T]:
    """过滤与 existing_uuids 重复以及批次内重复的消息，保持 incoming 顺序。"""
    seen = set(existing_uuids)
    result: List[T] = []
    for item in incoming:
        if item.uuid in seen:
            continue
        seen.add(item.uuid)
        result.append(item)
    return result


def build_fallback_uuid(source: str, type_: str, timestamp: str, content: str) -> str:
    """基于稳定字段生成确定性 ID。

    相同内容重复拉取时 ID 一致，可被 deduplicate_by_uuid 过滤；
    只包含 [a-z0-9-]，可安全用作本地音频缓存文件名。
    """
    fingerprint = f"{source}|{type_}|{timestamp}|{content}"
    digest = hashlib.sha1(fingerprint.encode("utf-8")).hexdigest()[:12]
    return f"history-{source or 'unknown'}-{type_ or 'text'}-{digest}"
