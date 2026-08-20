"""
日记能力：为高活跃用户生成每日日记。

## 设计思路

日记以 DynamicPost（作者类型=agent，可见性=private）的形式发布，
直接复用现有动态功能，无需独立存储和展示。用户可以在动态界面
中看到天依为自己写的日记（其他人不可见）。

## 日记格式（在动态中展示）

  2026-07-16 · 心情: 开心

  今天和主人聊了很多关于音乐的话题...

## 职责边界

本能力只负责「生成并发布日记」，不负责调度（何时写日记）。
调度由 world/diary_task 负责，每天 UTC 16:00 触发一次。
"""
from __future__ import annotations

import json
import re
from datetime import date
from typing import Any, Dict, List, Optional, Tuple, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.utils.llm_service import LLMService
    from src.utils.llm.llm_module import LLMModule
    from src.capabilities.dynamic import DynamicCapability


class DiaryCapability:
    """
    日记生成能力。

    核心流程：
      1. 收集素材（今日聊天记录 + 用户动态）
      2. 准备 prompt 模板变量（角色人设、表达风格、素材）
      3. 调用 LLM 生成日记文本
      4. 解析 LLM 输出（提取心情标签、正文）
      5. 通过 DynamicCapability.publish_agent_dynamic() 发布为 Agent 动态

    复用了动态系统的完整链路：
      DiaryCapability → DynamicCapability → DynamicStore → 用户可见
    """

    def __init__(self, config: Dict[str, Any] | None = None) -> None:
        """
        初始化日记能力。

        Args:
            config: 配置项，支持以下字段：
                - diary_llm: LLM 模块配置（用于注册日记专用的 LLM 模块）
                - diary_source_type: 日记动态的 source_type 标记（默认 "diary"）
        """
        self.config = config or {}
        self.logger = get_logger(__name__)

        # ── 外部依赖（由 wire_dependencies 注入） ──
        self.database_manager: "DatabaseManager | None" = None
        self._dynamic_capability: "DynamicCapability | None" = None  # DynamicCapability 实例

        # ── LLM 相关 ──
        self._diary_llm: "LLMModule | None" = None       # 日记专用的 LLM 模块
        # ── 标识 ──
        # 日记动态的 source_type，用于在动态列表中区分「日记」和普通动态
        self.diary_source_type: str = self.config.get("diary_source_type", "diary")

    # ────────────────────── 依赖注入 ──────────────────────

    def create_llm_module(self, llm_service: "LLMService") -> None:
        """
        从 config 注册日记专用的 LLM 模块。

        config.diary_llm 的结构与其它能力模块一致：
        {
            "llm_module": {
                "llm": {"name": "...", ...},
                "prompt_name": "..."
            }
        }

        如果配置缺失或注册失败，_diary_llm 保持为 None，后续
        ensure_dependencies() 会检测到并阻止日记生成。
        """
        module_cfg = self._module_config(self.config.get("diary_llm"))
        if module_cfg:
            try:
                # 注册一个名为 "diary_composer" 的 LLM 模块，专门用于日记生成
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
        """
        注入外部依赖。

        由 CapabilityManager.wire_dependencies() 在初始化阶段调用。
        dynamic_capability 是日记的发布通道——日记本质是一种特殊类型的动态。
        """
        self.database_manager = database_manager
        self._dynamic_capability = dynamic_capability

    # ────────────────────── 前置检查 ──────────────────────

    def ensure_llm(self) -> bool:
        """返回日记专用 LLM 模块是否已经注册。"""
        return self._diary_llm is not None

    def ensure_dependencies(self) -> Tuple[bool, str]:
        """检查所有依赖是否可用，不可用时记录警告并返回 (False, 错误信息)。"""
        if self._diary_llm is None:
            self.logger.warning("Diary LLM module is not available")
            return False, "日记 LLM 模块不可用"
        if self._dynamic_capability is None:
            self.logger.warning("DynamicCapability is not available")
            return False, "DynamicCapability 不可用"
        if self.database_manager is None:
            self.logger.warning("Database manager is not available")
            return False, "数据库管理器不可用"
        return True, ""

    # ────────────────────── 核心流程 ──────────────────────

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

        执行顺序：
          1. 前置检查（DynamicCapability、LLM、数据库是否可用）
          2. 获取用户信息和角色人设
          3. 收集今日聊天记录和用户动态作为素材
          4. 准备 prompt 变量并调 LLM 生成日记
          5. 解析 LLM 输出为标准化格式
          6. 通过 publish_agent_dynamic() 发布为私密动态

        Args:
            user_id: 目标用户 ID
            character_id: 角色 ID（默认 luotianyi）
            character_name: 角色显示名称（默认 洛天依）
            character_persona: 角色人设描述，从 CharacterRuntime 获取
            speaking_style: 角色表达风格，从 CharacterRuntime 获取
            diary_date: 日记日期（YYYY-MM-DD），默认今天。支持为过去日期补写。

        Returns:
            (成功标志, 消息字符串, 动态对象字典 | None)
        """
        # ── 前置检查 ──
        ok, err_msg = self.ensure_dependencies()
        if not ok:
            return False, err_msg, None

        # ── 准备上下文 ──
        target_date = diary_date or date.today().strftime("%Y-%m-%d")
        try:
            parsed_target_date = date.fromisoformat(target_date)
        except (TypeError, ValueError):
            return False, "日记日期格式无效", None
        if parsed_target_date.isoformat() != target_date:
            return False, "日记日期格式无效", None

        source_id = self._diary_source_id(character_id, user_id, target_date)
        dynamic_store = getattr(self.database_manager, "dynamic_store", None)
        get_existing = getattr(dynamic_store, "get_dynamic_by_source", None)
        if callable(get_existing):
            existing = get_existing(
                author_type="agent",
                author_id=character_id,
                source_type=self.diary_source_type,
                source_id=source_id,
            )
            if existing is not None and existing.get("owner_user_id") == user_id:
                return True, "日记已存在", existing

        user_name = self._get_user_name(user_id)
        user_description = self._get_user_description(user_id)
        user_preferences = self._get_user_preferences(user_id)

        # ── 收集素材（异步：需要查数据库） ──
        materials = await self._collect_materials(
            user_id=user_id,
            character_id=character_id,
            target_date=target_date,
        )

        # ── 调用 LLM 生成日记 ──
        try:
            result = await self._diary_llm.generate_response(
                character_name=character_name,
                user_name=user_name,
                diary_date=target_date,
                user_description=user_description,
                user_preferences=user_preferences,
                conversation_materials=materials,
                character_persona=character_persona or "一个温柔体贴的虚拟歌手",
                speaking_style=speaking_style or "温柔、细腻、有画面感，像在跟老朋友轻声诉说",
            )
            diary_text = self._parse_diary_result(result, target_date=target_date)
            if diary_text is None or diary_text.strip() == "":
                return False, "日记格式解析失败", None
        except Exception as exc:
            self.logger.error(f"Diary generation LLM call failed: {exc}")
            return False, f"日记生成失败: {str(exc)}", None

        # ── 通过 DynamicCapability 发布为 Agent 动态 ──
        try:
            # publish_agent_dynamic 会创建一条 author_type=agent 的动态，
            # 日记会被保存到 dynamic_posts 表，用户通过动态界面即可查看。
            ok, msg, item = self._dynamic_capability.publish_agent_dynamic(
                character_id=character_id,
                content=diary_text,
                source_type=self.diary_source_type,     # 标记为 "diary" 类型
                source_id=source_id,
                visibility="private",                    # 仅用户自己可见
                owner_user_id=user_id,                   # 归属于该用户
                allow_comment=False,                     # 日记不支持评论
                idempotent_by_source=True,
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

    # ────────────────────── 素材收集 ──────────────────────

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
        这样 LLM 仍然可以生成一篇简单的日记，例如表达思念。
        """
        if self.database_manager is None:
            return "今天没有特别的互动记录。"

        db = self.database_manager
        lines: List[str] = []

        # ── 收集聊天记录 ──
        try:
            total = db.conversation_service.get_total_conversation_count(user_id, character_id=character_id)
            if total > 0:
                # 取最近 100 条（最多），然后在内存中按日期过滤
                conversations = db.conversation_service.get_history_from_db(
                    user_id, max(0, total - 100), total, character_id=character_id
                )
                # 时间戳格式为 "YYYY-MM-DD HH:MM:SS"，前缀匹配目标日期即可
                today_convs = [
                    c for c in conversations
                    if c.timestamp.startswith(target_date)
                ]
                if today_convs:
                    lines.append("【今日聊天记录】")
                    # 最多展示 30 条，防止 prompt 过长
                    for c in today_convs[-30:]:
                        speaker = "用户" if c.source == "user" else "天依"
                        lines.append(f"[{speaker}] {c.content}")
        except Exception as exc:
            # 聊天记录收集失败不应阻断整个日记流程，记录日志后继续
            self.logger.warning(f"Failed to collect conversations for diary: {exc}")

        # ── 收集用户今日动态 ──
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

    @staticmethod
    def _diary_source_id(character_id: str, user_id: str, target_date: str) -> str:
        return f"diary:{character_id}:{user_id}:{target_date}"

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

        lines = raw.strip().split("\n")
        mood = ""
        body_lines: list[str] = []
        in_body = False

        for line in lines:
            stripped = line.strip()

            # 空行：在正文区域内保留（段落分隔），区域外忽略
            if not stripped:
                if in_body:
                    body_lines.append("")
                continue

            mood_match = re.match(r"^心情\s*[：:]\s*(.*)$", stripped)
            body_match = re.match(r"^正文(?:\s*[：:]\s*(.*))?$", stripped)
            if mood_match:
                mood = mood_match.group(1).strip()
            elif body_match:
                in_body = True
                inline_body = (body_match.group(1) or "").strip()
                if inline_body:
                    body_lines.append(inline_body)
            else:
                # 跳过「标题：」「摘要：」行——这些是旧版 prompt 的产物，
                # 日记动态不需要单独展示标题和摘要
                if not in_body and re.match(r"^(标题|摘要)\s*[：:]", stripped):
                    continue
                in_body = True
                body_lines.append(stripped)

        body = "\n".join(body_lines).strip()
        # 压缩连续空行（LLM 输出中常见多余空行）
        body = re.sub(r"\n{3,}", "\n\n", body)
        if not body:
            body = raw  # 保底：解析失败时使用原始输出

        # 构建最终展示文本
        date_str = target_date or date.today().strftime("%Y-%m-%d")
        header = f"{date_str} · 心情: {mood}" if mood else f"{date_str}"
        return f"{header}\n\n{body}"

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

    # ────────────────────── 工具方法 ──────────────────────

    @staticmethod
    def _module_config(config: Any) -> Dict[str, Any]:
        """
        从能力配置中提取 LLM 模块配置。

        config 结构示例：
            {"llm_module": {"llm": {"name": "gpt-4o"}, "prompt_name": "diary"}}

        兼容两种格式：
          - 直接在 config 中嵌套 llm_module 字段
          - config 本身就是模块配置（旧格式）
        """
        if not isinstance(config, dict):
            return {}
        llm_module = config.get("llm_module")
        if isinstance(llm_module, dict):
            return llm_module
        return config
