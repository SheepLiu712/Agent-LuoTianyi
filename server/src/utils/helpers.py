"""
辅助工具函数

提供各种通用的辅助功能
"""

import os
import sys
import json
## 移除yaml支持，只保留json
import hashlib
import time
import uuid
from typing import Any, Dict, List, Optional, Union
from pathlib import Path
import re


def load_config(config_path: str, default_config: Optional[Dict] = None) -> Dict[str, Any]:
    """加载配置文件
    
    Args:
        config_path: 配置文件路径
        default_config: 默认配置
        
    Returns:
        配置字典
    """
    config = default_config or {}
    
    config_file = Path(config_path)
    if not config_file.exists():
        print(f"配置文件不存在: {config_path}")
        return config
    
    try:
        with open(config_file, 'r', encoding='utf-8') as f:
            if config_file.suffix.lower() == '.json':
                file_config = json.load(f)
            else:
                raise ValueError(f"不支持的配置文件格式: {config_file.suffix}")
        
        # 递归合并配置
        config = merge_dict(config, file_config or {})
        
        # 处理环境变量替换
        config = apply_env_variables(config)
        
    except Exception as e:
        print(f"加载配置文件失败 {config_path}: {e}")
    
    return config


def merge_dict(base: Dict, update: Dict) -> Dict:
    """递归合并字典
    
    Args:
        base: 基础字典
        update: 更新字典
        
    Returns:
        合并后的字典
    """
    result = base.copy()
    
    for key, value in update.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = merge_dict(result[key], value)
        else:
            result[key] = value
    
    return result


def apply_env_variables(config: Any, parent_key: str = "") -> Any:
    """递归应用环境变量替换配置中的变量，支持多层嵌套
    Args:
        config: 配置字典或列表或值
        parent_key: 当前递归的父键路径
    Returns:
        替换后的配置
    """
    if isinstance(config, dict):
        for key, value in config.items():
            full_key = f"{parent_key}.{key}" if parent_key else key
            config[key] = apply_env_variables(value, full_key)
        return config
    elif isinstance(config, list):
        return [
            apply_env_variables(item, f"{parent_key}[{i}]")
            for i, item in enumerate(config)
        ]
    elif isinstance(config, str) and config.startswith("$"):
        env_var = config[1:]
        if env_var.startswith("{") and env_var.endswith("}"):
            env_var = env_var[1:-1]
        env_value = os.environ.get(env_var)
        if env_value is not None:
            # print(f"环境变量替换: {parent_key} -> {env_var} = {env_value}")
            return env_value
        else:
            print(f"环境变量未设置: {env_var} (路径: {parent_key})")
            return config
    else:
        return config


def generate_id(prefix: str = "", length: int = 8) -> str:
    """生成唯一ID
    
    Args:
        prefix: ID前缀
        length: ID长度
        
    Returns:
        生成的ID
    """
    if length <= 0:
        unique_part = str(uuid.uuid4()).replace('-', '')
    else:
        unique_part = str(uuid.uuid4()).replace('-', '')[:length]
    
    return f"{prefix}{unique_part}" if prefix else unique_part


def calculate_hash(content: Union[str, bytes], algorithm: str = "md5") -> str:
    """计算内容哈希值
    
    Args:
        content: 内容
        algorithm: 哈希算法
        
    Returns:
        哈希值
    """
    if isinstance(content, str):
        content = content.encode('utf-8')
    
    hash_obj = hashlib.new(algorithm)
    hash_obj.update(content)
    return hash_obj.hexdigest()


def safe_get(data: Dict, key_path: str, default: Any = None) -> Any:
    """安全获取嵌套字典的值
    
    Args:
        data: 数据字典
        key_path: 键路径，如 "a.b.c"
        default: 默认值
        
    Returns:
        获取的值或默认值
    """
    keys = key_path.split('.')
    current = data
    
    try:
        for key in keys:
            current = current[key]
        return current
    except (KeyError, TypeError):
        return default


def format_size(size_bytes: int) -> str:
    """格式化文件大小
    
    Args:
        size_bytes: 字节数
        
    Returns:
        格式化的大小字符串
    """
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"


def format_duration(seconds: float) -> str:
    """格式化时间持续时间
    
    Args:
        seconds: 秒数
        
    Returns:
        格式化的时间字符串
    """
    if seconds < 60:
        return f"{seconds:.1f}秒"
    elif seconds < 3600:
        minutes = seconds / 60
        return f"{minutes:.1f}分钟"
    else:
        hours = seconds / 3600
        return f"{hours:.1f}小时"


