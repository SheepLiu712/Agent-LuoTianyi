import base64
from types import SimpleNamespace

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from cli_client.safety import encrypt_pwd


def test_password_uses_current_key_after_server_restart(monkeypatch):
    current = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    available = True

    def get(*args, **kwargs):
        pem = (
            current.public_key()
            .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
            .decode()
        )
        return SimpleNamespace(status_code=200 if available else 503, json=lambda: {"public_key": pem})

    monkeypatch.setattr(encrypt_pwd.HttpClientFactory, "get_session", lambda **kwargs: SimpleNamespace(get=get))
    assert encrypt_pwd.encrypt_password("secret")
    current = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    encrypted = encrypt_pwd.encrypt_password("secret")
    assert (
        current.decrypt(
            base64.b64decode(encrypted),
            padding.OAEP(mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None),
        )
        == b"secret"
    )
    available = False
    assert encrypt_pwd.encrypt_password("secret") is None
