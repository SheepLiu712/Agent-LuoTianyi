"""业务测试通过统一生命周期结束 Stage，再读取业务快照。"""

import asyncio

from src.domain.stage.lifecycle import StageEndReason


async def finish_call(stage, reason=StageEndReason.USER_REQUESTED):
    await stage.terminate(reason)
    return stage.snapshot


async def wait_call_finished(stage):
    while not stage.interaction_ended:
        await asyncio.sleep(0)
    await stage.terminate(StageEndReason.SYSTEM_FAILURE)
    return stage.snapshot


async def wait_interaction_end(stage):
    while not stage.interaction_ended:
        await asyncio.sleep(0)


def observe_release(callback, ownership):
    def own(stage, operation):
        async def run():
            result = await operation()
            if result.resources_released and callback is not None:
                callback(ownership)
            return result

        return asyncio.create_task(run())

    return own
