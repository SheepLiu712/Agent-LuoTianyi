"""
配置加密模块
用于加密存储用户自定义 LLM 端点配置中的敏感字段（api_key, default_headers）。

使用 AES-256-GCM 认证加密。
密钥存储在 server/config/encryption.key，自动生成。
"""

import os
import json
import base64
from pathlib import Path
from typing import Any, Dict, Optional

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .logger import get_logger

logger = get_logger(__name__)

_KEY_FILE = Path(__file__).resolve().parent.parent.parent / "config" / "encryption.key"
_NONCE_LENGTH = 12  # GCM 推荐的 nonce 长度

_SENSITIVE_KEYS = {"api_key", "default_headers"}


def _load_or_generate_key() -> Optional[bytes]:
    """加载或生成 32 字节的 AES-256 密钥。"""
    if _KEY_FILE.exists():
        try:
            key = _KEY_FILE.read_bytes().strip()
            if len(key) != 32:
                raise ValueError(f"密钥长度应为 32 字节，实际为 {len(key)}")
            # 验证密钥可用
            AESGCM(key)
            return key
        except Exception as e:
            logger.warning(f"加密密钥文件无效，将重新生成: {e}")

    try:
        key = AESGCM.generate_key(bit_length=256)  # 32 bytes
        _KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        _KEY_FILE.write_bytes(key)
        logger.info(f"已生成新 AES-256 密钥: {_KEY_FILE}")
        return key
    except Exception as e:
        logger.warning(f"无法生成加密密钥文件，敏感配置将明文存储: {e}")
        return None


# 模块加载时初始化密钥
_key = _load_or_generate_key()
_aesgcm: Optional[AESGCM] = AESGCM(_key) if _key else None


def encrypt_value(plaintext: str) -> str:
    """用 AES-256-GCM 加密字符串。输出格式: base64(nonce + ciphertext)。"""
    if _aesgcm is None:
        return plaintext
    try:
        nonce = os.urandom(_NONCE_LENGTH)
        ciphertext = _aesgcm.encrypt(nonce, plaintext.encode("utf-8"), None)
        # GCM encrypt 返回的是密文 + 16 字节认证标签的拼接
        return base64.urlsafe_b64encode(nonce + ciphertext).decode("utf-8")
    except Exception as e:
        logger.error(f"加密失败，将明文存储: {e}")
        return plaintext


def decrypt_value(ciphertext: str) -> str:
    """解密 AES-256-GCM 密文。输入格式: base64(nonce + ciphertext)。"""
    if _aesgcm is None:
        return ciphertext
    try:
        data = base64.urlsafe_b64decode(ciphertext.encode("utf-8"))
        nonce = data[:_NONCE_LENGTH]
        ct = data[_NONCE_LENGTH:]
        return _aesgcm.decrypt(nonce, ct, None).decode("utf-8")
    except Exception as e:
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
