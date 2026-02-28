from dataclasses import dataclass
from typing import List, Dict, Callable
import json


@dataclass
class ToolOneParameter:
    name: str
    type: str
    description: str


@dataclass
class ToolFunction:
    name: str
    description: str
    parameters: List[ToolOneParameter]

    def to_dict(self) -> Dict:
        return {
            "tool_name": self.name,
            "description": self.description,
            "parameters": [{"name": param.name, "type": param.type, "description": param.description} for param in self.parameters],
        }


@dataclass
class MyTool:
    name: str
    description: str
    tool_interface: ToolFunction  # 工具的接口定义
    tool_func: Callable[..., str]  # 实际执行工具功能的函数
    additional_required_params: List[str] = None  # 主要包括数据库的接口等，不需要LLM传入

    def get_interface(self) -> Dict:
        return self.tool_interface.to_dict()
    
    def get_interface_str(self) -> str:
        return json.dumps(self.get_interface(), ensure_ascii=False, indent=2)
