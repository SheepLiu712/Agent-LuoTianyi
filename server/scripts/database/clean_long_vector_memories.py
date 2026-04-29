import argparse
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
os.chdir(REPO_ROOT)
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from src.database.vector_store import get_vector_store, init_vector_store
from src.utils.helpers import load_config


def _iter_batches(items: list[str], batch_size: int):
    for index in range(0, len(items), batch_size):
        yield items[index : index + batch_size]


def main() -> None:
    parser = argparse.ArgumentParser(description="Delete vector_store memories whose text length is greater than a threshold.")
    parser.add_argument("--min-length", type=int, default=40, help="Delete documents with content length greater than this value.")
    parser.add_argument("--dry-run", action="store_true", help="Only print matched documents without deleting them.")
    parser.add_argument("--batch-size", type=int, default=100, help="Delete IDs in batches.")
    args = parser.parse_args()

    config = load_config("config/config.json", default_config={})
    vector_cfg = config.get("database", {}).get("vector_store", {})
    init_vector_store(vector_cfg)
    vector_store = get_vector_store()

    collection = vector_store.collection
    results = collection.get(include=["documents", "metadatas"])

    ids = results.get("ids") or []
    documents = results.get("documents") or []
    metadatas = results.get("metadatas") or []

    matched_ids: list[str] = []
    matched_samples: list[str] = []

    for index, doc_id in enumerate(ids):
        content = documents[index] if index < len(documents) and documents[index] is not None else ""
        if len(content) > args.min_length:
            matched_ids.append(doc_id)
            metadata = metadatas[index] if index < len(metadatas) and metadatas[index] is not None else {}
            matched_samples.append(f"id={doc_id}, len={len(content)}, content={content[:40]}")

    print(f"Found {len(matched_ids)} documents with content length > {args.min_length}.")
    for sample in matched_samples[:20]:
        print(sample)

    if args.dry_run or not matched_ids:
        if args.dry_run:
            print("Dry run enabled, no documents were deleted.")
        return

    deleted_count = 0
    for batch in _iter_batches(matched_ids, max(1, args.batch_size)):
        collection.delete(ids=batch)
        deleted_count += len(batch)

    print(f"Deleted {deleted_count} documents from vector_store.")


if __name__ == "__main__":
    main()