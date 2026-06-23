from typing import Dict, Optional
from .llm.prompt_manager import PromptManager
from src.utils.logger import get_logger
from .llm.llm_api_interface import LLMAPIInterface, LLMAPIFactory
from .vision.vlm_api_interface import VLMAPIInterface, VLMAPIFactory
from .llm.llm_module import LLMModule
from .vision.vlm_module import VLMModule

class LLMService:
    def __init__(self, config: Dict):
        self.config = config
        self.logger = get_logger(__name__)
        self.prompt_manager = PromptManager(config.get("prompt_manager", {}))

        # 创建LLM和VLM接口
        self.llms_config = config.get("available_llms", {})
        self.vlms_config = config.get("available_vlms", {})
        self.llm_interfaces: Dict[str, LLMAPIInterface] = self._create_llm_interfaces()
        self.vlm_interfaces: Dict[str, VLMAPIInterface] = self._create_vlm_interfaces()

        self.llm_modules: Dict[str, LLMModule] = {}
        self.vlm_modules: Dict[str, VLMModule] = {}

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
        
        module = LLMModule(module_name, module_config, prompt_template, llm_interface)
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
        
        module = VLMModule(module_name, module_config, prompt_template, vlm_interface)
        self.vlm_modules[module_name] = module
        return module

    def _create_llm_interfaces(self) -> Dict[str, LLMAPIInterface]:
        llm_interfaces = {}
        for llm_name, llm_config in self.llms_config.items():
            try:
                llm_interfaces[llm_name] = LLMAPIFactory.create_interface(llm_config)
                self.logger.info(f"成功创建LLM接口: {llm_name}")
            except Exception as e:
                self.logger.error(f"创建LLM接口失败: {llm_name}, 错误: {e}")
        return llm_interfaces
    
    def _create_vlm_interfaces(self) -> Dict[str, VLMAPIInterface]:
        vlm_interfaces = {}
        for vlm_name, vlm_config in self.vlms_config.items():
            try:
                vlm_interfaces[vlm_name] = VLMAPIFactory.create_interface(vlm_config)
                self.logger.info(f"成功创建VLM接口: {vlm_name}")
            except Exception as e:
                self.logger.error(f"创建VLM接口失败: {vlm_name}, 错误: {e}")
        return vlm_interfaces