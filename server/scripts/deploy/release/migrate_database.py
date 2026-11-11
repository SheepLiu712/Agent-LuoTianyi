"""Offline schema 0→1 upgrade. Stop all database writers before invoking."""

import argparse
import importlib.util
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--kind", choices=["main", "songs"], required=True)
    parser.add_argument("--database", type=Path, required=True)
    args = parser.parse_args()
    if not args.database.is_file():
        parser.error("数据库不存在；迁移不会创建替代数据库")
    root = Path(__file__).resolve().parents[3]
    source = "database/sql_database.py" if args.kind == "main" else "song_knowledge.py"
    spec = importlib.util.spec_from_file_location(
        "deployment_database", root / "src/infrastructure/persistence" / source
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if args.kind == "main":
        module.init_sql_db(str(args.database.parent), args.database.name)
    else:
        module.init_song_db({"db_folder": str(args.database.parent), "db_file": args.database.name})
    print("数据库 schema 校验完成；旧库备份保留在数据库旁的 .schema-0-backup-* 文件。")


if __name__ == "__main__":
    main()
