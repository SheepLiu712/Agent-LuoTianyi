import sys
import os
import json

cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.llm.prompt_manager import PromptManager, PromptTemplate
from src.utils.helpers import load_config

main_config_path = os.path.join("config", "test_config.json")
main_config = load_config(main_config_path)

prompt_config = main_config.get("prompt_manager", {})
prompt_manager = PromptManager(prompt_config)

chat_prompt: PromptTemplate = prompt_manager.get_template("daily_chat_prompt")
print("模板变量:", chat_prompt.get_variables())