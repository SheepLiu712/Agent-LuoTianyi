from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import serialization, hashes
import base64
from fastapi import HTTPException
from jose import jwt
import uuid
from sqlalchemy.orm import Session
from datetime import datetime
from typing import Tuple

from ..utils.logger import get_logger
from ..database import User, InviteCode


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
    

# 账号服务：注册与登录逻辑

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
    if user and user.auth_token == token:
        return True
    return False

# 发送消息时使用的token，编码用户的UUID

PRIVATE_KEY = "LUOTIANYI_PRIVATE_KEY_73991"
ALGORITHM = "HS256"
def generate_message_token(db_session: Session, username: str) -> str:
    user: User = db_session.query(User).filter_by(username=username).first()
    if not user:
        return None
    user_uuid = user.uuid
    payload = {
        "user_uuid": user_uuid,
    }
    token = jwt.encode(payload, PRIVATE_KEY, algorithm=ALGORITHM)
    return token

def decode_message_token(token: str) -> str:
    try:
        payload = jwt.decode(token, PRIVATE_KEY, algorithms=[ALGORITHM])
        return payload.get("user_uuid")
    except jwt.JWTError:
        return None
    
def check_message_token(db_session: Session, username: str, token: str) -> Tuple[bool, str]:
    user: User = db_session.query(User).filter_by(username=username).first()
    if not user:
        return False, None
    user_uuid = user.uuid
    decoded_uuid = decode_message_token(token)
    if decoded_uuid == user_uuid:
        return True, user_uuid
    return False, None


def register_user(db_session: Session, username: str, password: str, invite_code_str: str):
    # 1. Check Invite Code
    code = db_session.query(InviteCode).filter_by(code=invite_code_str).first()
    if not code:
        return False, "邀请码无效"
    if code.is_used:
        return False, "邀请码已被使用"
        
    # 2. Check Username
    existing_user = db_session.query(User).filter_by(username=username).first()
    if existing_user:
        return False, "用户名已存在"
        
    # 3. Create User
    new_user = User(username=username, password=password)
    db_session.add(new_user)
    db_session.flush() # Populate defaults like uuid
    
    # 4. Update Invite Code
    code.is_used = True
    code.used_at = datetime.now(tz=None)
    code.user_id = new_user.uuid
    
    db_session.commit()
    return True, "注册成功"

def verify_user(db_session: Session, username: str, password: str) -> bool:
    user = db_session.query(User).filter_by(username=username, password=password).first()
    if user:
        # Update last login time
        user.last_login = datetime.now(tz=None)
        db_session.commit()
        return True
    return False