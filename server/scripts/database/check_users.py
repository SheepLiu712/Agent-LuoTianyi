import os
import sys
from datetime import datetime


# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.database.sql_database import User, get_sql_session, init_sql_db


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    init_sql_db("data/database", "luotianyi.db")
    session = get_sql_session()
    try:
        users = session.query(User).order_by(User.username.asc()).all()
        print(f"Found {len(users)} users.")
        for index, user in enumerate(users, start=1):
            print(f"\n[{index}] username: {user.username}")
            print(f"last_login: {_format_datetime(user.last_login)}")
            print(f"description: {user.description or ''}")
            print(f"all_memory_count: {user.all_memory_count if user.all_memory_count is not None else 0}")
    finally:
        session.close()


if __name__ == "__main__":
    main()