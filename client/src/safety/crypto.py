"""通用密钥加解密。

调用方只依赖 encrypt_secret / decrypt_secret，不关心具体后端；
更换或增加加密后端时只需修改本模块。当前后端为 Windows DPAPI，
非 Windows 平台无可用后端，加密返回 None，由调用方决定是否回退明文。
"""

import base64
import ctypes
import ctypes.wintypes as wintypes
import os

from ..utils.logger import get_logger


logger = get_logger("crypto")

_CRYPTPROTECT_UI_FORBIDDEN = 0x1


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


class _DpapiBackend:
    """Windows DPAPI 加解密后端。"""

    name = "dpapi"
    available = os.name == "nt"

    @staticmethod
    def _blob_from_bytes(data: bytes) -> tuple[_DATA_BLOB, ctypes.Array]:
        buffer = ctypes.create_string_buffer(data)
        blob = _DATA_BLOB(
            len(data), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte))
        )
        return blob, buffer

    def encrypt(self, data: bytes) -> bytes | None:
        blob_in, _ = self._blob_from_bytes(data)
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

    def decrypt(self, data: bytes) -> bytes | None:
        blob_in, _ = self._blob_from_bytes(data)
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


def _select_backend():
    """按平台选择可用后端；新增后端时在这里注册即可，调用方无需改动。"""
    for backend in (_DpapiBackend(),):
        if backend.available:
            return backend
    return None


_BACKEND = _select_backend()


def encrypt_secret(secret: str) -> str | None:
    """加密任意字符串并 base64 编码；无可用后端或失败时返回 None。"""
    if not secret or _BACKEND is None:
        return None
    try:
        encrypted = _BACKEND.encrypt(secret.encode("utf-8"))
        if not encrypted:
            return None
        return base64.b64encode(encrypted).decode("ascii")
    except Exception as exc:
        logger.error(f"Secret encrypt failed: {exc}")
        return None


def decrypt_secret(secret_b64: str) -> str | None:
    """base64 解码后解密；无可用后端或失败时返回 None。"""
    if not secret_b64 or _BACKEND is None:
        return None
    try:
        encrypted = base64.b64decode(secret_b64)
        decrypted = _BACKEND.decrypt(encrypted)
        if not decrypted:
            return None
        return decrypted.decode("utf-8")
    except Exception as exc:
        logger.error(f"Secret decrypt failed: {exc}")
        return None
