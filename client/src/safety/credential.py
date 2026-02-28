from ..utils.logger import get_logger
import os
import json
from typing import Tuple


logger = get_logger("credential")

def get_credential_path():
    cwd = os.getcwd() # root client directory
    temp_dir = os.path.join(cwd, "temp")
    os.makedirs(temp_dir, exist_ok=True)
    return os.path.join(temp_dir, "user.json")

def load_credentials() -> Tuple[str, str, bool]:
    try:
        path = get_credential_path()
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
                user_id = data.get("username", None)
                token = data.get("token", None)
                do_auto_login = data.get("auto_login", False)
                return user_id, token, do_auto_login
    except Exception as e:
        logger.error(f"Error loading credentials: {e}")

def save_credentials(user_id: str, token: str, do_auto_login: bool) -> None:
    try:
        path = get_credential_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump({
                "username": user_id,
                "token": token,
                "auto_login": do_auto_login
            }, f)
    except Exception as e:
        logger.error(f"Error saving credentials: {e}")