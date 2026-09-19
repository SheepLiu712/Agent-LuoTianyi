"""受控图片解析与视觉理解技能。"""

from __future__ import annotations

import asyncio
import base64
from typing import Protocol

from src.capabilities.media_resolution import (
    MediaResolutionError,
    MediaResolutionErrorCode,
    MediaResolver,
    ResolvedMedia,
)
from src.domain.agent import MediaRef


class ImageUnderstandingCapability(Protocol):
    """图片描述能力的最小调用面。"""

    async def describe_image(self, image_data_uri: str) -> str: ...


class ImagePreprocessingSkill:
    """先解析受控引用，再把编码图片交给视觉理解能力。"""

    def __init__(
        self,
        media_resolver: MediaResolver,
        understanding: ImageUnderstandingCapability,
    ) -> None:
        self._media_resolver = media_resolver
        self._understanding = understanding

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
        description = await self._understanding.describe_image(f"data:{media.mime_type};base64,{encoded}")
        if not isinstance(description, str) or not description.strip():
            raise MediaResolutionError(
                code=MediaResolutionErrorCode.EMPTY,
                media_id=media_ref.media_id,
            )
        return media, description.strip()

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
