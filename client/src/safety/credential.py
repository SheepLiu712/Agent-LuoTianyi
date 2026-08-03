from ..utils.logger import get_logger
import base64
import ctypes
import ctypes.wintypes as wintypes
import os
import json
from typing import Tuple, Optional


logger = get_logger("credential")

_DPAPI_AVAILABLE = os.name == "nt"
_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def _blob_from_bytes(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
    buffer = ctypes.create_string_buffer(data)
    blob = _DATA_BLOB(len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
    return blob, buffer


def _crypt_protect(data: bytes) -> bytes | None:
    if not _DPAPI_AVAILABLE:
        return None
    blob_in, _ = _blob_from_bytes(data)
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptProtectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        _CRYPTPROTECT_UI_FORBIDDEN,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _crypt_unprotect(data: bytes) -> bytes | None:
    if not _DPAPI_AVAILABLE:
        return None
    blob_in, _ = _blob_from_bytes(data)
    blob_out = _DATA_BLOB()
    if not ctypes.windll.crypt32.CryptUnprotectData(
        ctypes.byref(blob_in),
        None,
        None,
        None,
        None,
        0,
        ctypes.byref(blob_out),
    ):
        raise ctypes.WinError()
    try:
        return ctypes.string_at(blob_out.pbData, blob_out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(blob_out.pbData)


def _encrypt_token(token: str) -> str | None:
    if not token:
        return None
    try:
        encrypted = _crypt_protect(token.encode("utf-8"))
        if not encrypted:
            return None
        return base64.b64encode(encrypted).decode("ascii")
    except Exception as exc:
        logger.error(f"Token encrypt failed: {exc}")
        return None


def _decrypt_token(token_b64: str) -> str | None:
    if not token_b64:
        return None
    try:
        encrypted = base64.b64decode(token_b64)
        decrypted = _crypt_unprotect(encrypted)
        if not decrypted:
            return None
        return decrypted.decode("utf-8")
    except Exception as exc:
        logger.error(f"Token decrypt failed: {exc}")
        return None

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
                token = None
                token_enc = data.get("token_dpapi")
                if token_enc:
                    token = _decrypt_token(token_enc)
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
        # 保留已有的 server_url
        existing_data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                existing_data = json.load(f)
        data = {
            "username": username,
            "auto_login": do_auto_login,
        }
        if token:
            token_enc = _encrypt_token(token)
            if token_enc:
                data["token_dpapi"] = token_enc
            else:
                data["auto_login"] = False
                logger.error("Auto-login token not saved due to encryption failure.")
        if existing_data.get("server_url"):
            data["server_url"] = existing_data["server_url"]
        if existing_data.get("api_key_dpapi"):
            data["api_key_dpapi"] = existing_data["api_key_dpapi"]
        if existing_data.get("llm_provider"):
            data["llm_provider"] = existing_data["llm_provider"]
        if existing_data.get("llm_model"):
            data["llm_model"] = existing_data["llm_model"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving credentials: {e}")

def save_api_key(api_key: str) -> None:
    """保存用户的 LLM API Key 到本地凭据文件（与 token 相同方式加密）。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if api_key:
            key_enc = _encrypt_token(api_key)
            if key_enc:
                data["api_key_dpapi"] = key_enc
            else:
                logger.error("LLM API Key not saved due to encryption failure.")
        else:
            data.pop("api_key_dpapi", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("LLM API Key saved.")
    except Exception as e:
        logger.error(f"Error saving LLM API Key: {e}")

def get_api_key() -> Optional[str]:
    """读取用户保存的 LLM API Key；未配置时返回 None。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key_enc = data.get("api_key_dpapi")
            if key_enc:
                return _decrypt_token(key_enc)
    except Exception as e:
        logger.error(f"Error loading LLM API Key: {e}")
    return None

def save_provider(provider_name: str) -> None:
    """保存用户选择的 LLM provider 预设名称。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if provider_name:
            data["llm_provider"] = provider_name
        else:
            data.pop("llm_provider", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving LLM provider: {e}")

def get_provider() -> Optional[str]:
    """读取用户选择的 LLM provider 预设名称。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("llm_provider", None)
    except Exception as e:
        logger.error(f"Error loading LLM provider: {e}")
    return None

def save_model(model_name: str) -> None:
    """保存用户选择的 LLM model 名称。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if model_name:
            data["llm_model"] = model_name
        else:
            data.pop("llm_model", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving LLM model: {e}")

def get_model() -> Optional[str]:
    """读取用户保存的 LLM model 名称。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("llm_model", None)
    except Exception as e:
        logger.error(f"Error loading LLM model: {e}")
    return None

def save_server_url(server_url: str, verify_ssl: bool = True) -> None:
    """保存自定义服务器地址到凭据文件。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        data["server_url"] = server_url
        data.pop("server_verify_ssl", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info(f"Server URL saved: {server_url} (verify_ssl=True)")
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
    return True
