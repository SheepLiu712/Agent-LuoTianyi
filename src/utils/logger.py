"""
日志工具模块

提供统一的日志记录功能
"""

import os
import sys
from typing import Optional, Dict, Any
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
import colorlog


# 全局日志配置
_LOGGER_INSTANCES: Dict[str, logging.Logger] = {}
_DEFAULT_CONFIG = {
    "level": "DEBUG",
    "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
    "file": "./logs/agent.log",
    "rotation": "20 MB",
    "retention": "30 days",
    "console_output": True,
    "file_output": True
}


def setup_logging(config: Optional[Dict[str, Any]] = None) -> None:
    """设置全局日志配置
    
    Args:
        config: 日志配置字典
    """
    global _DEFAULT_CONFIG
    
    if config:
        _DEFAULT_CONFIG.update(config)
    
    # 创建日志目录
    log_file = Path(_DEFAULT_CONFIG["file"])
    log_file.parent.mkdir(parents=True, exist_ok=True)


def get_logger(name: str) -> logging.Logger:
    """获取日志记录器
    
    Args:
        name: 日志记录器名称
        
    Returns:
        日志记录器实例
    """
    if name in _LOGGER_INSTANCES:
        return _LOGGER_INSTANCES[name]
    
    # 创建新的日志记录器
    logger = logging.getLogger(name)
    logger.setLevel(getattr(logging, _DEFAULT_CONFIG["level"]))
    logger.propagate = False
    
    # 避免重复添加处理器
    if not logger.handlers:
        # 控制台处理器
        if _DEFAULT_CONFIG.get("console_output", True):
            console_handler = _create_console_handler()
            logger.addHandler(console_handler)
        
        # 文件处理器
        if _DEFAULT_CONFIG.get("file_output", True):
            file_handler = _create_file_handler()
            logger.addHandler(file_handler)
    
    # 缓存日志记录器
    _LOGGER_INSTANCES[name] = logger
    
    return logger


def _create_console_handler() -> logging.Handler:
    """创建控制台处理器
    
    Returns:
        控制台日志处理器
    """
    # 彩色日志格式
    color_formatter = colorlog.ColoredFormatter(
        fmt='%(log_color)s%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        log_colors={
            'DEBUG': 'cyan',
            'INFO': 'green',
            'WARNING': 'yellow',
            'ERROR': 'red',
            'CRITICAL': 'red,bg_white',
        }
    )
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(color_formatter)
    console_handler.setLevel(getattr(logging, _DEFAULT_CONFIG["level"]))
    
    return console_handler


def _create_file_handler() -> logging.Handler:
    """创建文件处理器
    
    Returns:
        文件日志处理器
    """
    # 解析轮转大小
    rotation_size = _parse_size(_DEFAULT_CONFIG.get("rotation", "20 MB"))
    
    # 文件日志格式
    file_formatter = logging.Formatter(
        fmt='%(asctime)s | %(levelname)-8s | %(name)s:%(funcName)s:%(lineno)d - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )
    if not os.path.exists(_DEFAULT_CONFIG["file"]):
        if not os.path.exists(os.path.dirname(_DEFAULT_CONFIG["file"])):
            os.makedirs(os.path.dirname(_DEFAULT_CONFIG["file"]))
        open(_DEFAULT_CONFIG["file"], 'a').close()
    file_handler = RotatingFileHandler(
        filename=_DEFAULT_CONFIG["file"],
        maxBytes=rotation_size,
        backupCount=5,
        encoding='utf-8'
    )
    file_handler.setFormatter(file_formatter)
    file_handler.setLevel(getattr(logging, _DEFAULT_CONFIG["level"]))
    
    return file_handler


def _parse_size(size_str: str) -> int:
    """解析大小字符串
    
    Args:
        size_str: 大小字符串，如 "100 MB"
        
    Returns:
        字节数
    """
    size_str = size_str.strip().upper()
    
    if size_str.endswith("KB"):
        return int(float(size_str[:-2]) * 1024)
    elif size_str.endswith("MB"):
        return int(float(size_str[:-2]) * 1024 * 1024)
    elif size_str.endswith("GB"):
        return int(float(size_str[:-2]) * 1024 * 1024 * 1024)
    else:
        # 默认按字节处理
        return int(float(size_str))


class LoggerMixin:
    """日志混入类
    
    为其他类提供日志功能
    """
    
    @property
    def logger(self) -> logging.Logger:
        """获取当前类的日志记录器
        
        Returns:
            日志记录器
        """
        return get_logger(self.__class__.__name__)


def log_function_call(func):
    """函数调用日志装饰器
    
    Args:
        func: 被装饰的函数
        
    Returns:
        装饰后的函数
    """
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        logger.debug(f"调用函数: {func.__name__} with args={args}, kwargs={kwargs}")
        
        try:
            result = func(*args, **kwargs)
            logger.debug(f"函数 {func.__name__} 执行成功")
            return result
        except Exception as e:
            logger.error(f"函数 {func.__name__} 执行失败: {e}")
            raise
    
    return wrapper


def log_execution_time(func):
    """执行时间日志装饰器
    
    Args:
        func: 被装饰的函数
        
    Returns:
        装饰后的函数
    """
    import time
    
    def wrapper(*args, **kwargs):
        logger = get_logger(func.__module__)
        start_time = time.time()
        
        try:
            result = func(*args, **kwargs)
            execution_time = time.time() - start_time
            logger.info(f"函数 {func.__name__} 执行时间: {execution_time:.3f}秒")
            return result
        except Exception as e:
            execution_time = time.time() - start_time
            logger.error(f"函数 {func.__name__} 执行失败 (耗时: {execution_time:.3f}秒): {e}")
            raise
    
    return wrapper


# 便捷的日志函数
def debug(message: str, logger_name: str = "main") -> None:
    """记录调试信息
    
    Args:
        message: 日志消息
        logger_name: 日志记录器名称
    """
    get_logger(logger_name).debug(message)


def info(message: str, logger_name: str = "main") -> None:
    """记录信息
    
    Args:
        message: 日志消息
        logger_name: 日志记录器名称
    """
    get_logger(logger_name).info(message)


def warning(message: str, logger_name: str = "main") -> None:
    """记录警告
    
    Args:
        message: 日志消息
        logger_name: 日志记录器名称
    """
    get_logger(logger_name).warning(message)


def error(message: str, logger_name: str = "main") -> None:
    """记录错误
    
    Args:
        message: 日志消息
        logger_name: 日志记录器名称
    """
    get_logger(logger_name).error(message)


def critical(message: str, logger_name: str = "main") -> None:
    """记录严重错误
    
    Args:
        message: 日志消息
        logger_name: 日志记录器名称
    """
    get_logger(logger_name).critical(message)
