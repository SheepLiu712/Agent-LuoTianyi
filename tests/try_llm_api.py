import sys
import os
import json
# add cwd to sys.path
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.llm import LLMAPIInterface, LLMAPIFactory
from src.utils.helpers import load_config

main_config_path = os.path.join("config", "test_config.json")
main_config = load_config(main_config_path)

llm_config = main_config.get("llm2", {})

llm_api: LLMAPIInterface = LLMAPIFactory.create_interface(llm_config)
response = llm_api.generate_response("你好，介绍一下自己吧！")
print("LLM Response:", response)
print("LLM Interface Info:", llm_api.get_interface_info())
response_times = llm_api.get_response_time()
print("Recent Response Times (s):", response_times)