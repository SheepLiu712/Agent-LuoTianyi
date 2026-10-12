import asyncio

import pytest

from src.application.user.reset_fence import UserResetFence


def test_reset_fence_blocks_only_owner_and_waits_existing_owned_task():
    async def scenario():
        fence = UserResetFence()
        release = asyncio.Event()
        owned = asyncio.create_task(release.wait())
        await fence.track("owner", owned)
        token = await fence.begin("owner")
        with pytest.raises(RuntimeError, match="RESET_IN_PROGRESS"):
            await fence.require_admission("owner")
        await fence.require_admission("other")
        waiting = asyncio.create_task(fence.wait("owner"))
        await asyncio.sleep(0)
        assert not waiting.done()
        release.set()
        await waiting
        await fence.end("owner", token)
        await fence.require_admission("owner")

    asyncio.run(scenario())


def test_reset_fence_requires_matching_token():
    async def scenario():
        fence = UserResetFence()
        token = await fence.begin("owner")
        other = token.__class__("owner", token.generation + 1)
        with pytest.raises(RuntimeError, match="TOKEN_MISMATCH"):
            await fence.end("owner", other)
        assert fence.is_resetting("owner")
        await fence.end("owner", token)

    asyncio.run(scenario())
