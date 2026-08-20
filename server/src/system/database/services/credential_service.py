import hashlib
import hmac
import secrets
import string
import time
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional, Tuple, TYPE_CHECKING

import bcrypt
from jose import jwt
from sqlalchemy.exc import IntegrityError

from src.system.database.redis_buffer import RedisBuffer
from src.system.database.sql_database import InviteCode, User
from src.utils.logger import get_logger

logger = get_logger("database.credential")

JWT_SECRET_ENV = "JWT_SECRET"
ALGORITHM = "HS256"

_BCRYPT_PREFIXES = ("$2a$", "$2b$", "$2y$")
_BCRYPT_ROUNDS = 12
_INVITE_CODE_LENGTH = 10
_INVITE_CODE_ALPHABET = string.ascii_uppercase + string.digits
_INVITE_CODE_COLLISION_RETRIES = 8


def _is_bcrypt_hash(value: str | None) -> bool:
    return bool(value and value.startswith(_BCRYPT_PREFIXES))


def _hash_password(password: str) -> str:
    hashed = bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=_BCRYPT_ROUNDS))
    return hashed.decode("utf-8")


def _generate_invite_code(length: int = _INVITE_CODE_LENGTH) -> str:
    return "".join(secrets.choice(_INVITE_CODE_ALPHABET) for _ in range(length))


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except ValueError:
        return False

