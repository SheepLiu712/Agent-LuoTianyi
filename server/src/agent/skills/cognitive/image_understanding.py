"""受控图片解析与 VLM 视觉理解技能。"""

from __future__ import annotations

import asyncio
import base64
from typing import TYPE_CHECKING, Any

from src.domain.agent import MediaRef
from src.infrastructure.media import (
    MediaResolutionError,
    MediaResolutionErrorCode,
    MediaResolver,
    ResolvedMedia,
)

if TYPE_CHECKING:
    from src.infrastructure.models.service import LLMService
    from src.infrastructure.models.vlm.module import VLMModule


class ImageUnderstandingSkill:
    """解析受控媒体、调用 VLM，并返回角色认知可用的图片描述。"""

    def __init__(
        self,
        config: dict[str, Any],
        media_resolver: MediaResolver,
        llm_service: LLMService | None = None,
        *,
        vlm_module: VLMModule | None = None,
    ) -> None:
        if not isinstance(config, dict):
            raise TypeError("image_understanding config must be a dictionary")
        self._media_resolver = media_resolver
        if vlm_module is None:
            if llm_service is None:
                raise RuntimeError("image understanding requires LLMService or VLMModule")
            vlm_module = llm_service.register_vlm_module(
                "image_understanding",
                config.get("vlm_module", {}),
            )
        self._vlm_module = vlm_module

    async def understand(
        self,
        media_ref: MediaRef,
        *,
        owner_user_id: str,
    ) -> tuple[ResolvedMedia, str]:
        """返回已解析媒体和非空机器描述；非法媒体不会进入视觉能力。"""
        media = await asyncio.to_thread(
            self._media_resolver.resolve,
            media_ref,
            owner_user_id=owner_user_id,
        )
        self._validate(media_ref, media)
        encoded = base64.b64encode(media.data).decode("ascii")
        response = await self._vlm_module.generate_response(image_base64=f"data:{media.mime_type};base64,{encoded}")
        description = response.get("content") if isinstance(response, dict) else None
        if not isinstance(description, str) or not description.strip():
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.EMPTY,
                media_id=media_ref.media_id,
            )
        return media, f"[一张图片]:{description.strip()}"

    @staticmethod
    def _validate(media_ref: MediaRef, media: ResolvedMedia) -> None:
        if not media.data:
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.EMPTY,
                media_id=media_ref.media_id,
            )
        if not media.mime_type.startswith("image/"):
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.UNSUPPORTED_TYPE,
                media_id=media_ref.media_id,
            )
