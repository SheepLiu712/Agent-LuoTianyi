"""OpenAI 兼容响应的共享解析实现。"""

from __future__ import annotations

from typing import Any, Optional


def _response_time(response: Any) -> Optional[float]:
    for attr in ("response_ms", "response_time", "timing"):
        value = getattr(response, attr, None)
        if value is None:
            continue
        try:
            return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _usage(response: Any, logger: Any, *, log_usage: bool) -> tuple[Optional[dict[str, int]], Optional[float]]:
    usage_obj = getattr(response, "usage", None)
    if not usage_obj:
        logger.warning("无法获取token usage信息")
        return None, None
    try:
        usage = {
            "prompt_tokens": getattr(usage_obj, "prompt_tokens", 0),
            "completion_tokens": getattr(usage_obj, "completion_tokens", 0),
            "total_tokens": getattr(usage_obj, "total_tokens", 0),
        }
        if log_usage:
            logger.debug(
                "Token usage - Prompt: %s, Completion: %s, Total: %s",
                usage["prompt_tokens"],
                usage["completion_tokens"],
                usage["total_tokens"],
            )
        timing = getattr(usage_obj, "completion_time", None) or getattr(usage_obj, "total_time", None)
        return usage, timing
    except Exception:
        logger.error("无法获取token usage信息", exc_info=True)
        return None, None


def _seconds(server_time: Any, elapsed: float) -> float:
    if server_time is None:
        return elapsed
    try:
        seconds = float(server_time)
    except (TypeError, ValueError):
        return elapsed
    return seconds / 1000.0 if seconds > 1000 else seconds


def _content(response: Any, logger: Any) -> str:
    try:
        choices = getattr(response, "choices", None)
        if not choices:
            logger.warning("无法从响应中提取内容")
            return ""
        message = getattr(choices[0], "message", None)
        return getattr(message, "content", "") or ""
    except Exception as exc:
        logger.error("提取响应内容失败: %s", exc)
        return ""


def extract_openai_response(
    response: Any,
    *,
    elapsed: float,
    logger: Any,
    log_usage: bool = False,
) -> dict[str, Any]:
    """返回统一的内容、用量与耗时结构。"""
    server_time = _response_time(response)
    usage, usage_time = _usage(response, logger, log_usage=log_usage)
    return {
        "content": _content(response, logger),
        "usage": usage,
        "response_time_s": _seconds(server_time if server_time is not None else usage_time, elapsed),
    }
