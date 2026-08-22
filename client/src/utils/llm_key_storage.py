"""LLM/VLM 模块配置的本地存储。

整份配置作为一个JSON 文件（temp/llm_modules.json）原子读写；
API Key 加密存储（加密失败且允许明文时回退明文），其余字段明文保存。
"""

from ..safety.crypto import decrypt_secret, encrypt_secret
from ..safety.storage import atomic_write_json, read_json_file, temp_path
from ..utils.logger import get_logger


logger = get_logger("llm_key_storage")


def get_llm_modules_path():
    return temp_path("llm_modules.json")


def get_llm_modules_config() -> dict:
    """读取统一模块配置 {能力key: {enabled, provider, model, base_url, params, api_key}}。

    api_key 已解密；未配置任何模块时返回空字典。
    """
    modules = read_json_file(get_llm_modules_path())
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
            entry["api_key"] = decrypt_secret(key_enc) or ""
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
    """原子写入整份模块配置到独立的 llm_modules.json。

    modules: {能力key: {enabled, provider, model, base_url, params,
    model_capabilities, api_key}}
    API Key 加密失败且不允许明文时返回 False（调用方二次确认后可重试）。
    """
    try:
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
                key_enc = encrypt_secret(api_key)
                if key_enc:
                    entry["api_key_dpapi"] = key_enc
                elif allow_plaintext:
                    logger.warning("API Key 无法加密，将以明文保存。")
                    entry["api_key_plain"] = api_key
                else:
                    return False
            cleaned[key] = entry
        atomic_write_json(get_llm_modules_path(), cleaned)
        return True
    except Exception as exc:
        logger.error(f"Error saving LLM modules config: {exc}")
        return False
