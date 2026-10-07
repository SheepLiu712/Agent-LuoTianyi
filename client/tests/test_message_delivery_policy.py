from src.delivery_policy import (
    MAX_DURABLE_MESSAGE_AGE_SECONDS,
    MAX_DURABLE_RETRY_ATTEMPTS,
    can_retry_durable_message,
    delivery_uncertain_result,
    get_send_retry_delay_seconds,
    is_durable_send_kind,
)


def test_retry_delay_is_exponential_and_capped():
    assert [get_send_retry_delay_seconds(value) for value in (0, 1, 2, 3, 4, 5, 8)] == [
        1.0,
        2.0,
        4.0,
        8.0,
        16.0,
        30.0,
        30.0,
    ]


def test_only_business_messages_are_durable():
    assert all(is_durable_send_kind(kind) for kind in ("text", "image", "proactive"))
    assert not any(
        is_durable_send_kind(kind)
        for kind in ("typing", "touch", "image_selecting", "image_selecting_cancel")
    )


def test_retry_policy_has_attempt_and_total_age_limits():
    enqueued_at = 100.0
    assert can_retry_durable_message(0, enqueued_at, 1.0, now=enqueued_at)
    assert not can_retry_durable_message(
        MAX_DURABLE_RETRY_ATTEMPTS,
        enqueued_at,
        1.0,
        now=enqueued_at,
    )
    assert not can_retry_durable_message(
        0,
        enqueued_at,
        1.0,
        now=enqueued_at + MAX_DURABLE_MESSAGE_AGE_SECONDS - 1.0,
    )


def test_delivery_uncertain_is_terminal_and_keeps_request_id():
    result = delivery_uncertain_result("msg-1", "ack timeout")

    assert result["request_id"] == "msg-1"
    assert result["code"] == "DELIVERY_UNCERTAIN"
    assert result["retryable"] is False
    assert result["drop"] is True
