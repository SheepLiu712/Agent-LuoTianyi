"""角色预制语音 Catalog 的模块测试。"""

import json
import wave
from pathlib import Path

import pytest

from src.agent.skills.expression.prepared_speech import PreparedSpeechCatalog


def _manifest(tmp_path: Path) -> Path:
    audio = tmp_path / "welcome.wav"
    with wave.open(str(audio), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes(b"\x00\x00" * 8)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "name": "welcome",
                    "audio_path": "welcome.wav",
                    "text": "欢迎回来",
                    "expression": "happy",
                }
            ]
        ),
        encoding="utf-8",
    )
    return manifest


@pytest.mark.asyncio
async def test_catalog_is_character_indexed_and_reads_validated_audio(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    catalog = PreparedSpeechCatalog({"luotianyi": {"manifest": str(manifest)}})

    entry = catalog.get("luotianyi", "welcome")

    assert entry.text == "欢迎回来"
    assert entry.expression == "happy"
    assert (await catalog.read_audio("luotianyi", "welcome")).data.startswith(b"RIFF")
    with pytest.raises(KeyError):
        catalog.get("unknown", "welcome")


def test_legacy_resources_package_is_absent() -> None:
    server_root = Path(__file__).resolve().parents[3]
    assert not (server_root / "src/resources").exists()
