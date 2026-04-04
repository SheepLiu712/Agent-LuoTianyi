import os
import sys
from getpass import getpass

# Ensure project root is importable
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.database import database_service
from src.database.sql_database import User, Conversation, get_sql_session
from src.database.vector_store import get_vector_store, VectorStore
from src.database.redis_buffer import get_redis_buffer
from src.utils.helpers import load_config


def _init_databases() -> None:
    config = load_config("config/config.json", default_config={})
    db_cfg = config.get("database", {})
    if db_cfg:
        database_service.init_all_databases(db_cfg)
    else:
        # Fallback for extremely minimal environments
        from src.database.sql_database import init_sql_db

        init_sql_db("data/database", "luotianyi.db")


def _authenticate(session, username: str, password: str) -> User | None:
    return session.query(User).filter(User.username == username, User.password == password).first()


def _update_nickname(session, redis_client, user: User) -> None:
    new_nickname = input("请输入新的昵称：").strip()
    if not new_nickname:
        print("昵称不能为空，已取消。")
        return

    user.nickname = new_nickname
    session.commit()

    # 同步更新内存缓存
    redis_client.setex(f"user_nickname:{user.uuid}", 3600, new_nickname)
    print("昵称更新成功。")


def _update_description(session, redis_client, user: User) -> None:
    print("请输入新的用户画像（直接回车结束输入）：")
    lines = []
    while True:
        line = input()
        if line == "":
            break
        lines.append(line)

    new_description = "\n".join(lines).strip()
    if not new_description:
        print("用户画像不能为空，已取消。")
        return

    user.description = new_description
    session.commit()

    # 同步更新内存缓存
    redis_client.setex(f"user_description:{user.uuid}", 3600, new_description)
    print("用户画像更新成功。")


def _delete_all_conversations(session, redis_client, user: User) -> None:
    confirm = input("确认删除该用户的所有历史对话？输入 YES 确认：").strip()
    if confirm != "YES":
        print("已取消删除。")
        return

    deleted = session.query(Conversation).filter(Conversation.user_id == user.uuid).delete(synchronize_session=False)

    # 历史对话被清空后，相关计数和上下文总结也应重置
    user.context_memory_count = 0
    user.all_memory_count = 0
    user.context_summary = ""

    session.commit()

    # 清理内存缓存中的上下文
    redis_client.delete(f"user_context:{user.uuid}")
    print(f"已删除 {deleted} 条历史对话，并重置上下文计数与总结。")

def _delete_all_vector_records(vector_store: VectorStore, user: User) -> None:
    confirm = input("确认删除该用户的所有向量数据库记录？输入 YES 确认：").strip()
    if confirm != "YES":
        print("已取消删除。")
        return

    deleted_count = vector_store.delete_user_records(user.uuid)
    print(f"已删除 {deleted_count} 条向量数据库记录。")

def _reset_user_profile(session, redis_client, user: User) -> None:
    confirm = input("确认重置用户画像为默认值？输入 YES 确认：").strip()
    if confirm != "YES":
        print("已取消重置。")
        return

    user.description = "新认识的朋友，还需要了解。"
    session.commit()

def _reset_user(session, redis_client, vector_store, user: User) -> None:
    confirm = input("确认完全重置用户（删除所有对话、向量记录，并重置画像）？输入 YES 确认：").strip()
    if confirm != "YES":
        print("已取消重置。")
        return

    # 删除历史对话
    deleted_conversations = session.query(Conversation).filter(Conversation.user_id == user.uuid).delete(synchronize_session=False)

    # 删除向量数据库记录
    deleted_vector_records = vector_store.delete_user_records(user.uuid)

    # 重置用户画像
    user.description = "新认识的朋友，还需要了解。"
    user.context_memory_count = 0
    user.all_memory_count = 0
    user.context_summary = ""

    session.commit()

    # 清理内存缓存中的上下文
    redis_client.delete(f"user_context:{user.uuid}")

    print(f"已完全重置用户：删除 {deleted_conversations} 条历史对话，{deleted_vector_records} 条向量记录，并重置用户画像。")


def _print_menu() -> None:
    print("\n请选择操作：")
    print("1. 修改用户昵称")
    print("2. 修改用户画像")
    print("3. 删除所有历史对话")
    print("4. 删除所有向量数据库记录")
    print("5. 重置用户画像为默认值")
    print("6. 完全重置用户（删除所有对话、向量记录，并重置画像）")
    print("0. 退出")


def main() -> None:
    _init_databases()

    session = get_sql_session()
    redis_client = get_redis_buffer()
    vector_store = get_vector_store()
    try:
        username = input("请输入用户名：").strip()
        password = getpass("请输入密码：").strip()

        user = _authenticate(session, username, password)
        if not user:
            print("用户名或密码错误。")
            return

        print(f"登录成功，当前用户：{user.username} (uuid={user.uuid})")

        while True:
            _print_menu()
            choice = input("输入选项编号：").strip()

            if choice == "1":
                _update_nickname(session, redis_client, user)
            elif choice == "2":
                _update_description(session, redis_client, user)
            elif choice == "3":
                _delete_all_conversations(session, redis_client, user)
            elif choice == "4":
                _delete_all_vector_records(vector_store, user)
            elif choice == "5":
                _reset_user_profile(session, redis_client, user)
            elif choice == "6":
                _reset_user(session, redis_client, vector_store, user)
            elif choice == "0":
                print("已退出。")
                return
            else:
                print("无效选项，请重新输入。")
    finally:
        session.close()


if __name__ == "__main__":
    main()
