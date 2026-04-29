import argparse
import asyncio
import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
os.chdir(REPO_ROOT)
if str(REPO_ROOT) not in sys.path:
    sys.path.append(str(REPO_ROOT))

from sqlalchemy.orm import Session

from src.database.sql_database import Conversation, User, get_sql_session, init_sql_db
from src.memory.user_profile_updater import UserProfileUpdater
from src.utils.helpers import load_config
from src.utils.llm.prompt_manager import PromptManager


def _chunk_items(items, chunk_size: int):
    for index in range(0, len(items), chunk_size):
        yield items[index : index + chunk_size]


def _format_conversation(conversation: Conversation) -> str:
    timestamp = conversation.timestamp.strftime("%Y-%m-%d %H:%M:%S") if conversation.timestamp else "N/A"
    source = conversation.source or "unknown"
    conv_type = conversation.type or "unknown"
    content = conversation.content or ""
    return f"[{timestamp}] {source}/{conv_type}: {content}"


def _build_history(conversations: list[Conversation], batch_index: int, batch_count: int) -> dict:
    return {
        "summary": f"第 {batch_index}/{batch_count} 组用户对话，共 {len(conversations)} 条。",
        "recent_conversation": [_format_conversation(conversation) for conversation in conversations],
    }


async def _update_one_user(
    session: Session,
    updater: UserProfileUpdater,
    user: User,
    batch_size: int,
) -> bool:
    conversations = (
        session.query(Conversation)
        .filter(Conversation.user_id == user.uuid)
        .order_by(Conversation.timestamp.asc(), Conversation.uuid.asc())
        .all()
    )

    if not conversations:
        print(f"[{user.username}] no conversations, skip")
        return False

    batch_count = (len(conversations) + batch_size - 1) // batch_size
    current_profile = user.description or ""
    updated = False

    print(f"[{user.username}] conversations={len(conversations)}, batches={batch_count}")
    for batch_index, batch in enumerate(_chunk_items(conversations, batch_size), start=1):
        history = _build_history(batch, batch_index, batch_count)
        new_profile = await updater.update_profile(history=history, current_profile=current_profile)
        if not new_profile:
            print(f"[{user.username}] batch {batch_index}/{batch_count}: no update")
            continue

        current_profile = new_profile.strip()
        user.description = current_profile
        session.commit()
        updated = True
        print(f"[{user.username}] batch {batch_index}/{batch_count}: updated")

    if not updated and current_profile != (user.description or ""):
        user.description = current_profile
        session.commit()
        updated = True

    print(f"[{user.username}] final description length={len(current_profile)}")
    return updated


async def main() -> None:
    parser = argparse.ArgumentParser(description="Batch update user descriptions from conversation history.")
    parser.add_argument("--batch-size", type=int, default=200, help="Number of conversations per update batch.")
    parser.add_argument("--username", type=str, default=None, help="Only update a single username.")
    args = parser.parse_args()

    config = load_config("config/config.json", default_config={})
    init_sql_db(config.get("database", {}).get("sql_db_folder", "data/database"), config.get("database", {}).get("sql_db_file", "luotianyi.db"))

    prompt_manager = PromptManager(config.get("prompt_manager", {}))
    updater = UserProfileUpdater(config.get("memory_manager", {}).get("user_profile", {}), prompt_manager)

    session = get_sql_session()
    try:
        query = session.query(User).order_by(User.username.asc())
        if args.username:
            query = query.filter(User.username == args.username)

        users = query.all()
        print(f"Found {len(users)} users to process.")

        for index, user in enumerate(users, start=1):
            print(f"\n[{index}/{len(users)}] processing {user.username}")
            try:
                await _update_one_user(session, updater, user, max(1, args.batch_size))
            except Exception as exc:
                session.rollback()
                print(f"[{user.username}] failed: {exc}")
    finally:
        session.close()


if __name__ == "__main__":
    asyncio.run(main())