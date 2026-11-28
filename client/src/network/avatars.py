"""头像协议的冻结请求；后台线程不持有账号或窗口对象。"""

from dataclasses import dataclass, field
from threading import Event
from urllib.parse import urlsplit, urlunsplit


def normalize_server_url(value: str) -> str:
    parts = urlsplit(value.strip())
    scheme, host = parts.scheme.lower(), parts.netloc.lower()
    if (scheme == "https" and host.endswith(":443")) or (scheme == "http" and host.endswith(":80")):
        host = host.rsplit(":", 1)[0]
    return urlunsplit((scheme, host, parts.path.rstrip("/"), "", ""))


@dataclass(frozen=True)
class AvatarRequest:
    context: tuple = field(repr=False)
    base_url: str
    username: str
    message_token: str = field(repr=False)
    sync_token: str | None = field(default=None, repr=False)
    revision: str | None = None
    side: str | None = None
    image: str | None = field(default=None, repr=False)
    versions: dict = field(default_factory=dict, repr=False)

    def fetch(self, session, cancelled: Event) -> dict:
        clear_token = False
        try:
            token = self.sync_token or self.message_token
            for attempt in range(2):
                if cancelled.is_set():
                    return {"ok": False, "message": "Request cancelled"}
                headers = {"Authorization": f"Bearer {token}"}
                if self.side is None and self.revision:
                    headers["If-None-Match"] = self.revision
                options = dict(params={"username": self.username}, headers=headers, verify=True, timeout=15)
                if self.side:
                    response = session.put(
                        f"{self.base_url}/avatars/{self.side}", json={"image": self.image}, **options
                    )
                else:
                    response = session.get(f"{self.base_url}/avatars", **options)
                if response.status_code == 401 and self.sync_token and attempt == 0:
                    clear_token = True
                    token = self.message_token
                    continue
                if response.status_code == 304 and self.side is None:
                    return {
                        "ok": True,
                        "not_modified": True,
                        "sync_token": response.headers.get("X-Avatar-Token"),
                        "clear_sync_token": clear_token,
                    }
                if response.status_code != 200:
                    return {
                        "ok": False,
                        "message": f"HTTP {response.status_code}",
                        "clear_sync_token": clear_token,
                    }
                snapshot = response.json()
                return {"ok": True, "snapshot": snapshot, "clear_sync_token": clear_token}
        except Exception as exc:
            return {"ok": False, "message": str(exc), "clear_sync_token": clear_token}
