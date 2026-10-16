from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.domain.call import CallEndReason, CallOutcome, CallState
from src.infrastructure.persistence.call_sessions import CallSessionRecord, SettlementStatus, SqlCallSessionRepository
from src.infrastructure.persistence.database.sql_database import Base


def _record(*, state, outcome, end_reason, summary, maintenance, now, claimed=True):
    return CallSessionRecord(
        call_id=uuid4(),
        client_request_id=str(uuid4()),
        user_id="user",
        character_id="luotianyi",
        state=state,
        requested_at=now - timedelta(minutes=2),
        created_at=now - timedelta(minutes=2),
        updated_at=now,
        outcome=outcome,
        end_reason=end_reason,
        ended_at=now if state is CallState.ENDED else None,
        active_duration_ms=1,
        summary_status=summary,
        maintenance_status=maintenance,
        settlement_input_digest="d" * 64 if claimed else None,
    )


@pytest.mark.parametrize(
    "state,outcome,end_reason,summary,maintenance,expected",
    [
        (
            CallState.ENDED,
            CallOutcome.CONNECTED,
            CallEndReason.USER_HANGUP,
            SettlementStatus.PENDING,
            SettlementStatus.SUCCEEDED,
            True,
        ),
        (
            CallState.ENDED,
            CallOutcome.CONNECTED,
            CallEndReason.USER_HANGUP,
            SettlementStatus.FAILED,
            SettlementStatus.SUCCEEDED,
            False,
        ),
        (
            CallState.ENDED,
            CallOutcome.CONNECTED,
            CallEndReason.USER_HANGUP,
            SettlementStatus.SUCCEEDED,
            SettlementStatus.PENDING,
            True,
        ),
        (
            CallState.ENDED,
            CallOutcome.CONNECTED,
            CallEndReason.USER_HANGUP,
            SettlementStatus.SUCCEEDED,
            SettlementStatus.FAILED,
            False,
        ),
        (
            CallState.ENDED,
            CallOutcome.CONNECTED,
            CallEndReason.USER_HANGUP,
            SettlementStatus.SUCCEEDED,
            SettlementStatus.SUCCEEDED,
            False,
        ),
        (
            CallState.ENDED,
            CallOutcome.CONNECTED,
            CallEndReason.SYSTEM_FAILURE,
            SettlementStatus.PENDING,
            SettlementStatus.SUCCEEDED,
            True,
        ),
        (
            CallState.ENDED,
            CallOutcome.CONNECTED,
            CallEndReason.SYSTEM_FAILURE,
            SettlementStatus.FAILED,
            SettlementStatus.SUCCEEDED,
            True,
        ),
        (
            CallState.ENDED,
            CallOutcome.CONNECTED,
            CallEndReason.SYSTEM_FAILURE,
            SettlementStatus.SUCCEEDED,
            SettlementStatus.PENDING,
            True,
        ),
        (
            CallState.ENDED,
            CallOutcome.CONNECTED,
            CallEndReason.SYSTEM_FAILURE,
            SettlementStatus.SUCCEEDED,
            SettlementStatus.FAILED,
            False,
        ),
        (
            CallState.ENDED,
            CallOutcome.CANCELLED_BEFORE_ANSWER,
            CallEndReason.USER_HANGUP,
            SettlementStatus.PENDING,
            SettlementStatus.PENDING,
            False,
        ),
        (CallState.ENDING, None, None, SettlementStatus.FAILED, SettlementStatus.FAILED, True),
    ],
)
def test_recovery_candidate_matrix(tmp_path, state, outcome, end_reason, summary, maintenance, expected):
    engine = create_engine(f"sqlite:///{tmp_path / 'candidates.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    record = repository.create_if_absent(
        _record(
            state=state,
            outcome=outcome,
            end_reason=end_reason,
            summary=summary,
            maintenance=maintenance,
            now=now,
        )
    )

    candidates = {item.call_id for item in repository.list_recovery_pending()}

    assert (record.call_id in candidates) is expected
    engine.dispose()


def test_unclaimed_normal_pending_record_remains_recovery_eligible(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'unclaimed.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallSessionRepository(sessionmaker(bind=engine))
    now = datetime(2026, 10, 14, 12, tzinfo=timezone.utc)
    record = repository.create_if_absent(
        _record(
            state=CallState.ENDED,
            outcome=CallOutcome.CONNECTED,
            end_reason=CallEndReason.USER_HANGUP,
            summary=SettlementStatus.PENDING,
            maintenance=SettlementStatus.PENDING,
            now=now,
            claimed=False,
        )
    )

    assert record.call_id in {item.call_id for item in repository.list_recovery_pending()}
    engine.dispose()
