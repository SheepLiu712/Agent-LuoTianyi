import os
import re
from typing import Callable, List, Tuple

from . import AuthApi, WsTransport
from ..types import ConversationItem
from ..utils.logger import get_logger
from ..utils.http_client import HttpClientFactory
from ..safety import credential
from ..utils.llm_client import fetch_llm_providers


_SAFE_UUID_RE = re.compile(r"^[A-Za-z0-9_-]+$")


def _is_safe_uuid(value: str | None) -> bool:
    return bool(value and _SAFE_UUID_RE.fullmatch(value))


class NetworkClient:
    def __init__(self, base_url: str | None = None, verify_ssl: bool = True):
        self.logger = get_logger(self.__class__.__name__)
        if not base_url:
            raise ValueError("Base URL is required. Please check config/config.json")

        self.base_url = base_url.rstrip("/")
        self.verify_ssl = True

        self.user_id: str | None = None
        self.message_token: str | None = None
        self.login_token: str | None = None
        self._llm_providers: list | None = None

        self.auth_api = AuthApi(self.base_url, verify_ssl=self.verify_ssl)
        self.session = HttpClientFactory.get_session(verify_ssl=self.verify_ssl)
        self.ws_transport = WsTransport(
            self.base_url,
            username_getter=lambda: self.user_id,
            token_getter=lambda: self.message_token,
            verify_ssl=self.verify_ssl,
        )

    def set_base_url(self, base_url: str, verify_ssl: bool) -> None:
        """更新服务器地址，同步更新 AuthApi、WsTransport 和 HTTP 会话。"""
        self.base_url = base_url.rstrip("/")
        self.verify_ssl = True
        self.auth_api.set_base_url(self.base_url, verify_ssl=self.verify_ssl)
        self.session = HttpClientFactory.get_session(verify_ssl=self.verify_ssl)
        self.ws_transport.set_base_url(self.base_url, verify_ssl=self.verify_ssl)
        self._llm_providers = None
        self.logger.info(f"Base URL updated to: {self.base_url}")

    def get_llm_providers(self, force_refresh: bool = False) -> list:
        """获取服务端下发的 LLM 服务商预设列表（带缓存）。

        失败时不缓存空结果，下次调用会重新尝试。
        """
        if force_refresh:
            self._llm_providers = None
        if self._llm_providers is None:
            try:
                self._llm_providers = fetch_llm_providers(self.base_url)
            except Exception as exc:
                self.logger.warning(f"获取 LLM 服务商列表失败: {exc}")
                return []
        return self._llm_providers

    def login(self, username: str, password: str, request_token: bool = False) -> Tuple[bool, str]:
        try:
            success, msg, data = self.auth_api.login(username, password, request_token=request_token)
            if not success:
                return False, msg

            self.user_id = data.get("user_id")
            self.login_token = data.get("login_token")
            self.message_token = data.get("message_token")

            if request_token:
                credential.save_credentials(self.user_id, self.login_token, True)
            else:
                credential.save_credentials(self.user_id, None, False)

            self.ws_transport.start()
            return True, msg
        except Exception as exc:
            return False, str(exc)

    def auto_login(self, username: str, token: str) -> bool:
        try:
            success, data = self.auth_api.auto_login(username, token)
            if not success:
                return False

            self.user_id = data.get("user_id")
            self.login_token = data.get("login_token")
            self.message_token = data.get("message_token")
            credential.save_credentials(self.user_id, self.login_token, True)
            self.ws_transport.start()
            return True
        except Exception as exc:
            self.logger.error(f"Auto login error: {exc}")
            return False

    def register(self, username: str, password: str, invite_code: str) -> Tuple[bool, str]:
        try:
            return self.auth_api.register(username, password, invite_code)
        except Exception as exc:
            return False, str(exc)

    def reset_account(self, invite_code: str, new_username: str, new_password: str) -> Tuple[bool, str]:
        """通过邀请码重置账号的用户名和密码。"""
        try:
            return self.auth_api.reset_account(invite_code, new_username, new_password)
        except Exception as exc:
            return False, str(exc)


    def send_chat(self, text: str, is_proactive: bool = False, ack_timeout: float = 10.0, client_msg_id: str | None = None):
        if not self.user_id or not self.message_token:
            return {"ok": False, "request_id": client_msg_id, "error": "Not logged in", "drop": True}

        return self.ws_transport.submit_user_text(
            text,
            is_proactive=is_proactive,
            ack_timeout=ack_timeout,
            client_msg_id=client_msg_id,
        )

    def send_image(
        self,
        image_base64: str,
        mime_type: str,
        image_client_path: str | None = None,
        ack_timeout: float = 10.0,
        client_msg_id: str | None = None,
    ):
        if not self.user_id or not self.message_token:
            return {"ok": False, "request_id": client_msg_id, "error": "Not logged in", "drop": True}

        try:
            return self.ws_transport.submit_user_image(
                image_base64=image_base64,
                mime_type=mime_type,
                image_client_path=image_client_path,
                ack_timeout=ack_timeout,
                client_msg_id=client_msg_id,
            )
        except Exception as exc:
            self.logger.error(f"Connection Error: {exc}")
            return {"ok": False, "request_id": client_msg_id, "error": f"Connection Error: {exc}"}
        
    def send_typing(self, text_length: int, ack_timeout: float = 10.0, client_msg_id: str | None = None):
        if not self.user_id or not self.message_token:
            return {"ok": False, "request_id": client_msg_id, "error": "Not logged in", "drop": True}

        try:
            return self.ws_transport.submit_typing_event(
                text_length=text_length,
                ack_timeout=ack_timeout,
                client_msg_id=client_msg_id,
            )
        except Exception as exc:
            self.logger.error(f"Connection Error: {exc}")
            return {"ok": False, "request_id": client_msg_id, "error": f"Connection Error: {exc}"}

    def send_touch(
        self,
        touch_area: str | list,
        click_frequency: dict = None,
        touch_meta: dict = None,
        ack_timeout: float = 10.0,
        client_msg_id: str | None = None,
    ):
        if not self.user_id or not self.message_token:
            return {"ok": False, "request_id": client_msg_id, "error": "Not logged in", "drop": True}
        try:
            return self.ws_transport.submit_user_touch(
                touch_area=touch_area,
                click_frequency=click_frequency,
                touch_meta=touch_meta,
                ack_timeout=ack_timeout,
                client_msg_id=client_msg_id,
            )
        except Exception as exc:
            self.logger.error(f"Connection Error: {exc}")
            return {"ok": False, "request_id": client_msg_id, "error": f"Connection Error: {exc}"}

    def send_image_selecting(self, ack_timeout: float = 5.0):
        """通知服务端用户开始选择图片。"""
        if not self.user_id or not self.message_token:
            return {"ok": False, "request_id": None, "error": "Not logged in", "drop": True}
        try:
            return self.ws_transport.submit_image_selecting(ack_timeout=ack_timeout)
        except Exception as exc:
            self.logger.error(f"Connection Error: {exc}")
            return {"ok": False, "request_id": None, "error": f"Connection Error: {exc}"}

    def send_image_selecting_cancel(self, ack_timeout: float = 5.0):
        """通知服务端用户取消了图片选择。"""
        if not self.user_id or not self.message_token:
            return {"ok": False, "request_id": None, "error": "Not logged in", "drop": True}
        try:
            return self.ws_transport.submit_image_selecting_cancel(ack_timeout=ack_timeout)
        except Exception as exc:
            self.logger.error(f"Connection Error: {exc}")
            return {"ok": False, "request_id": None, "error": f"Connection Error: {exc}"}

    def get_preferences(self) -> dict:
        """从服务器获取偏好设置。"""
        if not self.user_id:
            return {}
        try:
            resp = self.session.post(
                f"{self.base_url}/preference/get",
                json={"username": self.user_id, "token": self.message_token},
                verify=self.verify_ssl,
                timeout=15,
            )
            if resp.status_code == 200:
                data = resp.json()
                return data.get("preferences", data)
            elif resp.status_code == 401:
                self.logger.warning("获取偏好设置失败: 未授权")
                return {}
            else:
                self.logger.warning(f"获取偏好设置失败: HTTP {resp.status_code}")
                return {}
        except Exception as exc:
            self.logger.error(f"获取偏好设置失败: {exc}")
            return {}

    def overwrite_preferences(self, preferences: dict) -> dict:
        """覆盖保存偏好设置到服务器。"""
        if not self.user_id:
            return {"status": "error", "message": "Not logged in"}
        try:
            resp = self.session.post(
                f"{self.base_url}/preference/overwrite",
                json={
                    "username": self.user_id,
                    "token": self.message_token,
                    "preferences": preferences,
                },
                verify=self.verify_ssl,
                timeout=15,
            )
            if resp.status_code == 200:
                return resp.json()
            elif resp.status_code == 401:
                return {"status": "error", "message": "Unauthorized"}
            else:
                return {"status": "error", "message": f"HTTP {resp.status_code}"}
        except Exception as exc:
            self.logger.error(f"保存偏好设置失败: {exc}")
            return {"status": "error", "message": str(exc)}

    def get_history(self, count: int, end_index: int) -> Tuple[List[ConversationItem], int]:
        if not self.user_id:
            return [], -1

        try:
            params = {
                "username": self.user_id,
                "count": count,
                "end_index": end_index,
            }
            headers = {}
            if self.message_token:
                headers["Authorization"] = f"Bearer {self.message_token}"
            resp = self.session.get(
                f"{self.base_url}/history",
                params=params,
                headers=headers,
                verify=self.verify_ssl,
                timeout=20,
            )
            if resp.status_code != 200:
                return [], -1

            data = resp.json()
            if "history" not in data:
                return [], -1

            history_items = [ConversationItem(**item) for item in data.get("history", [])]
            history_items = self._clean_history(history_items)
            return history_items, data.get("start_index", 0)
        except Exception as exc:
            self.logger.error(f"History Error: {exc}")
            return [], -1

    def get_dynamics(self, limit: int = 50, cursor: str | None = None) -> dict:
        if not self.user_id:
            return {"ok": False, "message": "Not logged in", "items": [], "has_more": False, "next_cursor": None}

        try:
            params = {
                "username": self.user_id,
                "limit": limit,
            }
            if cursor:
                params["cursor"] = cursor
            headers = {}
            if self.message_token:
                headers["Authorization"] = f"Bearer {self.message_token}"
            resp = self.session.get(
                f"{self.base_url}/dynamics",
                params=params,
                headers=headers,
                verify=self.verify_ssl,
                timeout=20,
            )
            if resp.status_code != 200:
                detail = f"HTTP {resp.status_code}"
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                self.logger.warning(f"获取动态失败: {detail}")
                return {"ok": False, "message": detail, "items": [], "has_more": False, "next_cursor": None}
            data = resp.json()
            data["ok"] = True
            return data
        except Exception as exc:
            self.logger.error(f"获取动态失败: {exc}")
            return {"ok": False, "message": str(exc), "items": [], "has_more": False, "next_cursor": None}

    def create_dynamic(self, content: str) -> dict:
        if not self.user_id or not self.message_token:
            return {"ok": False, "message": "Not logged in"}

        try:
            resp = self.session.post(
                f"{self.base_url}/dynamics",
                json={
                    "username": self.user_id,
                    "token": self.message_token,
                    "content": content,
                },
                verify=self.verify_ssl,
                timeout=20,
            )
            if resp.status_code != 200:
                detail = f"HTTP {resp.status_code}"
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                return {"ok": False, "message": detail}
            data = resp.json()
            return {"ok": True, "item": data.get("item")}
        except Exception as exc:
            self.logger.error(f"发布动态失败: {exc}")
            return {"ok": False, "message": str(exc)}

    def get_dynamic_comments(self, dynamic_id: str, limit: int = 100, cursor: str | None = None) -> dict:
        if not self.user_id:
            return {"ok": False, "message": "Not logged in", "items": [], "has_more": False, "next_cursor": None}

        try:
            params = {
                "username": self.user_id,
                "limit": limit,
            }
            if cursor:
                params["cursor"] = cursor
            headers = {}
            if self.message_token:
                headers["Authorization"] = f"Bearer {self.message_token}"
            resp = self.session.get(
                f"{self.base_url}/dynamics/{dynamic_id}/comments",
                params=params,
                headers=headers,
                verify=self.verify_ssl,
                timeout=20,
            )
            if resp.status_code != 200:
                detail = f"HTTP {resp.status_code}"
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                self.logger.warning(f"获取动态评论失败: {detail}")
                return {"ok": False, "message": detail, "items": [], "has_more": False, "next_cursor": None}
            data = resp.json()
            data["ok"] = True
            return data
        except Exception as exc:
            self.logger.error(f"获取动态评论失败: {exc}")
            return {"ok": False, "message": str(exc), "items": [], "has_more": False, "next_cursor": None}

    def create_dynamic_comment(self, dynamic_id: str, content: str, parent_comment_id: str | None = None) -> dict:
        if not self.user_id or not self.message_token:
            return {"ok": False, "message": "Not logged in"}

        try:
            resp = self.session.post(
                f"{self.base_url}/dynamics/{dynamic_id}/comments",
                json={
                    "username": self.user_id,
                    "token": self.message_token,
                    "content": content,
                    "parent_comment_id": parent_comment_id,
                },
                verify=self.verify_ssl,
                timeout=20,
            )
            if resp.status_code != 200:
                detail = f"HTTP {resp.status_code}"
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                return {"ok": False, "message": detail}
            data = resp.json()
            return {"ok": True, "item": data.get("item")}
        except Exception as exc:
            self.logger.error(f"发表评论失败: {exc}")
            return {"ok": False, "message": str(exc)}

    def get_dynamic_unread_status(self) -> dict:
        if not self.user_id:
            return {
                "ok": False,
                "message": "Not logged in",
                "has_unread": False,
                "unread_count": 0,
                "unread_dynamic_count": 0,
                "unread_comment_count": 0,
            }

        try:
            params = {
                "username": self.user_id,
            }
            headers = {}
            if self.message_token:
                headers["Authorization"] = f"Bearer {self.message_token}"
            resp = self.session.get(
                f"{self.base_url}/dynamics/unread",
                params=params,
                headers=headers,
                verify=self.verify_ssl,
                timeout=15,
            )
            if resp.status_code != 200:
                detail = f"HTTP {resp.status_code}"
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                self.logger.warning(f"获取动态未读状态失败: {detail}")
                return {
                    "ok": False,
                    "message": detail,
                    "has_unread": False,
                    "unread_count": 0,
                    "unread_dynamic_count": 0,
                    "unread_comment_count": 0,
                }
            data = resp.json()
            data["ok"] = True
            return data
        except Exception as exc:
            self.logger.error(f"获取动态未读状态失败: {exc}")
            return {
                "ok": False,
                "message": str(exc),
                "has_unread": False,
                "unread_count": 0,
                "unread_dynamic_count": 0,
                "unread_comment_count": 0,
            }

    def mark_dynamics_read(self) -> dict:
        if not self.user_id or not self.message_token:
            return {"ok": False, "message": "Not logged in"}

        try:
            resp = self.session.post(
                f"{self.base_url}/dynamics/read",
                json={
                    "username": self.user_id,
                    "token": self.message_token,
                },
                verify=self.verify_ssl,
                timeout=15,
            )
            if resp.status_code != 200:
                detail = f"HTTP {resp.status_code}"
                try:
                    detail = resp.json().get("detail", detail)
                except Exception:
                    pass
                return {"ok": False, "message": detail}
            return resp.json()
        except Exception as exc:
            self.logger.error(f"标记动态已读失败: {exc}")
            return {"ok": False, "message": str(exc)}


    def network_set_message_listener(
        self,
        listener: Callable[[dict], None] | None,
        agent_state_listener: Callable[[bool], None] | None,
        system_message_listener: Callable[[str], None] | None = None,
        llm_request_listener: Callable[[dict], object] | None = None,
        llm_mode_getter: Callable[[], dict[str, bool]] | None = None,
    ) -> None:
        self.ws_transport.set_agent_message_listener(
            listener,
            agent_state_listener,
            system_message_listener,
            llm_request_listener,
        )
        self.ws_transport.llm_mode_getter = llm_mode_getter

    ###### Internal methods ######

    def _clean_history(self, history_items: List[ConversationItem]) -> List[ConversationItem]:
        modified_history = []
        for item in history_items:
            if item.type != "image":
                modified_history.append(item)
                continue

            if os.path.exists(item.content):
                modified_history.append(item)
                continue

            item = self._get_image_from_server(item)
            modified_history.append(item)

        return modified_history
    
    def _get_image_from_server(self, item: ConversationItem) -> ConversationItem:
        try:
            if not _is_safe_uuid(item.uuid):
                self.logger.error(f"Unsafe uuid from server: {item.uuid}")
                return item
            payload = {"username": self.user_id, "token": self.message_token, "uuid": item.uuid}
            resp = self.session.post(
                f"{self.base_url}/get_image",
                json=payload,
                stream=True,
                verify=self.verify_ssl,
                timeout=20,
            )
            if resp.status_code != 200:
                self.logger.error(
                    f"Failed to retrieve image for history item {item.uuid}, status code: {resp.status_code}"
                )
                return item

            content_type = resp.headers.get("Content-Type", "image/png")
            postfix = ".png"
            if content_type == "image/jpeg":
                postfix = ".jpg"
            elif content_type == "image/gif":
                postfix = ".gif"

            cwd = os.getcwd()
            new_file_path = os.path.join(cwd, "temp", "images", item.uuid + postfix)
            os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
            with open(new_file_path, "wb") as f:
                f.write(resp.content)

            item.content = new_file_path
            

            payload.update({"image_client_path": item.content})
            update_resp = self.session.post(
                f"{self.base_url}/update_image_client_path",
                json=payload,
                verify=self.verify_ssl,
                timeout=20,
            )
            if update_resp.status_code != 200:
                self.logger.error(
                    f"Failed to update image path for history item {item.uuid}, status code: {update_resp.status_code}"
                )
        except Exception as exc:
            self.logger.error(f"Failed to retrieve image for history item {item.uuid}: {exc}")
        return item
