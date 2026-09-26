"""CLI-only encrypted login token store; never changes GUI auto-login state."""

from pathlib import Path

from ..safety.crypto import decrypt_secret, encrypt_secret
from ..safety.storage import atomic_write_json, read_json_file


class CredentialStoreError(ValueError):
    pass


def save_login(path: str | Path, base_url: str, username: str, token: str) -> None:
    encrypted = encrypt_secret(token)
    if not encrypted:
        raise CredentialStoreError("encrypted credential storage is unavailable")
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(
        str(target),
        {
            "base_url": base_url,
            "username": username,
            "login_token_dpapi": encrypted,
        },
    )


def load_login(path: str | Path) -> tuple[str, str, str]:
    data = read_json_file(str(path))
    base_url = data.get("base_url")
    username = data.get("username")
    encrypted = data.get("login_token_dpapi")
    if not all(isinstance(value, str) and value for value in (base_url, username, encrypted)):
        raise CredentialStoreError("saved CLI login is missing or incomplete")
    token = decrypt_secret(encrypted)
    if not token:
        raise CredentialStoreError("saved CLI login cannot be decrypted")
    return base_url, username, token
