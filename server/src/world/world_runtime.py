from typing import Dict, TYPE_CHECKING
if TYPE_CHECKING:
    from src.utils.llm_service import LLMService

class WorldRuntime:
    def __init__(self, config: Dict, llm_service: "LLMService"):
        self.config = config
        self.llm_service = llm_service

    def start_background_services(self):
        # 启动世界相关的后台服务
        pass  # 如果有需要启动的后台服务，可以在这里实现

    async def stop_background_services(self):
        # 停止世界相关的后台服务
        pass  # 如果有需要停止的后台服务，可以在这里实现