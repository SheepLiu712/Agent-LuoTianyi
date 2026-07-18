from __future__ import annotations

import re
from dataclasses import dataclass

from src.agent.main_chat import DEFAULT_TTS_TONE

from .call_models import CallTTSLine


_TONE_TO_TTS = {
    "中性": "happy",
    "欣喜": "happy",
    "温柔": "tender",
    "伤心": "sad",
    "伤感": "sad",
    "生气": "angry",
    "愤怒": "angry",
    "惊讶": "happy",
    "害怕": "sad",
}
_TONE_TO_EXPRESSION = {
    "中性": "微笑脸",
    "欣喜": "卖萌",
    "温柔": "温柔脸",
    "伤心": "难过脸",
    "伤感": "难过脸",
    "生气": "生气脸",
    "愤怒": "生气脸",
    "惊讶": "呆呆脸",
    "害怕": "害怕脸",
}


@dataclass
class _ResponseBuffer:
    text: str = ""
    next_seq: int = 0
    cancelled: bool = False


class CallResponseParser:
    """按换行把 Qwen 文本流转换为 TTS 句子。"""

    def __init__(self, call_id: str, default_tone: str = "中性") -> None:
        self.call_id = call_id
        self.default_tone = default_tone
        self._buffers: dict[str, _ResponseBuffer] = {}

    def feed_text_delta(self, response_id: str, delta: str) -> list[CallTTSLine]:
        buffer = self._buffers.setdefault(response_id, _ResponseBuffer())
        if buffer.cancelled or not delta:
            return []
        buffer.text += delta
        return self._flush_complete_lines(response_id, buffer)

    def flush_response(self, response_id: str) -> list[CallTTSLine]:
        buffer = self._buffers.get(response_id)
        if not buffer or buffer.cancelled:
            self._buffers.pop(response_id, None)
            return []
        result: list[CallTTSLine] = []
        if buffer.text.strip():
            result.append(self._parse_line(response_id, buffer.text.strip(), buffer))
        self._buffers.pop(response_id, None)
        return result

    def cancel_response(self, response_id: str) -> None:
        buffer = self._buffers.setdefault(response_id, _ResponseBuffer())
        buffer.cancelled = True
        buffer.text = ""

    def _flush_complete_lines(self, response_id: str, buffer: _ResponseBuffer) -> list[CallTTSLine]:
        result: list[CallTTSLine] = []
        while "\n" in buffer.text:
            line, buffer.text = buffer.text.split("\n", 1)
            if line.strip():
                result.append(self._parse_line(response_id, line.strip(), buffer))
        return result

    def _parse_line(self, response_id: str, line: str, buffer: _ResponseBuffer) -> CallTTSLine:
        match = re.match(r"^\[([^\]]+)\]\s*(.*)$", line, re.S)
        if match:
            tone = match.group(1).strip()
            content = match.group(2).strip()
        else:
            tone = self.default_tone
            content = line.strip()
        if not content:
            return self._parse_line(response_id, f"[{self.default_tone}]嗯", buffer)
        normalized = tone if tone in _TONE_TO_TTS else self.default_tone
        tts_tone = _TONE_TO_TTS.get(normalized, DEFAULT_TTS_TONE)
        expression = _TONE_TO_EXPRESSION.get(normalized, "微笑脸")
        seq = buffer.next_seq
        buffer.next_seq += 1
        return CallTTSLine(
            call_id=self.call_id,
            response_id=response_id,
            seq=seq,
            content=content,
            tone=tts_tone,
            expression=expression,
        )
