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
        if existing_data.get("api_key_plain"):
            data["api_key_plain"] = existing_data["api_key_plain"]
        if existing_data.get("llm_provider"):
            data["llm_provider"] = existing_data["llm_provider"]
        if existing_data.get("llm_model"):
            data["llm_model"] = existing_data["llm_model"]
        if existing_data.get("vlm_model"):
            data["vlm_model"] = existing_data["vlm_model"]
        if existing_data.get("vlm_provider"):
            data["vlm_provider"] = existing_data["vlm_provider"]
        if existing_data.get("vlm_provider_base_url"):
            data["vlm_provider_base_url"] = existing_data["vlm_provider_base_url"]
        if existing_data.get("vlm_api_key_dpapi"):
            data["vlm_api_key_dpapi"] = existing_data["vlm_api_key_dpapi"]
        if existing_data.get("vlm_api_key_plain"):
            data["vlm_api_key_plain"] = existing_data["vlm_api_key_plain"]
        if existing_data.get("llm_provider_base_url"):
            data["llm_provider_base_url"] = existing_data["llm_provider_base_url"]
        if existing_data.get("llm_params"):
            data["llm_params"] = existing_data["llm_params"]
        if existing_data.get("vlm_params"):
            data["vlm_params"] = existing_data["vlm_params"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving credentials: {e}")

def _save_api_key_impl(api_key: str, allow_plaintext: bool, prefix: str) -> bool:
    """按前缀保存 API Key（加密优先；allow_plaintext 时明文兜底）。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if api_key:
            key_enc = _encrypt_token(api_key)
            if key_enc:
                data[f"{prefix}api_key_dpapi"] = key_enc
                data.pop(f"{prefix}api_key_plain", None)
            elif allow_plaintext:
                logger.warning("API Key 无法加密，将以明文保存。")
                data[f"{prefix}api_key_plain"] = api_key
                data.pop(f"{prefix}api_key_dpapi", None)
            else:
                logger.error("API Key not saved due to encryption failure.")
                return False
        else:
            data.pop(f"{prefix}api_key_dpapi", None)
            data.pop(f"{prefix}api_key_plain", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("API Key saved.")
        return True
    except Exception as e:
        logger.error(f"Error saving API Key: {e}")
        return False


def _save_api_key_plain_impl(api_key: str, prefix: str) -> None:
    """以明文保存 API Key。

    仅应在用户二次确认后调用；调用方需明确告知用户 key 将明文存储。
    """
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if api_key:
            logger.warning("API Key 将以明文保存。")
            data[f"{prefix}api_key_plain"] = api_key
            data.pop(f"{prefix}api_key_dpapi", None)
        else:
            data.pop(f"{prefix}api_key_plain", None)
            data.pop(f"{prefix}api_key_dpapi", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.info("API Key saved (plaintext).")
    except Exception as e:
        logger.error(f"Error saving API Key (plaintext): {e}")


def _get_api_key_impl(prefix: str) -> Optional[str]:
    """按前缀读取 API Key；未配置时返回 None。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            key_enc = data.get(f"{prefix}api_key_dpapi")
            if key_enc:
                return _decrypt_token(key_enc)
            plain = data.get(f"{prefix}api_key_plain")
            if plain:
                return str(plain)
    except Exception as e:
        logger.error(f"Error loading API Key: {e}")
    return None


def save_api_key(api_key: str) -> bool:
    """保存对话模块的 LLM API Key（加密优先）。"""
    return _save_api_key_impl(api_key, False, "")


def save_api_key_plain(api_key: str) -> None:
    """以明文保存对话模块的 LLM API Key（仅限二次确认后调用）。"""
    _save_api_key_plain_impl(api_key, "")


def get_api_key() -> Optional[str]:
    """读取对话模块的 LLM API Key；未配置时返回 None。"""
    return _get_api_key_impl("")


def save_vlm_api_key(api_key: str, allow_plaintext: bool = False) -> bool:
    """保存图片理解模块的 LLM API Key（加密优先；allow_plaintext 时明文兜底）。"""
    return _save_api_key_impl(api_key, allow_plaintext, "vlm_")


def save_vlm_api_key_plain(api_key: str) -> None:
    """以明文保存图片理解模块的 LLM API Key（仅限二次确认后调用）。"""
    _save_api_key_plain_impl(api_key, "vlm_")


def get_vlm_api_key() -> Optional[str]:
    """读取图片理解模块的 LLM API Key；未配置时返回 None。"""
    return _get_api_key_impl("vlm_")

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

def save_provider_base_url(base_url: str) -> None:
    """保存用户所选服务商的 base_url；请求时直接使用该缓存值。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if base_url:
            data["llm_provider_base_url"] = base_url
        else:
            data.pop("llm_provider_base_url", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving LLM provider base_url: {e}")

def get_provider_base_url() -> Optional[str]:
    """读取缓存的 LLM 服务商 base_url。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("llm_provider_base_url", None)
    except Exception as e:
        logger.error(f"Error loading LLM provider base_url: {e}")
    return None

def save_vlm_model(model_name: str) -> None:
    """保存用户选择的图片理解模型名称。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if model_name:
            data["vlm_model"] = model_name
        else:
            data.pop("vlm_model", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving LLM VLM model: {e}")

def get_vlm_model() -> Optional[str]:
    """读取用户保存的图片理解模型名称。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("vlm_model", None)
    except Exception as e:
        logger.error(f"Error loading LLM VLM model: {e}")
    return None

def save_vlm_provider(provider_name: str) -> None:
    """保存用户为图片理解单独选择的服务商。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if provider_name:
            data["vlm_provider"] = provider_name
        else:
            data.pop("vlm_provider", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving LLM VLM provider: {e}")

def get_vlm_provider() -> Optional[str]:
    """读取用户为图片理解单独选择的服务商。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("vlm_provider", None)
    except Exception as e:
        logger.error(f"Error loading LLM VLM provider: {e}")
    return None

def save_vlm_provider_base_url(base_url: str) -> None:
    """保存图片理解服务商的 base_url。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if base_url:
            data["vlm_provider_base_url"] = base_url
        else:
            data.pop("vlm_provider_base_url", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving LLM VLM provider base_url: {e}")

def get_vlm_provider_base_url() -> Optional[str]:
    """读取图片理解服务商的 base_url。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data.get("vlm_provider_base_url", None)
    except Exception as e:
        logger.error(f"Error loading LLM VLM provider base_url: {e}")
    return None

def save_llm_params(params: dict) -> None:
    """保存用户自定义的 LLM 请求参数（temperature / max_tokens / top_p）。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if params:
            data["llm_params"] = params
        else:
            data.pop("llm_params", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving LLM params: {e}")

def get_llm_params() -> dict:
    """读取用户自定义的 LLM 请求参数；未配置时返回空字典。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            params = data.get("llm_params")
            if isinstance(params, dict):
                return params
    except Exception as e:
        logger.error(f"Error loading LLM params: {e}")
    return {}

def save_vlm_params(params: dict) -> None:
    """保存图片理解模型的自定义请求参数（temperature / max_tokens / top_p 等）。"""
    try:
        path = get_credential_path()
        data = {}
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        if params:
            data["vlm_params"] = params
        else:
            data.pop("vlm_params", None)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.error(f"Error saving LLM VLM params: {e}")

def get_vlm_params() -> dict:
    """读取图片理解模型的自定义请求参数；未配置时返回空字典。"""
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            params = data.get("vlm_params")
            if isinstance(params, dict):
                return params
    except Exception as e:
        logger.error(f"Error loading LLM VLM params: {e}")
    return {}

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
