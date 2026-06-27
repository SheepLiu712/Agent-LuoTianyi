import os
import sys
from datetime import datetime


# Ensure valid import paths
cwd = os.getcwd()
if cwd not in sys.path:
    sys.path.append(cwd)

from src.system.database.sql_database import User, get_sql_session, init_sql_db, InviteCode


def _format_datetime(value: datetime | None) -> str:
    if value is None:
        return "N/A"
    return value.strftime("%Y-%m-%d %H:%M:%S")


def main() -> None:
    init_sql_db("data/database", "luotianyi.db")
    session = get_sql_session()
    try:
        invite_codes = session.query(InviteCode).order_by(InviteCode.code.asc()).all()
        for index, invite_code in enumerate(invite_codes, start=1):
            if not invite_code.code.startswith("EDJ"):
                continue
            print(f"\n[{index}] code: {invite_code.code}")
            print(f"created_at: {_format_datetime(invite_code.created_at)}")
            print(f"used_by: {invite_code.user_id or 'N/A'}")
            print(f"used_at: {_format_datetime(invite_code.used_at)}")
    finally:
        session.close()


if __name__ == "__main__":
    main()