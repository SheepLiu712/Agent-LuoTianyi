import os
import sys

cwd = os.getcwd()
sys.path.insert(0, str(cwd))

from src.music.singing_manager import SingingManager

music_manager = SingingManager(config={})

print(music_manager.get_all_song())

print(music_manager.can_i_sing_song("光与影的对白"))

tool_names = music_manager.get_tool_names()
print("工具名称列表：", tool_names)
tools = music_manager.get_tools()
print(tools[1].get_interface())

exit(0)

