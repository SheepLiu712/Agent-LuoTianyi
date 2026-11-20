"""加载通话提示词资源，在创建会话时渲染一次背景快照。"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from src.agent.processing.reply_delivery import render_conversation_history
from src.infrastructure.models.llm.prompts import PromptTemplate


class CallSessionPrompt:
    """Agent 创建时加载模板；不保存用户或通话状态。"""

    def __init__(self, path: str | Path) -> None:
        path = Path(path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parents[3] / path
        resource = json.loads(path.read_text(encoding="utf-8"))
        self._template = PromptTemplate("\n".join(resource["template"]), resource["variables"], resource["name"])

    def render(self, context, narrative) -> str:
        user = context.user.read()
        return self._template.render(
            call_started_at=datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d %H:%M:%S"),
            character_name=narrative.name,
            character_persona=narrative.persona,
            speaking_style=narrative.speaking_style,
            user_profile=user.profile.description,
            user_preferences=asdict(user.preferences),
            conversation_history=render_conversation_history(context.conversation.read()),
            memory_pool="\n".join(item.content for item in context.call_memory.snapshot()),
        )
