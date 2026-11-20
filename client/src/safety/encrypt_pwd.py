from cryptography.hazmat.primitives import serialization, hashes
from cryptography.hazmat.primitives.asymmetric import padding
import base64
from ..utils.logger import get_logger
from ..utils.http_client import HttpClientFactory

logger = get_logger("password")


def get_public_key(
    base_url="http://127.0.0.1:8000", verify_ssl: bool = True, session=None
) -> serialization.PublicFormat | None:
    try:
        if session is None:
            session = HttpClientFactory.get_session(verify_ssl=verify_ssl)
        resp = session.get(
            f"{base_url}/auth/public_key", verify=verify_ssl, timeout=15, headers={"Cache-Control": "no-cache"}
        )
        if resp.status_code == 200:
            pem = resp.json().get("public_key")
            public_key = serialization.load_pem_public_key(pem.encode("utf-8"))
            return public_key
    except Exception as e:
        logger.error(f"Error fetching public key: {e}")
    return None


def encrypt_password(
    password: str, base_url="http://127.0.0.1:8000", verify_ssl: bool = True, session=None
) -> str | None:
    key = get_public_key(base_url=base_url, verify_ssl=verify_ssl, session=session)
    if not key:
        return None
    try:
        encrypted = key.encrypt(
            password.encode("utf-8"),
            padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        return base64.b64encode(encrypted).decode("utf-8")
    except Exception as e:
        logger.error(f"Encryption error: {e}")
        return None
