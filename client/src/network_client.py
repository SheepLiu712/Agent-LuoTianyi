import requests
from typing import Tuple, List, Dict
from .types import ConversationItem
from .utils.logger import get_logger
from .safety import credential, encrypt_pwd

import datetime
import os
import json
class NetworkClient:
    def __init__(self, base_url=None):
        self.logger = get_logger(self.__class__.__name__)
        if not base_url:
            print("Base URL not provided, using default.")
            base_url = "https://equilibrium-copyrighted-singer-smoke.trycloudflare.com"
        self.base_url = base_url
        self.user_id = None
        self.message_token = None
        self.login_token = None




    def login(self, username: str, password: str, request_token: bool = False) -> Tuple[bool, str]:
        try:
            encrypted_password = encrypt_pwd.encrypt_password(password, base_url=self.base_url)
            if not encrypted_password:
                return False, "Failed to encrypt password. Check server connection."
                
            resp = requests.post(f"{self.base_url}/auth/login", json={
                "username": username, 
                "password": encrypted_password,
                "request_token": request_token
            },verify=True)
            if resp.status_code == 200:
                data = resp.json()
                self.user_id = data.get("user_id")
                self.login_token = data.get("login_token")
                self.message_token = data.get("message_token")
                if request_token:
                    credential.save_credentials(self.user_id, self.login_token, True)
                else:
                    credential.save_credentials(self.user_id, None, False)

                return True, "Login Successful"
            else:
                try:
                    detail = resp.json().get("detail", "Login Failed")
                except:
                    detail = "Login Failed"
                return False, detail
        except Exception as e:
            return False, str(e)

    def auto_login(self, username: str, token: str) -> bool:
        try:
            resp = requests.post(f"{self.base_url}/auth/auto_login", json={"username": username, "token": token}, verify=True)
            if resp.status_code == 200:
                data = resp.json()
                self.user_id = data.get("user_id")
                self.login_token = data.get("login_token")
                self.message_token = data.get("message_token")
                credential.save_credentials(self.user_id, self.login_token, True)
                return True
            return False
        except Exception as e:
            print(f"Auto login error: {e}")
            return False

    def register(self, username: str, password: str, invite_code: str) -> Tuple[bool, str]:
        try:
            encrypted_password = encrypt_pwd.encrypt_password(password, base_url=self.base_url)
            if not encrypted_password:
                return False, "Failed to encrypt password. Check server connection."

            resp = requests.post(f"{self.base_url}/auth/register", 
                                 json={"username": username, "password": encrypted_password, "invite_code": invite_code}, verify=True)
            if resp.status_code == 200:
                return True, "Registration Successful"
            else:
                try:
                    detail = resp.json().get("detail", "Registration Failed")
                except:
                    detail = "Registration Failed"
                return False, detail
        except Exception as e:
            return False, str(e)

    def send_chat(self, text: str):
        if not self.user_id:
            yield {"text": "Not logged in"}
            return
            
        try:
            payload = {"text": text, "username": self.user_id, "token": self.message_token}
            # Use stream=True for SSE
            with requests.post(f"{self.base_url}/chat", json=payload, stream=True, verify=True) as resp:
                if resp.status_code == 200:
                    for line in resp.iter_lines():
                        if line:
                            decoded_line = line.decode('utf-8')
                            if decoded_line.startswith("data: "):
                                self.logger.debug(f"Received line ")
                                json_str = decoded_line[6:]
                                try:
                                    data = json.loads(json_str)
                                    yield data
                                except json.JSONDecodeError:
                                    pass
                else:
                    self.logger.error(f"Server Error: {resp.status_code}")
                    yield {"text": f"Error: {resp.status_code}"}
        except Exception as e:
            self.logger.error(f"Connection Error: {e}")
            yield {"text": f"Connection Error: {e}"}

    def get_history(self, count: int, end_index: int) -> Tuple[List[ConversationItem], int]:
        if not self.user_id:
            return [], 0
            
        try:
            params = {"username": self.user_id, "token": self.message_token, "count": count, "end_index": end_index}
            resp = requests.get(f"{self.base_url}/history", params=params, verify=True)
            if resp.status_code == 200:
                data = resp.json()
                # Ensure we handle the response correctly. The provided attachment showed ConversationItem mapping
                if "history" in data:
                    history = data["history"]
                    history_items = [ConversationItem(**item) for item in data.get("history", [])]
                    history_items = self.clean_history(history_items)
                    return history_items, data.get("start_index", 0)
                else:
                    return [], 0

        except Exception as e:
            self.logger.error(f"History Error: {e}")
        return [], 0
    
    def clean_history(self, history_items: List[ConversationItem]) -> List[ConversationItem]:
        # 检查历史记录中的图片项，如果图片不存在则向服务器请求重新生成图片
        modified_history = []
        for item in history_items:
            if item.type != 'image':
                modified_history.append(item)
                continue
            if os.path.exists(item.content):
                modified_history.append(item)
                continue
            # 图片不存在，向服务器请求重新生成图片
            try:
                payload = {"username": self.user_id, "token": self.message_token, "uuid": item.uuid}
                resp = requests.post(f"{self.base_url}/get_image", json=payload, stream=True, verify=True)
                # StreamingResponse(iter([image_data]), media_type=content_type) content_type = "image/png" / "image/jpeg"
                if resp.status_code == 200:
                    content_type = resp.headers.get("Content-Type", "image/png")
                    postfix = ".png"
                    if content_type == "image/jpeg":
                        postfix = ".jpg"
                    elif content_type == "image/gif":
                        postfix = ".gif"
                    # get new file path
                    cwd = os.getcwd()
                    new_file_path = os.path.join(cwd, "temp", "images", item.uuid + postfix)
                    os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
                    with open(new_file_path, "wb") as f:
                        f.write(resp.content)
                    item.content = new_file_path
                    modified_history.append(item)
                else:
                    self.logger.error(f"Failed to retrieve image for history item {item.uuid}, status code: {resp.status_code}")
                    modified_history.append(item)  # 图片无法获取，保留原路径，可能会显示为损坏图片
                    continue
                
                payload.update({"image_client_path": item.content})
                resp = requests.post(f"{self.base_url}/update_image_client_path", json=payload, verify=True)
                if resp.status_code != 200:
                    self.logger.error(f"Failed to update image path for history item {item.uuid}, status code: {resp.status_code}")
            except Exception as e:
                self.logger.error(f"Failed to retrieve image for history item {item.uuid}: {e}")
                
        return modified_history

    def network_hear_callback(self, text: str):
        return self.send_chat(text)

    def network_history_callback(self, count: int, end_index: int) -> Tuple[List[ConversationItem], int]:
        return self.get_history(count, end_index)

    def network_hear_picture_callback(self, image_path: str):
        if not self.user_id:
            yield {"text": "Not logged in"}
            return
            
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()

            # get new file path
            cwd = os.getcwd()
            postfix = os.path.splitext(image_path)[1]
            new_file_path = os.path.join(cwd, "temp", "images", datetime.datetime.now().strftime("%Y%m%d%H%M%S")+postfix)
            os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
            with open(new_file_path, "wb") as f:
                f.write(image_data)
            image_type = "image/png"  # default type
            if postfix.lower() in [".jpg", ".jpeg"]:
                image_type = "image/jpeg"
            elif postfix.lower() == ".gif":
                image_type = "image/gif"
            files = {
                "image": (os.path.basename(new_file_path), image_data, image_type)
            }
            data = {
                "username": self.user_id,
                "token": self.message_token,
                "image_client_path": new_file_path # send the new file path to server   
            }
            # Use stream=True for SSE
            with requests.post(f"{self.base_url}/picture_chat", data=data, files=files, stream=True, verify=True) as resp:
                if resp.status_code == 200:
                    for line in resp.iter_lines():
                        if line:
                            decoded_line = line.decode('utf-8')
                            if decoded_line.startswith("data: "):
                                json_str = decoded_line[6:]
                                try:
                                    data = json.loads(json_str)
                                    yield data
                                except json.JSONDecodeError:
                                    pass
                else:
                    self.logger.error(f"Server Error: {resp.status_code}")
                    yield {"text": f"Error: {resp.status_code}"}
        except Exception as e:
            self.logger.error(f"Connection Error: {e}")
            yield {"text": f"Connection Error: {e}"}