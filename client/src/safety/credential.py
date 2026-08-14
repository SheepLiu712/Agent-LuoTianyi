"""凭据与 LLM 模块配置的本地安全存储。

LLM/VLM 模块配置以统一结构保存在凭据文件的 llm_modules 字段下：
{能力key: {enabled, provider, model, base_url, params, api_key_dpapi/api_key_plain}}，
一次读改写 + 临时文件替换原子落盘。
"""

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

_CREDENTIAL_PRESERVED_FIELDS = (
    "server_url",
)


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
        _CRYPTPROTECT_UI_FORBIDDEN,
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
        # 保留已有的本地配置字段
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
        for key in _CREDENTIAL_PRESERVED_FIELDS:
            if existing_data.get(key):
                data[key] = existing_data[key]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving credentials: {e}")


def _read_credential_data() -> dict:
    """读取凭据 JSON；文件缺失或内容损坏时返回空字典。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
    except Exception as exc:
        logger.error(f"Error loading credential data: {exc}")
    return {}


def get_llm_modules_config() -> dict:
    """读取统一模块配置 {能力key: {enabled, provider, model, base_url, params, api_key}}。

    api_key 已解密；未配置任何模块时返回空字典。
    """
    data = _read_credential_data()
    modules = data.get("llm_modules")
    if not isinstance(modules, dict):
        return {}
    result = {}
    for key, raw in modules.items():
        if not isinstance(raw, dict):
            continue
        entry = {
            "enabled": bool(raw.get("enabled", False)),
            "provider": str(raw.get("provider") or ""),
            "model": str(raw.get("model") or ""),
            "base_url": str(raw.get("base_url") or ""),
            "params": raw.get("params") if isinstance(raw.get("params"), dict) else {},
            "model_capabilities": (
                raw.get("model_capabilities")
                if isinstance(raw.get("model_capabilities"), dict)
                else {}
            ),
            "api_key": "",
        }
        key_enc = raw.get("api_key_dpapi")
        if key_enc:
            entry["api_key"] = _decrypt_token(key_enc) or ""
        else:
            plain = raw.get("api_key_plain")
            if plain:
                entry["api_key"] = str(plain)
        result[key] = entry
    return result


def get_module_config(module_key: str) -> dict | None:
    """返回单个模块配置（含解密 api_key）；不存在时返回 None。"""
    return get_llm_modules_config().get(module_key)


def save_llm_modules_config(
    modules: dict,
    allow_plaintext: bool = False,
) -> bool:
    """原子写入整份模块配置；保留其它凭据字段。

    modules: {能力key: {enabled, provider, model, base_url, params,
    model_capabilities, api_key}}
    API Key 加密失败且不允许明文时返回 False（调用方二次确认后可重试）。
    """
    try:
        data = _read_credential_data()
        cleaned: dict = {}
        for key, raw in (modules or {}).items():
            if not isinstance(raw, dict):
                continue
            api_key = str(raw.get("api_key") or "")
            entry = {
                "enabled": bool(raw.get("enabled", False)),
                "provider": str(raw.get("provider") or ""),
                "model": str(raw.get("model") or ""),
                "base_url": str(raw.get("base_url") or ""),
                "params": raw.get("params") if isinstance(raw.get("params"), dict) else {},
                "model_capabilities": (
                    raw.get("model_capabilities")
                    if isinstance(raw.get("model_capabilities"), dict)
                    else {}
                ),
            }
            if api_key:
                key_enc = _encrypt_token(api_key)
                if key_enc:
                    entry["api_key_dpapi"] = key_enc
                elif allow_plaintext:
                    logger.warning("API Key 无法加密，将以明文保存。")
                    entry["api_key_plain"] = api_key
                else:
                    return False
            cleaned[key] = entry
        data["llm_modules"] = cleaned
        _atomic_write_json(get_credential_path(), data)
        return True
    except Exception as exc:
        logger.error(f"Error saving LLM modules config: {exc}")
        return False


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


def _atomic_write_json(path: str, data: dict) -> None:
    """先写临时文件再原子替换，避免写一半损坏凭据文件。"""
    temp_path = f"{path}.tmp"
    with open(temp_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(temp_path, path)