class CredentialService:
    """登录、注册、账户重置和邀请码管理。由 DatabaseManager 组合。"""

    def __init__(
        self,
        *,
        sql_session_factory: Callable[[], Any],
        redis_buffer: RedisBuffer,
        jwt_secret: Optional[str],
        message_token_ttl_seconds: int,
    ) -> None:
        self._sql_session_factory = sql_session_factory
        self._redis = redis_buffer
        self.jwt_secret = jwt_secret
        self.message_token_ttl_seconds = message_token_ttl_seconds

    def _new_session(self) -> Any:
        """创建一个新的 SQL 会话；调用者负责关闭。"""
        return self._sql_session_factory()

    def _ensure_redis(self) -> RedisBuffer:
        return self._redis

    def _cache_user_uuid(self, username: str, user_uuid: str) -> None:
        try:
            self._ensure_redis().setex(f"user_id:{username}", 3600, user_uuid)
        except Exception as exc:
            logger.warning(
                "Failed to refresh username cache for %s (%s)",
                username,
                type(exc).__name__,
            )

    def _invalidate_username_caches(self, *usernames: str) -> None:
        for username in set(filter(None, usernames)):
            try:
                self._ensure_redis().delete(f"user_id:{username}")
            except Exception as exc:
                logger.warning(
                    "Failed to invalidate username cache for %s (%s)",
                    username,
                    type(exc).__name__,
                )

    def get_user_uuid_by_username(self, username: str) -> Optional[str]:
        '''
        根据用户名获取用户 UUID。会使用 Redis 缓存，缓存键为 user_id:{username}。如果缓存未命中，会从数据库查询并更新缓存。
        '''
        # 先尝试从 Redis 缓存获取，缓存键为 user_id:{username}
        redis = self._ensure_redis()
        cached_uuid = redis.get(f"user_id:{username}")
        if cached_uuid:
            return cached_uuid
        
        # 缓存未命中，从数据库查询并更新缓存
        db = self._new_session()
        try:
            user = db.query(User).filter_by(username=username).first()
            if user:
                # 更新缓存
                redis.setex(f"user_id:{username}", 3600, user.uuid)
                return user.uuid
            return None
        finally:
            db.close()

    # ────────────────────────────────────────────
    # Token 管理， 包括登录 token 和消息 token
    # ────────────────────────────────────────────

    def check_auth_token(self, username: str, token: str) -> bool:
        db = self._new_session()
        try:
            user = db.query(User).filter_by(username=username).first()
            return bool(
                user
                and user.auth_token
                and token
                and hmac.compare_digest(user.auth_token, token)
            )
        finally:
            db.close()

    def update_auth_token(self, username: str) -> Optional[str]:
        db = self._new_session()
        try:
            new_token = str(uuid.uuid4())
            user = db.query(User).filter_by(username=username).first()
            if not user:
                return None
            user.auth_token = new_token
            db.commit()
            return new_token
        except Exception as e:
            logger.error(f"Error updating auth token for {username}: {e}")
            db.rollback()
            return None
        finally:
            db.close()

    def _session_fingerprint(self, auth_token: str) -> Optional[str]:
        if not self.jwt_secret or not auth_token:
            return None
        return hmac.new(
            self.jwt_secret.encode("utf-8"),
            auth_token.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _encode_message_token(self, user_uuid: str, auth_token: str) -> Optional[str]:
        if not self.jwt_secret:
            logger.error("JWT_SECRET is not set. Cannot generate message token.")
            return None
        session_fp = self._session_fingerprint(auth_token)
        if not session_fp:
            return None
        issued_at = int(time.time())
        payload = {
            "user_uuid": user_uuid,
            "iat": issued_at,
            "exp": issued_at + self.message_token_ttl_seconds,
            "jti": str(uuid.uuid4()),
            "session_fp": session_fp,
        }
        return jwt.encode(payload, self.jwt_secret, algorithm=ALGORITHM)

    def generate_message_token(
        self,
        username: str,
        expected_auth_token: Optional[str] = None,
    ) -> Optional[str]:
        if not self.jwt_secret:
            logger.error("JWT_SECRET is not set. Cannot generate message token.")
            return None
        db = self._new_session()
        try:
            user = db.query(User).filter_by(username=username).first()
            if not user or not user.auth_token:
                return None
            if expected_auth_token and not hmac.compare_digest(user.auth_token, expected_auth_token):
                return None
            return self._encode_message_token(user.uuid, user.auth_token)
        finally:
            db.close()

    def _decode_message_token_claims(self, token: str) -> Optional[Dict[str, Any]]:
        if not self.jwt_secret:
            logger.error("JWT_SECRET is not set. Cannot decode message token.")
            return None
        try:
            payload = jwt.decode(token, self.jwt_secret, algorithms=[ALGORITHM])
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

    def decode_message_token(self, token: str) -> Optional[str]:
        payload = self._decode_message_token_claims(token)
        return str(payload["user_uuid"]) if payload else None

    def check_message_token(self, username: str, token: str) -> Tuple[bool, Optional[str]]:
        '''
        检查消息 token 是否有效。
        '''
        payload = self._decode_message_token_claims(token)
        if not payload:
            return False, None
        user_uuid = str(payload["user_uuid"])
        db = self._new_session()
        try:
            user = (
                db.query(User)
                .filter(User.uuid == user_uuid, User.username == username)
                .first()
            )
            if not user or not user.auth_token:
                return False, None
            expected_fp = self._session_fingerprint(user.auth_token)
            actual_fp = str(payload["session_fp"])
            if expected_fp and hmac.compare_digest(expected_fp, actual_fp):
                return True, user_uuid
            return False, None
        finally:
            db.close()
    
    # ────────────────────────────────────────────
    # 用户注册、登录、重置账户相关方法
    # ────────────────────────────────────────────

    def register_user(self, username: str, password: str, invite_code_str: str) -> Tuple[bool, str]:
        '''
        注册新用户，使用邀请码机制。检查邀请码是否存在和被使用。成功注册后，邀请码标记为已使用。
        成功返回 (True, "注册成功")，失败返回 (False, "失败原因")。
        '''
        db = self._new_session()
        try:
            available_code = (
                db.query(InviteCode.code)
                .filter(
                    InviteCode.code == invite_code_str,
                    InviteCode.is_used.is_(False),
                    InviteCode.disabled.is_(False),
                )
                .first()
            )
            if not available_code:
                logger.info(f"Register failed: invalid invite code for username={username}")
                return False, "注册失败，请检查邀请码或用户名"

            existing_user = db.query(User).filter_by(username=username).first()
            if existing_user:
                logger.info(f"Register failed: username already exists: {username}")
                return False, "注册失败，请检查邀请码或用户名"

            user_uuid = str(uuid.uuid4())
            new_user = User(
                uuid=user_uuid,
                username=username,
                password=_hash_password(password),
            )
            db.add(new_user)
            db.flush()

            claimed = (
                db.query(InviteCode)
                .filter(
                    InviteCode.code == invite_code_str,
                    InviteCode.is_used.is_(False),
                    InviteCode.disabled.is_(False),
                )
                .update(
                    {
                        InviteCode.is_used: True,
                        InviteCode.used_at: datetime.now(tz=None),
                        InviteCode.user_id: user_uuid,
                    },
                    synchronize_session=False,
                )
            )
            if claimed != 1:
                db.rollback()
                logger.info("Register failed: invite code unavailable for username=%s", username)
                return False, "注册失败，请检查邀请码或用户名"

            db.commit()
            self._cache_user_uuid(username, user_uuid)
            return True, "注册成功"
        except Exception as e:
            logger.error("Error registering user %s (%s)", username, type(e).__name__)
            db.rollback()
            return False, "注册失败，请检查邀请码或用户名"
        finally:
            db.close()

    def verify_user(self, username: str, password: str) -> bool:
        '''
        验证用户的用户名和密码。支持自动升级旧密码哈希。成功返回 True，失败返回 False。
        '''
        db = self._new_session()
        try:
            user = db.query(User).filter_by(username=username).first()
            if not user or not user.password:
                return False

            stored = user.password
            if _is_bcrypt_hash(stored):
                return _verify_password(password, stored)

            if hmac.compare_digest(stored, password):
                user.password = _hash_password(password)
                db.commit()
                return True
            return False
        except Exception as e:
            logger.error(f"Error verifying user {username}: {e}")
            db.rollback()
            return False
        finally:
            db.close()

    def reset_account(self, invite_code_str: str, new_username: str, new_password: str) -> Tuple[bool, str]:
        '''
        使用邀请码重置账户（更改用户名和密码）。成功返回 (True, "重置成功")，失败返回 (False, "失败原因")。
        '''
        db = self._new_session()
        old_username: Optional[str] = None
        try:
            code = db.query(InviteCode).filter_by(code=invite_code_str).first()
            if not code:
                return False, "邀请码无效"
            if code.disabled:
                return False, "邀请码已被禁用，无法重置"
            if not code.is_used or not code.user_id:
                return False, "邀请码尚未被使用，无法重置"

            user = db.query(User).filter_by(uuid=code.user_id).first()
            if not user:
                return False, "邀请码关联的用户不存在"

            existing = (
                db.query(User)
                .filter(User.username == new_username, User.uuid != user.uuid)
                .first()
            )
            if existing:
                return False, "新用户名已被其他用户使用"

            old_username = user.username
            user_uuid = user.uuid
            self._invalidate_username_caches(old_username, new_username)
            user.username = new_username
            user.password = _hash_password(new_password)
            user.auth_token = None
            db.commit()
            self._invalidate_username_caches(old_username, new_username)
            self._cache_user_uuid(new_username, user_uuid)
            logger.info("Account reset: old_username=%s, new_username=%s", old_username, new_username)
            return True, "重置成功"
        except Exception as e:
            db.rollback()
            if old_username:
                self._invalidate_username_caches(old_username, new_username)
            logger.error("Error resetting account for username=%s (%s)", new_username, type(e).__name__)
            return False, "重置失败"
        finally:
            db.close()

    # ────────────────────────────────────────────
    # 邀请码管理（admin 控制台）
    # ────────────────────────────────────────────

    def admin_list_invite_codes(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        status: Optional[str] = None,
        search: Optional[str] = None,
    ) -> Dict[str, Any]:
        '''
        邀请码列表（admin 控制台）。status 取值：'unused' | 'used' | 'disabled'。
        search 按邀请码模糊匹配。成功返回 {"items": [...], "total": N}。
        '''
        db = self._new_session()
        try:
            query = db.query(InviteCode)
            if status == "used":
                query = query.filter(InviteCode.is_used.is_(True))
            elif status == "disabled":
                query = query.filter(InviteCode.disabled.is_(True))
            elif status == "unused":
                query = query.filter(
                    InviteCode.is_used.is_(False),
                    InviteCode.disabled.is_(False),
                )

            if search:
                query = query.filter(InviteCode.code.contains(search.strip(), autoescape=True))

            total = query.count()
            rows = (
                query.order_by(InviteCode.created_at.desc())
                .offset(offset)
                .limit(limit)
                .all()
            )

            user_ids = {row.user_id for row in rows if row.user_id}
            usernames: Dict[str, str] = {}
            nicknames: Dict[str, str] = {}
            if user_ids:
                for user in db.query(User).filter(User.uuid.in_(user_ids)).all():
                    usernames[user.uuid] = user.username
                    nicknames[user.uuid] = user.nickname

            items = []
            for row in rows:
                items.append({
                    "code": row.code,
                    "is_used": bool(row.is_used),
                    "disabled": bool(row.disabled),
                    "created_at": row.created_at.strftime("%Y-%m-%d %H:%M:%S") if row.created_at else None,
                    "used_at": row.used_at.strftime("%Y-%m-%d %H:%M:%S") if row.used_at else None,
                    "user_id": row.user_id,
                    "username": usernames.get(row.user_id),
                    "nickname": nicknames.get(row.user_id),
                    "can_use": not bool(row.is_used) and not bool(row.disabled),
                })
            return {"items": items, "total": total}
        except Exception as exc:
            logger.error("Error listing invite codes (%s)", type(exc).__name__)
            db.rollback()
            return {"items": [], "total": 0}
        finally:
            db.close()

    def admin_generate_invite_codes(self, count: int = 1) -> Tuple[bool, Any]:
        '''批量生成 10 位大写字母和数字组成的邀请码。'''
        if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 100:
            return False, "生成数量需在 1-100 之间"

        db = self._new_session()
        added: List[str] = []
        try:
            db.begin()
            if db.get_bind().dialect.name == "sqlite":
                # pysqlite otherwise treats the first SAVEPOINT as the outer transaction.
                db.connection().exec_driver_sql("BEGIN")
            for _ in range(count):
                for _attempt in range(_INVITE_CODE_COLLISION_RETRIES):
                    candidate = _generate_invite_code()
                    try:
                        with db.begin_nested():
                            db.add(InviteCode(code=candidate))
                            db.flush()
                    except IntegrityError:
                        continue
                    added.append(candidate)
                    break
                else:
                    db.rollback()
                    logger.error(
                        "Invite code generation exhausted %d database collision retries",
                        _INVITE_CODE_COLLISION_RETRIES,
                    )
                    return False, "生成失败，请重试"
            db.commit()
            logger.info("Admin generated %d invite codes", len(added))
            return True, added
        except Exception as exc:
            db.rollback()
            logger.error("Error generating invite codes (%s)", type(exc).__name__)
            return False, "生成失败，请重试"
        finally:
            db.close()

    def admin_set_invite_code_disabled(self, code_str: str, disabled: bool) -> Tuple[bool, str]:
        '''设置邀请码的禁用状态（admin 控制台）。'''
        db = self._new_session()
        try:
            code = db.query(InviteCode).filter(InviteCode.code == code_str).first()
            if code is None:
                db.rollback()
                return False, "邀请码不存在"

            if bool(code.disabled) == disabled:
                db.rollback()
                return True, "已禁用" if disabled else "已启用"

            code.disabled = disabled
            db.commit()
            logger.info("Admin %s an invite code", "disabled" if disabled else "enabled")
            return True, "已禁用" if disabled else "已启用"
        except Exception as exc:
            db.rollback()
            logger.error("Error setting invite code disabled state (%s)", type(exc).__name__)
            return False, "操作失败，请重试"
        finally:
            db.close()

    def admin_disable_invite_code(self, code_str: str) -> Tuple[bool, str]:
        '''兼容旧管理接口，禁用邀请码。'''
        return self.admin_set_invite_code_disabled(code_str, True)

    def admin_delete_invite_code(self, code_str: str) -> Tuple[bool, str]:
        '''删除尚未使用且未禁用的邀请码（admin 控制台）。'''
        db = self._new_session()
        try:
            deleted = (
                db.query(InviteCode)
                .filter(
                    InviteCode.code == code_str,
                    InviteCode.is_used.is_(False),
                    InviteCode.disabled.is_(False),
                )
                .delete(synchronize_session=False)
            )
            if deleted == 1:
                db.commit()
                logger.info("Admin deleted an unused invite code")
                return True, "删除成功"

            db.rollback()
            code = db.query(InviteCode).filter(InviteCode.code == code_str).first()
            if code is None:
                return False, "邀请码不存在"
            if code.is_used:
                return False, "邀请码已被使用，无法删除"
            if code.disabled:
                return False, "邀请码已禁用，无法删除"
            return False, "邀请码状态已变化，请重试"
        except Exception as exc:
            db.rollback()
            logger.error("Error deleting invite code (%s)", type(exc).__name__)
            return False, "删除失败，请重试"
        finally:
            db.close()


    def _load_login_state(self, username: str) -> Optional[Dict[str, Any]]:
        """Load authoritative login state without consulting the UUID cache."""
        db = self._new_session()
        try:
            row = (
                db.query(User.uuid, User.password, User.auth_token, User.last_login)
                .filter(User.username == username)
                .first()
            )
            if row is None:
                return None
            return {
                "user_uuid": row.uuid,
                "password": row.password,
                "auth_token": row.auth_token,
                "last_login": row.last_login,
            }
        finally:
            db.close()

    def _rotate_authenticated_session(
        self,
        *,
        username: str,
        state: Dict[str, Any],
        expected_password: Optional[str] = None,
        replacement_password: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Compare-and-swap the authenticated DB state and return its signed session."""
        user_uuid = str(state["user_uuid"])
        previous_auth_token = state.get("auth_token")
        previous_last_login = state.get("last_login")
        login_token = str(uuid.uuid4())
        message_token = self._encode_message_token(user_uuid, login_token)
        if message_token is None:
            return None

        now = datetime.now()
        filters = [User.uuid == user_uuid, User.username == username]
        if previous_auth_token is None:
            filters.append(User.auth_token.is_(None))
        else:
            filters.append(User.auth_token == previous_auth_token)
        if previous_last_login is None:
            filters.append(User.last_login.is_(None))
        else:
            filters.append(User.last_login == previous_last_login)
        if expected_password is not None:
            filters.append(User.password == expected_password)

        updates: Dict[Any, Any] = {
            User.auth_token: login_token,
            User.last_login: now,
        }
        if replacement_password is not None:
            updates[User.password] = replacement_password

        db = self._new_session()
        try:
            updated = (
                db.query(User)
                .filter(*filters)
                .update(updates, synchronize_session=False)
            )
            if updated != 1:
                db.rollback()
                return None
            db.commit()
        except Exception as exc:
            db.rollback()
            logger.error(
                "Failed to rotate authenticated session for %s (%s)",
                username,
                type(exc).__name__,
            )
            return None
        finally:
            db.close()

        self._cache_user_uuid(username, user_uuid)
        elapsed = None
        if previous_last_login is not None:
            elapsed = (now - previous_last_login).total_seconds()
        return {
            "user_uuid": user_uuid,
            "login_token": login_token,
            "message_token": message_token,
            "elapsed_from_last_login": elapsed,
        }

    def authenticate_password_login(self, username: str, password: str) -> Optional[Dict[str, Any]]:
        if not self.jwt_secret:
            logger.error("JWT_SECRET is not set. Cannot authenticate password login.")
            return None
        try:
            state = self._load_login_state(username)
            if state is None or not state["password"]:
                return None

            stored_password = str(state["password"])
            replacement_password = None
            if _is_bcrypt_hash(stored_password):
                if not _verify_password(password, stored_password):
                    return None
            else:
                if not hmac.compare_digest(stored_password, password):
                    return None
                replacement_password = _hash_password(password)

            return self._rotate_authenticated_session(
                username=username,
                state=state,
                expected_password=stored_password,
                replacement_password=replacement_password,
            )
        except Exception as exc:
            logger.error(
                "Password authentication failed for %s (%s)",
                username,
                type(exc).__name__,
            )
            return None

    def authenticate_auto_login(self, username: str, token: str) -> Optional[Dict[str, Any]]:
        if not self.jwt_secret:
            logger.error("JWT_SECRET is not set. Cannot authenticate automatic login.")
            return None
        try:
            state = self._load_login_state(username)
            stored_auth_token = state.get("auth_token") if state else None
            if (
                not state
                or not stored_auth_token
                or not token
                or not hmac.compare_digest(str(stored_auth_token), token)
            ):
                return None
            return self._rotate_authenticated_session(username=username, state=state)
        except Exception as exc:
            logger.error(
                "Automatic authentication failed for %s (%s)",
                username,
                type(exc).__name__,
            )
            return None
    
    def update_login_time(self, user_id: str) -> Optional[float]:
        """
        将用户的最新登录时间更新为当前时间，返回距离上次登录的时间差（秒）。
        如果是第一次登录，返回 None。
        """
        db = self._new_session()
        try:
            user = db.query(User).filter(User.uuid == user_id).first()
            if not user:
                logger.error(f"User {user_id} not found for update_login_time.")
                return None

            now = datetime.now()
            last_login_time = user.last_login
            user.last_login = now
            db.commit()

            if last_login_time:
                return (now - last_login_time).total_seconds()
            return None
        except Exception as e:
            logger.error(f"Error updating login time for user {user_id}: {e}")
            db.rollback()
            return None
        finally:
            db.close()
    
