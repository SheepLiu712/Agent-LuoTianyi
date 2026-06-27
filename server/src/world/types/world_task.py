from abc import ABC, abstractmethod
from typing import Any, Dict, TYPE_CHECKING

if TYPE_CHECKING:
    from src.system.system_runtime import SystemRuntime

class WorldTask(ABC):

    def __init__(self, name: str, config: Dict[str, Any] | None = None):
        self.name = name
        self.task_name = name
        self.config = config or {}
        self.clock_config = self.config.get("clock_config", {})

    @abstractmethod
    def initialize(self, system_runtime: 'SystemRuntime') -> None:
        pass

    @abstractmethod
    async def run_once(self) -> None:
        pass

    def ensure_dependencies(self) -> None:
        """检查任务基础配置已经初始化；具体任务可按需扩展。"""
        if self.config is None:
            raise RuntimeError(f"{self.__class__.__name__} dependency is missing: config")

    def get_task_type(self) -> str:
        return self.clock_config.get("type", "interval")
    
    def get_task_params(self) -> dict:
        return self.clock_config.get("params", {})
    
    def get_task_name(self) -> str:
        return self.name
