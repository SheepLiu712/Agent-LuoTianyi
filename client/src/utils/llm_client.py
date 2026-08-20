"""客户端侧 LLM 执行助手。

服务端下发 llm_request（按客户端模型类型）后，客户端使用用户自己的
api-key 直接调用 OpenAI 兼容的 chat/completions 接口，并把结果回传。
委托完全由 type 驱动，代码中不区分 llm/vlm。
"""

import asyncio
import time
from typing import Any, Dict, Optional

import requests

from ..utils.logger import get_logger


logger = get_logger("llm_client")


def fetch_client_model_types(
    server_base_url: str,
    timeout: float = 15.0,
) -> list[Dict[str, Any]]:
    """从服务端获取客户端模型类型字典（type / providers / models[含勾选]）。"""
    url = f"{server_base_url.rstrip('/')}/llm/providers"
    try:
        resp = requests.get(url, timeout=timeout)
    except Exception as exc:
        raise RuntimeError(f"获取客户端模型类型列表失败: {exc}") from exc
    if resp.status_code < 200 or resp.status_code >= 300:
        raise RuntimeError(f"获取客户端模型类型列表失败: HTTP {resp.status_code}")
    data = resp.json()
    types = data.get("types")
    if isinstance(types, list):
        return [t for t in types if isinstance(t, dict)]
    return []


def build_chat_completions_payload(
    *,
    prompt: str,
    model: str,
    params: Optional[Dict[str, Any]] = None,
    enable_thinking: bool = False,
    use_json: bool = False,
    image_base64: Optional[str] = None,
) -> Dict[str, Any]:
    """根据服务端下发的请求构造 chat/completions 请求体。"""
    params = params or {}
    if image_base64:
        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": image_base64, "detail": "auto"},
                    },
                ],
            }
        ]
    else:
        messages = [{"role": "system", "content": prompt}]

    payload: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_tokens": params.get("max_tokens", 4096),
        "temperature": params.get("temperature", 0.7),
        "top_p": params.get("top_p", 0.9),
    }
    # 其余用户参数全量透传（stop、presence_penalty 等），避免静默丢弃
    for key, value in params.items():
        if key not in payload:
            payload[key] = value
    if enable_thinking:
        payload["enable_thinking"] = True
    if use_json:
        payload["response_format"] = {"type": "json_object"}
    return payload


def call_llm_api(
    *,
    url: str,
    api_key: str,
    payload: Dict[str, Any],
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """同步调用 OpenAI 兼容 chat/completions。

    返回 {"content": str, "usage": dict|None, "response_time_s": float}
    """
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    started = time.perf_counter()
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=timeout)
    except Exception as exc:
        raise RuntimeError(f"LLM provider request failed: {exc}") from exc
    elapsed = time.perf_counter() - started

    if resp.status_code < 200 or resp.status_code >= 300:
        detail = resp.text
        try:
            error_data = resp.json().get("error")
            if error_data:
                detail = str(error_data)
        except Exception:
            pass
        raise RuntimeError(f"LLM provider returned HTTP {resp.status_code}: {detail}")

    data = resp.json()
    content = ""
    usage = None
    try:
        if data.get("choices"):
            message = data["choices"][0].get("message", {})
            content = message.get("content") or ""
        usage = data.get("usage")
    except Exception as exc:
        logger.warning(f"Failed to parse LLM provider response: {exc}")

    return {
        "content": content,
        "usage": usage,
        "response_time_s": elapsed,
    }


async def call_llm_api_async(
    *,
    url: str,
    api_key: str,
    payload: Dict[str, Any],
    timeout: float = 120.0,
) -> Dict[str, Any]:
    """异步包装，避免阻塞 WebSocket 接收循环。"""
    return await asyncio.to_thread(
        call_llm_api,
        url=url,
        api_key=api_key,
        payload=payload,
        timeout=timeout,
    )


def probe_llm_config(
    base_url: str,
    api_key: str,
    model: str,
    flags: Optional[Dict[str, Any]] = None,
    params: Optional[Dict[str, Any]] = None,
    timeout: float = 30.0,
) -> None:
    """保存前探测：用所选模型/开关向服务商发一次最小请求，失败抛异常。"""
    flags = flags or {}
    use_json = bool(flags.get("use_json"))
    probe_params = dict(params or {})
    probe_params["max_tokens"] = 8
    probe_params["temperature"] = 0
    body = build_chat_completions_payload(
        prompt='返回 JSON：{"ok": true}' if use_json else "ping",
        model=model,
        params=probe_params,
        enable_thinking=bool(flags.get("enable_thinking")),
        use_json=use_json,
    )
    call_llm_api(
        url=f"{base_url.rstrip('/')}/chat/completions",
        api_key=api_key,
        payload=body,
        timeout=timeout,
    )
