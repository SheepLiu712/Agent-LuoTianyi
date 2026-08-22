"""凭据与服务器地址的本地安全存储"""

from typing import Optional, Tuple

from ..utils.logger import get_logger
from .crypto import decrypt_secret, encrypt_secret
from .storage import atomic_write_json, read_json_file, temp_path


logger = get_logger("credential")


def get_credential_path():
    return temp_path("user.json")


def load_credentials() -> Tuple[Optional[str], Optional[str], bool, Optional[str]]:
    """返回 (username, token, do_auto_login, server_url)"""
    try:
        data = read_json_file(get_credential_path())
        username = data.get("username", None)
        token = None
        token_enc = data.get("token_dpapi")
        if token_enc:
            token = decrypt_secret(token_enc)
        elif data.get("token"):
            token = data.get("token")
        do_auto_login = data.get("auto_login", False)
        if do_auto_login and not token:
            do_auto_login = False
        server_url = data.get("server_url", None)
        return username, token, do_auto_login, server_url
    except Exception as e:
        logger.error(f"Error loading credentials: {e}")
    return None, None, False, None


def save_credentials(username: str, token: str, do_auto_login: bool) -> None:
    try:
        path = get_credential_path()
        data = read_json_file(path)
        data["username"] = username
        data["auto_login"] = do_auto_login
        data.pop("token_dpapi", None)
        data.pop("token", None)
        if token:
            token_enc = encrypt_secret(token)
            if token_enc:
                data["token_dpapi"] = token_enc
            else:
                data["auto_login"] = False
                logger.error("Auto-login token not saved due to encryption failure.")
        atomic_write_json(path, data)
    except Exception as e:
        logger.error(f"Error saving credentials: {e}")


def save_server_url(server_url: str, verify_ssl: bool = True) -> None:
    """保存自定义服务器地址到凭据文件。"""
    try:
        path = get_credential_path()
        data = read_json_file(path)
        data["server_url"] = server_url
        data.pop("server_verify_ssl", None)
        atomic_write_json(path, data)
        logger.info(f"Server URL saved: {server_url} (verify_ssl=True)")
    except Exception as e:
        logger.error(f"Error saving server URL: {e}")


def get_server_url() -> Optional[str]:
    """获取保存的自定义服务器地址。"""
    try:
        data = read_json_file(get_credential_path())
        return data.get("server_url", None)
    except Exception as e:
        logger.error(f"Error loading server URL: {e}")
    return None


def get_server_verify_ssl() -> bool:
    """获取保存的自定义服务器 SSL 验证设置，默认开启验证。"""
    return True
