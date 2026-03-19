from typing import Tuple

import requests

from ..safety import encrypt_pwd
from ..utils.http_client import HttpClientFactory


class AuthApi:
    def __init__(self, base_url: str, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl
        self.session = HttpClientFactory.get_session(verify_ssl=self.verify_ssl)

    def login(self, username: str, password: str, request_token: bool = False) -> Tuple[bool, str, dict]:
        encrypted_password = encrypt_pwd.encrypt_password(
            password,
            base_url=self.base_url,
            verify_ssl=self.verify_ssl,
        )
        if not encrypted_password:
            return False, "Failed to encrypt password. Check server connection.", {}

        resp = self.session.post(
            f"{self.base_url}/auth/login",
            json={
                "username": username,
                "password": encrypted_password,
                "request_token": request_token,
            },
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            detail = "Login Failed"
            try:
                detail = resp.json().get("detail", detail)
            except Exception:
                pass
            return False, detail, {}

        data = resp.json()
        return True, "Login Successful", data

    def auto_login(self, username: str, token: str) -> tuple[bool, dict]:
        resp = self.session.post(
            f"{self.base_url}/auth/auto_login",
            json={"username": username, "token": token},
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code != 200:
            return False, {}
        return True, resp.json()

    def register(self, username: str, password: str, invite_code: str) -> Tuple[bool, str]:
        encrypted_password = encrypt_pwd.encrypt_password(
            password,
            base_url=self.base_url,
            verify_ssl=self.verify_ssl,
        )
        if not encrypted_password:
            return False, "Failed to encrypt password. Check server connection."

        resp = self.session.post(
            f"{self.base_url}/auth/register",
            json={"username": username, "password": encrypted_password, "invite_code": invite_code},
            verify=self.verify_ssl,
            timeout=15,
        )
        if resp.status_code == 200:
            return True, "Registration Successful"
        try:
            detail = resp.json().get("detail", "Registration Failed")
        except Exception:
            detail = "Registration Failed"
        return False, detail
