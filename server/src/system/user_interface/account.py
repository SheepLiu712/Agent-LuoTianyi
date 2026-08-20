from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
import base64
import os
import hmac
import hashlib
import bcrypt
from fastapi import HTTPException
from jose import jwt
import uuid
import time
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Any, Optional, Tuple

from src.utils.logger import get_logger
from src.system.database import User, InviteCode


logger = get_logger("account_service")

# 账号安全部分：RSA 密钥对生成与密码解密
private_key = None
public_key_pem = None

def get_public_key_pem() -> str:
    return public_key_pem

def generate_keys():
    global private_key, public_key_pem
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
    )
    public_key = private_key.public_key()
    public_key_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')
    logger.info("RSA Keys generated.")

def decrypt_password(encrypted_b64: str) -> str:
    try:
        encrypted_bytes = base64.b64decode(encrypted_b64)
        original_message = private_key.decrypt(
            encrypted_bytes,
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return original_message.decode('utf-8')
    except Exception as e:
        logger.error(f"Decryption error: {e}")
        raise HTTPException(status_code=400, detail="Encryption error")
    
# ————————————————————————————————————————————————————————————————
# 下面的方法已经整合进DatabaseManager中，保留在这里是为了兼容旧代码
# ————————————————————————————————————————————————————————————————

# 自动登录使用的 token 管理
def update_auth_token(db_session: Session, username: str) -> str:
    new_token = str(uuid.uuid4())
    user: User = db_session.query(User).filter_by(username=username).first()
    if user:
        user.auth_token = new_token
        db_session.commit()
        return new_token
    
def check_auth_token(db_session: Session, username: str, token: str) -> bool:
    user: User = db_session.query(User).filter_by(username=username).first()
    if not user or not user.auth_token or not isinstance(token, str):
        return False
    return hmac.compare_digest(user.auth_token, token)

# 发送消息时使用的token，编码用户的UUID

JWT_SECRET_ENV = "JWT_SECRET"
ALGORITHM = "HS256"
MESSAGE_TOKEN_TTL_SECONDS = 3600


def _get_jwt_secret() -> str | None:
    return os.environ.get(JWT_SECRET_ENV)


def _session_fingerprint(jwt_secret: str, auth_token: str) -> str:
    return hmac.new(
        jwt_secret.encode("utf-8"),
        auth_token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def generate_message_token(db_session: Session, username: str) -> Optional[str]:
    jwt_secret = _get_jwt_secret()
    if not jwt_secret:
        logger.error("JWT_SECRET is not set. Cannot generate legacy message token.")
        return None
    user: User = db_session.query(User).filter_by(username=username).first()
    if not user or not user.auth_token:
        return None
    issued_at = int(time.time())
    payload = {
        "user_uuid": user.uuid,
        "iat": issued_at,
        "exp": issued_at + MESSAGE_TOKEN_TTL_SECONDS,
        "jti": str(uuid.uuid4()),
        "session_fp": _session_fingerprint(jwt_secret, user.auth_token),
    }
    return jwt.encode(payload, jwt_secret, algorithm=ALGORITHM)


def _decode_message_token_claims(token: str) -> Optional[dict[str, Any]]:
    jwt_secret = _get_jwt_secret()
    if not jwt_secret:
        logger.error("JWT_SECRET is not set. Cannot decode legacy message token.")
        return None
    try:
        payload = jwt.decode(token, jwt_secret, algorithms=[ALGORITHM])
        required_claims = ("user_uuid", "iat", "exp", "jti", "session_fp")
        if not isinstance(payload, dict) or any(not payload.get(name) for name in required_claims):
            return None
        issued_at = int(payload["iat"])
        expires_at = int(payload["exp"])
        now = int(time.time())
        if expires_at <= now or issued_at > now + 60 or expires_at <= issued_at:
            return None
        return payload
    except (jwt.JWTError, TypeError, ValueError):
        return None


def decode_message_token(token: str) -> Optional[str]:
    payload = _decode_message_token_claims(token)
    return str(payload["user_uuid"]) if payload else None


def check_message_token(db_session: Session, username: str, token: str) -> Tuple[bool, Optional[str]]:
    payload = _decode_message_token_claims(token)
    if not payload:
        return False, None
    user: User = db_session.query(User).filter_by(username=username).first()
    if not user or not user.auth_token or str(payload["user_uuid"]) != user.uuid:
        return False, None
    jwt_secret = _get_jwt_secret()
    expected_fingerprint = _session_fingerprint(jwt_secret, user.auth_token)
    if hmac.compare_digest(expected_fingerprint, str(payload["session_fp"])):
        return True, user.uuid
    return False, None


_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")
_BCRYPT_ROUNDS = 12


def _is_bcrypt_hash(value: str | None) -> bool:
    return bool(value and value.startswith(_BCRYPT_PREFIXES))


def _hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return hashed.decode("utf-8")


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False


def register_user(db_session: Session, username: str, password: str, invite_code_str: str):
    try:
        available_code = (
            db_session.query(InviteCode.code)
            .filter(
                InviteCode.code == invite_code_str,
                InviteCode.is_used.is_(False),
            )
            .first()
        )
        if not available_code:
            logger.info("Register failed: invalid invite code for username=%s", username)
            return False, "注册失败，请检查邀请码或用户名"

        existing_user = db_session.query(User).filter_by(username=username).first()
        if existing_user:
            logger.info("Register failed: username already exists: %s", username)
            return False, "注册失败，请检查邀请码或用户名"

        new_user = User(username=username, password=_hash_password(password))
        db_session.add(new_user)
        db_session.flush()

        claimed = (
            db_session.query(InviteCode)
            .filter(
                InviteCode.code == invite_code_str,
                InviteCode.is_used.is_(False),
            )
            .update(
                {
                    InviteCode.is_used: True,
                    InviteCode.used_at: datetime.now(tz=None),
                    InviteCode.user_id: new_user.uuid,
                },
                synchronize_session=False,
            )
        )
        if claimed != 1:
            db_session.rollback()
            logger.info("Register failed: invite code unavailable for username=%s", username)
            return False, "注册失败，请检查邀请码或用户名"

        db_session.commit()
        return True, "注册成功"
    except Exception as exc:
        db_session.rollback()
        logger.error("Error registering legacy user %s (%s)", username, type(exc).__name__)
        return False, "注册失败，请检查邀请码或用户名"

def verify_user(db_session: Session, username: str, password: str) -> bool:
    user = db_session.query(User).filter_by(username=username).first()
    if not user or not user.password:
        return False

    stored = user.password
    if _is_bcrypt_hash(stored):
        return _verify_password(password, stored)

    if hmac.compare_digest(stored, password):
        user.password = _hash_password(password)
        db_session.commit()
        return True
    return False


def reset_account(
    db_session: Session, invite_code_str: str, new_username: str, new_password: str
) -> Tuple[bool, str]:
    """以邀请码重置账号的用户名和密码。

    邀请码必须已被使用（关联到一个已注册用户）。
    成功后将该用户的 username 和 password 更新为新的值。
    """
    code = db_session.query(InviteCode).filter_by(code=invite_code_str).first()
    if not code:
        return False, "邀请码无效"
    if not code.is_used or not code.user_id:
        return False, "邀请码尚未被使用，无法重置"

    user = db_session.query(User).filter_by(uuid=code.user_id).first()
    if not user:
        return False, "邀请码关联的用户不存在"

    # 检查新用户名是否已被其他用户使用
    existing = (
        db_session.query(User)
        .filter(User.username == new_username, User.uuid != user.uuid)
        .first()
    )
    if existing:
        return False, "新用户名已被其他用户使用"

    old_username = user.username
    user.username = new_username
    user.password = _hash_password(new_password)
    # 清除旧的 auth_token，强制重新登录
    user.auth_token = None
    db_session.commit()

    logger.info("Account reset: old_username=%s, new_username=%s", old_username, new_username)
    return True, "重置成功"
