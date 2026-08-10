import time


MAX_DURABLE_RETRY_ATTEMPTS = 8
MAX_DURABLE_MESSAGE_AGE_SECONDS = 4 * 60
DURABLE_SEND_KINDS = frozenset({"text", "image", "proactive"})


def get_send_retry_delay_seconds(retry_attempt: int) -> float:
    return float(min(2 ** max(0, retry_attempt), 30))


def is_durable_send_kind(kind: str) -> bool:
    return kind in DURABLE_SEND_KINDS


def can_retry_durable_message(
    retry_attempt: int,
    enqueued_monotonic: float,
    retry_delay: float,
    *,
    now: float | None = None,
) -> bool:
    current = time.monotonic() if now is None else now
    return (
        retry_attempt < MAX_DURABLE_RETRY_ATTEMPTS
        and current - enqueued_monotonic + retry_delay < MAX_DURABLE_MESSAGE_AGE_SECONDS
    )


def delivery_uncertain_result(request_id: str, reason: str) -> dict:
    return {
        "ok": False,
        "request_id": request_id,
        "error": f"[DELIVERY_UNCERTAIN] {reason}",
        "code": "DELIVERY_UNCERTAIN",
        "retryable": False,
        "drop": True,
    }
