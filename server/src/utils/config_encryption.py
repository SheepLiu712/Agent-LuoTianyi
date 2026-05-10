"""
配置加密模块
用于加密存储用户自定义 LLM 端点配置中的敏感字段（api_key, default_headers）。

使用 Fernet (AES-128-CBC + HMAC-SHA256) 对称加密。
密钥存储在 server/config/encryption.key，自动生成。
"""

import os
import json
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.fernet import Fernet, InvalidToken

from .logger import get_logger

logger = get_logger(__name__)

_KEY_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "encryption.key"

_SENSITIVE_KEYS = {"api_key", "default_headers"}


def _load_or_generate_key() -> Optional[bytes]:
    """加载或生成加密密钥。"""
    if _KEY_FILE.exists():
        try:
            key = _KEY_FILE.read_bytes().strip()
            # 验证密钥是否合法
            Fernet(key)
            return key
        except Exception as e:
            logger.warning(f"加密密钥文件无效，将重新生成: {e}")

    try:
        key = Fernet.generate_key()
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_bytes(key)
        logger.info(f"已生成新加密密钥: {_KEY_FILE}")
        return key
    except Exception as e:
        logger.warning(f"无法生成加密密钥文件，敏感配置将明文存储: {e}")
        return None


# 模块加载时初始化密钥
_fernet: Optional[Fernet] = None
_key = _load_or_generate_key()
if _key:
    _fernet = Fernet(_key)


def encrypt_value(plaintext: str) -> str:
    """加密字符串。"""
    if _fernet is None:
        return plaintext
    try:
        return _fernet.encrypt(plaintext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        logger.error(f"加密失败，将明文存储: {e}")
        return plaintext


def decrypt_value(ciphertext: str) -> str:
    """解密字符串。"""
    if _fernet is None:
        return ciphertext
    try:
        return _fernet.decrypt(ciphertext.encode("utf-8")).decode("utf-8")
    except Exception as e:
        if isinstance(e, InvalidToken):
            logger.error("解密失败：密钥不匹配或数据已损坏")
        else:
            logger.error(f"解密失败: {e}")
        return ciphertext


def encrypt_sensitive_fields(config: Dict[str, Any]) -> Dict[str, Any]:
    """加密配置中的敏感字段，返回深拷贝后的新字典。"""
    result = {}
    for key, value in config.items():
        if key in _SENSITIVE_KEYS and value is not None:
            if isinstance(value, dict):
                result[key] = encrypt_value(json.dumps(value, ensure_ascii=False))
            elif isinstance(value, str):
                result[key] = encrypt_value(value)
            else:
                result[key] = value
        else:
            result[key] = value
    return result


def decrypt_sensitive_fields(config: Dict[str, Any]) -> Dict[str, Any]:
    """解密配置中的敏感字段，返回深拷贝后的新字典。"""
    result = {}
    for key, value in config.items():
        if key in _SENSITIVE_KEYS and isinstance(value, str):
            decrypted = decrypt_value(value)
            # 尝试 JSON 解析（如果是加密的 dict）
            if key == "default_headers":
                try:
                    result[key] = json.loads(decrypted)
                except (json.JSONDecodeError, TypeError):
                    result[key] = decrypted
            else:
                result[key] = decrypted
        else:
            result[key] = value
    return result
