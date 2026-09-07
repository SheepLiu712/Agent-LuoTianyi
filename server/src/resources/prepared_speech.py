"""读取本地预制语音清单，不加载音频内容。"""

import io
import wave
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.utils.asyncio_helpers import run_sync_owned


@dataclass(frozen=True)
class PreparedSpeech:
    """预制语音的名称、音频文件位置、文字和呈现表情。"""

    name: str
    audio_path: Path
    text: str
    expression: str


def load_prepared_speech(manifest_path: str | Path) -> tuple[PreparedSpeech, ...]:
    """读取 manifest_path；相对音频路径限定在清单目录内，空表情解释为 normal。"""
    manifest = Path(manifest_path).resolve()
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError("预制语音 manifest 必须是列表")
    entries = []
    names: set[str] = set()
    for item in data:
        if not isinstance(item, dict):
            raise ValueError("预制语音条目必须是对象")
        for field in ("name", "audio_path", "text", "expression"):
            if not isinstance(item.get(field), str):
                raise ValueError(f"预制语音 {field} 必须是字符串")
        name = item["name"]
        if not name.strip() or name in names:
            raise ValueError("预制语音名称不能为空或重复")
        relative = Path(item["audio_path"])
        audio = (manifest.parent / relative).resolve()
        if (not item["audio_path"].strip() or relative.is_absolute()
                or not audio.is_relative_to(manifest.parent) or not audio.is_file()):
            raise ValueError(f"预制语音 {name} 的音频路径无效")
        names.add(name)
        entries.append(PreparedSpeech(name, audio, item["text"], item["expression"].strip() or "normal"))
    return tuple(entries)


@dataclass(frozen=True)
class _PreparedSpeechConfig:
    manifest: str | None

    @classmethod
    def from_dict(cls, config: dict[str, Any]) -> "_PreparedSpeechConfig":
        if not isinstance(config, dict):
            raise TypeError("prepared_speech 必须是字典")
        manifest = config.get("manifest")
        if manifest is not None and (not isinstance(manifest, str) or not manifest.strip()):
            raise ValueError("prepared_speech.manifest 必须是非空路径字符串")
        return cls(manifest)


class EmptyPreparedAudioError(Exception):
    """预制音频文件为空或没有音频帧。"""


@dataclass(frozen=True)
class PreparedAudio:
    """已验证的完整 WAV 文件字节。"""

    data: bytes


class PreparedSpeechResources:
    """按 manifest 名称管理本地资源描述，音频在读取请求时加载。"""

    def __init__(self, config: dict[str, Any]) -> None:
        """解析本层 config 并加载 manifest 描述；省略 manifest 时目录为空。"""
        self._config = _PreparedSpeechConfig.from_dict(config)
        self._root = Path(self._config.manifest).resolve().parent if self._config.manifest else None
        entries = load_prepared_speech(self._config.manifest) if self._config.manifest else ()
        self._entries = {entry.name: entry for entry in entries}

    def get(self, name: str) -> PreparedSpeech:
        """按资源名称返回描述，不读取音频；名称不存在时抛 KeyError。"""
        return self._entries[name]

    async def read_audio(self, name: str) -> PreparedAudio:
        """在工作线程中读取完整 WAV 并验证音频帧；不缓存文件内容。"""
        return await run_sync_owned(self._read_audio, name)

    def _read_audio(self, name: str) -> PreparedAudio:
        entry = self.get(name)
        path = entry.audio_path.resolve()
        if self._root is None or not path.is_relative_to(self._root):
            raise ValueError("预制音频路径超出资源目录")
        if path.suffix.lower() != ".wav":
            raise ValueError("预制音频当前只支持 WAV 文件")
        data = path.read_bytes()
        if not data:
            raise EmptyPreparedAudioError("预制音频文件为空")
        with wave.open(io.BytesIO(data), "rb") as audio:
            frames = audio.getnframes()
            if frames == 0:
                raise EmptyPreparedAudioError("预制音频没有音频帧")
            expected = frames * audio.getnchannels() * audio.getsampwidth()
            if len(audio.readframes(frames)) != expected:
                raise ValueError("预制音频文件不完整")
        return PreparedAudio(data)
