"""
Migration Script: Multi-Key Memory Format
==========================================
遍历 ChromaDB 中所有旧格式记忆，使用 LLM 为每条记忆生成多个查询 key，
然后以新格式（keys + value + value_id）重新写入。

用法:
    python scripts/migrate_multi_key.py                    # 执行迁移
    python scripts/migrate_multi_key.py --dry-run           # 只预览，不修改
    python scripts/migrate_multi_key.py --batch-size 20     # 每批 20 条
"""

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

# Ensure src is importable
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
if project_root not in sys.path:
    sys.path.insert(0, project_root)

from uuid import uuid4
from src.utils.logger import get_logger
from src.utils.llm.llm_api_interface import LLMAPIFactory
from src.database.vector_store import ChromaVectorStore, Document

logger = get_logger("MigrateMultiKey")

# Prompt for generating keys from old memory text
GENERATE_KEYS_PROMPT = """你是一个记忆 key 生成助手。请为以下记忆文本生成多个查询 key，每个 key 可以从不同角度帮助检索到这个记忆。

## 要求
- 至少生成 2 个 key，最多 5 个 key
- key 可以是问句形式（如"洛天依喜欢吃什么？"）或关键词（如"小笼包"）
- key 应该覆盖不同的查询意图和措辞
- 直接返回 JSON 数组，不要包含其他内容

## 示例
记忆：洛天依喜欢吃小笼包
输出：["洛天依喜欢吃什么？", "洛天依喜欢小笼包吗？", "小笼包", "洛天依的饮食偏好"]

## 记忆
{memory_text}

## 输出
"""


class MigrationPipeline:
    """旧→新格式迁移管道。"""

    def __init__(self, config_path: str):
        self.config = self._load_config(config_path)
        # Direct LLM client — no prompt template needed for the simple generate_keys prompt
        llm_config = (
            self.config.get("memory_manager", {})
            .get("memory_writer", {})
            .get("llm_module", {})
            .get("llm", {
                "api_type": "openai",
                "model": "qwen3.5-plus",
                "api_key": "$QWEN_API_KEY",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
            })
        )
        self.llm_client = LLMAPIFactory.create_interface(llm_config)
        vector_store_config = self.config.get("database", {}).get("vector_store", {})
        if not vector_store_config:
            vector_store_config = {
                "vector_store_path": "data/database/vector_store",
                "collection_name": "luotianyi_memory",
            }
        self.vector_store = ChromaVectorStore(vector_store_config)

    def _load_config(self, config_path: str) -> Dict[str, Any]:
        with open(config_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def scan_old_documents(self) -> List[Dict[str, Any]]:
        """找出所有没有 value_id 的旧格式文档（待迁移）。"""
        all_docs = self.vector_store.get_documents({})  # 获取全部
        old_docs = []
        for doc in all_docs:
            meta = doc.get_metadata() if hasattr(doc, "get_metadata") else {}
            if not meta.get("value_id"):
                old_docs.append({
                    "id": getattr(doc, "id", ""),
                    "content": doc.get_content() if hasattr(doc, "get_content") else "",
                    "metadata": meta,
                    "doc": doc,
                })
        return old_docs

    def group_by_user_and_type(self, old_docs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        """按 user_id + memory_type 分组。"""
        groups: Dict[str, List[Dict[str, Any]]] = {}
        for item in old_docs:
            meta = item["metadata"]
            uid = meta.get("user_id", "__unknown__")
            mtype = meta.get("memory_type", "user_memory")
            key = f"{uid}|{mtype}"
            groups.setdefault(key, []).append(item)
        return groups

    async def generate_keys(self, memory_text: str) -> List[str]:
        """调用 LLM 为单条记忆生成 key 列表。"""
        prompt = GENERATE_KEYS_PROMPT.format(memory_text=memory_text)
        try:
            response = await self.llm_client.generate_response(prompt, use_json=False)
            raw = (response or "").strip()
            if raw.startswith("```"):
                lines = raw.splitlines()
                if lines and lines[0].startswith("```"):
                    lines = lines[1:]
                if lines and lines[-1].strip() == "```":
                    lines = lines[:-1]
                raw = "\n".join(lines).strip()
            keys = json.loads(raw)
            if isinstance(keys, list) and len(keys) > 0:
                return [str(k).strip() for k in keys if str(k).strip()]
        except Exception as e:
            logger.warning(f"Failed to generate keys for '{memory_text[:30]}': {e}")
        # Fallback: use content as sole key
        return [memory_text]

    async def migrate_group(
        self,
        group_key: str,
        items: List[Dict[str, Any]],
        dry_run: bool = False,
    ) -> int:
        """迁移单个分组（同一 user_id + memory_type）的旧文档。"""
        migrated = 0
        user_id, memory_type = group_key.split("|", 1)
        timestamp = time.strftime("%Y-%m-%d")

        for item in items:
            old_id = item["id"]
            content = item["content"]
            meta = item["metadata"]

            # Determine the value text
            value = content

            # Generate keys
            keys = await self.generate_keys(value)

            # Build new documents
            value_id = str(uuid4())
            docs = []
            for key in keys:
                new_meta = dict(meta)
                new_meta.update({
                    "source": new_meta.get("source", "migration"),
                    "timestamp": new_meta.get("timestamp", timestamp),
                    "event_date": new_meta.get("event_date", timestamp),
                    "value": value,
                    "value_id": value_id,
                    "keys": keys,
                })
                docs.append(Document(content=key, metadata=new_meta))

            if dry_run:
                logger.info(
                    f"[DRY-RUN] Would migrate {old_id[:12]} → {len(docs)} key-docs, "
                    f"value='{value[:40]}', keys={keys[:3]}..."
                )
            else:
                # Write new docs
                self.vector_store.add_documents(docs)
                # Delete old doc
                self.vector_store.delete_documents([old_id])
                logger.info(f"Migrated {old_id[:12]} → {len(docs)} key-docs")

            migrated += 1

        return migrated

    async def run(self, dry_run: bool = False, batch_size: int = 10) -> None:
        """执行完整迁移流程。"""
        logger.info(
            f"Starting multi-key migration (dry_run={dry_run}, batch_size={batch_size})"
        )

        old_docs = self.scan_old_documents()
        logger.info(f"Found {len(old_docs)} old-format documents to migrate")

        if not old_docs:
            logger.info("Nothing to migrate!")
            return

        groups = self.group_by_user_and_type(old_docs)
        logger.info(f"Grouped into {len(groups)} user+type groups")

        total = 0
        for group_key, items in groups.items():
            # Process in batches
            for i in range(0, len(items), batch_size):
                batch = items[i : i + batch_size]
                count = await self.migrate_group(group_key, batch, dry_run=dry_run)
                total += count
                logger.info(
                    f"Progress: {total}/{len(old_docs)} "
                    f"({group_key}: batch {i // batch_size + 1})"
                )

        logger.info(
            f"Migration {'[DRY-RUN] ' if dry_run else ''}complete! "
            f"Processed {total} old documents."
        )


async def main():
    parser = argparse.ArgumentParser(description="Migrate old memories to multi-key format")
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to config.json (default: config/config.json)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview only, don't modify anything",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=10,
        help="Batch size per LLM call (default: 10)",
    )
    args = parser.parse_args()

    pipeline = MigrationPipeline(args.config)
    await pipeline.run(dry_run=args.dry_run, batch_size=args.batch_size)


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
