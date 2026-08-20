from fastapi import HTTPException, Request
import hashlib
import time
from collections import OrderedDict, deque
from threading import Lock

_RATE_LIMITS = {
    "auth_login": (10, 60),
    "auth_register": (5, 60),
    "auth_auto_login": (10, 60),
    "auth_reset": (3, 300),
    "admin_login": (5, 300),
}
_rate_limit_lock = Lock()
_RATE_LIMIT_MAX_KEYS = 4096
_rate_limit_store: "OrderedDict[str, deque[float]]" = OrderedDict()


def _get_client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _subject_digest(subject: str) -> str:
    normalized = subject.strip().casefold().encode("utf-8")
    return hashlib.sha256(normalized).hexdigest()[:24]


def _prune_expired(now: float) -> None:
    for key in list(_rate_limit_store):
        bucket = key.split(":", 1)[0]
        config = _RATE_LIMITS.get(bucket)
        if config is None:
            _rate_limit_store.pop(key, None)
            continue
        _, window_sec = config
        timestamps = _rate_limit_store[key]
        while timestamps and now - timestamps[0] >= window_sec:
            timestamps.popleft()
        if not timestamps:
            _rate_limit_store.pop(key, None)


def _reset_rate_limit_state() -> None:
    """Clear process-local limiter state. Intended for isolated tests."""
    with _rate_limit_lock:
        _rate_limit_store.clear()


def enforce_rate_limit(request: Request, bucket: str, subject: str | None) -> None:
    if bucket not in _RATE_LIMITS:
        return
    limit, window_sec = _RATE_LIMITS[bucket]
    client_ip = _get_client_ip(request)
    keys = [f"{bucket}:ip:{client_ip}"]
    if subject:
        keys.append(f"{bucket}:subject:{_subject_digest(subject)}")
    now = time.monotonic()
    with _rate_limit_lock:
        _prune_expired(now)
        new_key_count = sum(1 for key in keys if key not in _rate_limit_store)
        if len(_rate_limit_store) + new_key_count > _RATE_LIMIT_MAX_KEYS:
            raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")

        states = []
        for key in keys:
            timestamps = _rate_limit_store.get(key)
            if timestamps is None:
                timestamps = deque()
            while timestamps and now - timestamps[0] >= window_sec:
                timestamps.popleft()
            if len(timestamps) >= limit:
                raise HTTPException(status_code=429, detail="请求过于频繁，请稍后再试")
            states.append((key, timestamps))

        for key, timestamps in states:
            timestamps.append(now)
            _rate_limit_store[key] = timestamps
            _rate_limit_store.move_to_end(key)
