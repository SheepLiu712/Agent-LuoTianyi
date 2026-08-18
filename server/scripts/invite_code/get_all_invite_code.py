"""Export invite-code usage and associated users to a UTF-8 text file."""

from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path


SERVER_ROOT = Path(__file__).resolve().parents[2]
if str(SERVER_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVER_ROOT))

from src.system.database.sql_database import (  # noqa: E402
    InviteCode,
    User,
    get_sql_session,
    init_sql_db,
)


DATABASE_FOLDER = SERVER_ROOT / "data" / "database"
DATABASE_FILE = "luotianyi.db"
DEFAULT_OUTPUT = DATABASE_FOLDER / "invite_code_usage.txt"


def format_datetime(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S") if value else "-"


def build_report(rows: list[tuple[InviteCode, str | None, str | None]]) -> str:
    lines = [
        "邀请码使用情况",
        f"生成时间：{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"邀请码总数：{len(rows)}",
        "",
    ]

    for index, (invite_code, username, nickname) in enumerate(rows, start=1):
        if invite_code.is_used:
            usage_status = "已使用"
            if username or nickname or invite_code.user_id:
                user_info = (
                    f"用户名：{username or '-'}；"
                    f"昵称：{nickname or '-'}；"
                    f"用户 UUID：{invite_code.user_id or '-'}"
                )
            else:
                user_info = "关联用户：不存在"
        else:
            usage_status = "未使用"
            user_info = "关联用户：-"

        disabled_status = "已禁用" if invite_code.disabled else "可用"
        lines.extend(
            [
                f"[{index}] 邀请码：{invite_code.code}",
                f"使用状态：{usage_status}",
                f"禁用状态：{disabled_status}",
                f"创建时间：{format_datetime(invite_code.created_at)}",
                f"使用时间：{format_datetime(invite_code.used_at)}",
                user_info,
                "",
            ]
        )

    return "\n".join(lines)


def export_invite_code_usage(output_path: Path) -> tuple[int, int]:
    init_sql_db(str(DATABASE_FOLDER), DATABASE_FILE)
    session = get_sql_session()
    try:
        rows = (
            session.query(InviteCode, User.username, User.nickname)
            .outerjoin(User, InviteCode.user_id == User.uuid)
            .order_by(InviteCode.created_at.asc(), InviteCode.code.asc())
            .all()
        )
        report = build_report(rows)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        used_count = sum(1 for invite_code, _, _ in rows if invite_code.is_used)
        return len(rows), used_count
    finally:
        session.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="将所有邀请码的使用情况导出到 TXT 文件。")
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
        help=f"输出文件路径，默认：{DEFAULT_OUTPUT}",
    )
    args = parser.parse_args()

    total_count, used_count = export_invite_code_usage(args.output)
    print(f"已写入：{args.output}")
    print(f"邀请码总数：{total_count}，已使用：{used_count}，未使用：{total_count - used_count}")


if __name__ == "__main__":
    main()
