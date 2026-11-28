"""Account-scoped avatar sync, independent of chat session rotation."""

from __future__ import annotations

import hashlib
import hmac
import time

from jose import jwt

from src.infrastructure.media.avatar import normalize_avatar
from src.infrastructure.persistence.avatar_store import AvatarStore
from src.infrastructure.persistence.database.sql_database import User

_AVATAR_AUDIENCE = "chat-avatar-sync"
_SYNC_TOKEN_TTL = 30 * 24 * 60 * 60


class AvatarAuthenticationError(ValueError):
    pass


class AvatarService:
    def __init__(self, database):
        self._database = database
        self._store = AvatarStore(database.open_sql_session)

    def _password_fingerprint(self, user: User) -> str:
        # Password reset revokes these narrowly scoped credentials on every device.
        return hmac.new(
            self._database.credential_service.jwt_secret.encode(),
            f"{user.uuid}:{user.password}".encode(),
            hashlib.sha256,
        ).hexdigest()

    def _authenticate(self, username: str, token: str) -> tuple[str, str]:
        credentials = self._database.credential_service
        claims = None
        try:
            claims = jwt.decode(
                token,
                credentials.jwt_secret,
                algorithms=["HS256"],
                audience=_AVATAR_AUDIENCE,
                options={"require_aud": True, "require_exp": True, "require_sub": True},
            )
        except (jwt.JWTError, TypeError, ValueError):
            pass
        with self._database.open_sql_session() as session:
            if claims is None:
                user = credentials.authenticate_message_user_in_session(session, username, token)
            else:
                user = session.query(User).filter_by(uuid=claims.get("sub"), username=username).first()
            if user is None:
                raise AvatarAuthenticationError("头像同步凭据无效，请重新登录")
            user_id = user.uuid
            fingerprint = self._password_fingerprint(user)
            if claims is not None and not hmac.compare_digest(str(claims.get("password_fp", "")), fingerprint):
                raise AvatarAuthenticationError("头像同步凭据无效，请重新登录")
            sync_token = jwt.encode(
                {
                    "sub": user.uuid,
                    "aud": _AVATAR_AUDIENCE,
                    "password_fp": fingerprint,
                    # A stable daily renewal avoids rewriting secure storage on every poll.
                    "exp": int(time.time()) // 86400 * 86400 + _SYNC_TOKEN_TTL,
                },
                credentials.jwt_secret,
                algorithm="HS256",
            )
        return user_id, sync_token

    def get(self, username: str, token: str) -> dict:
        user_id, sync_token = self._authenticate(username, token)
        return {**self._store.get(user_id), "sync_token": sync_token}

    def put(self, username: str, token: str, side: str, image: str | None) -> dict:
        user_id, sync_token = self._authenticate(username, token)
        image = normalize_avatar(image)
        return {**self._store.put(user_id, side, image), "sync_token": sync_token}
