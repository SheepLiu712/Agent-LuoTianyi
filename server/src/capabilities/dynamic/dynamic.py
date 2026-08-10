from __future__ import annotations

from typing import Any, Optional, TYPE_CHECKING

from src.utils.logger import get_logger

if TYPE_CHECKING:
    from src.system.database import DatabaseManager
    from src.utils.llm_service import LLMService
    from src.utils.llm.llm_module import LLMModule
    from src.utils.llm.llm_api_interface import LLMContentInspectionError

from src.capabilities.dynamic.dynamic_replier import DynamicReplier


class DynamicCapability:
    """Publishing capability for agent/world generated dynamics and comments.

    Also responsible for generating world dynamic content via LLM (moved from LuoTianyiAgent),
    and dynamic reply generation via DynamicReplier.
    """

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.logger = get_logger(__name__)
        self.database_manager: "DatabaseManager | None" = None
        self._dynamic_composer: "LLMModule | None" = None
        # Default character context kept for legacy callers. Multi-character
        # runtime calls pass character context explicitly instead of mutating this object.
        self._character_name: str = "洛天依"
        self._character_persona: str = ""
        self._speaking_style: str = ""
        # 动态回复器
        self.replier: DynamicReplier = DynamicReplier(
            self.config.get("dynamic_replier") or self.config.get("reply", {})
        )

    def create_llm_module(self, llm_service: "LLMService") -> None:
        """从 config 注册 world dynamic composer LLM 模块。"""
        composer_cfg = self._module_config(self.config.get("dynamic_composer"))
        if composer_cfg:
            try:
                self._dynamic_composer = llm_service.register_llm_module("dynamic_composer", composer_cfg)
            except Exception as exc:
                self._dynamic_composer = None
                self.logger.warning(f"Dynamic composer module unavailable: {exc}")
        # 同时注册动态回复 LLM 模块
        self.replier.create_llm_module(llm_service)

    @staticmethod
    def _module_config(config: Any) -> dict[str, Any]:
        if not isinstance(config, dict):
            return {}
        llm_module = config.get("llm_module")
        if isinstance(llm_module, dict):
            return llm_module
        return config

    def wire_dependencies(self, *, database_manager: "DatabaseManager") -> None:
        self.database_manager = database_manager
        self.ensure_dependencies()

    def wire_character_context(
        self,
        *,
        character_name: str = "洛天依",
        character_persona: str = "",
        speaking_style: str = "",
    ) -> None:
        """设置角色上下文（供动态文案生成和回复使用）。"""
        self._character_name = character_name
        self._character_persona = character_persona
        self._speaking_style = speaking_style
        self.replier.set_character_context(character_name=character_name)

    def ensure_dependencies(self) -> None:
        if self.database_manager is None:
            raise RuntimeError("DynamicCapability dependencies are missing: database_manager")

    def publish_agent_dynamic(
        self,
        *,
        character_id: str,
        content: str,
        source_type: str,
        source_id: str | None = None,
        visibility: str = "global",
        owner_user_id: str | None = None,
        allow_comment: bool = True,
        image_refs: list[Any] | None = None,
        idempotent_by_source: bool = False,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        self.ensure_dependencies()
        return self.database_manager.dynamic_store.create_dynamic(
            author_type="agent",
            author_id=character_id,
            owner_user_id=owner_user_id,
            visibility=visibility,
            content=content,
            source_type=source_type,
            source_id=source_id,
            allow_comment=allow_comment,
            image_refs=image_refs,
            memory_policy="disabled",
            memory_status="disabled",
            reply_status="not_applicable",
            idempotent_by_source=idempotent_by_source,
        )

    def publish_agent_comment(
        self,
        *,
        dynamic_id: str,
        owner_user_id: str,
        content: str,
        character_id: str = "luotianyi",
        parent_comment_id: str | None = None,
    ) -> tuple[bool, str, Optional[dict[str, Any]]]:
        self.ensure_dependencies()
        return self.database_manager.dynamic_store.create_dynamic_comment(
            dynamic_id=dynamic_id,
            author_type="agent",
            author_id=character_id,
            owner_user_id=owner_user_id,
            content=content,
            parent_comment_id=parent_comment_id,
            memory_policy="disabled",
            memory_status="disabled",
            reply_status="not_applicable",
        )

    async def publish_citywalk_dynamic(
        self,
        *,
        character_id: str,
        character_name: str,
        character_persona: str,
        speaking_style: str,
        report: dict[str, Any],
        source_id: str | None = None,
    ) -> dict[str, Any]:
        """生成并发布 citywalk 动态。

        world 侧只传入 citywalk report 材料；文案生成和动态落库都由 capability 负责。
        """
        content = await self.compose_citywalk_dynamic_content(
            character_name=character_name,
            character_persona=character_persona,
            speaking_style=speaking_style,
            report=report,
        )
        ok, message, item = self.publish_agent_dynamic(
            character_id=character_id,
            content=content,
            source_type="citywalk",
            source_id=source_id,
            visibility="global",
            allow_comment=True,
        )
        return {
            "ok": ok,
            "message": message,
            "item": item,
            "dynamic_id": item.get("id") if ok and item else None,
            "content": content,
        }

    async def compose_citywalk_dynamic_content(
        self,
        *,
        character_name: str,
        character_persona: str,
        speaking_style: str,
        report: dict[str, Any],
    ) -> str:
        fallback = self._build_citywalk_fallback_content(report)
        overview = report.get("overview") if isinstance(report.get("overview"), dict) else {}
        event_cards = report.get("event_cards") if isinstance(report.get("event_cards"), list) else []
        poi_details = report.get("poi_details") if isinstance(report.get("poi_details"), list) else []
        instruction = (
            "这是一次散步（citywalk）完成后的角色动态。"
            "请以角色的第一人称视角，分享散步中的见闻和感受，"
            "语气轻松自然，带一点生活气息。"
            "不要写成后台报告，不要逐条罗列字段。"
        )
        structured_context = "\n".join(
            [
                f"城市：{overview.get('city') or '-'}",
                f"目的地：{overview.get('selected_destination') or '-'}",
                f"目的地理由：{overview.get('destination_reason') or '-'}",
                f"总时长：{overview.get('total_duration_minutes') or '-'}分钟",
                f"经过地点：{', '.join(str(x) for x in report.get('places', []) if str(x).strip()) or '-'}",
                "行程事件：",
                self._format_citywalk_events(event_cards),
                "地点细节：",
                self._format_citywalk_poi_details(poi_details),
            ]
        )
        result = await self.generate_world_dynamic_content(
            character_name=character_name,
            character_persona=character_persona,
            speaking_style=speaking_style,
            dynamic_type="citywalk",
            instruction=instruction,
            structured_context=structured_context,
        )
        return result or fallback

    async def publish_learned_song_dynamic(
        self,
        *,
        character_id: str,
        character_name: str,
        character_persona: str,
        speaking_style: str,
        song_name: str,
        segment_description: str = "",
        lyrics: str = "",
    ) -> dict[str, Any]:
        """生成并发布学会新歌动态。

        world 侧负责收集新歌和歌词材料；文案生成和动态落库都由 capability 负责。
        """
        self.ensure_dependencies()
        existing = self.database_manager.dynamic_store.get_dynamic_by_source(
            author_type="agent",
            author_id=character_id,
            source_type="song_learned",
            source_id=song_name,
        )
        if existing is not None:
            return {
                "ok": True,
                "message": "dynamic already exists",
                "item": existing,
                "dynamic_id": existing.get("id"),
                "content": existing.get("content", ""),
                "created": False,
            }

        content = await self.compose_learned_song_dynamic_content(
            character_name=character_name,
            character_persona=character_persona,
            speaking_style=speaking_style,
            song_name=song_name,
            segment_description=segment_description,
            lyrics=lyrics,
        )
        ok, message, item = self.publish_agent_dynamic(
            character_id=character_id,
            content=content,
            source_type="song_learned",
            source_id=song_name,
            visibility="global",
            allow_comment=True,
            idempotent_by_source=True,
        )
        return {
            "ok": ok,
            "message": message,
            "item": item,
            "dynamic_id": item.get("id") if ok and item else None,
            "content": content,
            "created": message != "dynamic already exists",
        }

    async def compose_learned_song_dynamic_content(
        self,
        *,
        character_name: str,
        character_persona: str,
        speaking_style: str,
        song_name: str,
        segment_description: str = "",
        lyrics: str = "",
    ) -> str:
        fallback = f"今天学会了《{song_name}》。之后如果你想听，我就可以唱给你听啦。"
        instruction = (
            "这是一次学歌成功后的角色动态。"
            "请以角色的第一人称视角，表达学会一首新歌后的开心、对这首歌或唱段的感受，"
            "以及想唱给用户听的心情。语气活泼可爱，但不要复述整段歌词。"
        )
        structured_context = "\n".join(
            [
                f"角色名：{character_name}",
                f"新学会的歌曲：{song_name}",
                f"可唱唱段：{segment_description or '-'}",
                f"唱段歌词：{lyrics or '-'}",
            ]
        )
        result = await self.generate_world_dynamic_content(
            character_name=character_name,
            character_persona=character_persona,
            speaking_style=speaking_style,
            dynamic_type="song_learned",
            instruction=instruction,
            structured_context=structured_context,
        )
        return result or fallback

    async def generate_world_dynamic_content(
        self,
        *,
        character_name: str | None = None,
        character_persona: str | None = None,
        speaking_style: str | None = None,
        dynamic_type: str,
        instruction: str,
        structured_context: str,
    ) -> str:
        """为 world 事件生成角色动态文案（从 LuoTianyiAgent 移入）。

        Args:
            dynamic_type: 动态类型，如 "citywalk" / "song_learned"
            instruction: 针对该动态类型的特定生成要求
            structured_context: 结构化的上下文信息

        Returns:
            生成的动态文案；如果 LLM 不可用或生成失败，返回空字符串。
        """
        if self._dynamic_composer is None:
            return ""
        try:
            response = await self._dynamic_composer.generate_response(
                character_name=character_name or self._character_name,
                character_persona=character_persona if character_persona is not None else self._character_persona,
                speaking_style=speaking_style if speaking_style is not None else self._speaking_style,
                dynamic_type=dynamic_type,
                instruction=instruction,
                structured_context=structured_context,
            )
            text = str(response or "").strip()
            return text
        except Exception as exc:
            self.logger.warning(f"Dynamic composer failed: {exc}")
            return ""

    @staticmethod
    def _build_citywalk_fallback_content(report: dict[str, Any]) -> str:
        overview = report.get("overview") if isinstance(report.get("overview"), dict) else {}
        city = str(overview.get("city") or "").strip()
        destination = str(overview.get("selected_destination") or "").strip()
        places = [str(x).strip() for x in report.get("places", []) if str(x).strip()]
        title = "今天出去散步啦"
        if city and destination:
            title = f"今天去{city}的{destination}散步啦"
        elif city:
            title = f"今天去{city}散步啦"
        elif destination:
            title = f"今天去了{destination}"
        if places:
            return f"{title}\n\n路上经过了{', '.join(places[:5])}，留下了不少新鲜的小发现。"
        return title

    @staticmethod
    def _format_citywalk_events(event_cards: list[Any]) -> str:
        lines: list[str] = []
        for item in event_cards[:8]:
            if not isinstance(item, dict):
                continue
            poi = item.get("poi") if isinstance(item.get("poi"), dict) else {}
            name = str(poi.get("name") or "").strip()
            activity = str(item.get("poi_activity") or "").strip()
            reason = str(item.get("reason") or "").strip()
            if name or activity:
                lines.append(f"- {name or '未知地点'}：{activity or '有新的见闻'}；理由：{reason or '-'}")
        return "\n".join(lines) or "-"

    @staticmethod
    def _format_citywalk_poi_details(poi_details: list[Any]) -> str:
        lines: list[str] = []
        for item in poi_details[:8]:
            if not isinstance(item, dict):
                continue
            name = str(item.get("name") or "").strip()
            tags = item.get("signature_or_tags")
            if isinstance(tags, list):
                tag_text = "、".join(str(x).strip() for x in tags if str(x).strip())
            else:
                tag_text = str(tags or "").strip()
            image_description = str(item.get("image_description") or "").strip()
            if name or tag_text or image_description:
                lines.append(f"- {name or '未知地点'}：标签={tag_text or '-'}；图片观察={image_description or '-'}")
        return "\n".join(lines) or "-"
