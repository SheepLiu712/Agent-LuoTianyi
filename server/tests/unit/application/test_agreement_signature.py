"""协议签署记录与签署时间：UTC+8、秒精度、幂等写入与边界校验。"""

from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.application.user.agreement_service import (
    AgreementService,
    AgreementTimeError,
    agreement_now,
    first_signed_at,
    format_agreement_time,
    parse_agreement_time,
    record_signature,
    validate_signature_time,
)
from src.infrastructure.persistence.database.sql_database import AgreementVersion, Base

UTC8 = timezone(timedelta(hours=8))


@pytest.fixture
def session():
    engine = create_engine("sqlite://")
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine)()
    session.add(
        AgreementVersion(
            version="terms-2026-10-v1",
            title="用户协议",
            format="agreement.richtext.v1",
            content_json="[]",
            content_sha256="0" * 64,
            created_at="2026-10-10T14:30:25+08:00",
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def test_format_agreement_time_drops_microseconds_and_keeps_offset():
    moment = datetime(2026, 10, 10, 14, 30, 25, 987654, tzinfo=UTC8)

    assert format_agreement_time(moment) == "2026-10-10T14:30:25+08:00"


def test_format_agreement_time_converts_other_offsets_to_utc8():
    moment = datetime(2026, 10, 10, 6, 30, 25, tzinfo=timezone.utc)

    assert format_agreement_time(moment) == "2026-10-10T14:30:25+08:00"


def test_format_agreement_time_rejects_naive_datetime():
    with pytest.raises(AgreementTimeError):
        format_agreement_time(datetime(2026, 10, 10, 14, 30, 25))


def test_agreement_now_uses_injected_clock_and_requires_timezone():
    fixed = datetime(2026, 10, 10, 14, 30, 25, 500000, tzinfo=UTC8)

    assert format_agreement_time(agreement_now(lambda: fixed)) == "2026-10-10T14:30:25+08:00"

    with pytest.raises(AgreementTimeError):
        agreement_now(lambda: datetime(2026, 10, 10, 14, 30, 25))


def test_agreement_now_defaults_to_utc8_without_injection():
    moment = agreement_now()

    assert moment.utcoffset() == timedelta(hours=8)


@pytest.mark.parametrize(
    "value",
    [
        "2026-10-10T14:30:25.987+08:00",  # 带小数秒
        "2026-10-10T14:30:25",  # 无偏移
        "2026-10-10T06:30:25+00:00",  # 偏移不是 +08:00
        "not-a-time",
        "",
    ],
)
def test_parse_agreement_time_rejects_non_canonical_values(value):
    with pytest.raises(AgreementTimeError):
        parse_agreement_time(value)


def test_parse_agreement_time_accepts_canonical_value():
    parsed = parse_agreement_time("2026-10-10T14:30:25+08:00")

    assert parsed.year == 2026 and parsed.utcoffset() == timedelta(hours=8)


def test_validate_signature_time_rejects_future_value():
    now = datetime(2026, 10, 10, 14, 30, 25, tzinfo=UTC8)

    assert validate_signature_time("2026-10-10T14:30:25+08:00", now) == "2026-10-10T14:30:25+08:00"
    with pytest.raises(AgreementTimeError):
        validate_signature_time("2026-10-10T14:30:26+08:00", now)


def test_record_signature_is_idempotent_and_keeps_first_time(session):
    assert first_signed_at(session, "user-1", "terms-2026-10-v1") is None

    stored, created = record_signature(
        session, user_uuid="user-1", agreement_version="terms-2026-10-v1", accepted_at="2026-10-10T14:30:25+08:00"
    )
    session.commit()
    assert (stored, created) == ("2026-10-10T14:30:25+08:00", True)

    stored_again, created_again = record_signature(
        session, user_uuid="user-1", agreement_version="terms-2026-10-v1", accepted_at="2026-10-11T09:00:00+08:00"
    )
    session.commit()

    assert created_again is False
    assert stored_again == "2026-10-10T14:30:25+08:00"
    assert first_signed_at(session, "user-1", "terms-2026-10-v1") == "2026-10-10T14:30:25+08:00"


def test_signatures_are_per_user_and_per_version(session):
    record_signature(
        session, user_uuid="user-1", agreement_version="terms-2026-10-v1", accepted_at="2026-10-10T14:30:25+08:00"
    )
    record_signature(
        session, user_uuid="user-2", agreement_version="terms-2026-10-v1", accepted_at="2026-10-10T15:00:00+08:00"
    )
    session.commit()

    assert first_signed_at(session, "user-2", "terms-2026-10-v1") == "2026-10-10T15:00:00+08:00"
    assert first_signed_at(session, "user-1", "terms-2026-10-v2") is None


def test_agreement_service_reports_current_version():
    service = AgreementService("terms-2026-10-v1", {})

    assert service.current_version == "terms-2026-10-v1"
    assert service.is_current("terms-2026-10-v1") is True
    assert service.is_current("terms-2026-10-v0") is False
    assert service.is_current(None) is False
