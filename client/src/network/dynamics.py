"""动态窗口的冻结请求；同步与后台入口共享协议解析。"""

from dataclasses import dataclass, field
from threading import Event

from ..utils.http_client import HttpClientFactory


@dataclass(frozen=True)
class DynamicRequest:
    context: tuple = field(repr=False)
    action: str
    base_url: str
    username: str | None
    token: str | None = field(repr=False)
    dynamic_id: str | None = None
    content: str = field(default="", repr=False)
    limit: int = 50
    cursor: str | None = None
    parent_comment_id: str | None = None

    def execute(self, cancelled: Event):
        if cancelled.is_set():
            return False, "Request cancelled", {}
        with HttpClientFactory.create_session() as session:
            payload = self.fetch(session)
        return payload.get("ok", False), payload.get("message", ""), payload

    def fetch(self, session) -> dict:
        reading = self.action in ("list", "comments")
        failure = {"ok": False, "items": [], "has_more": False, "next_cursor": None} if reading else {"ok": False}
        if not self.username or (not reading and not self.token):
            return {**failure, "message": "Not logged in"}
        path = "/dynamics"
        if self.action in ("comments", "comment"):
            path += f"/{self.dynamic_id}/comments"
        elif self.action == "read":
            path += "/read"
        try:
            if reading:
                params = {"username": self.username, "limit": self.limit}
                if self.cursor:
                    params["cursor"] = self.cursor
                headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
                response = session.get(
                    f"{self.base_url}{path}", params=params, headers=headers, verify=True, timeout=20
                )
            else:
                body = {"username": self.username, "token": self.token}
                if self.action in ("post", "comment"):
                    body["content"] = self.content
                if self.action == "comment":
                    body["parent_comment_id"] = self.parent_comment_id
                response = session.post(
                    f"{self.base_url}{path}", json=body, verify=True, timeout=15 if self.action == "read" else 20
                )
            if response.status_code != 200:
                detail = f"HTTP {response.status_code}"
                try:
                    detail = response.json().get("detail", detail)
                except Exception:
                    pass
                return {**failure, "message": detail}
            data = response.json()
            if self.action == "read":
                return data
            if not reading:
                return {"ok": True, "item": data.get("item")}
            data["ok"] = True
            return data
        except Exception as exc:
            return {**failure, "message": str(exc)}
