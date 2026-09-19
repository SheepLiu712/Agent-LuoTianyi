"""幂等接纳歌曲知识候选，在同一幂等边界内写入歌曲知识与关键词索引。

写入对象是既有歌曲知识库（`res/knowledge/knowledge_db.db`）与既有关键词文件
（`res/knowledge/song_name_keywords.txt`、`song_lyric_keywords.txt`），不新建第二份知识库。

现有 `Song` 表没有来源与修订列，因此幂等门以名称与 safe name 的既有项为准
（与工单 #81 的「名称/safe name 已有项跳过」一致）；来源、外部标识与修订随结果返回，
供调用方记录与追踪，不参与去重判定。

「缺介绍失败、不提交半份知识」由领域类型保证：`SongKnowledgeCandidate` 要求介绍非空白，
world 侧也只会投递介绍非空的候选，因此本技能不需要额外的完整性分支。
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

from src.domain.agent import SongKnowledgeCandidate, SourceRef
from src.subconscious.music_knowledge.song_database import (
    Song,
    get_song_session,
    init_song_db,
)


class SongAcceptanceStatus(str, Enum):
    """一次接纳的结果：已写入、已有项跳过或写入失败。"""

    ACCEPTED = "accepted"
    ALREADY_PRESENT = "already_present"
    FAILED = "failed"


@dataclass(frozen=True)
class SongAcceptanceResult:
    """接纳结果的只读事实；detail 记录跳过或失败原因。"""

    status: SongAcceptanceStatus
    detail: str = ""

    @property
    def knowledge_written(self) -> bool:
        """本次接纳是否真的写入了知识。"""
        return self.status is SongAcceptanceStatus.ACCEPTED


def safe_song_name(name: str) -> str:
    """按既有数据使用的规则清洗歌名，用于与已有项比对。"""
    return "".join(c for c in name if c.isalnum() or c in (" ", "-", "_")).strip()


class SongKnowledgeAcceptanceSkill:
    """把已规范化的歌曲候选写入歌曲知识与关键词索引，不产生任何外部效果。"""

    def __init__(self, config: dict[str, Any]) -> None:
        """校验本层配置容器并解析知识库与关键词文件位置；构造阶段不触碰文件系统。"""
        if not isinstance(config, dict):
            raise TypeError("song_knowledge 配置必须是字典")
        song_database = config.get("song_database")
        if song_database is not None and not isinstance(song_database, dict):
            raise TypeError("song_knowledge.song_database 必须是字典")
        server_root = Path(__file__).resolve().parents[4]
        configured = dict(song_database or {})
        self._song_database = {
            "db_folder": configured.get("db_folder") or str(server_root / "res" / "knowledge"),
            "db_file": configured.get("db_file") or "knowledge_db.db",
        }
        knowledge_dir = Path(config.get("knowledge_dir") or server_root / "res" / "knowledge")
        self._song_name_file = knowledge_dir / "song_name_keywords.txt"
        self._lyric_file = knowledge_dir / "song_lyric_keywords.txt"
        self._database_lock = threading.Lock()
        self._database_ready = False

    async def accept(
        self,
        *,
        source_ref: SourceRef,
        external_song_id: str,
        revision: int,
        candidate: SongKnowledgeCandidate,
    ) -> SongAcceptanceResult:
        """接纳一个候选；阻塞的知识库与文件写入在工作线程内完成。

        返回的 detail 记录来源与外部标识，便于调用方追踪；同一候选重复接纳时跳过写入。
        """
        if not isinstance(source_ref, SourceRef) or not isinstance(candidate, SongKnowledgeCandidate):
            raise TypeError("source_ref 与 candidate 必须使用领域类型")
        if not isinstance(external_song_id, str) or not external_song_id.strip():
            raise ValueError("external_song_id 不能为空")
        if type(revision) is not int or revision < 0:
            raise ValueError("revision 必须是非负整数")
        result = await asyncio.to_thread(self._accept_sync, candidate)
        if result.status is SongAcceptanceStatus.ACCEPTED:
            return SongAcceptanceResult(
                result.status,
                f"{source_ref.source_id}/{external_song_id}@{revision}",
            )
        return result

    def _accept_sync(self, candidate: SongKnowledgeCandidate) -> SongAcceptanceResult:
        song_name = candidate.song_name
        safe_name = safe_song_name(song_name)
        try:
            self._ensure_database()
        except Exception as error:  # noqa: BLE001 - 知识库不可用时明确失败，不写半份知识
            return SongAcceptanceResult(SongAcceptanceStatus.FAILED, f"知识库不可用：{error}")
        session = get_song_session()
        try:
            if self._exists(session, song_name, safe_name):
                return SongAcceptanceResult(SongAcceptanceStatus.ALREADY_PRESENT, f"已有项：{song_name}")
            row = Song(
                name=song_name,
                safe_name=safe_name,
                uploader=candidate.uploader or "",
                singers=",".join(candidate.singers),
                introduction=candidate.introduction,
                lyrics=candidate.lyrics or "",
            )
            session.add(row)
            session.commit()
            try:
                self._append_keywords(song_name, candidate.lyric_keywords)
            except Exception as error:  # noqa: BLE001 - 关键词写入失败时回滚知识，不留半份
                session.query(Song).filter(Song.uuid == row.uuid).delete()
                session.commit()
                return SongAcceptanceResult(
                    SongAcceptanceStatus.FAILED,
                    f"关键词索引写入失败：{error}",
                )
            return SongAcceptanceResult(SongAcceptanceStatus.ACCEPTED, song_name)
        except Exception as error:  # noqa: BLE001 - 单首歌失败不得影响其它候选
            session.rollback()
            return SongAcceptanceResult(SongAcceptanceStatus.FAILED, f"知识写入失败：{error}")
        finally:
            session.close()

    def _ensure_database(self) -> None:
        with self._database_lock:
            if not self._database_ready:
                init_song_db(self._song_database)
                self._database_ready = True

    @staticmethod
    def _exists(session, song_name: str, safe_name: str) -> bool:
        return session.query(Song).filter((Song.name == song_name) | (Song.safe_name == safe_name)).first() is not None

    def _append_keywords(self, song_name: str, lyric_keywords: tuple[str, ...]) -> None:
        self._song_name_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self._song_name_file, "a", encoding="utf-8") as name_file:
            name_file.write(f"{song_name}\n")
        lines = [f"{keyword}=>{keyword}是《{song_name}》的歌词" for keyword in lyric_keywords if keyword.strip()]
        if not lines:
            return
        with open(self._lyric_file, "a", encoding="utf-8") as lyric_file:
            lyric_file.writelines(f"{line}\n" for line in lines)
