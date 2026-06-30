from __future__ import annotations

import re


_PARENTHETICAL_CONTENT_RE = re.compile(r"[\(（][^()（）]*[\)）]")


def build_sound_content(content: str) -> str:
    """生成用于 TTS 的文本，去掉括号内的动作、神态等非发声内容。"""
    text = content or ""
    previous = None
    while previous != text:
        previous = text
        text = _PARENTHETICAL_CONTENT_RE.sub("", text)
    cleaned = re.sub(r"[ \t]{2,}", " ", text).strip()
    corrected_cleaned = cleaned.replace("咯", "啰") # “咯”在TTS中会被读成ge，而不是作语气词时的luo。所以换一个字
    return corrected_cleaned
