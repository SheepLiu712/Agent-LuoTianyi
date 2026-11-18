"""日记授权材料与表达格式的内部实现。"""

from __future__ import annotations

import json
import re
from datetime import date
from typing import List, Optional

from src.utils.asyncio_helpers import run_sync_owned
from src.utils.logger import get_logger


class DiaryMaterials:
    def __init__(self, config: dict, *, database):
        self.config = config
        self.database_manager = database
        self.logger = get_logger(__name__)

    async def _collect_materials(
        self,
        user_id: str,
        character_id: str,
        target_date: str,
    ) -> str:
        """
        收集日记素材：今日聊天记录 + 今日用户动态。

        返回值是一个纯文本字符串，直接嵌入到 prompt 的
        {{conversation_materials}} 占位符中。

        收集策略：
          - 聊天记录：从数据库中拉取最近 100 条对话，在内存中按日期过滤
          - 用户动态：通过 DynamicStore 获取最近 50 条，按日期 + author_type 过滤
          - 两者各取最多 30 条，避免 prompt 过长

        如果没有任何素材，返回友好的缺省提示（"今天没有特别的互动记录。"）。
        日记能力据此跳过生成，不编造当日互动。
        """
        if self.database_manager is None:
            return "今天没有特别的互动记录。"

        lines: List[str] = []
        lines.extend(await run_sync_owned(self._collect_conversation_materials, user_id, character_id, target_date))
        lines.extend(await run_sync_owned(self._collect_dynamic_materials, user_id, target_date))
        return "\n".join(lines) if lines else "今天没有特别的互动记录。"

    def _collect_conversation_materials(
        self,
        user_id: str,
        character_id: str,
        target_date: str,
    ) -> list[str]:
        """读取并格式化当天最近的对话材料。"""
        service = self.database_manager.conversation_service
        total = service.get_total_conversation_count(user_id, character_id=character_id)
        if total <= 0:
            return []
        conversations = service.get_history_from_db(
            user_id,
            max(0, total - 100),
            total,
            character_id=character_id,
        )
        today = [item for item in conversations if item.timestamp.startswith(target_date)]
        if not today:
            return []
        return [
            "【今日聊天记录】",
            *(f"[{'用户' if item.source == 'user' else '角色'}] {item.content}" for item in today[-30:]),
        ]

    def _collect_dynamic_materials(self, user_id: str, target_date: str) -> list[str]:
        """读取并格式化当天由用户发布的动态材料。"""
        store = self.database_manager.dynamic_store
        if store is None:
            return []
        items = store.list_dynamics_for_user(user_id, limit=50).get("items", [])
        today = [
            item
            for item in items
            if item.get("created_at", "").startswith(target_date) and item.get("author_type") == "user"
        ]
        if not today:
            return []
        return ["\n【今日用户动态】", *(f"[用户] {item.get('content', '')}" for item in today)]

    # ────────────────────── 日记文本解析 ──────────────────────

    def _parse_diary_result(self, raw: str, target_date: Optional[str] = None) -> Optional[str]:
        """
        解析 LLM 返回的日记文本，返回格式化后的完整文本。

        LLM 输出期望格式（严格按照 prompt 要求）：

            心情：<标签>

            <正文内容>

        解析规则：
          1. 匹配「心情：」或「心情:」行提取心情标签（支持中英文冒号）
          2. 匹配「正文：」或「正文」行标记正文开始
          3. 跳过「标题：」「摘要：」行（旧版 prompt 产物，兼容处理）
          4. 正文中的空行保留（段落分隔），开头空行会被 strip 掉
          5. 如果没有任何正文内容，回退使用原始 LLM 输出

        返回格式：

            2026-07-16 · 心情: 开心

            <正文>

        Args:
            raw: LLM 原始输出文本
            target_date: 日记日期（YYYY-MM-DD），用于构建表头

        Returns:
            格式化后的完整日记文本，解析失败返回 None
        """
        if not raw or not raw.strip():
            return None

        # 先剔除 LLM 思考块（<think>...</think>），避免思考内容混入日记
        raw = self._strip_think_block(raw)
        if not raw:
            return None

        mood, body_lines = self._parse_diary_lines(raw.strip().split("\n"))
        body = "\n".join(body_lines).strip()
        # 压缩连续空行（LLM 输出中常见多余空行）
        body = re.sub(r"\n{3,}", "\n\n", body)
        if not body:
            body = raw  # 保底：解析失败时使用原始输出

        # 构建最终展示文本
        date_str = target_date or date.today().strftime("%Y-%m-%d")
        header = f"{date_str} · 心情: {mood}" if mood else f"{date_str}"
        return f"{header}\n\n{body}"

    @staticmethod
    def _parse_diary_lines(lines: list[str]) -> tuple[str, list[str]]:
        """提取心情和正文行，同时兼容旧版标题与摘要。"""
        mood = ""
        body_lines: list[str] = []
        in_body = False
        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_body:
                    body_lines.append("")
                continue
            mood_match = re.match(r"^心情\s*[：:]\s*(.*)$", stripped)
            if mood_match:
                mood = mood_match.group(1).strip()
                continue
            body_match = re.match(r"^正文(?:\s*[：:]\s*(.*))?$", stripped)
            if body_match:
                in_body = True
                inline_body = (body_match.group(1) or "").strip()
                if inline_body:
                    body_lines.append(inline_body)
                continue
            if not in_body and re.match(r"^(标题|摘要)\s*[：:]", stripped):
                continue
            in_body = True
            body_lines.append(stripped)
        return mood, body_lines

    # ────────────────────── 用户信息查询 ──────────────────────

    @staticmethod
    def _strip_think_block(raw: str) -> str:
        """
        剔除 LLM 输出中的思考块（<think>...</think>）。

        部分 LLM 在返回最终答案前会输出思考链，若混入日记正文
        会破坏解析格式。使用非贪婪匹配剔除完整思考块。
        """
        return re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

    def _get_user_name(self, user_id: str) -> str:
        """获取用户昵称，用于 prompt 中个性化称呼。查询失败时返回「你」。"""
        if self.database_manager is None:
            return "你"
        prefs = self.database_manager.conversation_service.get_user_preferences(user_id)
        if prefs and isinstance(prefs, dict):
            return prefs.get("nickname", prefs.get("name", "你"))
        return "你"

    def _get_user_description(self, user_id: str) -> str:
        """获取用户画像描述，用于 prompt 背景信息。"""
        if self.database_manager is None:
            return ""
        desc = self.database_manager.conversation_service.get_user_description(user_id)
        return desc or ""

    def _get_user_preferences(self, user_id: str) -> str:
        """
        获取用户偏好设置，序列化为 JSON 字符串。

        偏好信息（称呼、关系设定、表达风格偏好等）会被注入 prompt，
        帮助 LLM 写出更贴合用户与天依关系的日记。
        """
        if self.database_manager is None:
            return ""
        prefs = self.database_manager.conversation_service.get_user_preferences(user_id)
        if prefs and isinstance(prefs, dict):
            return json.dumps(prefs, ensure_ascii=False)
        return ""
