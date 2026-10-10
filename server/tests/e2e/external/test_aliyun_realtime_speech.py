"""Opt-in smoke for the configured Aliyun realtime speech provider."""

import os
from uuid import uuid4

import pytest

from src.infrastructure.models.realtime_speech import (
    AliyunRealtimeSpeechSessionFactory,
    RealtimeSpeechConfig,
)


@pytest.mark.asyncio
async def test_aliyun_realtime_speech_handshake_smoke():
    api_key = os.getenv("ALIYUN_REALTIME_SPEECH_API_KEY")
    workspace_id = os.getenv("ALIYUN_REALTIME_SPEECH_WORKSPACE_ID")
    model = os.getenv("ALIYUN_REALTIME_SPEECH_MODEL")
    if not api_key or not workspace_id or not model:
        pytest.skip("Aliyun realtime speech smoke configuration is incomplete")

    factory = AliyunRealtimeSpeechSessionFactory.from_mapping(
        {
            "enabled": True,
            "api_key": api_key,
            "workspace_id": workspace_id,
            "model": model,
        }
    )
    session = await factory.create(uuid4())
    try:
        await session.start(RealtimeSpeechConfig(language="zh"))
    finally:
        await session.close()
