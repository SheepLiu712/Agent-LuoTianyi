from ..llm.llm_module import LLMModule
from ..llm.prompt_manager import PromptManager
from typing import Dict, Any, List, Optional
from jinja2 import Template
import time
import dataclasses
import json


@dataclasses.dataclass
class OneSentenceChat:
    expression: str
    tone: str
    content: str


class MainChat:
    def __init__(
        self, config: Dict[str, Any], prompt_manager: PromptManager, available_tone: List[str], available_expression: List[str]
    ) -> None:
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.variables: List[str] = self.llm.prompt_template.get_variables()

        self.init_static_variables(available_tone, available_expression)

    def generate_response(self, user_input: str) -> list[OneSentenceChat]:
        current_time = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())
        persona = self.persona
        response_requirements = self.response_requirements
        response_format = self.response_format
        conversation_history = ""  # Placeholder for conversation history
        knowledge = ""  # Placeholder for knowledge

        response = self.llm.generate_response(
            user_message=user_input,
            current_time=current_time,
            persona=persona,
            response_requirements=response_requirements,
            response_format=response_format,
            conversation_history=conversation_history,
            knowledge=knowledge,
        )

        sentences = response.split("\n\n")
        result: list[OneSentenceChat] = []
        for sentence in sentences:
            parts = sentence.split("||")
            if len(parts) != 3:
                continue
            expression, tone, content = parts
            result.append(OneSentenceChat(expression.strip(), tone.strip(), content.strip()))

        return result

    def init_static_variables(self, available_tone: List[str], available_expression: List[str]) -> None:
        """获取在prompt中不变的变量： persona, response_requirements, response_format"""
        static_variables_file = self.config.get("static_variables_file", None)
        if not static_variables_file:
            raise ValueError("static_variables_file must be provided in main_chat config")
        with open(static_variables_file, "r", encoding="utf-8") as f:
            static_vars: Dict[str, Any] = json.load(f)

        self.persona = static_vars.get("persona")
        if isinstance(self.persona, list):
            self.persona = "\n".join(self.persona)
        self.response_requirements = static_vars.get("response_requirements")
        if isinstance(self.response_requirements, list):
            self.response_requirements = "\n".join(self.response_requirements)


        response_format_raw = static_vars.get("response_format")
        if isinstance(response_format_raw, list):
            response_format_raw = "\n".join(response_format_raw)
        
        template = Template(response_format_raw)
        self.response_format = template.render(available_tone=available_tone, available_expression=available_expression)