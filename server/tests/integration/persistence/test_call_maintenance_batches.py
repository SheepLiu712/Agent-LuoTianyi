from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import src.domain.agent as d
from src.infrastructure.persistence.call_maintenance import CallMaintenanceBatch, SqlCallMaintenanceBatchRepository
from src.infrastructure.persistence.database.sql_database import Base, _migrate_sqlite_schema


def test_call_maintenance_batch_has_one_durable_winner_and_user_delete(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'batch.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    repository = SqlCallMaintenanceBatchRepository(sessionmaker(bind=engine))
    call_id = uuid4()

    def create(content):
        return repository.create_or_load(
            CallMaintenanceBatch(
                maintenance_id=f"candidate-{content}",
                call_id=call_id,
                user_id="user",
                character_id="luotianyi",
                previous_turn_seq=0,
                target_turn_seq=2,
                settlement_input_digest="a" * 64,
                candidates=(d.MaintenanceCandidate(d.MaintenanceMemoryType.USER_FACT, content),),
                proposed_profile=f"profile-{content}",
                status="frozen",
            )
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        winners = tuple(pool.map(create, ("A", "B")))

    assert winners[0] == winners[1]
    assert (
        repository.load(
            call_id=call_id,
            user_id="user",
            character_id="luotianyi",
            previous_turn_seq=0,
            target_turn_seq=2,
        )
        == winners[0]
    )
    assert repository.mark_completed(winners[0].maintenance_id)
    assert repository.delete_by_user("user") == 1


def test_batch_range_rejects_reuse_for_another_settlement_digest(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'digest-batch.sqlite'}")
    Base.metadata.create_all(engine)
    repository = SqlCallMaintenanceBatchRepository(sessionmaker(bind=engine))
    call_id = uuid4()
    original = CallMaintenanceBatch(
        maintenance_id="winner",
        call_id=call_id,
        user_id="user",
        character_id="luotianyi",
        previous_turn_seq=0,
        target_turn_seq=1,
        settlement_input_digest="a" * 64,
        candidates=(),
        proposed_profile=None,
        status="frozen",
    )
    assert repository.create_or_load(original) == original
    loser = repository.create_or_load(
        CallMaintenanceBatch(
            maintenance_id="loser",
            call_id=call_id,
            user_id="user",
            character_id="luotianyi",
            previous_turn_seq=0,
            target_turn_seq=1,
            settlement_input_digest="b" * 64,
            candidates=(),
            proposed_profile=None,
            status="frozen",
        )
    )
    assert loser.settlement_input_digest == "a" * 64


def _create_legacy_batch_table(engine, *, with_row: bool) -> None:
    with engine.begin() as connection:
        connection.exec_driver_sql("DROP TABLE IF EXISTS call_maintenance_batches")
        connection.exec_driver_sql(
            "CREATE TABLE call_maintenance_batches (maintenance_id VARCHAR PRIMARY KEY, call_id VARCHAR NOT NULL, "
            "user_id VARCHAR NOT NULL, character_id VARCHAR NOT NULL, previous_turn_seq INTEGER NOT NULL, "
            "target_turn_seq INTEGER NOT NULL, candidates TEXT NOT NULL, proposed_profile TEXT, "
            "status VARCHAR NOT NULL, created_at DATETIME NOT NULL, updated_at DATETIME NOT NULL)"
        )
        if with_row:
            connection.exec_driver_sql(
                "INSERT INTO call_maintenance_batches VALUES "
                "('legacy','00000000-0000-0000-0000-000000000001','user','luotianyi',0,1,'[]',NULL,"
                "'frozen','2026-10-11 00:00:00','2026-10-11 00:00:00')"
            )


def test_legacy_batch_schema_migrates_twice_without_fabricating_digest_or_losing_row(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-batch.sqlite'}")
    Base.metadata.create_all(engine)
    _create_legacy_batch_table(engine, with_row=True)

    _migrate_sqlite_schema(engine)
    _migrate_sqlite_schema(engine)

    with engine.connect() as connection:
        columns = {row[1] for row in connection.exec_driver_sql("PRAGMA table_info(call_maintenance_batches)")}
        row = connection.exec_driver_sql(
            "SELECT maintenance_id,candidates,status,settlement_input_digest FROM call_maintenance_batches"
        ).one()
    assert "settlement_input_digest" in columns
    assert tuple(row) == ("legacy", "[]", "frozen", None)
    repository = SqlCallMaintenanceBatchRepository(sessionmaker(bind=engine))
    with pytest.raises(ValueError, match="LEGACY_CALL_MAINTENANCE_DIGEST_UNAVAILABLE"):
        repository.load(
            call_id=UUID("00000000-0000-0000-0000-000000000001"),
            user_id="user",
            character_id="luotianyi",
            previous_turn_seq=0,
            target_turn_seq=1,
        )


def test_empty_legacy_batch_table_accepts_new_strict_batch_after_migration(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy-empty.sqlite'}")
    Base.metadata.create_all(engine)
    _create_legacy_batch_table(engine, with_row=False)
    _migrate_sqlite_schema(engine)
    repository = SqlCallMaintenanceBatchRepository(sessionmaker(bind=engine))
    call_id = uuid4()
    batch = CallMaintenanceBatch(
        maintenance_id="new",
        call_id=call_id,
        user_id="user",
        character_id="luotianyi",
        previous_turn_seq=0,
        target_turn_seq=1,
        settlement_input_digest="c" * 64,
        candidates=(),
        proposed_profile=None,
        status="frozen",
    )
    assert repository.create_or_load(batch) == batch


def test_fresh_batch_contract_rejects_missing_or_invalid_digest():
    with pytest.raises(ValueError, match="SHA-256"):
        CallMaintenanceBatch(
            maintenance_id="bad",
            call_id=uuid4(),
            user_id="user",
            character_id="luotianyi",
            previous_turn_seq=0,
            target_turn_seq=1,
            settlement_input_digest="",
            candidates=(),
            proposed_profile=None,
            status="frozen",
        )
