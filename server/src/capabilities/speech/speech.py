from __future__ import annotations

import asyncio
from typing import Generator, Dict

from src.capabilities.speech.tts_module import init_tts_module, TTSModule
from src.utils.asyncio_helpers import (
    DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
    run_sync_owned,
    wait_for_owned_tasks,
)
from src.utils.logger import get_logger


class SpeechCapability:
    """Action capability for saying text through TTS."""

    def __init__(self, config: Dict) -> None:
        self.logger = get_logger(__name__)
        self.tts_config = config
        self.tts_module: Dict[str, TTSModule] = {}
        self._stop_lock = asyncio.Lock()
        self._stopped_server_ids: set[int] = set()
        self._stop_signaled_server_ids: set[int] = set()
        self._stop_tasks: dict[int, asyncio.Task] = {}
        self.stop_timeout_seconds = DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS
        try:
            for character, tts_config in self.tts_config.items():
                self.tts_module[character] = init_tts_module(tts_config)
        except BaseException:
            self._abort_initialization()
            raise

    def ensure_dependencies(self) -> None:
        """检查语音能力依赖已经初始化。"""
        if self.tts_config is None:
            raise RuntimeError("SpeechCapability dependency is missing: tts_config")
        if self.tts_module is None:
            raise RuntimeError("SpeechCapability dependency is missing: tts_module")

    def shutdown(self) -> None:
        """Stop every character-specific TTS worker."""
        for tts_module in self.tts_module.values():
            tts_module.shutdown()

    async def say(self, character: str, text: str, tone: str) -> str:
        '''
        使用TTS合成语音。

        :param character: 角色名称
        :param text: 要合成的文本
        :param tone: 语音 tone
        :return: Base64编码的音频数据
        '''
        if character not in self.tts_module:
            raise ValueError(f"TTS module for character '{character}' is not initialized.")
        character_tts_module: TTSModule = self.tts_module[character]
        audio_bytes = await character_tts_module.synthesize_speech_with_tone(text, tone)
        return character_tts_module.encode_audio_to_base64(audio_bytes)

    def say_stream(self, character: str, text: str, tone: str) -> Generator[str, None, None]:
        '''
        使用TTS合成语音，采用流式输出方式。

        :param character: 角色名称
        :param text: 要合成的文本
        :param tone: 语音 tone
        :return: 生成器，逐块返回Base64编码的音频数据
        '''
        if character not in self.tts_module:
            raise ValueError(f"TTS module for character '{character}' is not initialized.")
        
        character_tts_module: TTSModule = self.tts_module[character]
        for chunk in character_tts_module.stream_synthesize_speech_with_tone(text, tone):
            yield character_tts_module.encode_audio_to_base64(chunk)

    def request_stop(self) -> None:
        """Synchronously wake active TTS requests before awaiting their workers."""
        errors: list[str] = []
        for server_id, server in self._distinct_servers().items():
            if server_id in self._stop_signaled_server_ids:
                continue
            request_stop = getattr(server, "request_stop", None)
            if request_stop is None:
                self._stop_signaled_server_ids.add(server_id)
                continue
            try:
                request_stop()
            except Exception as error:
                errors.append(f"{type(error).__name__}: {error}")
            else:
                self._stop_signaled_server_ids.add(server_id)
        if errors:
            raise RuntimeError("Failed to signal TTS shutdown: " + "; ".join(errors))

    def _distinct_servers(self) -> dict[int, object]:
        return {
            id(server): server
            for module in self.tts_module.values()
            if (server := getattr(module, "tts_server", None)) is not None
        }

    def _abort_initialization(self) -> None:
        """Synchronously release TTS workers when construction cannot complete."""
        errors: list[str] = []
        try:
            self.request_stop()
        except Exception as error:
            errors.append(str(error))

        for server_id, server in self._distinct_servers().items():
            if server_id in self._stopped_server_ids:
                continue
            try:
                server.stop()
            except Exception as error:
                errors.append(f"{type(error).__name__}: {error}")
            else:
                self._stopped_server_ids.add(server_id)

        if errors:
            self.logger.error("TTS initialization rollback had errors: " + "; ".join(errors))

    async def stop(self) -> None:
        """Stop each distinct TTS backend once, retrying only prior failures."""
        async with self._stop_lock:
            errors: list[str] = []
            try:
                self.request_stop()
            except Exception as error:
                errors.append(str(error))
            servers = self._distinct_servers()

            pending = [
                (server_id, server)
                for server_id, server in servers.items()
                if server_id not in self._stopped_server_ids
            ]
            if not pending:
                if errors:
                    raise RuntimeError("TTS shutdown failed: " + "; ".join(errors))
                return

            stop_tasks = getattr(self, "_stop_tasks", None)
            if stop_tasks is None:
                stop_tasks = self._stop_tasks = {}
            for server_id, server in pending:
                if server_id not in stop_tasks:
                    stop_tasks[server_id] = asyncio.create_task(run_sync_owned(server.stop))
            tasks = [stop_tasks[server_id] for server_id, _ in pending]
            cancellation: asyncio.CancelledError | None = None
            try:
                done, still_running = await wait_for_owned_tasks(
                    tasks,
                    timeout_seconds=getattr(
                        self,
                        "stop_timeout_seconds",
                        DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
                    ),
                )
            except asyncio.CancelledError as error:
                cancellation = error
                done, still_running = await asyncio.shield(
                    wait_for_owned_tasks(
                        tasks,
                        timeout_seconds=getattr(
                            self,
                            "stop_timeout_seconds",
                            DEFAULT_OWNED_TASK_STOP_TIMEOUT_SECONDS,
                        ),
                    )
                )
            for server_id, _server in pending:
                task = stop_tasks[server_id]
                if task not in done:
                    continue
                try:
                    task.result()
                except BaseException as error:
                    errors.append(f"{type(error).__name__}: {error}")
                else:
                    self._stopped_server_ids.add(server_id)
                finally:
                    stop_tasks.pop(server_id, None)

            if still_running:
                errors.append(f"{len(still_running)} TTS backend stop task(s) still running")

            if errors:
                raise RuntimeError("TTS shutdown failed: " + "; ".join(errors))
            if cancellation is not None:
                raise cancellation
