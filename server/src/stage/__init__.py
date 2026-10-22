"""聊天与世界交互调度及生命周期管理。"""

from src.domain.stage import DueEvent, DueEventProvider

from ._call_records import CallStartFailed
from ._finalization import InteractionFinalizing
from ._world_sinks import NoChannelOutputSink, WorldFactSink
from .call_stage import CallIngressReceipt, CallStage
from .chat_stage import ChatStage
from .stage_manager import StageManager
from .world_stage import WorldStage

__all__ = [
    "CallStartFailed",
    "InteractionFinalizing",
    "ChatStage",
    "CallStage",
    "CallIngressReceipt",
    "DueEvent",
    "DueEventProvider",
    "NoChannelOutputSink",
    "StageManager",
    "WorldFactSink",
    "WorldStage",
]
