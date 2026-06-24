"""World runtime, clocks, and world-facing services."""

__all__ = ["WorldRuntime", "WorldClock"]


def __getattr__(name: str):
    if name == "WorldRuntime":
        from src.world.world_runtime import WorldRuntime

        return WorldRuntime
    if name == "WorldClock":
        from src.world.world_clock import WorldClock

        return WorldClock
    raise AttributeError(name)
