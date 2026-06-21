"""Plugins package for LuoTianyi server.

Keep package initialization lightweight. Concrete plugins are imported lazily
so capability modules can depend on narrow plugin helpers without pulling the
whole plugin graph into memory.
"""

__all__ = ["DailyScheduler"]


def __getattr__(name: str):
    if name == "DailyScheduler":
        from src.plugins.daily_scheduler import DailyScheduler

        return DailyScheduler
    raise AttributeError(name)
