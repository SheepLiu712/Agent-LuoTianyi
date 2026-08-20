from typing import Dict, Optional
from .llm.prompt_manager import PromptManager
from src.utils.logger import get_logger
from .llm.llm_api_interface import LLMAPIInterface, LLMAPIFactory
from .vision.vlm_api_interface import VLMAPIInterface, VLMAPIFactory
from .llm.llm_module import LLMModule
from .vision.vlm_module import VLMModule
from .llm.client_llm_executor import ClientLLMExecutor

class LLMService:
    def __init__(self, config: Dict, client_llm_executor: Optional[ClientLLMExecutor] = None):
        self.config = config
        self.client_llm_executor = client_llm_executor
        self.logger = get_logger(__name__)
        self.prompt_manager = PromptManager(config.get("prompt_manager", {}))

        # 创建LLM和VLM接口
        self.llms_config = config.get("available_llms", {})
        self.vlms_config = config.get("available_vlms", {})
        self.llm_interfaces: Dict[str, LLMAPIInterface] = self._create_llm_interfaces()
        self.vlm_interfaces: Dict[str, VLMAPIInterface] = self._create_vlm_interfaces()

        self.llm_modules: Dict[str, LLMModule] = {}
        self.vlm_modules: Dict[str, VLMModule] = {}

    def ensure_dependencies(self) -> None:
        """检查 LLM 服务的基础依赖已经初始化。"""
        required = {
            "prompt_manager": self.prompt_manager,
            "llm_interfaces": self.llm_interfaces,
            "vlm_interfaces": self.vlm_interfaces,
            "llm_modules": self.llm_modules,
            "vlm_modules": self.vlm_modules,
        }
        missing = [name for name, value in required.items() if value is None]
        if missing:
            raise RuntimeError(f"LLMService dependencies are missing: {', '.join(missing)}")

    def register_llm_module(self, module_name: str, module_config: Dict) -> LLMModule:
        if module_name in self.llm_modules:
            self.logger.warning(f"LLM模块已存在，覆盖注册: {module_name}")

        llm_config = module_config.get("llm", {})
        prompt_name = module_config.get("prompt_name", None)
        
        prompt_template = self.prompt_manager.get_template(prompt_name)
        llm_interface = self.llm_interfaces.get(llm_config.get("name", ""), None)
        if not llm_interface:
            raise ValueError(f"LLM接口未找到: {llm_config.get('name', '')}, 无法注册模块: {module_name}")
        if not prompt_template:
            raise ValueError(f"Prompt模板未找到: {prompt_name}, 无法注册模块: {module_name}")
        
        module = LLMModule(
            module_name,
            llm_config,
            prompt_template,
            llm_interface,
            client_llm_executor=self.client_llm_executor,
        )
        self.llm_modules[module_name] = module
        return module

    def register_vlm_module(self, module_name: str, module_config: Dict) -> VLMModule:
        if module_name in self.vlm_modules:
            self.logger.warning(f"VLM模块已存在，覆盖注册: {module_name}")

        vlm_config = module_config.get("vlm", {})
        prompt_name = module_config.get("prompt_name", None)
        
        prompt_template = self.prompt_manager.get_template(prompt_name)
        vlm_interface = self.vlm_interfaces.get(vlm_config.get("name", ""), None)
        if not vlm_interface:
            raise ValueError(f"VLM接口未找到: {vlm_config.get('name', '')}, 无法注册VLM模块: {module_name}")
        if not prompt_template:
            raise ValueError(f"Prompt模板未找到: {prompt_name}, 无法注册VLM模块: {module_name}")
        
        module = VLMModule(
            module_name,
            module_config,
            prompt_template,
            vlm_interface,
            client_llm_executor=self.client_llm_executor,
        )
        self.vlm_modules[module_name] = module
        return module

    def get_llm_interface_info(self) -> Dict[str, Dict]:
        """获取所有已注册的LLM接口信息"""
        return {
            name: interface.get_interface_info()
            for name, interface in self.llm_interfaces.items()
        }

    def get_vlm_interface_info(self) -> Dict[str, Dict]:
        """获取所有已注册的VLM接口信息"""
        return {
            name: interface.get_interface_info()
            for name, interface in self.vlm_interfaces.items()
        }

    def get_client_model_types(self) -> list:
        """返回客户端模型类型字典（类型 -> 服务商+baseURL -> 模型[含勾选]）。

        直接由 llm_service.client_model_types 配置生成，作为客户端设置页
        的唯一数据来源；不包含任何密钥。
        """
        raw = (self.config or {}).get("client_model_types") or []
        types = []
        for item in raw:
            if not isinstance(item, dict):
                continue
            type_name = str(item.get("type") or "").strip()
            if not type_name:
                continue
            description = str(item.get("description") or "").strip()
            providers = []
            for provider in item.get("providers") or []:
                if not isinstance(provider, dict):
                    continue
                name = str(provider.get("name") or "").strip()
                base_url = str(provider.get("base_url") or "").strip()
                if not name or not base_url:
                    continue
                models = []
                for model in provider.get("models") or []:
                    if isinstance(model, dict):
                        model_id = str(model.get("id") or "").strip()
                        if not model_id:
                            continue
                        models.append(
                            {
                                "id": model_id,
                                "can_enable_thinking": bool(
                                    model.get("can_enable_thinking", False)
                                ),
                                "can_use_json": bool(model.get("can_use_json", False)),
                            }
                        )
                    elif isinstance(model, str) and model.strip():
                        models.append(
                            {
                                "id": model.strip(),
                                "can_enable_thinking": False,
                                "can_use_json": False,
                            }
                        )
                providers.append(
                    {
                        "name": name,
                        "base_url": base_url.rstrip("/"),
                        "models": models,
                    }
                )
            types.append(
                {"type": type_name, "description": description, "providers": providers}
            )
        return types

    def _create_llm_interfaces(self) -> Dict[str, LLMAPIInterface]:
        llm_interfaces = {}
        for llm_name, llm_config in self.llms_config.items():
            try:
                interface = LLMAPIFactory.create_interface(llm_config)
                llm_interfaces[llm_name] = interface
                self.logger.info(f"成功创建LLM接口: {llm_name}")
            except Exception as e:
                self.logger.error(f"创建LLM接口失败: {llm_name}, 错误: {e}")
        
        return llm_interfaces
    
    def _create_vlm_interfaces(self) -> Dict[str, VLMAPIInterface]:
        vlm_interfaces = {}
        for vlm_name, vlm_config in self.vlms_config.items():
            try:
                interface = VLMAPIFactory.create_interface(vlm_config)
                vlm_interfaces[vlm_name] = interface
                self.logger.info(f"成功创建VLM接口: {vlm_name}")
            except Exception as e:
                self.logger.error(f"创建VLM接口失败: {vlm_name}, 错误: {e}")
        return vlm_interfaces
