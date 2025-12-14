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

    def __init__(self, template_str: str, var_list: list[str] = [], name: str = ""):
        """初始化模板

        Args:
            template_str: 模板字符串
            name: 模板名称
        """
        self.name = name
        self.template_str = template_str
        self.var_list = var_list
        self.template: Template = Template(template_str)

    def render(self, **kwargs) -> str:
        """渲染模板

        Args:
            **kwargs: 模板变量

        Returns:
            渲染后的文本
        """
        # kwargs 应该有 self.var_list 中的所有变量
        missing_vars = [var for var in self.var_list if var not in kwargs]
        if missing_vars:
            raise ValueError(f"缺少模板变量: {missing_vars}")
        try:
            return self.template.render(**kwargs)
        except Exception as e:
            raise ValueError(f"模板渲染失败: {e}")
    
    def get_variables(self) -> List[str]:
        """获取模板变量列表

        Returns:
            变量名列表
        """
        return self.var_list


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
        else:
            self.logger.warning("未指定模板目录，未加载任何模板")

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
                with open(file_path, "r", encoding="utf-8") as f:
                    template_data = json.load(f)

                name = template_data.get("name", file_path.stem)
                template_str = template_data.get("template", "")
                if isinstance(template_str, list):
                    template_str = "\n\n".join(template_str)

                if template_str:
                    var_list = self._extract_template_variables(template_str)
                    self.templates[name] = PromptTemplate(template_str, var_list, name)
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
            "variables": self._extract_template_variables(template.template_str),
        }

    def _extract_template_variables(self, template_str: str) -> List[str]:
        """提取模板中的变量

        Args:
            template_str: 模板字符串

        Returns:
            变量名列表
        """
        import re

        # 简单的变量提取（可以改进）
        # 匹配形如 {{ variable }} 或 {{ object.property }} 的模板变量
        pattern = r"\{\{\s*(\w+)(?:\.\w+)*\s*\}\}"
        variables = re.findall(pattern, template_str)
        return list(set(variables))
