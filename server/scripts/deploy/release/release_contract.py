"""Release configuration and database declarations, without importing the application."""

import copy
import json
import re
from pathlib import PurePosixPath
from urllib.parse import urlsplit

SCHEMA = "src/utils/database_schema.json"
TEMPLATE = "config/config.json.template"
CONFIG = "config/config.json"
MIGRATOR = "scripts/deploy/release/migrate_database.py"


def validate_config(value):
    if isinstance(value, list):
        for item in value:
            validate_config(item)
    if not isinstance(value, dict):
        return
    for key, item in value.items():
        if key.lower() in {"api_key", "password", "secret", "token", "cookie", "access_token", "refresh_token"}:
            if item and (not isinstance(item, str) or not re.fullmatch(r"\$[A-Z_][A-Z0-9_]*", item)):
                raise ValueError(f"发布配置中的 {key} 必须使用环境变量引用")
        validate_config(item)


def database_paths(config):
    main = config["database"]
    songs = config["agent_runtime"]["skills"]["knowledge"]["song_database"]
    paths = {}
    for kind, folder, filename in (
        ("main", main["sql_db_folder"], main["sql_db_file"]),
        ("songs", songs["db_folder"], songs["db_file"]),
    ):
        path = PurePosixPath(folder) / filename
        if path.is_absolute() or ".." in path.parts or path.parts[0] != "data" or "\\" in str(path):
            raise ValueError("发布数据库路径必须位于实例 data/ 内")
        paths[kind] = str(path)
    if len(set(paths.values())) != len(paths):
        raise ValueError("不同数据库不能映射到同一文件")
    return paths


def declarations(files):
    config = json.loads(files[CONFIG])
    validate_config(config)
    schema = json.loads(files[SCHEMA])
    if schema["schema_version"] != 1:
        raise ValueError("不支持的数据库契约版本")
    paths = database_paths(config)
    databases = {}
    for kind, requirement in schema["databases"].items():
        if requirement["version"] != 1 or not requirement["tables"]:
            raise ValueError("不支持的数据库目标版本")
        databases[kind] = {**requirement, "path": paths[kind]}
    return {
        "configuration": {"source": CONFIG, "target": CONFIG, "policy": "replace_file_only"},
        "databases": databases,
        "database_migrations": [{"from": 0, "to": 1, "entrypoint": MIGRATOR}],
    }


def effective_config(config, instance):
    """Only deployment identity fields vary between instances of the same package."""
    result = copy.deepcopy(config)
    result["is_debug"] = instance.get("is_debug", result["is_debug"])
    if type(result["is_debug"]) is not bool:
        raise ValueError("实例 is_debug 必须是布尔值")
    key = "debug_port" if result["is_debug"] else "production_port"
    result["server"][key] = urlsplit(instance["health_url"]).port or 80
    return result
