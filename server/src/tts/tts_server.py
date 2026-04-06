import io
import os
import time
import atexit
import traceback
import multiprocessing
from queue import Empty
from typing import Any, Dict, Generator, Optional
from multiprocessing.queues import Queue as MPQueue
from multiprocessing.synchronize import Event as MPEvent

import yaml

from ..utils.logger import get_logger


def _build_absolute_path(path_value: Optional[str]) -> Optional[str]:
    if not path_value:
        return None
    if os.path.isabs(path_value):
        return path_value
    return os.path.abspath(path_value)


def _extract_model_paths_from_yaml(config_path: str) -> Dict[str, Any]:
    with open(config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}

    custom = data.get("custom", {}) if isinstance(data, dict) else {}
    gpt_path = _build_absolute_path(custom.get("t2s_weights_path"))
    sovits_path = _build_absolute_path(custom.get("vits_weights_path"))

    return {
        "gpt_model_path": gpt_path,
        "sovits_model_path": sovits_path,
        "device": custom.get("device"),
        "is_half": custom.get("is_half"),
    }


def _audio_to_wav_bytes(audio_data, samplerate: int) -> bytes:
    import soundfile as sf

    buffer = io.BytesIO()
    sf.write(buffer, audio_data, samplerate, format="WAV", subtype="PCM_16")
    return buffer.getvalue()


def _strip_wav_header(wav_bytes: bytes) -> bytes:
    # Parse RIFF/WAV chunks and return only the payload of the data chunk.
    if len(wav_bytes) < 12:
        return wav_bytes
    if wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        return wav_bytes

    offset = 12
    total = len(wav_bytes)
    while offset + 8 <= total:
        chunk_id = wav_bytes[offset : offset + 4]
        chunk_size = int.from_bytes(wav_bytes[offset + 4 : offset + 8], "little", signed=False)
        data_start = offset + 8
        data_end = data_start + chunk_size
        if data_end > total:
            return wav_bytes
        if chunk_id == b"data":
            return wav_bytes[data_start:data_end]
        # WAV chunks are word-aligned.
        offset = data_end + (chunk_size % 2)

    return wav_bytes


def _make_wav_chunk_streamable(wav_bytes: bytes) -> bytes:
    # Mark RIFF and data chunk sizes as unknown (0xFFFFFFFF), so appended PCM bytes
    # can still be read as one continuous WAV stream after direct concatenation.
    if len(wav_bytes) < 12:
        return wav_bytes
    if wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        return wav_bytes

    patched = bytearray(wav_bytes)
    patched[4:8] = (0xFFFFFFFF).to_bytes(4, "little", signed=False)

    offset = 12
    total = len(patched)
    while offset + 8 <= total:
        chunk_id = patched[offset : offset + 4]
        chunk_size = int.from_bytes(patched[offset + 4 : offset + 8], "little", signed=False)
        data_start = offset + 8
        data_end = data_start + chunk_size
        if data_end > total:
            return bytes(patched)
        if chunk_id == b"data":
            patched[offset + 4 : offset + 8] = (0xFFFFFFFF).to_bytes(4, "little", signed=False)
            break
        offset = data_end + (chunk_size % 2)

    return bytes(patched)


