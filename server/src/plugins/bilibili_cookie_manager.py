"""
Bilibili Cookie 管理器

不依赖浏览器，全部通过 Bilibili API 完成：
1. refresh_token 自动续期 SESSDATA（静默，无需用户操作）
2. QR 码登录（首次或无 refresh_token 时）：生成二维码保存为图片，轮询等待扫码
3. 手动导入 cookie（通过 API / CLI）

Cookie 仅在服务端内存中暂存（不落盘），由客户端自行持久化。
支持多组 Cookie 共存，供 Bilibili API 调用时随机选取。

依赖: requests, Pillow (可选，用于生成二维码图片)
"""

from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from src.utils.logger import get_logger

logger = get_logger(__name__)

BILI_PASSPORT = "https://passport.bilibili.com/x/passport-login/web"
BILI_OAUTH2 = "https://passport.bilibili.com/x/passport-login/oauth2"


# ── Cookie 数据模型 ─────────────────────────────────────────────


@dataclass
class BilibiliCookies:
    """Bilibili cookie 存储结构。"""

    SESSDATA: str = ""
    bili_jct: str = ""
    bili_ticket: str = ""
    refresh_token: str = ""
    expires_at: Optional[str] = None          # SESSDATA 过期时间
    ticket_expires_at: Optional[str] = None    # bili_ticket 过期时间
    last_refresh: Optional[str] = None
    source: str = "unknown"                    # 来源标识（password_login / sms_login / qrcode / manual / api_refresh）
    extras: Dict[str, str] = field(default_factory=dict)

    @property
    def is_sessdata_valid(self) -> bool:
        if not self.SESSDATA or not self.expires_at:
            return False
        try:
            return datetime.fromisoformat(self.expires_at) > datetime.now()
        except (ValueError, TypeError):
            return False

    @property
    def is_valid(self) -> bool:
        return self.is_sessdata_valid

    @property
    def sessdata_remaining_days(self) -> Optional[float]:
        if not self.expires_at:
            return None
        try:
            return (datetime.fromisoformat(self.expires_at) - datetime.now()).total_seconds() / 86400
        except (ValueError, TypeError):
            return None

    def to_dict(self) -> Dict[str, str]:
        return {k: v for k, v in asdict(self).items() if v}


# ── Cookie 解码 ─────────────────────────────────────────────


def decode_sessdata(sessdata: str) -> Optional[int]:
    """解码 Bilibili SESSDATA，返回过期时间戳（秒）。

    SESSDATA 格式: {user_id_hex},{expiry_timestamp},{secret}
    原始字符串中逗号被编码为 %2C，解码后以逗号分隔三部分。
    """
    try:
        from urllib.parse import unquote
        decoded = unquote(sessdata)
        parts = decoded.split(",")
        if len(parts) >= 2:
            return int(parts[1])
        return None
    except (ValueError, IndexError, Exception) as e:
        logger.debug(f"Failed to decode SESSDATA: {e}")
        return None


def make_session() -> requests.Session:
    """创建一个模仿浏览器的 requests Session。"""
    s = requests.Session()
    s.headers.update({
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.6099.71 Safari/537.36"
        ),
        "Referer": "https://www.bilibili.com/",
    })
    return s


# ── Cookie 管理器 ─────────────────────────────────────────────


