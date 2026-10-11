"""Production reset port over StageManager and CallSettlementCoordinator."""

from __future__ import annotations


class UserResetInteractionCoordinator:
    def __init__(self, *, fence, stage_manager, call_settlements) -> None:
        self._fence = fence
        self._stages = stage_manager
        self._settlements = call_settlements

    async def begin_user_data_reset(self, user_id: str) -> object:
        return await self._fence.begin(user_id)

    async def stop_user_interactions(self, user_id: str) -> int:
        return await self._stages.stop_user_interactions(user_id)

    async def wait_user_settlements(self, user_id: str) -> None:
        await self._settlements.wait_user(user_id)
        await self._fence.wait(user_id)

    async def end_user_data_reset(self, user_id: str, token: object) -> None:
        await self._fence.end(user_id, token)
