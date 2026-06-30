from fastapi import  HTTPException, Request
from typing import Dict
import time
from collections import deque
from threading import Lock

_RATE_LIMITS = {
    "auth_login": (10, 60),
    "auth_register": (5, 60),
    "auth_auto_login": (10, 60),
    "auth_reset": (3, 300),
}
_rate_limit_lock = Lock()
_rate_limit_store: Dict[str, deque] = {}


def _get_client_key(request: Request, username: str | None) -> str:
    client_ip = request.client.host if request.client else "unknown"
    user = username or "unknown"
    return f"{client_ip}:{user}"


def enforce_rate_limit(request: Request, bucket: str, username: str | None) -> None:
    if bucket not in _RATE_LIMITS:
        return
    limit, window_sec = _RATE_LIMITS[bucket]
    key = f"{bucket}:{_get_client_key(request, username)}"
    now = time.monotonic()
    with _rate_limit_lock:
        timestamps = _rate_limit_store.setdefault(key, deque())
        while timestamps and now - timestamps[0] > window_sec:
            timestamps.popleft()
        if len(timestamps) >= limit:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
        timestamps.append(now)