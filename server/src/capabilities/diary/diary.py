"""
日记能力：为高活跃用户生成每日日记。

日记以 DynamicPost（作者类型=agent，可见性=private）的形式发布，
用户可以在现有动态界面中查看，无需独立存储和展示。

格式：
  2026-07-16 · 心情: 开心

  <正文内容>

本能力不负责调度（何时写日记），调度由 world/diary_task 负责。
"""
from __future__ import annotations

import json
import os
from datetime import date
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.utils.llm_service import LLMService
    from src.utils.llm.llm_module import LLMModule


class DiaryCapability:
    """日记生成能力。生成的日记以 DynamicPost 形式发布，复用现有动态功能。"""

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.logger = get_logger(__name__)
        self.database_manager: "DatabaseManager | None" = None
        self._diary_llm: "LLMModule | None" = None
        self._prompt_template: str | None = None
        # 日记动态的 source_type 标记，用于区分普通动态
        self.diary_source_type: str = self.config.get("diary_source_type", "diary")

    def create_diary_llm_module(self, llm_service: "LLMService") -> None:
        """从 config 注册日记 LLM 模块。"""
        module_cfg = self._module_config(self.config.get("diary_llm"))
        if module_cfg:
            try:
                self._diary_llm = llm_service.register_llm_module("diary_composer", module_cfg)
            except Exception as exc:
                self._diary_llm = None
                self.logger.warning(f"Diary LLM module unavailable: {exc}")

    def wire_dependencies(
        self,
        *,
        database_manager: "DatabaseManager",
        dynamic_capability: Any | None = None,
    ) -> None:
        self.database_manager = database_manager
        self._dynamic_capability = dynamic_capability

    def ensure_llm(self) -> bool:
        """确保 LLM 模块可用。"""
        if self._diary_llm is None:
            self.logger.warning("Diary LLM module is not available")
            return False
        return True

    def _get_dynamic_capability(self):
        """获取动态能力实例。"""
        return self._dynamic_capability

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

    def update_prompt_with_persona(self, prompt: str, persona: str, style: str) -> str:
        """用人设和表达风格替换 prompt 占位符。"""
        return (prompt
                .replace("{{character_persona}}", persona or "一个温柔体贴的虚拟歌手")
                .replace("{{speaking_style}}", style or "温柔、细腻、有画面感，像在跟老朋友轻声诉说"))

    async def generate_and_post_diary(
        self,
        user_id: str,
        *,
        character_id: str = "luotianyi",
        character_name: str = "洛天依",
        character_persona: str = "",
        speaking_style: str = "",
        diary_date: Optional[str] = None,
    ) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
        """
        生成日记并通过 DynamicCapability 发布为 Agent 动态。

        Returns:
            (成功标志, 消息, 动态对象)
        """
        dynamic_capability = self._get_dynamic_capability()
        if dynamic_capability is None:
            return False, "DynamicCapability 不可用", None

        if not self.ensure_llm() or self._diary_llm is None:
            return False, "日记 LLM 模块不可用", None

        if self.database_manager is None:
            return False, "数据库管理器不可用", None

        target_date = diary_date or date.today().strftime("%Y-%m-%d")
        user_name = self._get_user_name(user_id)
        user_description = self._get_user_description(user_id)
        user_preferences = self._get_user_preferences(user_id)

        # 收集素材
        materials = await self._collect_materials(
            user_id=user_id,
            character_id=character_id,
            target_date=target_date,
        )

        # 构建 prompt
        prompt_template = self._load_prompt_template()
        system_prompt = (
            prompt_template
            .replace("{{character_name}}", character_name)
            .replace("{{user_name}}", user_name)
            .replace("{{diary_date}}", target_date)
            .replace("{{user_description}}", user_description)
            .replace("{{user_preferences}}", user_preferences)
            .replace("{{conversation_materials}}", materials)
        )
        system_prompt = self.update_prompt_with_persona(system_prompt, character_persona, speaking_style)

        # 调用 LLM 生成
        try:
            result = await self._diary_llm.generate_async(
                system_prompt=system_prompt,
                user_prompt=f"请为{user_name}撰写{target_date}的日记。",
            )
            diary_text = self._parse_diary_result(result, target_date=target_date)
            if diary_text is None or diary_text.strip() == "":
                return False, "日记格式解析失败", None
        except Exception as exc:
            self.logger.error(f"Diary generation LLM call failed: {exc}")
            return False, f"日记生成失败: {str(exc)}", None

        # 通过 DynamicCapability.publish_agent_dynamic 发布为 Agent 动态
        if not self._dynamic_capability:
            return False, "DynamicCapability 不可用", None

        try:
            ok, msg, item = self._dynamic_capability.publish_agent_dynamic(
                character_id=character_id,
                content=diary_text,
                source_type=self.diary_source_type,
                source_id=None,
                visibility="private",
                owner_user_id=user_id,
                allow_comment=False,
            )
            if ok:
                self.logger.info(f"Diary posted as dynamic for user={user_id} date={target_date}")
                return True, "日记已发布到动态", item
            else:
                self.logger.warning(f"Failed to post diary as dynamic: {msg}")
                return False, f"日记发布失败: {msg}", None
        except Exception as exc:
            self.logger.error(f"DynamicCapability call failed: {exc}")
            return False, f"日记发布失败: {str(exc)}", None

    async def _collect_materials(
        self,
        user_id: str,
        character_id: str,
        target_date: str,
    ) -> str:
        """收集日记素材：今日聊天记录、动态。"""
        if self.database_manager is None:
            return "今天没有特别的互动记录。"

        db = self.database_manager
        lines: List[str] = []

        today_start = f"{target_date} 00:00:00"
        today_end = f"{target_date} 23:59:59"

        try:
            # 获取今日对话
            total = db.get_total_conversation_count(user_id, character_id=character_id)
            if total > 0:
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
                        speaker = "用户" if c.source == "user" else "天依"
                        lines.append(f"[{speaker}] {c.content}")
        except Exception as exc:
            self.logger.warning(f"Failed to collect conversations for diary: {exc}")

        # 获取今日动态（用户发的）
        try:
            if db.dynamic_store is not None:
                dynamics = db.dynamic_store.list_dynamics_for_user(user_id, limit=50)
                today_dynamics = [
                    d for d in dynamics.get("items", [])
                    if d.get("created_at", "").startswith(target_date)
                    and d.get("author_type") == "user"
                ]
                if today_dynamics:
                    lines.append("\n【今日用户动态】")
                    for d in today_dynamics:
                        lines.append(f"[用户] {d.get('content', '')}")
        except Exception as exc:
            self.logger.warning(f"Failed to collect dynamics for diary: {exc}")

        if not lines:
            return "今天没有特别的互动记录。"

        return "\n".join(lines)

    def _parse_diary_result(self, raw: str, target_date: Optional[str] = None) -> Optional[str]:
        """解析 LLM 返回的日记文本，返回格式化后的完整文本。

        期望格式：
        心情：<标签>

        <正文内容>
        """
        if not raw or not raw.strip():
            return None

        lines = raw.strip().split("\n")
        mood = ""
        body_lines: list[str] = []
        in_body = False

        for line in lines:
            stripped = line.strip()
            if not stripped:
                if in_body:
                    body_lines.append("")
                continue

            if stripped.startswith("心情：") or stripped.startswith("心情:"):
                # 处理中文冒号或英文冒号
                mood = stripped.removeprefix("心情：").removeprefix("心情:").strip()
            elif stripped.startswith("正文：") or stripped == "正文":
                in_body = True
            else:
                if not in_body and (stripped.startswith("标题：") or stripped.startswith("摘要：")):
                    continue  # 跳过标题/摘要行（动态不需要单独展示）
                body_lines.append(stripped)

        body = "\n".join(body_lines).strip()
        if not body:
            body = raw  # 保底

        # 构建最终文本：日期 + 心情表头 + 正文
        date_str = target_date or date.today().strftime("%Y-%m-%d")
        header = f"{date_str} · 心情: {mood}" if mood else f"{date_str}"
        return f"{header}\n\n{body}"

    def _get_user_name(self, user_id: str) -> str:
        if self.database_manager is None:
            return "你"
        prefs = self.database_manager.get_user_preferences(user_id)
        if prefs and isinstance(prefs, dict):
            return prefs.get("nickname", prefs.get("name", "你"))
        return "你"

    def _get_user_description(self, user_id: str) -> str:
        if self.database_manager is None:
            return ""
        desc = self.database_manager.get_user_description(user_id)
        return desc or ""

    def _get_user_preferences(self, user_id: str) -> str:
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