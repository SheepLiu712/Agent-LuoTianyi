import os
from typing import Callable, List, Tuple

import requests

from . import AuthApi, WsTransport
from ..types import ConversationItem
from ..utils.logger import get_logger
from ..utils.http_client import HttpClientFactory
from ..safety import credential


class NetworkClient:
    def __init__(self, base_url: str | None = None, verify_ssl: bool = True):
        self.logger = get_logger(self.__class__.__name__)
        if not base_url:
            raise ValueError("Base URL is required. Please check config/config.json")

        self.base_url = base_url.rstrip("/")
        self.verify_ssl = verify_ssl

        self.user_id: str | None = None
        self.message_token: str | None = None
        self.login_token: str | None = None

        self.auth_api = AuthApi(self.base_url, verify_ssl=self.verify_ssl)
        self.session = HttpClientFactory.get_session(verify_ssl=self.verify_ssl)
        self.ws_transport = WsTransport(
            self.base_url,
            username_getter=lambda: self.user_id,
            token_getter=lambda: self.message_token,
            verify_ssl=self.verify_ssl,
        )

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

    def send_chat(self, text: str, ack_timeout: float = 10.0):
        if not self.user_id or not self.message_token:
            return {"ok": False, "request_id": None, "error": "Not logged in", "drop": True}

        return self.ws_transport.submit_user_text(text, ack_timeout=ack_timeout)

    def send_image(self, image_base64: str, mime_type: str, image_client_path: str | None = None, ack_timeout: float = 10.0):
        if not self.user_id or not self.message_token:
            return {"ok": False, "request_id": None, "error": "Not logged in", "drop": True}

        try:
            return self.ws_transport.submit_user_image(
                image_base64=image_base64,
                mime_type=mime_type,
                image_client_path=image_client_path,
                ack_timeout=ack_timeout,
            )
        except Exception as exc:
            self.logger.error(f"Connection Error: {exc}")
            return {"ok": False, "request_id": None, "error": f"Connection Error: {exc}"}
        
    def send_typing(self, ack_timeout: float = 10.0):
        if not self.user_id or not self.message_token:
            return {"ok": False, "request_id": None, "error": "Not logged in", "drop": True}

        try:
            return self.ws_transport.submit_typing_event(ack_timeout=ack_timeout)
        except Exception as exc:
            self.logger.error(f"Connection Error: {exc}")
            return {"ok": False, "request_id": None, "error": f"Connection Error: {exc}"}
        

    def get_history(self, count: int, end_index: int) -> Tuple[List[ConversationItem], int]:
        if not self.user_id:
            return [], -1

        try:
            params = {
                "username": self.user_id,
                "token": self.message_token,
                "count": count,
                "end_index": end_index,
            }
            resp = self.session.get(f"{self.base_url}/history", params=params, verify=self.verify_ssl, timeout=20)
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


    def network_set_message_listener(self, listener: Callable[[dict], None] | None, agent_state_listener: Callable[[bool], None] | None) -> None:
        self.ws_transport.set_agent_message_listener(listener, agent_state_listener)

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
        finally:
            return item
