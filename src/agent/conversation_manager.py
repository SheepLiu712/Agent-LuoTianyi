import os
import json
from datetime import datetime
from typing import List, Dict, Any
from dataclasses import dataclass, asdict
from ..utils.logger import get_logger
from ..llm.llm_module import LLMModule
from ..llm.prompt_manager import PromptManager
from threading import Thread
from ..utils.enum_type import ContextType, ConversationSource

@dataclass
class ConversationItem:
    timestamp: str
    source: str
    type: str
    content: str
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
        time_format = "%Y-%m-%d %H:%M:%S"
        past_time = datetime.strptime(self.timestamp, time_format)
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
        

class ConversationManager:
    """
    对话管理器
    负责管理对话历史，包括存储、读取和上下文生成
    支持文件轮转和索引管理
    """
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager) -> None:
        self.logger = get_logger(__name__)
        self.config = config
        self.llm = LLMModule(config["llm_module"], prompt_manager)
        self.history_dir = self.config.get("history_dir", "data/memory/conversation_history")
        self.max_file_lines = self.config.get("max_file_lines", 2500)
        self.recent_limit = self.config.get("recent_history_limit", 100)
        
        self._ensure_directory()
        self.index_file = os.path.join(self.history_dir, "index.json")

        
        self.index_data = self._load_index()
        
        # 内存缓存（仅存储最近的对话）
        self.recent_history: List[ConversationItem] = []
        self._load_recent_history()

        # 上下文管理相关
        self.context_file = self.config.get("context_file", "data/memory/context/context.json")
        if not os.path.exists(os.path.dirname(self.context_file)):
            os.makedirs(os.path.dirname(self.context_file), exist_ok=True)
        self.raw_conversation_context_limit = self.config.get("raw_conversation_context_limit", 100)
        self.forget_conversation_days = self.config.get("forget_conversation_days", 10)
        self.not_zip_conversation_count = self.config.get("not_zip_conversation_count", 20)
        self._load_context()
        self.update_context_thread: Thread | None = None

    def add_conversation(self, source: ConversationSource, content: str, type: ContextType = ContextType.TEXT):
        """
        添加对话
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        item = ConversationItem(
            timestamp=timestamp,
            source=source.value,
            type=type.value,
            content=content
        )
        
        # 1. 获取当前文件信息
        file_info = self._get_current_file_info()
        file_path = os.path.join(self.history_dir, file_info["filename"])
        
        # 2. 写入文件
        with open(file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(asdict(item), ensure_ascii=False) + "\n")
        
        # 3. 更新索引
        file_info["count"] += 1
        file_info["end_index"] += 1
        self.index_data["total_count"] += 1
        self._save_index()
        
        # 4. 更新内存缓存
        self.recent_history.append(item)
        if len(self.recent_history) > self.recent_limit:
            self.recent_history.pop(0)
        
        self.context.append(item)
        if len(self.context) > self.raw_conversation_context_limit:
            self.update_context_thread = Thread(target=self._update_context)
            self.update_context_thread.daemon = True
            self.update_context_thread.start()
        else:
            # 直接保存上下文
            self._save_context()

    def get_nearset_history(self, n: int) -> List[ConversationItem]:
        """
        获取最近的n条对话
        """
        total_cnt = self.index_data["total_count"]
        start = max(0, total_cnt - n)
        return self.get_history(start, total_cnt)

    def get_history(self, start: int, end: int) -> List[ConversationItem]:
        """
        调用历史对话
        :param start: 开始编号 (包含)
        :param end: 结束编号 (不包含)
        :return: 对话对象列表
        """
        total = self.index_data["total_count"]
        if start < 0: start = 0
        if end > total: end = total
        if start >= end: return []

        # 检查是否完全在最近缓存中
        # 缓存范围: [total - len(recent), total)
        cache_start_idx = total - len(self.recent_history)
        if start >= cache_start_idx:
            # 计算在缓存中的相对位置
            rel_start = start - cache_start_idx
            rel_end = end - cache_start_idx
            return self.recent_history[rel_start:rel_end]

        # 如果不在缓存中，或者跨越了缓存，则从文件读取
        # 为了简单起见，只要请求范围不完全在缓存中，就去查文件
        # (也可以优化为部分查文件+部分查缓存，但这里直接查文件逻辑更统一)
        
        result = []
        # 找到涉及的文件
        for file_info in self.index_data["files"]:
            f_start = file_info["start_index"]
            f_end = file_info["end_index"] # exclusive for the file range logic usually, but let's check logic
            # index logic: start_index is inclusive, end_index is exclusive (start + count)
            
            # 检查区间重叠
            # 请求区间 [start, end)
            # 文件区间 [f_start, f_end)
            
            if start < f_end and end > f_start:
                # 计算重叠部分
                read_start = max(start, f_start)
                read_end = min(end, f_end)
                
                # 计算文件内的行号偏移
                # 文件第一行对应 f_start
                skip_lines = read_start - f_start
                count_lines = read_end - read_start
                
                file_items = self._read_lines_from_file(file_info["filename"], skip_lines, count_lines)
                result.extend(file_items)
                
        return result
    
    def get_context(self) -> str:
        """
        调用上下文 
        返回一个长度的上下文，包含最近对话中的部分原文和更远对话的总结
        """
        if self.update_context_thread is not None and self.update_context_thread.is_alive(): # 等待上下文更新线程完成
            self.update_context_thread.join()
        return "更早对话总结：" + self.summary + \
              "\n 最近对话：\n" + "\n".join([f"[{item.timestamp}]{item.source}: {item.content}" for item in self.context])

    def _ensure_directory(self):
        if not os.path.exists(self.history_dir):
            os.makedirs(self.history_dir)

    def _load_index(self) -> Dict[str, Any]:
        """加载或初始化索引文件"""
        if os.path.exists(self.index_file):
            try:
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception:
                pass
        
        # 初始化默认索引
        default_index = {
            "total_count": 0,
            "files": []
        }
        return default_index

    def _save_index(self):
        """保存索引文件"""
        with open(self.index_file, 'w', encoding='utf-8') as f:
            json.dump(self.index_data, f, ensure_ascii=False, indent=4)

    def _get_current_file_info(self) -> Dict[str, Any]:
        """获取当前正在写入的文件信息，如果不存在则创建"""
        if not self.index_data["files"]:
            # 创建第一个文件
            new_file = {
                "filename": "history_0.jsonl",
                "count": 0,
                "start_index": 0,
                "end_index": 0
            }
            self.index_data["files"].append(new_file)
            return new_file
        
        current = self.index_data["files"][-1]
        if current["count"] >= self.max_file_lines:
            # 需要轮转到新文件
            next_idx = len(self.index_data["files"])
            new_file = {
                "filename": f"history_{next_idx}.jsonl",
                "count": 0,
                "start_index": self.index_data["total_count"],
                "end_index": self.index_data["total_count"]
            }
            self.index_data["files"].append(new_file)
            return new_file
        
        return current

    def _load_recent_history(self):
        """加载最近的N条历史对话"""
        self.recent_history = []
        total = self.index_data["total_count"]
        if total == 0:
            return

        start_idx = max(0, total - self.recent_limit)
        self.recent_history = self.get_history(start_idx, total)
    
    def _load_context(self):
        if not os.path.exists(self.context_file):
            self.context = []
            self.summary = ""
            return
        try:
            with open(self.context_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
                raw_context = data.get("context", [])
                self.context = [ConversationItem(**item) for item in raw_context]
                self.summary = data.get("summary", "")
        except Exception:
            self.context = []
            self.summary = ""
    
    def _save_context(self):
        data = {
            "summary": self.summary,
            "context": [asdict(item) for item in self.context],
        }
        with open(self.context_file, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
            
    
    def _update_context(self):
        '''
        更新上下文，将较早的对话进行总结
        通过调用LLM生成新的总结
        这一过程会在后台线程中进行，但是如果要调用上下文时会等待完成
        生成新的summary后，更新self.summary和self.context
        '''
        self.logger.debug("Updating conversation context summary...")
        new_summary = self.llm.generate_response(
            forget_conversation_days = self.forget_conversation_days,
            current_summary = self.summary,
            recent_conversation = "\n".join([f"[{item.timestamp}]{item.source}: {item.content}" for item in self.context])
        )
        print(new_summary)
        self.summary = new_summary.strip()
        self.context = self.context[-self.not_zip_conversation_count:]
        self._save_context()

    def _read_lines_from_file(self, filename: str, skip: int, count: int) -> List[ConversationItem]:
        """从指定文件读取指定行"""
        items = []
        file_path = os.path.join(self.history_dir, filename)
        if not os.path.exists(file_path):
            return items
            
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                # 跳过前 skip 行
                for _ in range(skip):
                    next(f, None)
                
                # 读取 count 行
                for _ in range(count):
                    line = next(f, None)
                    if line is None:
                        break
                    if line.strip():
                        try:
                            data = json.loads(line)
                            items.append(ConversationItem(**data))
                        except Exception:
                            continue
        except Exception:
            pass
        return items


