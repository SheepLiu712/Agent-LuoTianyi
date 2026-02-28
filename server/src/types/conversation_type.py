from datetime import datetime
from dataclasses import dataclass
from typing import Dict, Any


def timestamp_to_elapsed_time(timestamp: str) -> str:
    try:
        time_format = "%Y-%m-%d %H:%M:%S"
        past_time = datetime.strptime(timestamp, time_format)
        now = datetime.now()
        delta = now - past_time

        seconds = int(delta.total_seconds())
        minutes = seconds // 60
        hours = minutes // 60
        days = delta.days

        if seconds < 60:
            return f"{seconds}秒前"
        elif minutes < 60:
            return f"{minutes}分钟前"
        elif hours < 6:
            return f"{hours}小时{minutes % 60}分钟前"
        elif hours < 24:
            return f"{hours}小时前"
        elif days <= 5:
            return f"{days}天前"
        else:
            return past_time.strftime("%Y-%m-%d")
    except:
        return timestamp

@dataclass
class ConversationItem:
    uuid: str
    timestamp: str
    source: str
    type: str # 'text' | 'audio' | 'image'
    content: str
    data: Any = None # Optional binary data or extra payload (e.g. image bytes/base64)
    
    def __repr__(self) -> str:
        elapsed_time: str = self._timestamp_to_elapsed_time()
        return f"[{elapsed_time}] {self.source} ({self.type}): {self.content}"
    def __str__(self):
        return self.__repr__()
    
    def _timestamp_to_elapsed_time(self) -> str:
        """
        将时间戳转换为距离现在的时间差字符串：
        1. 当时间差不足一分钟，显示xx秒前
        2. 当时间差不足一小时，显示xx分钟前
        3. 当时间差不足6小时，显示xx小时xx分钟前
        4. 当时间差不足一天，显示xx小时前
        5. 超过一天但不超过5天，显示xx天前
        6. 超过5天，显示具体日期如2023-10-01

        Returns:
            时间差字符串
        """
        return timestamp_to_elapsed_time(self.timestamp)

class KnowledgeItem:
    def __init__(self, uuid: str, content: str, metadata: Dict[str, Any] = {}):
        self.uuid = uuid
        self.content = content
        self.metadata = metadata
