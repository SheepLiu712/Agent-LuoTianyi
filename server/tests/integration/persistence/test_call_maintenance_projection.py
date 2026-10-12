from uuid import UUID, uuid5

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.domain.agent import MaintenanceCandidate, MaintenanceMemoryType
from src.domain.memory_record import MemoryRecord, MemoryType, MemoryVisibility
from src.infrastructure.persistence.call_maintenance import CallMaintenanceBatch
from src.infrastructure.persistence.call_maintenance_projection import CallMaintenanceProjectionVerifier
from src.infrastructure.persistence.database.redis_buffer import RedisBuffer
from src.infrastructure.persistence.database.services.memory_store import MemoryStore
from src.infrastructure.persistence.database.services.user_store import UserStore
from src.infrastructure.persistence.database.sql_database import Base, MemoryChunkRecord, User

MEMORY_NAMESPACE = UUID("49f9894e-fdc7-5fab-bbb0-3940c0fc02e9")
VECTOR_NAMESPACE = UUID("8ad336a2-bd98-52e4-857e-e0feac29e70a")


class _Document:
    def __init__(self, content, metadata):
        self._content = content
        self._metadata = metadata

    def get_content(self):
        return self._content

    def get_metadata(self):
        return self._metadata


class _Vectors:
    def __init__(self, documents):
        self.documents = documents

    def get_document_by_id(self, ids):
        return [self.documents[item] for item in ids if item in self.documents]


def test_completed_batch_verification_requires_canonical_vector_link_and_profile(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'projection.sqlite'}")
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    redis = RedisBuffer()
    users = UserStore({}, sessions, redis)
    memories = MemoryStore({}, sessions, redis)
    with sessions() as session:
        session.add(User(uuid="owner", username="owner", password="hash", description="profile"))
        session.commit()
    candidate = MaintenanceCandidate(MaintenanceMemoryType.USER_FACT, "stable fact")
    batch = CallMaintenanceBatch(
        maintenance_id="maintenance",
        call_id=UUID("aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"),
        user_id="owner",
        character_id="luotianyi",
        previous_turn_seq=0,
        target_turn_seq=1,
        settlement_input_digest="a" * 64,
        candidates=(candidate,),
        proposed_profile="profile",
        status="completed",
    )
    identity = "maintenance:0"
    record_id = str(uuid5(MEMORY_NAMESPACE, identity))
    vector_id = str(uuid5(VECTOR_NAMESPACE, identity))
    record = MemoryRecord(
        id=record_id,
        owner_character_id="luotianyi",
        subject_user_id="owner",
        memory_type=MemoryType.USER_FACT,
        visibility=MemoryVisibility.PRIVATE,
        source="cognitive_maintenance",
        content=candidate.content,
        metadata={"maintenance_id": "maintenance", "candidate_index": 0},
    )
    assert memories.write_agent_memory_record_if_absent(record)
    memories.link_agent_memory_embeddings(record_id, chunk_texts=[candidate.content], embedding_ids=[vector_id])
    document = _Document(
        candidate.content,
        {
            "user_id": "owner",
            "owner_character_id": "luotianyi",
            "memory_type": candidate.memory_type.value,
            "maintenance_id": "maintenance",
            "candidate_index": 0,
        },
    )
    verifier = CallMaintenanceProjectionVerifier(
        memory_store=memories,
        vector_store=_Vectors({vector_id: document}),
        user_store=users,
    )
    assert verifier.verify_completed_batch(batch)
    with sessions() as session:
        chunk = session.query(MemoryChunkRecord).filter_by(memory_record_id=record_id).one()
        chunk.chunk_text = "wrong chunk"
        session.commit()
    assert not verifier.verify_completed_batch(batch)
    memories.link_agent_memory_embeddings(record_id, chunk_texts=[candidate.content], embedding_ids=["wrong-link"])
    with sessions() as session:
        chunk = session.query(MemoryChunkRecord).filter_by(memory_record_id=record_id, embedding_id=vector_id).one()
        chunk.chunk_text = candidate.content
        session.commit()
    assert verifier.verify_completed_batch(batch)
    users.update_user_description("owner", "different")
    assert not verifier.verify_completed_batch(batch)
    engine.dispose()