def _run_gsv_worker(
    config_path: str,
    request_queue: MPQueue,
    response_queue: MPQueue,
    ready_event: MPEvent,
    stop_event: MPEvent,
):
    logger = get_logger("TTSServerWorker")
    try:
        from gsv_tts import TTS

        model_config = _extract_model_paths_from_yaml(config_path)
        tts = TTS(
            device=model_config.get("device"),
            is_half=model_config.get("is_half"),
            models_dir=model_config.get("pretrained_models_path"),
            use_bert=True,
        )

        gpt_model_path = model_config.get("gpt_model_path")
        sovits_model_path = model_config.get("sovits_model_path")

        if gpt_model_path:
            tts.load_gpt_model(gpt_model_path)
            logger.info(f"Preloaded GPT model: {gpt_model_path}")
        else:
            tts.load_gpt_model()
            logger.info("Preloaded default GPT model")

        if sovits_model_path:
            tts.load_sovits_model(sovits_model_path)
            logger.info(f"Preloaded SoVITS model: {sovits_model_path}")
        else:
            tts.load_sovits_model()
            logger.info("Preloaded default SoVITS model")

        ready_event.set()
        logger.info("gsv_tts worker is ready")

        while not stop_event.is_set():
            try:
                message = request_queue.get(timeout=0.2)
            except Empty:
                continue
            except (EOFError, OSError):
                # Parent process closed queue handle (common during Ctrl+C shutdown on Windows).
                logger.info("gsv_tts worker request queue closed, exiting worker loop")
                break
            except KeyboardInterrupt:
                logger.info("gsv_tts worker interrupted, exiting worker loop")
                break

            command = message.get("command")
            request_id = message.get("request_id")

            if command == "shutdown":
                break

            if command == "health_check":
                response_queue.put({"request_id": request_id, "ok": True, "message": "ready"})
                continue

            if command != "synthesize":
                if command == "stream_synthesize":
                    try:
                        spk_audio_path = message["spk_audio_path"]
                        prompt_audio_path = message["prompt_audio_path"]
                        prompt_audio_text = message["prompt_audio_text"]
                        text = message["text"]

                        is_first_chunk = True
                        for clip in tts.infer_stream(
                            spk_audio_path=spk_audio_path,
                            prompt_audio_path=prompt_audio_path,
                            prompt_audio_text=prompt_audio_text,
                            text=text,
                        ):
                            chunk_bytes = _audio_to_wav_bytes(clip.audio_data, clip.samplerate)
                            if not is_first_chunk:
                                chunk_bytes = _strip_wav_header(chunk_bytes)
                            else:
                                chunk_bytes = _make_wav_chunk_streamable(chunk_bytes)
                                is_first_chunk = False

                            response_queue.put(
                                {
                                    "request_id": request_id,
                                    "ok": True,
                                    "audio_bytes": chunk_bytes,
                                    "is_final": False,
                                }
                            )

                        response_queue.put(
                            {
                                "request_id": request_id,
                                "ok": True,
                                "is_final": True,
                            }
                        )
                    except Exception as e:
                        response_queue.put(
                            {
                                "request_id": request_id,
                                "ok": False,
                                "error": str(e),
                                "traceback": traceback.format_exc(),
                                "is_final": True,
                            }
                        )
                    continue

                response_queue.put(
                    {
                        "request_id": request_id,
                        "ok": False,
                        "error": f"Unknown command: {command}",
                    }
                )
                continue

            try:
                spk_audio_path = message["spk_audio_path"]
                prompt_audio_path = message["prompt_audio_path"]
                prompt_audio_text = message["prompt_audio_text"]
                text = message["text"]

                clip = tts.infer(
                    spk_audio_path=spk_audio_path,
                    prompt_audio_path=prompt_audio_path,
                    prompt_audio_text=prompt_audio_text,
                    text=text,
                )
                wav_bytes = _audio_to_wav_bytes(clip.audio_data, clip.samplerate)

                response_queue.put(
                    {
                        "request_id": request_id,
                        "ok": True,
                        "audio_bytes": wav_bytes,
                        "audio_len_s": clip.audio_len_s,
                    }
                )
            except Exception as e:
                response_queue.put(
                    {
                        "request_id": request_id,
                        "ok": False,
                        "error": str(e),
                        "traceback": traceback.format_exc(),
                    }
                )
    except KeyboardInterrupt:
        logger.info("gsv_tts worker received KeyboardInterrupt, shutting down")
    except BaseException:
        try:
            response_queue.put(
                {
                    "request_id": "__boot__",
                    "ok": False,
                    "error": "Failed to boot gsv_tts worker",
                    "traceback": traceback.format_exc(),
                }
            )
        except Exception:
            pass
        ready_event.set()
    finally:
        stop_event.set()

