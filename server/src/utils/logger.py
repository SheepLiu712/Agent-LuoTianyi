"""
日志工具模块

提供统一的日志记录功能
"""

import os
import re
import sys
from typing import Optional, Dict, Any
from pathlib import Path
import logging
from logging.handlers import RotatingFileHandler
from urllib.parse import unquote_plus
import colorlog


# 全局日志配置
_LOGGER_INSTANCES: Dict[str, logging.Logger] = {}
_OBSERVABILITY_HANDLER: logging.Handler | None = None
_CONSOLE_HANDLER: logging.Handler | None = None
_FILE_HANDLER: logging.Handler | None = None
_DEFAULT_CONFIG = {
    "level": "DEBUG",
    "format": "{time:YYYY-MM-DD HH:mm:ss} | {level} | {name}:{function}:{line} - {message}",
    "file": "./logs/luotianyi-server.log",
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
    global _DEFAULT_CONFIG, _CONSOLE_HANDLER, _FILE_HANDLER
    
    if config:
        _DEFAULT_CONFIG.update(config)
    
    # 创建日志目录
    log_file = Path(_DEFAULT_CONFIG["file"])
    log_file.parent.mkdir(parents=True, exist_ok=True)
    old_handlers = []
    if _CONSOLE_HANDLER is not None:
        old_handlers.append(_CONSOLE_HANDLER)
    if _FILE_HANDLER is not None:
        old_handlers.append(_FILE_HANDLER)
    for handler in old_handlers:
        try:
            handler.close()
        except Exception:
            pass
    _CONSOLE_HANDLER = None
    _FILE_HANDLER = None
    for logger in _LOGGER_INSTANCES.values():
        logger.handlers.clear()
        if _DEFAULT_CONFIG.get("console_output", True):
            logger.addHandler(_get_console_handler())
        if _DEFAULT_CONFIG.get("file_output", True):
            logger.addHandler(_get_file_handler())
        if _OBSERVABILITY_HANDLER and _OBSERVABILITY_HANDLER not in logger.handlers:
            logger.addHandler(_OBSERVABILITY_HANDLER)


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
            logger.addHandler(_get_console_handler())
        
        # 文件处理器
        if _DEFAULT_CONFIG.get("file_output", True):
            logger.addHandler(_get_file_handler())
    if _OBSERVABILITY_HANDLER and _OBSERVABILITY_HANDLER not in logger.handlers:
        logger.addHandler(_OBSERVABILITY_HANDLER)
    
    # 缓存日志记录器
    _LOGGER_INSTANCES[name] = logger
    
    return logger

_SENSITIVE_QUERY_KEYS = {
    "token",
    "message_token",
    "login_token",
    "access_token",
    "refresh_token",
    "invite_code",
    "setup_token",
    "authorization",
    "api_key",
    "apikey",
    "password",
    "secret",
}
_ACCESS_REQUEST_TARGET_RE = re.compile(
    r'(?P<prefix>"[A-Z]+\s+)(?P<target>\S+)(?P<suffix>\s+HTTP/\d(?:\.\d+)?")'
)


def _normalized_query_key(raw_key: str) -> str:
    decoded = raw_key
    for _ in range(3):
        next_value = unquote_plus(decoded)
        if next_value == decoded:
            break
        decoded = next_value
    return decoded.strip().casefold().replace("-", "_")


def _is_sensitive_query_key(raw_key: str) -> bool:
    normalized = _normalized_query_key(raw_key)
    return (
        normalized in _SENSITIVE_QUERY_KEYS
        or normalized.endswith("_token")
        or normalized.endswith("_secret")
    )


def _redact_sensitive_query(target: str) -> str:
    base, separator, query = target.partition("?")
    if not separator:
        return target
    redacted_fields = []
    changed = False
    for field in query.split("&"):
        raw_key, equals, _ = field.partition("=")
        if _is_sensitive_query_key(raw_key):
            redacted_fields.append(f"{raw_key}=REDACTED")
            changed = True
        else:
            redacted_fields.append(field if equals else raw_key)
    if not changed:
        return target
    return f"{base}?{'&'.join(redacted_fields)}"


def _redact_access_message(message: str) -> str:
    return _ACCESS_REQUEST_TARGET_RE.sub(
        lambda match: (
            f"{match.group('prefix')}"
            f"{_redact_sensitive_query(match.group('target'))}"
            f"{match.group('suffix')}"
        ),
        message,
    )


class AdminSuccessAccessLogFilter(logging.Filter):
    """Hide noisy successful admin polling from uvicorn access logs."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args if isinstance(record.args, tuple) else ()
        if len(args) >= 3:
            sanitized_args = list(args)
            sanitized_args[2] = _redact_sensitive_query(str(sanitized_args[2]))
            record.args = tuple(sanitized_args)
        else:
            try:
                message = record.getMessage()
            except (TypeError, ValueError):
                message = ""
            sanitized_message = _redact_access_message(message)
            if sanitized_message != message:
                record.msg = sanitized_message
                record.args = ()

        if record.levelno >= logging.WARNING:
            return True
        args = record.args if isinstance(record.args, tuple) else ()
        try:
            if len(args) >= 5:
                method = str(args[1])
                path = str(args[2])
                status_code = int(args[4])
            else:
                message = record.getMessage()
                request_part = message.split('"', 2)[1]
                method, path, *_ = request_part.split()
                status_code = int(message.rsplit(" ", 2)[-2])
        except (IndexError, TypeError, ValueError):
            return True
        return not (path.startswith("/admin") and status_code < 400 and method in {"GET", "POST", "PUT", "DELETE", "PATCH"})


def install_access_log_filter() -> None:
    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(item, AdminSuccessAccessLogFilter) for item in access_logger.filters):
        access_logger.addFilter(AdminSuccessAccessLogFilter())

class ObservabilityLogHandler(logging.Handler):
    """Capture warning/error logs into the admin observability store."""

    def __init__(self, observability_service):
        super().__init__(level=logging.WARNING)
        self.observability_service = observability_service
        self._traceback_formatter = logging.Formatter()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            traceback_text = None
            if record.exc_info:
                traceback_text = self._traceback_formatter.formatException(record.exc_info)
            self.observability_service.record_log_event(
                level=record.levelname,
                logger_name=record.name,
                message=record.getMessage(),
                traceback_text=traceback_text,
                module_name=record.module,
            )
        except Exception:
            self.handleError(record)


def install_observability_log_handler(observability_service) -> None:
    """Install or replace the warning/error handler used by all project loggers."""
    global _OBSERVABILITY_HANDLER
    if _OBSERVABILITY_HANDLER is not None:
        for logger in _LOGGER_INSTANCES.values():
            if _OBSERVABILITY_HANDLER in logger.handlers:
                logger.removeHandler(_OBSERVABILITY_HANDLER)
    _OBSERVABILITY_HANDLER = ObservabilityLogHandler(observability_service)
    for logger in _LOGGER_INSTANCES.values():
        if _OBSERVABILITY_HANDLER not in logger.handlers:
            logger.addHandler(_OBSERVABILITY_HANDLER)


def uninstall_observability_log_handler() -> None:
    global _OBSERVABILITY_HANDLER
    if _OBSERVABILITY_HANDLER is None:
        return
    for logger in _LOGGER_INSTANCES.values():
        if _OBSERVABILITY_HANDLER in logger.handlers:
            logger.removeHandler(_OBSERVABILITY_HANDLER)
    _OBSERVABILITY_HANDLER = None


class WindowsSafeRotatingFileHandler(RotatingFileHandler):
    """RotatingFileHandler that tolerates Windows file-lock rollover failures."""

    def doRollover(self) -> None:
        try:
            super().doRollover()
        except PermissionError:
            # Windows refuses os.rename() when another process still has the
            # log open. Keep the current file and continue logging instead of
            # letting logging.Handler print a noisy "--- Logging error ---".
            if self.stream is None or self.stream.closed:
                self.stream = self._open()


def _get_console_handler() -> logging.Handler:
    global _CONSOLE_HANDLER
    if _CONSOLE_HANDLER is None:
        _CONSOLE_HANDLER = _create_console_handler()
    return _CONSOLE_HANDLER


def _get_file_handler() -> logging.Handler:
    global _FILE_HANDLER
    if _FILE_HANDLER is None:
        _FILE_HANDLER = _create_file_handler()
    return _FILE_HANDLER


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
    file_handler = WindowsSafeRotatingFileHandler(
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
