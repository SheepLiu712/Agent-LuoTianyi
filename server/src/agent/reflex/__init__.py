"""Fast, ephemeral reflex responses.

Reflexes handle low-latency stimuli that should not become topics or memories
unless the reflex cannot answer and the event deliberately falls back.
"""

from src.agent.reflex.touch import TouchFastReplyBuilder, TouchReflexResponder

__all__ = [
    "TouchFastReplyBuilder",
    "TouchReflexResponder",
]