class TTSServer:
    """
    Manages the lifecycle of a dedicated gsv_tts worker process.
    """
    def __init__(self, config_path: str, timeout: int = 600):
        self.config_path = config_path
        self.timeout = timeout
        self.logger = get_logger("TTSServer")
        self.server_process: Optional[multiprocessing.Process] = None
        self.request_queue: Optional[MPQueue] = None
        self.response_queue: Optional[MPQueue] = None
        self.ready_event: Optional[MPEvent] = None
        self.stop_event: Optional[MPEvent] = None
        self._request_counter = 0
        self._synthesize_lock = multiprocessing.Lock()

    def start(self):
        """Starts the gsv_tts worker process if not already running."""
        if self.server_process and self.server_process.is_alive():
            self.logger.info("gsv_tts worker is already running")
            return

        if not os.path.exists(self.config_path):
            self.logger.error(f"Config file not found at {self.config_path}")
            raise FileNotFoundError(f"Config file not found at {self.config_path}")

        self.request_queue = multiprocessing.Queue()
        self.response_queue = multiprocessing.Queue()
        self.ready_event = multiprocessing.Event()
        self.stop_event = multiprocessing.Event()

        self.logger.info("Starting gsv_tts worker in a separate process...")

        self.server_process = multiprocessing.Process(
            target=_run_gsv_worker,
            args=(
                self.config_path,
                self.request_queue,
                self.response_queue,
                self.ready_event,
                self.stop_event,
            ),
            daemon=True
        )
        self.server_process.start()

        if not self._wait_for_worker_ready(self.timeout):
            self.logger.error("Failed to start gsv_tts worker.")
            self.stop(force=True)
            raise RuntimeError("Failed to start gsv_tts worker")

        self.logger.info("gsv_tts worker started successfully")

        # Ensure cleanup on main process exit
        atexit.register(self.stop)

    def stop(self, force: bool = False):
        """Stops the gsv_tts worker process."""
        if not self.server_process:
            return

        self.logger.info("Stopping gsv_tts worker...")
        if self.stop_event:
            self.stop_event.set()
        try:
            if self.request_queue and not force:
                self.request_queue.put({"command": "shutdown", "request_id": "__shutdown__"})
        except Exception:
            pass

        if self.server_process.is_alive():
            self.server_process.join(timeout=10)
            if self.server_process.is_alive():
                self.logger.warning("gsv_tts worker did not exit gracefully, terminating...")
                self.server_process.terminate()
                self.server_process.join(timeout=5)

        self.server_process = None

        if self.request_queue is not None:
            try:
                self.request_queue.close()
                self.request_queue.cancel_join_thread()
            except Exception:
                pass
        if self.response_queue is not None:
            try:
                self.response_queue.close()
                self.response_queue.cancel_join_thread()
            except Exception:
                pass

        self.request_queue = None
        self.response_queue = None
        self.ready_event = None
        self.stop_event = None
        self.logger.info("gsv_tts worker stopped")

    def synthesize(
        self,
        text: str,
        spk_audio_path: str,
        prompt_audio_path: str,
        prompt_audio_text: str,
        timeout: int = 600,
    ) -> bytes:
        if not self.server_process or not self.server_process.is_alive():
            raise RuntimeError("gsv_tts worker is not running")

        if not self.request_queue or not self.response_queue:
            raise RuntimeError("gsv_tts worker queues are not initialized")

        with self._synthesize_lock:
            self._request_counter += 1
            request_id = f"req-{self._request_counter}"

            self.request_queue.put(
                {
                    "command": "synthesize",
                    "request_id": request_id,
                    "text": text,
                    "spk_audio_path": spk_audio_path,
                    "prompt_audio_path": prompt_audio_path,
                    "prompt_audio_text": prompt_audio_text,
                }
            )

            response = self._wait_for_response(request_id=request_id, timeout=timeout)
            if not response.get("ok"):
                error = response.get("error", "unknown error")
                tb = response.get("traceback")
                if tb:
                    self.logger.error(f"gsv_tts synthesize failed: {error}\n{tb}")
                raise RuntimeError(f"gsv_tts synthesize failed: {error}")
            return response.get("audio_bytes", b"")

    def stream_synthesize(
        self,
        text: str,
        spk_audio_path: str,
        prompt_audio_path: str,
        prompt_audio_text: str,
        timeout: int = 600,
    ) -> Generator[bytes, None, None]:
        if not self.server_process or not self.server_process.is_alive():
            raise RuntimeError("gsv_tts worker is not running")

        if not self.request_queue or not self.response_queue:
            raise RuntimeError("gsv_tts worker queues are not initialized")

        with self._synthesize_lock:
            self._request_counter += 1
            request_id = f"req-{self._request_counter}"

            self.request_queue.put(
                {
                    "command": "stream_synthesize",
                    "request_id": request_id,
                    "text": text,
                    "spk_audio_path": spk_audio_path,
                    "prompt_audio_path": prompt_audio_path,
                    "prompt_audio_text": prompt_audio_text,
                }
            )

            while True:
                response = self._wait_for_response(request_id=request_id, timeout=timeout)
                if not response.get("ok"):
                    error = response.get("error", "unknown error")
                    tb = response.get("traceback")
                    if tb:
                        self.logger.error(f"gsv_tts stream synthesize failed: {error}\n{tb}")
                    raise RuntimeError(f"gsv_tts stream synthesize failed: {error}")

                chunk = response.get("audio_bytes")
                if chunk:
                    yield chunk

                if response.get("is_final"):
                    break

    def _wait_for_worker_ready(self, timeout: int) -> bool:
        if not self.ready_event:
            return False

        if not self.ready_event.wait(timeout=timeout):
            return False

        if self.server_process and not self.server_process.is_alive():
            return False

        if self.response_queue:
            try:
                while True:
                    msg = self.response_queue.get_nowait()
                    if msg.get("request_id") == "__boot__" and not msg.get("ok"):
                        self.logger.error(msg.get("traceback", msg.get("error", "boot failed")))
                        return False
            except Empty:
                pass

        return True

    def _wait_for_response(self, request_id: str, timeout: int) -> Dict[str, Any]:
        start_time = time.time()
        while (time.time() - start_time) < timeout:
            if self.server_process and not self.server_process.is_alive():
                raise RuntimeError("gsv_tts worker exited unexpectedly")

            if not self.response_queue:
                raise RuntimeError("gsv_tts response queue is unavailable")

            if self.server_process and not self.server_process.is_alive():
                raise RuntimeError("gsv_tts worker exited unexpectedly")

            try:
                remaining = max(0.1, timeout - (time.time() - start_time))
                message = self.response_queue.get(timeout=min(1.0, remaining))
            except Empty:
                continue

            if message.get("request_id") == request_id:
                return message

            self.logger.warning(f"Discarding unexpected response id: {message.get('request_id')}")

        raise TimeoutError(f"Timed out waiting for gsv_tts response ({request_id})")