def validate_config(config: Dict, required_keys: List[str]) -> List[str]:
    """验证配置完整性
    
    Args:
        config: 配置字典
        required_keys: 必需的键列表
        
    Returns:
        缺失的键列表
    """
    missing_keys = []
    
    for key in required_keys:
        if '.' in key:
            # 嵌套键
            if safe_get(config, key) is None:
                missing_keys.append(key)
        else:
            # 简单键
            if key not in config:
                missing_keys.append(key)
    
    return missing_keys


def ensure_directory(path: Union[str, Path]) -> Path:
    """确保目录存在
    
    Args:
        path: 目录路径
        
    Returns:
        目录路径对象
    """
    dir_path = Path(path)
    dir_path.mkdir(parents=True, exist_ok=True)
    return dir_path


def clean_text(text: str) -> str:
    """清理文本
    
    Args:
        text: 原始文本
        
    Returns:
        清理后的文本
    """
    # 移除多余的空白字符
    text = re.sub(r'\s+', ' ', text)
    
    # 移除首尾空白
    text = text.strip()
    
    # 移除控制字符
    text = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', text)
    
    return text


def split_text_chunks(text: str, max_length: int = 1000, overlap: int = 100) -> List[str]:
    """将文本分割成块
    
    Args:
        text: 原始文本
        max_length: 最大块长度
        overlap: 重叠长度
        
    Returns:
        文本块列表
    """
    if len(text) <= max_length:
        return [text]
    
    chunks = []
    start = 0
    
    while start < len(text):
        end = start + max_length
        
        # 如果不是最后一块，尝试在句子边界分割
        if end < len(text):
            # 寻找句号、问号、感叹号
            sentence_end = max(
                text.rfind('。', start, end),
                text.rfind('？', start, end),
                text.rfind('！', start, end),
                text.rfind('.', start, end),
                text.rfind('?', start, end),
                text.rfind('!', start, end)
            )
            
            if sentence_end > start:
                end = sentence_end + 1
        
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        
        # 下一块的开始位置（有重叠）
        start = max(start + 1, end - overlap)
    
    return chunks


def retry_on_exception(
    func,
    max_retries: int = 3,
    delay: float = 1.0,
    backoff_factor: float = 2.0,
    exceptions: tuple = (Exception,)
):
    """重试装饰器
    
    Args:
        func: 要重试的函数
        max_retries: 最大重试次数
        delay: 初始延迟时间
        backoff_factor: 退避因子
        exceptions: 要捕获的异常类型
        
    Returns:
        装饰后的函数
    """
    def wrapper(*args, **kwargs):
        last_exception = None
        current_delay = delay
        
        for attempt in range(max_retries + 1):
            try:
                return func(*args, **kwargs)
            except exceptions as e:
                last_exception = e
                
                if attempt < max_retries:
                    time.sleep(current_delay)
                    current_delay *= backoff_factor
                else:
                    raise last_exception
        
        raise last_exception
    
    return wrapper


class Timer:
    """计时器类"""
    
    def __init__(self):
        self.start_time = None
        self.end_time = None
    
    def start(self):
        """开始计时"""
        self.start_time = time.time()
        self.end_time = None
    
    def stop(self):
        """停止计时"""
        if self.start_time is None:
            raise RuntimeError("计时器未启动")
        self.end_time = time.time()
    
    def elapsed(self) -> float:
        """获取已用时间
        
        Returns:
            已用时间（秒）
        """
        if self.start_time is None:
            return 0.0
        
        end = self.end_time or time.time()
        return end - self.start_time
    
    def __enter__(self):
        self.start()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.stop()


def get_system_info() -> Dict[str, Any]:
    """获取系统信息
    
    Returns:
        系统信息字典
    """
    import platform
    import psutil
    
    return {
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "cpu_count": psutil.cpu_count(),
        "memory_total": psutil.virtual_memory().total,
        "memory_available": psutil.virtual_memory().available,
        "disk_usage": dict(psutil.disk_usage('/'))
    }


def check_dependencies() -> Dict[str, bool]:
    """检查依赖包是否安装
    
    Returns:
        依赖检查结果
    """
    dependencies = {
        "langchain": False,
        "openai": False,
        "chromadb": False,
        "neo4j": False,
        "pandas": False,
        "numpy": False,
        "yaml": False,
        "requests": False
    }
    
    for package in dependencies:
        try:
            __import__(package)
            dependencies[package] = True
        except ImportError:
            dependencies[package] = False
    
    return dependencies
