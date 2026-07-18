from __future__ import annotations

from typing import Any

from src.utils.logger import get_logger

from .models import RealtimeToolDefinition
from .qwen_session import QwenRealtimeSession


class RealtimeDialogueService:
    """实时对话供应商工厂；不持有任何用户通话状态。"""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self.logger = get_logger("RealtimeDialogueService")
        self.provider = str(self.config.get("provider") or "qwen").strip().lower()

    def ensure_dependencies(self) -> None:
        if not self.config:
            # 电话是可选能力；没有配置实时供应商时不应阻塞普通聊天启动。
            return
        if self.provider != "qwen":
            raise RuntimeError(f"Unsupported realtime dialogue provider: {self.provider}")
        qwen = self.config.get("qwen") or {}
        required = ("api_key", "model", "base_url")
        missing = [key for key in required if not qwen.get(key)]
        unresolved = [key for key in required if str(qwen.get(key, "")).startswith("$")]
        if missing or unresolved:
            details = []
            if missing:
                details.append(f"missing={','.join(missing)}")
            if unresolved:
                details.append(f"unresolved={','.join(unresolved)}")
            raise RuntimeError("Realtime dialogue configuration is incomplete: " + "; ".join(details))

    async def create_session(
        self,
        *,
        trace_id: str,
        call_id: str,
        instructions: str,
        tools: list[RealtimeToolDefinition],
    ) -> QwenRealtimeSession:
        self.ensure_dependencies()
        return QwenRealtimeSession(
            config=self.config.get("qwen") or {},
            trace_id=trace_id,
            call_id=call_id,
            instructions=instructions,
            tools=tools,
        )
