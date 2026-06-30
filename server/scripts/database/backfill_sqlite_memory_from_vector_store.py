import argparse
import json
import sqlite3
import sys
import uuid
from datetime import datetime, time
from pathlib import Path
from typing import Any


SERVER_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE_DB = SERVER_ROOT / "data" / "database" / "luotianyi.db"
DEFAULT_VECTOR_STORE = SERVER_ROOT / "data" / "database" / "vector_store"
DEFAULT_COLLECTION = "luotianyi_memory"
BACKFILL_SOURCE = "vector_store_backfill"
LEGACY_MEMORY_TYPE_MAP = {
    "user_memory": "user_fact",
    "event_memory": "interaction_event",
}


def _connect(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=15000")
    return conn


def _parse_datetime(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%Y/%m/%d", "%Y-%m-%dT%H:%M:%S"):
        try:
            parsed = datetime.strptime(text, fmt)
            if fmt in ("%Y-%m-%d", "%Y/%m/%d"):
                parsed = datetime.combine(parsed.date(), time.min)
            return parsed.strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue
    return None


def _read_metadata_value(row: sqlite3.Row) -> Any:
    for key in ("string_value", "int_value", "float_value", "bool_value"):
        value = row[key]
        if value is not None:
            return value
    return None


def _load_vector_documents(vector_store_path: Path) -> list[dict[str, Any]]:
    chroma_db = vector_store_path / "chroma.sqlite3"
    if not chroma_db.exists():
        raise RuntimeError(f"Chroma sqlite database is missing: {chroma_db}")

    conn = _connect(chroma_db)
    try:
        embeddings = {
            row["id"]: {
                "row_id": row["id"],
                "embedding_id": row["embedding_id"],
                "created_at": row["created_at"],
                "metadata": {},
            }
            for row in conn.execute(
                "SELECT id, embedding_id, created_at FROM embeddings ORDER BY id"
            )
        }

        for row in conn.execute(
            """
            SELECT id, key, string_value, int_value, float_value, bool_value
            FROM embedding_metadata
            ORDER BY id
            """
        ):
            item = embeddings.get(row["id"])
            if item is None:
                continue
            item["metadata"][row["key"]] = _read_metadata_value(row)

        documents = []
        for item in embeddings.values():
            metadata = dict(item["metadata"])
            content = str(metadata.pop("chroma:document", "") or "").strip()
            user_id = str(metadata.get("user_id") or "").strip()
            embedding_id = str(item["embedding_id"] or "").strip()
            if not content or not user_id or not embedding_id:
                continue
            documents.append(
                {
                    "embedding_id": embedding_id,
                    "content": content,
                    "user_id": user_id,
                    "created_at": _parse_datetime(item["created_at"]) or datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "metadata": metadata,
                }
            )
        return documents
    finally:
        conn.close()


def _memory_record_id(embedding_id: str) -> str:
    return f"vector_store:{embedding_id}"


def _chunk_id(embedding_id: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, f"luotianyi-vector-store-chunk:{embedding_id}"))


def _to_canonical_memory_type(legacy_type: Any) -> str:
    return LEGACY_MEMORY_TYPE_MAP.get(str(legacy_type or "").strip(), "interaction_event")


def _to_happened_at(metadata: dict[str, Any]) -> str | None:
    legacy_type = str(metadata.get("memory_type") or "").strip()
    if legacy_type != "event_memory":
        return None
    return _parse_datetime(metadata.get("event_date") or metadata.get("timestamp"))


def _backfill_sqlite(
    sqlite_db: Path,
    documents: list[dict[str, Any]],
    *,
    dry_run: bool,
) -> dict[str, int]:
    conn = _connect(sqlite_db)
    try:
        before_records = conn.execute("SELECT COUNT(*) FROM agent_memory_records").fetchone()[0]
        before_chunks = conn.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0]
        existing_mapped = conn.execute(
            """
            SELECT COUNT(*)
            FROM memory_chunks
            WHERE embedding_id IS NOT NULL AND embedding_id != ''
            """
        ).fetchone()[0]

        inserted_or_updated = 0
        if not dry_run:
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("BEGIN")
            try:
                for doc in documents:
                    embedding_id = doc["embedding_id"]
                    record_id = _memory_record_id(embedding_id)
                    chunk_id = _chunk_id(embedding_id)
                    metadata = dict(doc["metadata"])
                    metadata.update(
                        {
                            "backfill_source": BACKFILL_SOURCE,
                            "legacy_vector_id": embedding_id,
                            "legacy_vector_ids": [embedding_id],
                        }
                    )
                    content = doc["content"]
                    created_at = doc["created_at"]

                    conn.execute(
                        "DELETE FROM memory_chunks WHERE embedding_id = ? AND id != ?",
                        (embedding_id, chunk_id),
                    )
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO agent_memory_records (
                            id, owner_character_id, subject_user_id, memory_type,
                            visibility, source, content, summary, importance,
                            confidence, emotional_valence, happened_at, created_at,
                            last_accessed_at, meta_data
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            record_id,
                            str(metadata.get("owner_character_id") or "luotianyi"),
                            doc["user_id"],
                            _to_canonical_memory_type(metadata.get("memory_type")),
                            "private",
                            "chat",
                            content,
                            None,
                            0.5,
                            1.0,
                            None,
                            _to_happened_at(metadata),
                            created_at,
                            None,
                            json.dumps(metadata, ensure_ascii=False),
                        ),
                    )
                    conn.execute(
                        """
                        INSERT OR REPLACE INTO memory_chunks (
                            id, memory_record_id, chunk_text, chunk_type,
                            embedding_id, created_at, meta_data
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            chunk_id,
                            record_id,
                            content,
                            "content",
                            embedding_id,
                            created_at,
                            json.dumps(
                                {
                                    "backfill_source": BACKFILL_SOURCE,
                                    "legacy_memory_type": metadata.get("memory_type"),
                                },
                                ensure_ascii=False,
                            ),
                        ),
                    )
                    inserted_or_updated += 1
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        after_records = conn.execute("SELECT COUNT(*) FROM agent_memory_records").fetchone()[0]
        after_chunks = conn.execute("SELECT COUNT(*) FROM memory_chunks").fetchone()[0]
        mapped_after = conn.execute(
            """
            SELECT COUNT(DISTINCT embedding_id)
            FROM memory_chunks
            WHERE embedding_id IS NOT NULL AND embedding_id != ''
            """
        ).fetchone()[0]
        return {
            "vector_documents": len(documents),
            "before_records": before_records,
            "before_chunks": before_chunks,
            "existing_mapped_chunks": existing_mapped,
            "inserted_or_updated": inserted_or_updated,
            "after_records": after_records,
            "after_chunks": after_chunks,
            "distinct_mapped_embeddings": mapped_after,
        }
    finally:
        conn.close()


def _verify_sqlite_mapping(sqlite_db: Path, documents: list[dict[str, Any]]) -> None:
    conn = _connect(sqlite_db)
    try:
        ids = [doc["embedding_id"] for doc in documents]
        missing = []
        mismatched_content = []
        for doc in documents:
            row = conn.execute(
                """
                SELECT c.chunk_text, r.content
                FROM memory_chunks c
                JOIN agent_memory_records r ON r.id = c.memory_record_id
                WHERE c.embedding_id = ?
                """,
                (doc["embedding_id"],),
            ).fetchone()
            if row is None:
                missing.append(doc["embedding_id"])
            elif row["chunk_text"] != doc["content"] or row["content"] != doc["content"]:
                mismatched_content.append(doc["embedding_id"])

        integrity = conn.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_key_errors = conn.execute("PRAGMA foreign_key_check").fetchall()
        print(f"sqlite_integrity_check={integrity}")
        print(f"sqlite_foreign_key_check_count={len(foreign_key_errors)}")
        print(f"sqlite_missing_vector_mappings={len(missing)}")
        print(f"sqlite_mismatched_vector_contents={len(mismatched_content)}")
        if missing[:5]:
            print(f"first_missing={missing[:5]}")
        if mismatched_content[:5]:
            print(f"first_mismatched={mismatched_content[:5]}")
        if integrity != "ok":
            raise RuntimeError(f"SQLite integrity_check failed: {integrity}")
        if foreign_key_errors:
            raise RuntimeError(f"SQLite foreign_key_check failed: {foreign_key_errors}")
        if missing or mismatched_content:
            raise RuntimeError("SQLite mapping verification failed.")
    finally:
        conn.close()


def _verify_static_vector_retrieval(
    vector_store_path: Path,
    collection_name: str,
    sqlite_db: Path,
) -> None:
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=str(vector_store_path),
        settings=Settings(anonymized_telemetry=False),
    )
    collection = client.get_collection(collection_name)
    sample = collection.get(limit=1, include=["documents", "metadatas", "embeddings"])
    if not sample.get("ids"):
        raise RuntimeError("Vector store is empty; cannot verify retrieval.")

    sample_id = sample["ids"][0]
    sample_embedding = sample["embeddings"][0]
    result = collection.query(
        query_embeddings=[sample_embedding],
        n_results=1,
        include=["documents", "metadatas", "distances"],
    )
    retrieved_id = result["ids"][0][0]
    retrieved_doc = result["documents"][0][0]
    distance = result["distances"][0][0]
    if retrieved_id != sample_id:
        raise RuntimeError(f"Static vector retrieval returned {retrieved_id}, expected {sample_id}")

    conn = _connect(sqlite_db)
    try:
        row = conn.execute(
            """
            SELECT r.id, r.content
            FROM memory_chunks c
            JOIN agent_memory_records r ON r.id = c.memory_record_id
            WHERE c.embedding_id = ?
            """,
            (retrieved_id,),
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Retrieved vector id has no SQLite canonical record: {retrieved_id}")
        if row["content"] != retrieved_doc:
            raise RuntimeError("Retrieved vector content differs from SQLite canonical content.")
        print(
            "static_retrieval_ok "
            f"embedding_id={retrieved_id} memory_record_id={row['id']} distance={distance}"
        )
        print(f"static_retrieval_content={retrieved_doc[:120]}")
    finally:
        conn.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Backfill canonical SQLite memory rows from Chroma vector_store documents."
    )
    parser.add_argument("--sqlite-db", type=Path, default=DEFAULT_SQLITE_DB)
    parser.add_argument("--vector-store", type=Path, default=DEFAULT_VECTOR_STORE)
    parser.add_argument("--collection", default=DEFAULT_COLLECTION)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    sqlite_db = args.sqlite_db.resolve()
    vector_store = args.vector_store.resolve()

    if not sqlite_db.exists():
        raise RuntimeError(f"SQLite database is missing: {sqlite_db}")
    if not vector_store.exists():
        raise RuntimeError(f"Vector store directory is missing: {vector_store}")

    documents = _load_vector_documents(vector_store)
    print(f"loaded_vector_documents={len(documents)}")
    stats = _backfill_sqlite(sqlite_db, documents, dry_run=args.dry_run)
    for key, value in stats.items():
        print(f"{key}={value}")

    if args.dry_run:
        print("Dry-run complete; no SQLite rows were modified.")
        return

    _verify_sqlite_mapping(sqlite_db, documents)
    _verify_static_vector_retrieval(vector_store, args.collection, sqlite_db)
    print("Backfill completed and verified.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise
