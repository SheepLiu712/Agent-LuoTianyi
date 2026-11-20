"""Durable privacy-allowlisted frozen results for call cognitive maintenance."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from src.domain.agent import MaintenanceCandidate, MaintenanceMemoryType
from src.infrastructure.persistence.database.sql_database import CallMaintenanceBatch as BatchRow
from src.infrastructure.persistence.database.sql_writer import run_sql_write


@dataclass(frozen=True, slots=True)
class CallMaintenanceBatch:
    maintenance_id: str
    call_id: UUID
    user_id: str
    character_id: str
    previous_turn_seq: int
    target_turn_seq: int
    settlement_input_digest: str
    candidates: tuple[MaintenanceCandidate, ...]
    proposed_profile: str | None
    status: str

    def __post_init__(self) -> None:
        if len(self.settlement_input_digest) != 64 or any(
            character not in "0123456789abcdef" for character in self.settlement_input_digest
        ):
            raise ValueError("settlement_input_digest must be a lowercase SHA-256 hex digest")


class SqlCallMaintenanceBatchRepository:
    def __init__(self, session_factory) -> None:
        self._session_factory = session_factory

    def load(self, *, call_id, user_id, character_id, previous_turn_seq, target_turn_seq):
        db = self._session_factory()
        try:
            row = self._query(db, call_id, user_id, character_id, previous_turn_seq, target_turn_seq)
            return self._contract(row) if row is not None else None
        finally:
            db.close()

    def create_or_load(self, batch: CallMaintenanceBatch) -> CallMaintenanceBatch:
        if not isinstance(batch, CallMaintenanceBatch):
            raise TypeError("batch must be CallMaintenanceBatch")
        db = self._session_factory()
        try:

            def write():
                existing = self._query(
                    db,
                    batch.call_id,
                    batch.user_id,
                    batch.character_id,
                    batch.previous_turn_seq,
                    batch.target_turn_seq,
                )
                if existing is not None:
                    return existing
                row = BatchRow(
                    maintenance_id=batch.maintenance_id,
                    call_id=str(batch.call_id),
                    user_id=batch.user_id,
                    character_id=batch.character_id,
                    previous_turn_seq=batch.previous_turn_seq,
                    target_turn_seq=batch.target_turn_seq,
                    settlement_input_digest=batch.settlement_input_digest,
                    candidates=self._encode_candidates(batch.candidates),
                    proposed_profile=batch.proposed_profile,
                    status="frozen",
                    created_at=datetime.now(),
                    updated_at=datetime.now(),
                )
                db.add(row)
                db.commit()
                return row

            return self._contract(run_sql_write(write))
        except IntegrityError:
            db.rollback()
            winner = self._query(
                db,
                batch.call_id,
                batch.user_id,
                batch.character_id,
                batch.previous_turn_seq,
                batch.target_turn_seq,
            )
            if winner is None:
                raise
            return self._contract(winner)
        finally:
            db.close()

    def mark_completed(self, maintenance_id: str) -> bool:
        db = self._session_factory()
        try:

            def write():
                row = db.query(BatchRow).filter(BatchRow.maintenance_id == maintenance_id).first()
                if row is None:
                    return False
                row.status = "completed"
                row.updated_at = datetime.now()
                db.commit()
                return True

            return run_sql_write(write)
        finally:
            db.close()

    def list_for_call(self, *, call_id, user_id, character_id) -> tuple[CallMaintenanceBatch, ...]:
        db = self._session_factory()
        try:
            rows = (
                db.query(BatchRow)
                .filter_by(call_id=str(call_id), user_id=user_id, character_id=character_id)
                .order_by(BatchRow.previous_turn_seq, BatchRow.target_turn_seq)
                .all()
            )
            return tuple(self._contract(row) for row in rows)
        finally:
            db.close()

    def delete_by_user(self, user_id: str) -> int:
        db = self._session_factory()
        try:
            return run_sql_write(lambda: self._delete(db, user_id))
        finally:
            db.close()

    @staticmethod
    def _delete(db, user_id):
        count = db.query(BatchRow).filter(BatchRow.user_id == user_id).delete(synchronize_session=False)
        db.commit()
        return count

    @staticmethod
    def _query(db, call_id, user_id, character_id, previous_turn_seq, target_turn_seq):
        return (
            db.query(BatchRow)
            .filter_by(
                call_id=str(call_id),
                user_id=user_id,
                character_id=character_id,
                previous_turn_seq=previous_turn_seq,
                target_turn_seq=target_turn_seq,
            )
            .first()
        )

    @staticmethod
    def _encode_candidates(candidates):
        return json.dumps(
            [
                {"candidate_index": index, "memory_type": item.memory_type.value, "content": item.content}
                for index, item in enumerate(candidates)
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )

    @staticmethod
    def _contract(row):
        if row.settlement_input_digest is None:
            raise ValueError("LEGACY_CALL_MAINTENANCE_DIGEST_UNAVAILABLE")
        payload = json.loads(row.candidates)
        candidates = tuple(
            MaintenanceCandidate(MaintenanceMemoryType(item["memory_type"]), item["content"])
            for item in sorted(payload, key=lambda item: item["candidate_index"])
        )
        return CallMaintenanceBatch(
            maintenance_id=row.maintenance_id,
            call_id=UUID(row.call_id),
            user_id=row.user_id,
            character_id=row.character_id,
            previous_turn_seq=row.previous_turn_seq,
            target_turn_seq=row.target_turn_seq,
            settlement_input_digest=row.settlement_input_digest,
            candidates=candidates,
            proposed_profile=row.proposed_profile,
            status=row.status,
        )