class BilibiliCookieManager:
    """管理 Bilibili cookies 的 API 登录、刷新和状态检查。

    Cookie 仅保存在服务端内存中，不写入磁盘。
    可同时持有来自不同客户端的多组 Cookie，
    在需要调用 Bilibili API 时随机选取一组。
    """

    def __init__(
        self,
        sessdata_threshold_days: int = 7,
        ticket_threshold_hours: int = 2,
        check_interval_seconds: int = 3600,
        qrcode_image_path: str = "data/bilibili/qrcode.png",
    ):
        self.sessdata_threshold_days = sessdata_threshold_days
        self.ticket_threshold_hours = ticket_threshold_hours
        self.check_interval = check_interval_seconds
        self.qrcode_image_path = qrcode_image_path

        # 多组 Cookie 集合（仅内存，不落盘）
        self._cookie_sets: List[BilibiliCookies] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._session = make_session()

        logger.info("BilibiliCookieManager initialized (in-memory only, no file persistence)")

    # ── 内部工具 ─────────────────────────────────────────────

    @staticmethod
    def _apply_dict(c: BilibiliCookies, data: Dict[str, str]) -> None:
        """将 dict 数据写入 BilibiliCookies 实例。"""
        c.SESSDATA = data.get("SESSDATA", c.SESSDATA)
        c.bili_jct = data.get("bili_jct", c.bili_jct)
        c.bili_ticket = data.get("bili_ticket", c.bili_ticket)
        c.refresh_token = data.get("refresh_token", c.refresh_token)

        if c.SESSDATA:
            ts = decode_sessdata(c.SESSDATA)
            if ts:
                c.expires_at = datetime.fromtimestamp(ts).isoformat()

        c.last_refresh = datetime.now().isoformat()

        known = {"SESSDATA", "bili_jct", "bili_ticket", "refresh_token"}
        for k, v in data.items():
            if k not in known and v:
                c.extras[k] = v

    def _add_set(self, data: Dict[str, str], source: str) -> BilibiliCookies:
        """创建一组新 Cookie 并加入内存池。"""
        c = BilibiliCookies(source=source)
        self._apply_dict(c, data)
        with self._lock:
            self._cookie_sets.append(c)
        logger.info("Cookie set added (source=%s, total=%d)", source, len(self._cookie_sets))
        return c

    def _get_valid_sets(self) -> List[BilibiliCookies]:
        """获取所有有效的 Cookie 集合（线程安全）。"""
        with self._lock:
            return [c for c in self._cookie_sets if c.is_sessdata_valid and c.SESSDATA]

    # ── Cookie 存取 ─────────────────────────────────────────────

    def get_cookies(self) -> Dict[str, str]:
        """随机选取一组有效的 Cookie。

        供 OfficialFeedFetcher 等模块调用 Bilibili API 时使用。
        """
        valid = self._get_valid_sets()
        if not valid:
            logger.debug("No valid cookie sets available")
            return {}
        chosen = random.choice(valid)
        result = {"SESSDATA": chosen.SESSDATA, "bili_jct": chosen.bili_jct}
        if chosen.bili_ticket:
            result["bili_ticket"] = chosen.bili_ticket
        result.update(chosen.extras)
        return {k: v for k, v in result.items() if v}

    def set_cookies(self, cookies: Dict[str, str], source: str = "manual") -> None:
        """手动导入 cookies（从外部粘贴等）。"""
        self._add_set(cookies, source)
        logger.info("Bilibili cookies updated manually (source=%s)", source)

    # ── 刷新 Cookie（使用 refresh_token） ──────────────────

    def refresh_via_api(self) -> bool:
        """随机选取一个有 refresh_token 的 Cookie 集合，通过 Bilibili OAuth2 API 续期。

        返回 True 表示至少有一组刷新成功。
        """
        with self._lock:
            candidates = [(i, c) for i, c in enumerate(self._cookie_sets) if c.refresh_token]

        if not candidates:
            logger.info("No refresh_token available in any cookie set")
            return False

        idx, chosen = random.choice(candidates)
        logger.info("Attempting to refresh SESSDATA via refresh_token API (set #%d)...", idx)
        try:
            resp = self._session.post(
                f"{BILI_OAUTH2}/refresh_token",
                data={"refresh_token": chosen.refresh_token},
                timeout=15,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.warning(
                    "refresh_token API error: %s (code=%s)",
                    data.get("message", "unknown"),
                    data.get("code"),
                )
                return False

            token_info = data.get("data", {}).get("token_info", {})
            if not token_info:
                logger.warning("refresh_token response missing token_info")
                return False

            new_cookies = {
                "SESSDATA": token_info.get("sessdata", ""),
                "bili_jct": token_info.get("bili_jct", ""),
                "refresh_token": token_info.get("refresh_token", chosen.refresh_token),
            }

            with self._lock:
                if idx < len(self._cookie_sets):
                    self._apply_dict(self._cookie_sets[idx], new_cookies)
            logger.info("SESSDATA refreshed successfully via API (set #%d)", idx)
            return True

        except requests.RequestException as e:
            logger.error(f"refresh_token API request failed: {e}")
            return False

    # ── QR 码登录 ──────────────────────────────────────────

    def generate_qrcode(self) -> Optional[Dict[str, Any]]:
        """生成 B站 登录二维码，返回 {'url': ..., 'qrcode_key': ...}。

        二维码图片会保存到 self.qrcode_image_path。
        """
        try:
            resp = self._session.get(
                f"{BILI_PASSPORT}/qrcode/generate",
                timeout=15,
            )
            data = resp.json()
            if data.get("code") != 0:
                logger.error("QR code generate failed: %s", data.get("message"))
                return None

            result = data.get("data", {})
            url = result.get("url", "")
            qrcode_key = result.get("qrcode_key", "")

            if not url or not qrcode_key:
                logger.error("QR code generate response missing url or qrcode_key")
                return None

            self._save_qrcode_image(url)
            return {"url": url, "qrcode_key": qrcode_key}

        except requests.RequestException as e:
            logger.error(f"QR code generate request failed: {e}")
            return None

    def _save_qrcode_image(self, url: str) -> None:
        """将二维码 URL 生成图片保存到本地。"""
        qr_path = Path(self.qrcode_image_path)
        qr_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            import qrcode
            img = qrcode.make(url)
            img.save(qr_path)
            logger.info("QR code image saved to %s", qr_path)
        except ImportError:
            logger.info(
                "QR code URL: %s\n"
                "Install 'qrcode' (pip install qrcode[pil]) to auto-save as image. "
                "For now, open this URL or scan it with your phone.",
                url,
            )

    def poll_qrcode_login(self, qrcode_key: str, timeout: int = 120) -> bool:
        """轮询 QR 码扫码结果。

        Args:
            qrcode_key: QR 码的 key（由 generate_qrcode 返回）
            timeout: 最长等待秒数（默认 120）

        Returns:
            True 表示登录成功，cookies 已加入内存池
        """
        logger.info("Polling QR code scan result (timeout=%ds)...", timeout)
        start_time = time.time()
        poll_interval = 2

        while time.time() - start_time < timeout:
            try:
                resp = self._session.get(
                    f"{BILI_PASSPORT}/qrcode/poll",
                    params={"qrcode_key": qrcode_key},
                    timeout=10,
                )
                data = resp.json()
                code = data.get("code", -1)

                if code == 0:
                    login_data = data.get("data", {})
                    cookie_data = {
                        "SESSDATA": login_data.get("sessdata", ""),
                        "bili_jct": login_data.get("bili_jct", ""),
                        "refresh_token": login_data.get("refresh_token", ""),
                    }
                    for c in login_data.get("set_cookies", []):
                        if c.get("name") in ("bili_ticket",):
                            cookie_data[c["name"]] = c.get("value", "")

                    self._add_set(cookie_data, source="qrcode_login")
                    logger.info("QR code login successful! Cookies added to pool.")
                    return True

                elif code == 86101:
                    elapsed = int(time.time() - start_time)
                    if elapsed % 10 == 0:
                        logger.info("Waiting for QR code scan... (%ds elapsed)", elapsed)

                elif code == 86090:
                    logger.info("QR code scanned, waiting for confirmation...")

                elif code == 86038:
                    logger.warning("QR code expired, need to generate a new one")
                    return False

                else:
                    logger.warning("QR code poll unknown code=%s: %s", code, data)

            except requests.RequestException as e:
                logger.error(f"QR code poll request failed: {e}")

            time.sleep(poll_interval)

        logger.warning("QR code login timeout after %d seconds", timeout)
        return False

    # ── 供客户端驱动的 QR 登录 ─────────────────────────────

    def generate_qrcode_for_client(self) -> Optional[Dict[str, Any]]:
        """生成 QR 码并返回 url 和 key（客户端自行显示二维码）。"""
        return self.generate_qrcode()

    def poll_qrcode_for_client(self, qrcode_key: str) -> Dict[str, Any]:
        """客户端驱动 QR 码轮询：将结果中的 cookies 加入内存池。

        Returns:
            {"status": "waiting"|"scanned"|"success"|"expired"|"error",
             "message": "...",
             "cookies": {...}}  # 仅 success 时有
        """
        try:
            resp = self._session.get(
                f"{BILI_PASSPORT}/qrcode/poll",
                params={"qrcode_key": qrcode_key},
                timeout=10,
            )
            data = resp.json()
            code = data.get("code", -1)

            if code == 0:
                login_data = data.get("data", {})
                cookie_data = {
                    "SESSDATA": login_data.get("sessdata", ""),
                    "bili_jct": login_data.get("bili_jct", ""),
                    "refresh_token": login_data.get("refresh_token", ""),
                }
                for c in login_data.get("set_cookies", []):
                    if c.get("name") in ("bili_ticket",):
                        cookie_data[c["name"]] = c.get("value", "")

                self._add_set(cookie_data, source="qrcode_client")

                return {"status": "success", "message": "扫码成功", "cookies": cookie_data}
            elif code == 86101:
                return {"status": "waiting", "message": "等待扫码"}
            elif code == 86090:
                return {"status": "scanned", "message": "已扫码，请在手机上确认"}
            elif code == 86038:
                return {"status": "expired", "message": "二维码已过期"}
            else:
                return {"status": "error", "message": f"未知状态 code={code}"}
        except requests.RequestException as e:
            return {"status": "error", "message": f"请求失败: {e}"}

    # ── 密码 / 短信登录 ─────────────────────────────────

    @staticmethod
    def _bili_encrypt_password(password: str, hash_str: str, pub_key: str) -> Optional[str]:
        """用 B站 RSA 公钥加密密码。"""
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric import padding as asym_padding
            from cryptography.hazmat.backends import default_backend
            import base64

            public_key = serialization.load_pem_public_key(pub_key.encode(), backend=default_backend())
            encrypted = public_key.encrypt(
                (hash_str + password).encode(),
                asym_padding.PKCS1v15(),
            )
            return base64.b64encode(encrypted).decode()
        except Exception as e:
            logger.error(f"RSA encrypt failed: {e}")
            return None

    def get_login_key(self) -> Optional[Dict[str, str]]:
        """获取 Bilibili RSA 公钥，供客户端本地加密使用。"""
        try:
            resp = self._session.get(f"{BILI_PASSPORT}/web/key", timeout=15)
            data = resp.json()
            if data.get("code") != 0:
                logger.error("Failed to get login key: %s", data.get("message"))
                return None
            key_data = data.get("data", {})
            pub_key = key_data.get("key", "")
            hash_str = key_data.get("hash", "")
            if not pub_key or not hash_str:
                logger.error("Login key response missing key or hash")
                return None
            return {"key": pub_key, "hash": hash_str}
        except requests.RequestException as e:
            logger.error(f"Failed to get login key: {e}")
            return None

    def login_with_encrypted_password(self, username: str, encrypted_password: str) -> Dict[str, Any]:
        """使用客户端已加密的密码登录 B站。

        客户端从 get_login_key() 获取公钥后自行 RSA 加密，
        服务端仅做转发，不接触密码明文。
        """
        logger.info("Processing client-encrypted password login...")
        try:
            resp = self._session.post(
                f"{BILI_PASSPORT}/web/login",
                data={
                    "username": username,
                    "password": encrypted_password,
                    "keep": "1",
                    "source": "main_web",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            login_data = resp.json()

            if login_data.get("code") != 0:
                msg = login_data.get("message", "登录失败")
                if login_data.get("code") == -449:
                    return {"success": False, "message": "需要验证码，请改用短信登录或 QR 码"}
                return {"success": False, "message": msg}

            cookie_dict = {}
            for c in resp.cookies:
                if c.name in ("SESSDATA", "bili_jct", "refresh_token", "bili_ticket"):
                    cookie_dict[c.name] = c.value

            if cookie_dict.get("SESSDATA"):
                self._add_set(cookie_dict, source="password_login")
                logger.info("Client-encrypted password login successful")
                return {"success": True, "message": "登录成功", "cookies": cookie_dict}
            return {"success": False, "message": "响应中未包含 SESSDATA"}

        except requests.RequestException as e:
            logger.error(f"Encrypted password login request failed: {e}")
            return {"success": False, "message": f"请求失败: {e}"}

    def login_with_password(self, username: str, password: str) -> Dict[str, Any]:
        """使用 B站 账号密码登录（服务端加密，兼容旧流程）。"""
        logger.info("Attempting Bilibili password login (server-side encrypt)...")
        key_data = self.get_login_key()
        if not key_data:
            return {"success": False, "message": "获取密钥失败"}

        encrypted_pw = self._bili_encrypt_password(password, key_data["hash"], key_data["key"])
        if not encrypted_pw:
            return {"success": False, "message": "密码加密失败"}

        return self.login_with_encrypted_password(username, encrypted_pw)

    def send_sms_code(self, phone: str, country_code: str = "86") -> Dict[str, Any]:
        """发送 B站 短信验证码。"""
        logger.info(f"Sending SMS code to {country_code} {phone[:3]}****")
        try:
            resp = self._session.post(
                f"{BILI_PASSPORT}/web/sms/send",
                data={
                    "tel": json.dumps({"tel": phone, "country_code": country_code}),
                    "source": "main_web",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            data = resp.json()
            if data.get("code") == 0:
                return {"success": True, "message": "验证码已发送"}
            return {"success": False, "message": data.get("message", "发送失败")}
        except requests.RequestException as e:
            return {"success": False, "message": f"请求失败: {e}"}

    def login_with_sms(self, phone: str, code: str, country_code: str = "86") -> Dict[str, Any]:
        """使用短信验证码登录 B站。"""
        logger.info(f"Attempting SMS login for {country_code} {phone[:3]}****")
        try:
            resp = self._session.post(
                f"{BILI_PASSPORT}/web/sms/login",
                data={
                    "tel": json.dumps({"tel": phone, "country_code": country_code}),
                    "code": code,
                    "keep": "1",
                    "source": "main_web",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=15,
            )
            data = resp.json()
            if data.get("code") != 0:
                return {"success": False, "message": data.get("message", "登录失败")}

            cookie_dict = {}
            for c in resp.cookies:
                if c.name in ("SESSDATA", "bili_jct", "refresh_token", "bili_ticket"):
                    cookie_dict[c.name] = c.value

            if cookie_dict.get("SESSDATA"):
                self._add_set(cookie_dict, source="sms_login")
                logger.info("SMS login successful")
                return {"success": True, "message": "登录成功", "cookies": cookie_dict}
            return {"success": False, "message": "响应中未包含 SESSDATA"}
        except requests.RequestException as e:
            return {"success": False, "message": f"请求失败: {e}"}

    async def login_via_qrcode(self, timeout: int = 120) -> bool:
        """完整的 QR 码登录流程：生成二维码 → 保存图片 → 轮询等待扫码。"""
        logger.info("Starting QR code login flow...")
        qr_info = self.generate_qrcode()
        if not qr_info:
            logger.error("Failed to generate QR code")
            return False

        logger.info(
            "QR code saved to %s. Please scan it with your Bilibili app.",
            self.qrcode_image_path,
        )

        short_url = qr_info.get("url", "")
        if len(short_url) > 80:
            short_url = short_url[:77] + "..."
        logger.info("QR code URL (open in browser if scan fails): %s", short_url)

        return self.poll_qrcode_login(qr_info["qrcode_key"], timeout=timeout)

    # ── 综合刷新 ───────────────────────────────────────────

    async def refresh(self) -> bool:
        """综合刷新策略：尝试 refresh_token API 续期。"""
        if self.refresh_via_api():
            return True

        logger.info("API refresh failed or no refresh_token available")
        return False

    # ── 状态检查 ─────────────────────────────────────────────

    def needs_refresh(self) -> bool:
        """检查是否有 Cookie 需要刷新。"""
        with self._lock:
            total = len(self._cookie_sets)
            valid = sum(1 for c in self._cookie_sets if c.is_sessdata_valid and c.SESSDATA)
        if total == 0:
            return True
        if valid < total:
            logger.info(
                "Cookie sets: %d valid / %d total, some need refresh",
                valid, total,
            )
        return valid == 0

    # ── 手动触发 ─────────────────────────────────────────────

    async def manual_refresh(self) -> Dict[str, Any]:
        """手动触发一次 cookie 刷新。"""
        logger.info("Manual cookie refresh triggered")
        success = self.refresh_via_api()
        valid = self._get_valid_sets()
        best = max(valid, key=lambda c: c.sessdata_remaining_days or 0) if valid else None
        return {
            "success": success,
            "has_sessdata": len(valid) > 0,
            "expires_at": best.expires_at if best else None,
            "remaining_days": best.sessdata_remaining_days if best else None,
        }

    def get_status(self) -> Dict[str, Any]:
        """返回 Cookie 池状态（无敏感信息）。"""
        with self._lock:
            total = len(self._cookie_sets)
            valid = sum(1 for c in self._cookie_sets if c.is_sessdata_valid and c.SESSDATA)
            best = max(self._cookie_sets, key=lambda c: c.sessdata_remaining_days or 0) if self._cookie_sets else None
        return {
            "has_sessdata": valid > 0,
            "pool_total": total,
            "pool_valid": valid,
            "expires_at": best.expires_at if best else None,
            "remaining_days": best.sessdata_remaining_days if best else None,
            "last_refresh": best.last_refresh if best else None,
            "needs_refresh": total > 0 and valid == 0,
        }
