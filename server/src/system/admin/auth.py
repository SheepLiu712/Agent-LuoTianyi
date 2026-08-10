from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from pathlib import Path
from typing import Any

from fastapi import HTTPException, Request, Response


class AdminAuthService:
    """Password based admin auth with local setup token and in-memory sessions."""

    COOKIE_NAME = "agentluo_admin_token"

    def __init__(self, auth_file: str | Path, setup_token_file: str | Path) -> None:
        self.auth_file = Path(auth_file)
        self.setup_token_file = Path(setup_token_file)
        self.sessions: dict[str, float] = {}
        self.session_ttl_seconds = 12 * 3600
        self._password_work_slots = asyncio.Semaphore(4)
        self._password_work_admission_timeout = 1.0
        if not self.is_configured():
            self._ensure_setup_token()

    def is_configured(self) -> bool:
        data = self._read_auth()
        return bool(data.get("password_hash") and data.get("salt"))

    def status(self) -> dict[str, Any]:
        return {
            "configured": self.is_configured(),
            "setup_required": not self.is_configured(),
        }

    def setup(self, setup_token: str, password: str) -> dict[str, Any]:
        if self.is_configured():
            raise HTTPException(status_code=400, detail={"code": "ADMIN_ALREADY_CONFIGURED", "message": "Admin password is already configured"})
        expected = self._ensure_setup_token()
        if not hmac.compare_digest(setup_token.strip(), expected.strip()):
            raise HTTPException(status_code=403, detail={"code": "BAD_SETUP_TOKEN", "message": "Invalid admin setup token"})
        self._write_password(password)
        if self.setup_token_file.exists():
            self.setup_token_file.unlink()
        return {"ok": True}

    def login(self, password: str, response: Response) -> dict[str, Any]:
        if not self.is_configured():
            raise HTTPException(status_code=403, detail={"code": "ADMIN_SETUP_REQUIRED", "message": "Admin password has not been configured"})
        if not self._verify_password(password):
            raise HTTPException(status_code=401, detail={"code": "BAD_ADMIN_PASSWORD", "message": "Invalid admin password"})
        return self._create_session(response)

    async def login_async(self, password: str, response: Response) -> dict[str, Any]:
        if not self.is_configured():
            raise HTTPException(status_code=403, detail={"code": "ADMIN_SETUP_REQUIRED", "message": "Admin password has not been configured"})
        try:
            await asyncio.wait_for(
                self._password_work_slots.acquire(),
                timeout=self._password_work_admission_timeout,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(status_code=503, detail={"code": "ADMIN_AUTH_BUSY", "message": "Admin authentication is busy"}) from exc
        try:
            password_valid = await asyncio.to_thread(self._verify_password, password)
        finally:
            self._password_work_slots.release()
        if not password_valid:
            raise HTTPException(status_code=401, detail={"code": "BAD_ADMIN_PASSWORD", "message": "Invalid admin password"})
        return self._create_session(response)

    def _create_session(self, response: Response) -> dict[str, Any]:
        token = secrets.token_urlsafe(32)
        expires_at = time.time() + self.session_ttl_seconds
        self.sessions[token] = expires_at
        response.set_cookie(
            self.COOKIE_NAME,
            token,
            httponly=True,
            samesite="lax",
            secure=False,
            max_age=self.session_ttl_seconds,
            path="/admin",
        )
        return {"ok": True, "token": token, "expires_at": expires_at}

    def logout(self, request: Request, response: Response) -> dict[str, Any]:
        token = self._extract_token(request)
        if token:
            self.sessions.pop(token, None)
        response.delete_cookie(self.COOKIE_NAME, path="/admin")
        return {"ok": True}

    def require_admin(self, request: Request) -> None:
        token = self._extract_token(request)
        if not token:
            raise HTTPException(status_code=401, detail={"code": "ADMIN_AUTH_REQUIRED", "message": "Admin authentication required"})
        expires_at = self.sessions.get(token)
        if not expires_at or expires_at < time.time():
            self.sessions.pop(token, None)
            raise HTTPException(status_code=401, detail={"code": "ADMIN_SESSION_EXPIRED", "message": "Admin session expired"})

    def _extract_token(self, request: Request) -> str | None:
        auth_header = request.headers.get("authorization", "")
        if auth_header.lower().startswith("bearer "):
            return auth_header.split(" ", 1)[1].strip()
        return request.cookies.get(self.COOKIE_NAME)

    def _write_password(self, password: str) -> None:
        password = password or ""
        if len(password) < 8:
            raise HTTPException(status_code=400, detail={"code": "WEAK_ADMIN_PASSWORD", "message": "Admin password must be at least 8 characters"})
        salt = secrets.token_bytes(16)
        iterations = 210_000
        digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        data = {
            "algorithm": "pbkdf2_sha256",
            "iterations": iterations,
            "salt": base64.b64encode(salt).decode("ascii"),
            "password_hash": base64.b64encode(digest).decode("ascii"),
        }
        self.auth_file.parent.mkdir(parents=True, exist_ok=True)
        self.auth_file.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def _verify_password(self, password: str) -> bool:
        data = self._read_auth()
        salt = base64.b64decode(data.get("salt") or "")
        expected = base64.b64decode(data.get("password_hash") or "")
        iterations = int(data.get("iterations") or 210_000)
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(actual, expected)

    def _read_auth(self) -> dict[str, Any]:
        if not self.auth_file.exists():
            return {}
        try:
            return json.loads(self.auth_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _ensure_setup_token(self) -> str:
        self.setup_token_file.parent.mkdir(parents=True, exist_ok=True)
        if self.setup_token_file.exists():
            token = self.setup_token_file.read_text(encoding="utf-8").strip()
            if token:
                return token
        token = secrets.token_urlsafe(24)
        self.setup_token_file.write_text(token + "\n", encoding="utf-8")
        try:
            os.chmod(self.setup_token_file, 0o600)
        except OSError:
            pass
        return token
