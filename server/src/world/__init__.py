"""World and sandbox-facing adapters.

The first refactor phase keeps existing plugin implementations in place and
exposes them through world-facing facades. Later phases can move the concrete
providers behind these boundaries.
"""

from .world_runtime import WorldRuntime

__all__ = ["WorldRuntime"]