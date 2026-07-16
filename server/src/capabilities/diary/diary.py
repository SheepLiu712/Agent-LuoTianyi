"""
日记能力：为高活跃用户生成每日日记。

职责：
- 收集日记素材（今日聊天记录、记忆、事件）
- 调用 LLM 生成日记文本
- 通过 DiaryStore 持久化

注意：本能力不负责调度（何时写日记），调度由 world/diary_task 负责。
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.utils.llm_service import LLMService
    from src.utils.llm.llm_module import LLMModule


class DiaryCapability:
    """日记生成能力。负责收集素材、调用 LLM 生成日记并持久化。"""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.logger = get_logger(__name__)
        self.database_manager: "DatabaseManager | None" = None
        self._diary_llm: "LLMModule | None" = None
        self._prompt_template: str | None = None

    def create_diary_llm_module(self, llm_service: "LLMService") -> None:
        """从 config 注册日记 LLM 模块。"""
        module_cfg = self._module_config(self.config.get("diary_llm"))
        if module_cfg:
            try:
                self._diary_llm = llm_service.register_llm_module("diary_composer", module_cfg)
            except Exception as exc:
                self._diary_llm = None
                self.logger.warning(f"Diary LLM module unavailable: {exc}")

    def wire_dependencies(self, *, database_manager: "DatabaseManager") -> None:
        self.database_manager = database_manager

    def ensure_llm(self) -> bool:
        """确保 LLM 模块可用。"""
        if self._diary_llm is None:
            self.logger.warning("Diary LLM module is not available")
            return False
        return True

    def _load_prompt_template(self) -> str:
        """加载日记 prompt 模板。"""
        if self._prompt_template is not None:
            return self._prompt_template

        prompt_path = self.config.get(
            "prompt_path",
            os.path.join("res", "agent", "prompts", "diary_prompt.json"),
        )
        try:
            with open(prompt_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._prompt_template = data.get("system_prompt", "")
        except Exception as exc:
            self.logger.error(f"Failed to load diary prompt template: {exc}")
            self._prompt_template = ""
        return self._prompt_template

    async def generate_diary(
        self,
        user_id: str,
        *,
        character_id: str = "luotianyi",
        character_name: str = "洛天依",
        diary_date: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        为指定用户生成一篇日记。

        Args:
            user_id: 用户 ID
            character_id: 角色 ID
            character_name: 角色名（用于 prompt）
            diary_date: 日记日期，默认为今天

        Returns:
            (成功标志, 消息, 日记对象)
        """
        if not self.ensure_llm() or self._diary_llm is None:
            return False, "日记 LLM 模块不可用", None

        if self.database_manager is None:
            return False, "数据库管理器不可用", None

        diary_store = self.database_manager.diary_store
        if diary_store is None:
            return False, "日记存储不可用", None

        target_date = diary_date or date.today().strftime("%Y-%m-%d")

        # 检查是否已有日记
        if diary_store.has_diary_for_date(user_id, target_date, character_id=character_id):
            existing = diary_store.get_diary_by_date(user_id, target_date, character_id=character_id)
            if existing and existing.get("status") == "published":
                return False, f"{target_date} 已有日记", existing

        # 收集素材
        materials = await self._collect_materials(
            user_id=user_id,
            character_id=character_id,
            target_date=target_date,
        )

        # 获取用户信息
        user_name = self._get_user_name(user_id)
        user_description = self._get_user_description(user_id)
        user_preferences = self._get_user_preferences(user_id)

        # 构建 prompt
        prompt_template = self._load_prompt_template()
        system_prompt = (
            prompt_template.replace("{{character_name}}", character_name)
            .replace("{{user_name}}", user_name)
            .replace("{{diary_date}}", target_date)
            .replace("{{user_description}}", user_description)
            .replace("{{user_preferences}}", user_preferences)
            .replace("{{conversation_materials}}", materials)
        )

        # 调用 LLM 生成
        try:
            result = await self._diary_llm.generate_async(
                system_prompt=system_prompt,
                user_prompt=f"请为{user_name}撰写{target_date}的日记。",
            )
            diary_data = self._parse_diary_result(result)
            if diary_data is None:
                return False, "日记格式解析失败，请重试", None
        except Exception as exc:
            self.logger.error(f"Diary generation LLM call failed: {exc}")
            return False, f"日记生成失败: {str(exc)}", None

        # 持久化
        ok, msg, item = diary_store.create_diary(
            user_id=user_id,
            diary_date=target_date,
            character_id=character_id,
            title=diary_data["title"],
            content=diary_data["content"],
            summary=diary_data.get("summary"),
            mood=diary_data.get("mood"),
            tags=diary_data.get("tags"),
            source="auto",
            metadata_json=json.dumps({"material_count": materials.count("\n")}, ensure_ascii=False),
        )

        if ok:
            self.logger.info(f"Diary created for user={user_id} date={target_date}")
        else:
            self.logger.warning(f"Diary creation failed for user={user_id} date={target_date}: {msg}")

        return ok, msg, item

    async def _collect_materials(
        self,
        user_id: str,
        character_id: str,
        target_date: str,
    ) -> str:
        """收集日记素材：今日聊天记录、记忆和事件。"""
        if self.database_manager is None:
            return "今天没有特别的互动记录。"

        db = self.database_manager
        lines: List[str] = []

        try:
            # 1. 获取今日聊天记录
            today_start = f"{target_date} 00:00:00"
            today_end = f"{target_date} 23:59:59"
            from datetime import datetime as dt
            start_dt = dt.strptime(today_start, "%Y-%m-%d %H:%M:%S")
            end_dt = dt.strptime(today_end, "%Y-%m-%d %H:%M:%S")

            # 通过 database_manager 获取今日对话
            total = db.get_total_conversation_count(user_id, character_id=character_id)
            if total > 0:
                # 从最新记录往前找今天的
                conversations = db.get_history_from_db(
                    user_id, max(0, total - 100), total, character_id=character_id
                )
                today_convs = [
                    c for c in conversations
                    if today_start <= c.timestamp <= today_end
                ]
                if today_convs:
                    lines.append("【今日聊天记录】")
                    for c in today_convs[-30:]:  # 最多 30 条
                        speaker = "用户" if c.source == "user" else character_id
                        lines.append(f"[{speaker}] {c.content}")
        except Exception as exc:
            self.logger.warning(f"Failed to collect conversations for diary: {exc}")

        # 2. 获取今日动态
        try:
            if db.dynamic_store is not None:
                dynamics = db.dynamic_store.list_dynamics_for_user(
                    user_id, limit=50
                )
                today_dynamics = [
                    d for d in dynamics.get("items", [])
                    if d.get("created_at", "").startswith(target_date)
                ]
                if today_dynamics:
                    lines.append("\n【今日动态】")
                    for d in today_dynamics:
                        author = d.get("author_name", d.get("author_type", "用户"))
                        lines.append(f"[{author}] {d.get('content', '')}")
        except Exception as exc:
            self.logger.warning(f"Failed to collect dynamics for diary: {exc}")

        if not lines:
            return "今天没有特别的互动记录。"

        return "\n".join(lines)

    def _parse_diary_result(self, raw: str) -> Optional[Dict[str, Any]]:
        """解析 LLM 返回的日记文本。"""
        if not raw or not raw.strip():
            return None

        lines = raw.strip().split("\n")
        title = ""
        mood = ""
        summary = ""
        content_lines: List[str] = []
        in_content = False

        for line in lines:
            line = line.strip()
            if not line:
                if in_content:
                    content_lines.append("")
                continue

            if line.startswith("标题："):
                title = line[len("标题："):].strip()
            elif line.startswith("心情："):
                mood = line[len("心情："):].strip()
            elif line.startswith("摘要："):
                summary = line[len("摘要："):].strip()
            elif line in ("正文：", "正文"):
                in_content = True
            else:
                if in_content:
                    content_lines.append(line)
                elif not title and not mood and not summary:
                    # 容错：如果没有明确标记，尝试智能分配
                    content_lines.append(line)

        # 如果没有找到标题，尝试从第一行提取
        if not title and content_lines:
            first_line = content_lines[0]
            if len(first_line) < 30:
                title = first_line
                content_lines = content_lines[1:]

        if not title:
            title = f"{date.today().strftime('%Y-%m-%d')} 的日记"

        content = "\n".join(content_lines).strip()
        if not content:
            content = raw  # 保底：使用原始输出

        return {
            "title": title,
            "mood": mood or "平静",
            "summary": summary or title,
            "content": content,
            "tags": [mood] if mood else ["日常"],
        }

    def _get_user_name(self, user_id: str) -> str:
        """获取用户显示名。"""
        if self.database_manager is None:
            return "你"
        prefs = self.database_manager.get_user_preferences(user_id)
        if prefs and isinstance(prefs, dict):
            return prefs.get("nickname", prefs.get("name", "你"))
        return "你"

    def _get_user_description(self, user_id: str) -> str:
        """获取用户画像描述。"""
        if self.database_manager is None:
            return ""
        desc = self.database_manager.get_user_description(user_id)
        return desc or ""

    def _get_user_preferences(self, user_id: str) -> str:
        """获取用户偏好描述。"""
        if self.database_manager is None:
            return ""
        prefs = self.database_manager.get_user_preferences(user_id)
        if prefs and isinstance(prefs, dict):
            return json.dumps(prefs, ensure_ascii=False)
        return ""

    @staticmethod
    def _module_config(config: Any) -> Dict[str, Any]:
        if not isinstance(config, dict):
            return {}
        llm_module = config.get("llm_module")
        if isinstance(llm_module, dict):
            return llm_module
        return config