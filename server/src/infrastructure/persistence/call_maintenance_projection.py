"""Verification of durable projections produced by a completed call maintenance batch."""

from __future__ import annotations

from uuid import UUID, uuid5

_MAINTENANCE_MEMORY_NAMESPACE = UUID("49f9894e-fdc7-5fab-bbb0-3940c0fc02e9")
_MAINTENANCE_VECTOR_NAMESPACE = UUID("8ad336a2-bd98-52e4-857e-e0feac29e70a")


class CallMaintenanceProjectionVerifier:
    """Verify canonical memory, vector, link, and profile projections without repairing them."""

    def __init__(self, *, memory_store, vector_store, user_store) -> None:
        self._memories = memory_store
        self._vectors = vector_store
        self._users = user_store

    def verify_completed_batch(self, batch) -> bool:
        for index, candidate in enumerate(batch.candidates):
            identity = f"{batch.maintenance_id}:{index}"
            record_id = str(uuid5(_MAINTENANCE_MEMORY_NAMESPACE, identity))
            vector_id = str(uuid5(_MAINTENANCE_VECTOR_NAMESPACE, identity))
            record = self._memories.get_agent_memory_record(record_id)
            if record is None or not self._memory_matches(record, batch, index, candidate):
                return False
            if not self._memories.agent_memory_record_has_embedding(record_id, vector_id, candidate.content):
                return False
            documents = self._vectors.get_document_by_id([vector_id])
            if len(documents) != 1 or not self._vector_matches(documents[0], batch, index, candidate):
                return False
        if batch.proposed_profile is not None:
            return self._users.get_user_description(batch.user_id) == batch.proposed_profile
        return True

    @staticmethod
    def _memory_matches(record, batch, index, candidate) -> bool:
        metadata = dict(record.metadata or {})
        return (
            record.owner_character_id == batch.character_id
            and record.subject_user_id == batch.user_id
            and record.memory_type.value == candidate.memory_type.value
            and record.visibility.value == "private"
            and record.source == "cognitive_maintenance"
            and record.content == candidate.content
            and metadata.get("maintenance_id") == batch.maintenance_id
            and metadata.get("candidate_index") == index
        )

    @staticmethod
    def _vector_matches(document, batch, index, candidate) -> bool:
        metadata = document.get_metadata()
        return (
            document.get_content() == candidate.content
            and metadata.get("user_id") == batch.user_id
            and metadata.get("owner_character_id") == batch.character_id
            and metadata.get("memory_type") == candidate.memory_type.value
            and metadata.get("maintenance_id") == batch.maintenance_id
            and metadata.get("candidate_index") == index
        )
