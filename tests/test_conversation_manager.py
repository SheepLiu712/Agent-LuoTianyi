import sys
import os
import json

# add cwd to sys.path
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)


from src.agent.conversation_manager import ConversationManager
from src.llm.prompt_manager import PromptManager
from src.utils.helpers import load_config
from src.utils.enum_type import ContextType, ConversationSource

config_path = "config/config.json"
config = load_config(config_path)
pm_config = config.get("prompt_manager", {})
cm_config = config.get("conversation_manager", {})
prompt_manager = PromptManager(pm_config)
manager = ConversationManager(cm_config, prompt_manager)

manager.add_conversation(source=ConversationSource.USER, type=ContextType.TEXT, content="我们来玩报数吧,从0开始！0")
for i in range(50):
    manager.add_conversation(source=ConversationSource.AGENT, type=ContextType.TEXT, content=f"{2*i+1}")
    manager.add_conversation(source=ConversationSource.USER, type=ContextType.TEXT, content=f"{2*i+2}")

input("Added 100 messages, press Enter to update summary...")
context = manager.get_context()
print("Current context:")
print(context)