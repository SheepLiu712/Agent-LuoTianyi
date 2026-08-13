from typing import Dict, Optional
from .llm.prompt_manager import PromptManager
from src.utils.logger import get_logger
from .llm.llm_api_interface import LLMAPIInterface, LLMAPIFactory
from .vision.vlm_api_interface import VLMAPIInterface, VLMAPIFactory
from .llm.llm_module import LLMModule
from .vision.vlm_module import VLMModule
from .llm.client_llm_executor import ClientLLMExecutor
from .llm.client_delegating_interface import (
    ClientDelegatingLLMInterface,
    ClientDelegatingVLMInterface,
)

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
        # 需要 JSON 输出的模块：module_name -> 用户可见标签（来自模块配置）
        self._llm_json_modules: Dict[str, str] = {}
        self._vlm_json_modules: Dict[str, str] = {}

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
        
        module = LLMModule(module_name, llm_config, prompt_template, llm_interface)
        self.llm_modules[module_name] = module
        self._llm_json_modules.pop(module_name, None)
        if llm_config.get("use_json", False):
            self._llm_json_modules[module_name] = str(
                module_config.get("label") or module_name
            )
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
        self._vlm_json_modules.pop(module_name, None)
        if module_config.get("use_json", vlm_config.get("use_json", False)):
            self._vlm_json_modules[module_name] = str(
                module_config.get("label") or module_name
            )
        return module

    def get_llm_json_required_modules(self) -> list:
        """返回需要 JSON 输出的 LLM 模块（名称+友好标签），客户端能力不足时这些模块回退服务端 key。"""
        return [
            {"name": name, "label": label}
            for name, label in sorted(self._llm_json_modules.items())
        ]

    def get_vlm_json_required_modules(self) -> list:
        """返回需要 JSON 输出的 VLM 模块（名称+友好标签）。"""
        return [
            {"name": name, "label": label}
            for name, label in sorted(self._vlm_json_modules.items())
        ]
    
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

    def get_llm_model_capabilities(self) -> Dict[str, Dict]:
        """返回各 LLM 模型的能力标注（思考/JSON），作为客户端唯一能力来源。"""
        return {
            str(cfg.get("model")): {
                "can_enable_thinking": bool(cfg.get("can_enable_thinking", False)),
                "can_use_json": bool(cfg.get("can_use_json", False)),
            }
            for cfg in (self.llms_config or {}).values()
            if isinstance(cfg, dict) and isinstance(cfg.get("model"), str)
        }

    def get_vlm_model_capabilities(self) -> Dict[str, Dict]:
        """返回各 VLM 模型的能力标注（思考/JSON），作为客户端唯一能力来源。"""
        return {
            str(cfg.get("model")): {
                "can_enable_thinking": bool(cfg.get("can_enable_thinking", False)),
                "can_use_json": bool(cfg.get("can_use_json", False)),
            }
            for cfg in (self.vlms_config or {}).values()
            if isinstance(cfg, dict) and isinstance(cfg.get("model"), str)
        }

    def get_client_providers(self) -> list:
        """由已配置的 LLM/VLM 接口拼接客户端可选服务商列表。

        不再维护独立的 llm_providers 配置：每个接口按名称去重合并，
        LLM 接口提供 llm_models，VLM 接口提供 vlm_models，均取接口配置
        中的 model 与 base_url。
        """
        providers: Dict[str, Dict] = {}

        def _merge(name: str, cfg: Dict, key: str) -> None:
            if not isinstance(cfg, dict):
                return
            entry = providers.setdefault(
                name,
                {"name": name, "base_url": "", "llm_models": [], "vlm_models": []},
            )
            if cfg.get("base_url"):
                entry["base_url"] = str(cfg["base_url"])
            model = cfg.get("model")
            if isinstance(model, str) and model and model not in entry[key]:
                entry[key].append(model)

        for name, cfg in (self.llms_config or {}).items():
            _merge(name, cfg, "llm_models")
        for name, cfg in (self.vlms_config or {}).items():
            _merge(name, cfg, "vlm_models")
        return [
            p for p in providers.values() if p["llm_models"] or p["vlm_models"]
        ]

    def _create_llm_interfaces(self) -> Dict[str, LLMAPIInterface]:
        llm_interfaces = {}
        for llm_name, llm_config in self.llms_config.items():
            try:
                interface = LLMAPIFactory.create_interface(llm_config)
                if self.client_llm_executor is not None:
                    wrapped = ClientDelegatingLLMInterface(interface, self.client_llm_executor)
                    wrapped._module_name = llm_name
                    interface = wrapped
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
                if self.client_llm_executor is not None:
                    wrapped = ClientDelegatingVLMInterface(interface, self.client_llm_executor)
                    wrapped._module_name = vlm_name
                    interface = wrapped
                vlm_interfaces[vlm_name] = interface
                self.logger.info(f"成功创建VLM接口: {vlm_name}")
            except Exception as e:
                self.logger.error(f"创建VLM接口失败: {vlm_name}, 错误: {e}")
        return vlm_interfaces
