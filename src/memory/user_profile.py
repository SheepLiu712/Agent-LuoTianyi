from ..utils.logger import get_logger
import os
from typing import Dict, List, Optional, Any, Tuple
from ..llm.prompt_manager import PromptManager
import json
class UserProfile:
    def __init__(self, config: Dict[str, Any], prompt_manager: PromptManager):
        self.config = config
        self.prompt_manager = prompt_manager
        self.logger = get_logger(__name__)
        self._load_user_profile()

    def _load_user_profile(self) -> None:
        self.user_profile_path = self.config.get("profile_file", "user_profile.json")
        if not os.path.exists(os.path.dirname(self.user_profile_path)):
            os.makedirs(os.path.dirname(self.user_profile_path), exist_ok=True)
        try:
            with open(self.user_profile_path, 'r', encoding='utf-8') as f:
                self.user_profile = json.load(f)
        except Exception as e:
            self.user_profile = {
                "name": "你",
                "profile": ""
            }
            self.username = self.user_profile["name"]
            self.description = self.user_profile["profile"]
            self._save_user_profile()
        self.username = self.user_profile.get("name", "你")
        self.description = self.user_profile.get("profile", "")

    def _save_user_profile(self) -> None:
        self.user_profile["name"] = self.username
        self.user_profile["profile"] = self.description
        with open(self.user_profile_path, 'w', encoding='utf-8') as f:
            json.dump(self.user_profile, f, ensure_ascii=False, indent=4)

    def update_username(self, new_name:str) -> None:
        self.username = new_name
        self._save_user_profile()

    def update_description(self, profile: str) -> None:
        self.description = profile
        self._save_user_profile()

    def get_username(self) -> str:
        return self.username
