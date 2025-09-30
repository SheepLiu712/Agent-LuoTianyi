from src.agents.luotianyi_agent import LuoTianyiAgent
import re
agent = LuoTianyiAgent("config/config.json")

try:
    while True:
        query = input()
        response = agent.chat(query)

        # 按照中文标点符号和emoji将回复文本分割成多个部分
        # segments = re.split(r'(?<=[。！？])|(?=[\U0001F600-\U0001F64F])', response)
        segments = re.split(r'\n\n', response)
        # 逐个输出
        import time
        for segment in segments:
            # 删除所有回车
            length = len(segment)
            time.sleep(0.1 * length)  # 根据文本长度调整延迟时间
            print(f"[{time.strftime('%H:%M')}] {segment}")
except KeyboardInterrupt:
    pass