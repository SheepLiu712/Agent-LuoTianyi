"""本地 JSON 文件读写工具：整份读取、损坏备份、临时文件原子替换。"""

import json
import os
import shutil

from ..utils.logger import get_logger


logger = get_logger("storage")


def temp_path(filename: str) -> str:
    """返回 client 根目录 temp 下的文件路径，并确保目录存在。"""
    cwd = os.getcwd()  # root client directory
    temp_dir = os.path.join(cwd, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    return os.path.join(temp_dir, filename)


def _backup_corrupt_file(path: str) -> None:
    """损坏文件首次出现时保留一份 .bak，避免后续重写时数据被静默抹掉。"""
    backup = f"{path}.bak"
    try:
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
            logger.warning(f"Corrupted file backed up to {backup}")
    except Exception as exc:
        logger.error(f"Failed to back up corrupted file {path}: {exc}")


def read_json_file(path: str) -> dict:
    """读取 JSON 文件；文件缺失返回空字典，损坏时先备份再返回空字典。"""
    if not os.path.exists(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            raise ValueError(f"{path} is not a JSON object")
        return data
    except Exception as exc:
        logger.error(f"Error loading JSON data from {path}: {exc}")
        _backup_corrupt_file(path)
    return {}


def atomic_write_json(path: str, data: dict) -> None:
    """先写临时文件再原子替换，避免写一半损坏目标文件。"""
    tmp_file = f"{path}.tmp"
    with open(tmp_file, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp_file, path)
