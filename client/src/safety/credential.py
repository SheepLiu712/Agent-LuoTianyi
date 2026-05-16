from ..utils.logger import get_logger
import os
import json
from typing import Tuple, Optional


logger = get_logger("credential")

def get_credential_path():
    cwd = os.getcwd() # root client directory
    temp_dir = os.path.join(cwd, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    return os.path.join(temp_dir, "user.json")

def load_credentials() -> Tuple[Optional[str], Optional[str], bool, Optional[str]]:
    """返回 (username, token, do_auto_login, server_url)"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                username = data.get("username", None)
                token = data.get("token", None)
                do_auto_login = data.get("auto_login", False)
                server_url = data.get("server_url", None)
                return username, token, do_auto_login, server_url
    except Exception as e:
        logger.error(f"Error loading credentials: {e}")
    return None, None, False, None

def save_credentials(username: str, token: str, do_auto_login: bool) -> None:
    try:
        path = get_credential_path()
        # 保留已有的 server_url
        existing_data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        data = {
            "username": username,
            "token": token,
            "auto_login": do_auto_login,
        }
        if existing_data.get("server_url"):
            data["server_url"] = existing_data["server_url"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving credentials: {e}")

def save_server_url(server_url: str, verify_ssl: bool = True) -> None:
    """保存自定义服务器地址及 SSL 验证设置到凭据文件。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["server_url"] = server_url
        data["server_verify_ssl"] = verify_ssl
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Server URL saved: {server_url} (verify_ssl={verify_ssl})")
    except Exception as e:
        logger.error(f"Error saving server URL: {e}")

def get_server_url() -> Optional[str]:
    """获取保存的自定义服务器地址。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("server_url", None)
    except Exception as e:
        logger.error(f"Error loading server URL: {e}")
    return None

def get_server_verify_ssl() -> bool:
    """获取保存的自定义服务器 SSL 验证设置，默认开启验证。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data.get("server_verify_ssl", True)
    except Exception as e:
        logger.error(f"Error loading server verify_ssl: {e}")
    return True