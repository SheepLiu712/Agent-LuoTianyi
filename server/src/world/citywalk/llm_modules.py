from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class _Message:
    content: str


@dataclass
class _Choice:
    message: _Message


class _Response:
    def __init__(self, content: str) -> None:
        self.choices = [_Choice(_Message(content))]


class _ChatCompletions:
    def __init__(self, owner: "CitywalkLLMModules") -> None:
        self._owner = owner

    def create(self, *, messages: List[Dict[str, Any]], response_format: Dict[str, Any] | None = None, **_: Any) -> _Response:
        system_prompt, user_prompt, image_url = self._split_messages(messages)
        if image_url:
            content = self._owner.generate_vlm(prompt=user_prompt or system_prompt, image_url=image_url)
        elif response_format and response_format.get("type") == "json_object":
            content = self._owner.generate_json(system_prompt=system_prompt, user_prompt=user_prompt)
        else:
            content = self._owner.generate_text(system_prompt=system_prompt, user_prompt=user_prompt)
        return _Response(content)

    @staticmethod
    def _split_messages(messages: List[Dict[str, Any]]) -> tuple[str, str, Optional[str]]:
        system_parts: list[str] = []
        user_parts: list[str] = []
        image_url: Optional[str] = None
        for message in messages or []:
            role = message.get("role")
            content = message.get("content", "")
            if isinstance(content, list):
                for item in content:
                    if item.get("type") == "text":
                        user_parts.append(str(item.get("text") or ""))
                    elif item.get("type") == "image_url":
                        image = item.get("image_url") or {}
                        image_url = str(image.get("url") or "") or image_url
                continue
            if role == "system":
                system_parts.append(str(content))
            else:
                user_parts.append(str(content))
        return "\n".join(system_parts).strip(), "\n".join(user_parts).strip(), image_url


class _Chat:
    def __init__(self, owner: "CitywalkLLMModules") -> None:
        self.completions = _ChatCompletions(owner)


class CitywalkLLMModules:
    """OpenAI-compatible sync facade backed by LLMService modules."""

    def __init__(
        self,
        json_module: Any | None = None,
        text_module: Any | None = None,
        vlm_module: Any | None = None,
    ) -> None:
        self.json_module = json_module
        self.text_module = text_module
        self.vlm_module = vlm_module
        self.chat = _Chat(self)

    def generate_json(self, *, system_prompt: str, user_prompt: str) -> str:
        if self.json_module is None:
            raise RuntimeError("citywalk JSON LLM module is unavailable")
        return self._run(self.json_module.generate_response(system_prompt=system_prompt, user_prompt=user_prompt))

    def generate_text(self, *, system_prompt: str, user_prompt: str) -> str:
        module = self.text_module or self.json_module
        if module is None:
            raise RuntimeError("citywalk text LLM module is unavailable")
        return self._run(module.generate_response(system_prompt=system_prompt, user_prompt=user_prompt))

    def generate_vlm(self, *, prompt: str, image_url: str) -> str:
        if self.vlm_module is None:
            raise RuntimeError("citywalk VLM module is unavailable")
        response = self._run(self.vlm_module.generate_response(image_url, prompt=prompt))
        return (response or {}).get("content", "") if isinstance(response, dict) else str(response)

    @staticmethod
    def _run(awaitable: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(awaitable)
        raise RuntimeError("Citywalk LLM facade must be called from a synchronous worker thread")
