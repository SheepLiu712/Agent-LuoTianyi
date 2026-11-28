"""按用户名缓存头像；每个服务器分别记录迁移待办、revision 与同步凭据。"""

from .network.avatars import AvatarRequest, normalize_server_url
from .safety.crypto import decrypt_secret, encrypt_secret
from .safety.storage import atomic_write_json, read_json_file, temp_path

SIDES = ("user", "agent")


class AvatarStore:
    def __init__(self, path: str | None = None):
        self.path = path or temp_path("avatars.json")
        self.accounts = read_json_file(self.path)
        self.username = None
        self.server_url = ""
        self.versions = {side: 0 for side in SIDES}
        self.tokens = {}

    def activate(self, username: str | None, server_url: str):
        self.username = username
        self.server_url = normalize_server_url(server_url)
        self.versions = {side: 0 for side in SIDES}
        if not username:
            return
        account = self.accounts.setdefault(username, {"images": {}, "servers": {}})
        servers = account["servers"]
        servers.setdefault(self.server_url, {"pending": [], "revision": None})
        if account.get("last_server") != self.server_url:
            # 每次换服（包括 A→B→A）迁移已知边，null 也已知；未知边留给远端快照。
            self.server["pending"] = [side for side in SIDES if side in account["images"]]
            self.server["revision"] = None
            account["last_server"] = self.server_url
            self.persist()

    @property
    def images(self):
        return self.accounts[self.username]["images"] if self.username else {}

    @property
    def server(self):
        return self.accounts[self.username]["servers"][self.server_url]

    def persist(self):
        atomic_write_json(self.path, self.accounts)

    def save(self, side: str, image: str | None):
        if side not in SIDES or not self.username:
            raise ValueError("账号或头像类型无效")
        self.images[side] = image
        self.versions[side] += 1
        if side not in self.server["pending"]:
            self.server["pending"].append(side)
        self.persist()

    def request(self, context: tuple, message_token: str) -> AvatarRequest:
        key = (self.username, self.server_url)
        if key not in self.tokens:
            self.tokens[key] = decrypt_secret(self.server.get("sync_token", ""))
        side = next((side for side in SIDES if side in self.server["pending"]), None)
        return AvatarRequest(
            context=context,
            base_url=self.server_url,
            username=self.username,
            message_token=message_token,
            sync_token=self.tokens[key],
            revision=self.server["revision"],
            side=side,
            image=self.images.get(side),
            versions=self.versions.copy(),
        )

    def apply(self, request: AvatarRequest, result: dict):
        key = (self.username, self.server_url)
        changed = False
        images_changed = False
        if result.get("clear_sync_token"):
            self.tokens[key] = None
            changed = "sync_token" in self.server
            self.server.pop("sync_token", None)
        snapshot = result.get("snapshot")
        token = snapshot.get("sync_token") if snapshot else result.get("sync_token")
        if token and token != self.tokens.get(key):
            self.tokens[key] = token
            encrypted = encrypt_secret(token)
            if encrypted:
                self.server["sync_token"] = encrypted
                changed = True
        if snapshot:
            if request.side and self.versions[request.side] == request.versions[request.side]:
                self.server["pending"].remove(request.side)
                changed = True
            for side in SIDES:
                if side not in self.server["pending"] and self.versions[side] == request.versions[side]:
                    images_changed |= side not in self.images or self.images[side] != snapshot[side]
                    self.images[side] = snapshot[side]
            changed |= images_changed or self.server["revision"] != snapshot["revision"]
            self.server["revision"] = snapshot["revision"]
        if changed:
            self.persist()
        return images_changed
