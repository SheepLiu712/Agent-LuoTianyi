"""
Prompt模板管理器

管理和渲染各种Prompt模板
"""

from typing import Dict, List, Optional, Any
import os
import json
from pathlib import Path
from jinja2 import Template, Environment, FileSystemLoader

from ..utils.logger import get_logger


class PromptTemplate:
    """Prompt模板类"""
    
    def __init__(self, template_str: str, name: str = ""):
        """初始化模板
        
        Args:
            template_str: 模板字符串
            name: 模板名称
        """
        self.name = name
        self.template_str = template_str
        self.template: Template = Template(template_str)
    
    def render(self, **kwargs) -> str:
        """渲染模板
        
        Args:
            **kwargs: 模板变量
            
        Returns:
            渲染后的文本
        """
        # TODO: 实现模板渲染
        # - 验证必需变量
        # - 渲染模板
        # - 处理渲染错误
        try:
            return self.template.render(**kwargs)
        except Exception as e:
            raise ValueError(f"模板渲染失败: {e}")


class PromptManager:
    """Prompt管理器
    
    管理洛天依Agent的各种Prompt模板
    """
    
    def __init__(self, config: Dict[str, Any]):
        """初始化Prompt管理器
        
        Args:
            config: 配置字典
        """
        self.logger = get_logger(__name__)
        self.config = config
        self.templates: Dict[str, PromptTemplate] = {}
        
        # 从配置文件加载模板
        if "template_dir" in config:
            self._load_templates_from_dir(config["template_dir"])
        
        self.logger.info(f"Prompt管理器初始化完成，加载模板数: {len(self.templates)}")
    
    def _load_templates_from_dir(self, template_dir: str) -> None:
        """从目录加载模板文件
        
        Args:
            template_dir: 模板目录路径
        """
        
        template_path = Path(template_dir)
        if not template_path.exists():
            self.logger.warning(f"模板目录不存在: {template_dir}")
            return
        
        for file_path in template_path.glob("*.json"):
                try:
                    with open(file_path, 'r', encoding='utf-8') as f:
                        template_data = json.load(f)
                    
                    name = template_data.get("name", file_path.stem)
                    template_str = template_data.get("template", "")
                    if isinstance(template_str, list):
                        template_str = "\n\n".join(template_str)
                    
                    if template_str:
                        self.templates[name] = PromptTemplate(template_str, name)
                        self.logger.info(f"加载模板: {name}")
                        
                except Exception as e:
                    self.logger.error(f"加载模板文件失败 {file_path}: {e}")
    
    def get_template(self, name: str) -> Optional[PromptTemplate]:
        """获取模板
        
        Args:
            name: 模板名称
            
        Returns:
            模板对象，如果不存在则返回None
        """
        return self.templates.get(name)
    
    def render_template(self, name: str, **kwargs) -> str:
        """渲染指定模板
        
        Args:
            name: 模板名称
            **kwargs: 模板变量
            
        Returns:
            渲染后的文本
            
        Raises:
            ValueError: 模板不存在或渲染失败
        """
        template = self.get_template(name)
        if not template:
            raise ValueError(f"模板不存在: {name}")
        
        return template.render(**kwargs)
    
    def build_conversation_prompt(
        self,
        user_message: str,
        persona: Dict[str, Any],
        knowledge: Optional[Dict[str, Any]] = None,
        conversation_history: Optional[List[Dict[str, str]]] = None,
        intent: Optional[str] = None
    ) -> str:
        """构建对话Prompt
        
        Args:
            user_message: 用户消息
            persona: 人设信息
            knowledge: 知识信息
            conversation_history: 对话历史
            intent: 用户意图
            
        Returns:
            构建的Prompt文本
        """
        # TODO: 根据意图选择合适的模板并构建Prompt
        
        # 根据意图选择模板
        template_name = self._select_template_by_intent(intent)
        
        # 准备模板变量
        import datetime
        template_vars = {
            "user_message": user_message,
            "persona": persona,
            "knowledge": knowledge or {},
            "conversation_history": conversation_history or {},
            "current_time": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "intent": intent
        }
        
        # 渲染模板
        return self.render_template(template_name, **template_vars)
    
    def _select_template_by_intent(self, intent: Optional[str]) -> str:
        """根据意图选择模板
        
        Args:
            intent: 用户意图
            
        Returns:
            模板名称
        """
        # TODO: 实现意图到模板的映射逻辑
        
        intent_template_map = {
            "greeting": "greeting",
            "song_inquiry": "song_inquiry",
            "basic_chat": "basic_chat"
        }
        
        return intent_template_map.get(intent, "daily_chat_prompt")
    
    def add_template(self, name: str, template_str: str) -> None:
        """添加新模板
        
        Args:
            name: 模板名称
            template_str: 模板字符串
        """
        self.templates[name] = PromptTemplate(template_str, name)
        self.logger.info(f"添加模板: {name}")
    
    def remove_template(self, name: str) -> bool:
        """移除模板
        
        Args:
            name: 模板名称
            
        Returns:
            是否成功移除
        """
        if name in self.templates:
            del self.templates[name]
            self.logger.info(f"移除模板: {name}")
            return True
        return False
    
    def list_templates(self) -> List[str]:
        """列出所有模板名称
        
        Returns:
            模板名称列表
        """
        return list(self.templates.keys())
    
    def get_template_info(self, name: str) -> Optional[Dict[str, Any]]:
        """获取模板信息
        
        Args:
            name: 模板名称
            
        Returns:
            模板信息字典
        """
        template = self.get_template(name)
        if not template:
            return None
        
        return {
            "name": template.name,
            "template": template.template_str,
            "variables": self._extract_template_variables(template.template_str)
        }
    
    def _extract_template_variables(self, template_str: str) -> List[str]:
        """提取模板中的变量
        
        Args:
            template_str: 模板字符串
            
        Returns:
            变量名列表
        """
        # TODO: 解析模板中的变量
        # - 使用正则表达式或AST解析
        # - 提取所有模板变量
        import re
        
        # 简单的变量提取（可以改进）
        pattern = r'\{\{\s*(\w+)(?:\.\w+)*\s*\}\}'
        variables = re.findall(pattern, template_str)
        return list(set(variables))
