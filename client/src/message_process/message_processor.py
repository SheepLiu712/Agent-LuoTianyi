import queue
from .multi_media_stream import MultiMediaStream
import threading
from ..live2d import Live2dModel
import time
import os
import base64
import datetime
from dataclasses import dataclass
from collections import deque
from typing import Callable, TYPE_CHECKING
from ..network.event_types import AgentMessage
from ..utils.logger import get_logger

if TYPE_CHECKING:
    from ..network.network_client import NetworkClient

@dataclass
class OutgoingMessage:
    local_id: str
    kind: str
    payload: dict
    done_event: threading.Event
    result: dict | None = None

class MessageProcessor:
    def __init__(self,
                network_client: "NetworkClient",
                ):
        self._event_queue: queue.Queue = queue.Queue() # 收到的WS消息会被放入这个队列，等待处理线程处理
        self._send_queue: deque[OutgoingMessage] = deque() # 需要发送的消息会被放入这个队列
        self._send_cond = threading.Condition() # 发送线程会等待这个条件变量，直到有消息需要发送
        self._listener_thread = threading.Thread(target=self._listen_ws_events, daemon=True) # 处理WS消息的线程
        self._sender_thread = threading.Thread(target=self._send_loop, daemon=True) # 处理发送消息的线程
        self.model: Live2dModel | None = None # Live2D模型实例，用于根据消息中的表情指令更新模型表情
        self.response_signal: Callable[[str, str], None] | None = None # 为ui增加一条回复信息
        self.update_bubble_signal: Callable[[str, str], None] | None = None # 更新气泡信息
        self.agent_thinking_signal: Callable[[bool], None] | None = None # 显示agent正在思考的状态
        self.local_tts_state_signal: Callable[[str, str], None] | None = None # 本地TTS状态变化的回调信号，参数为事件类型（start/finish）和对应的conv_uuid

        self._reply_counter = 0
        self._running = True
        self._last_typing_time = None

        self.multimedia_stream: MultiMediaStream | None = MultiMediaStream()
        self.multimedia_stream.set_local_playback_state_callback(self._on_local_tts_state)

        self.logger = get_logger("MessageProcessor")

        # 设置消息处理器发送消息的网络客户端接口，以及将消息处理器接收消息的函数传入网络客户端，以便网络客户端能将WS消息传入消息处理器
        network_client.network_set_message_listener(self.feed_agent_msg, self.change_agent_state)
        self.send_text_func:Callable[[str], dict] = network_client.send_chat
        self.send_image_func:Callable[..., dict] = network_client.send_image
        self.send_typing_func:Callable[[int], dict] = network_client.send_typing
        self.send_touch_func:Callable[[str], dict] = network_client.send_touch
        self.start()

        self.processing_uuid = None
        self.processing_audio: bytearray = bytearray()

    def start(self):
        self._listener_thread.start()
        self._sender_thread.start()
        self.multimedia_stream.start()

    def send_typing_event(self, text_length):
        # 1. 如果队列中有未发送的消息，不发送输入状态事件，避免过于频繁
        with self._send_cond:
            if self._send_queue:
                return
        # 2. 如果上次发送输入状态事件的时间距离现在不足0.25秒，也不发送，避免过于频繁
        if self._last_typing_time and time.time() - self._last_typing_time < 0.25 and text_length > 0:
            return
        # 3. 发送输入状态事件
        self._last_typing_time = time.time()
        local_id = self._next_local_id("typing")
        item = OutgoingMessage(
            local_id=local_id,
            kind="typing",
            payload={"text_length": text_length},
            done_event=threading.Event(),
        )
        with self._send_cond:
            self._send_queue.append(item)
            self._send_cond.notify()

    def send_text(self, text: str):
        local_id = self._next_local_id("txt")
        item = OutgoingMessage(
            local_id=local_id,
            kind="text",
            payload={"text": text},
            done_event=threading.Event(),
        )
        with self._send_cond:
            self._send_queue.append(item)
            self._send_cond.notify()
        return local_id

    def send_image(self, image_path: str):
        prepared = self._prepare_image_payload(image_path)
        if not prepared.get("ok", False):
            return

        local_id = self._next_local_id("img")
        item = OutgoingMessage(
            local_id=local_id,
            kind="image",
            payload={
                "image_base64": prepared["image_base64"],
                "mime_type": prepared["mime_type"],
                "image_client_path": prepared["image_client_path"],
            },
            done_event=threading.Event(),
        )
        with self._send_cond:
            self._send_queue.append(item)
            self._send_cond.notify()
        return local_id

    def send_touch(self, touch_area: str):
        local_id = self._next_local_id("touch")
        item = OutgoingMessage(
            local_id=local_id,
            kind="touch",
            payload={"touch_area": touch_area},
            done_event=threading.Event(),
        )
        with self._send_cond:
            self._send_queue.append(item)
            self._send_cond.notify()
        return local_id
    

    def play_local_tts_by_uuid(self, conv_uuid: str) -> bool:
        if not conv_uuid or not self.multimedia_stream:
            return False

        wav_path = os.path.join(os.getcwd(), "temp", "tts_output", f"{conv_uuid}.wav")
        if not os.path.exists(wav_path):
            return False
        # WAV header is typically 44 bytes; smaller/equal indicates no usable audio payload.
        if os.path.getsize(wav_path) <= 44:
            return False
        return self.multimedia_stream.feed_local_wav(wav_path, conv_uuid=conv_uuid)

    def stop_local_tts(self) -> bool:
        if not self.multimedia_stream:
            return False
        return self.multimedia_stream.stop_local_wav()

    def set_playback_volume(self, percent: int):
        if not self.multimedia_stream:
            return
        self.multimedia_stream.set_volume_percent(percent)

    def process_transport_message(self, response: AgentMessage): # 真正处理消息的函数
        if self.processing_uuid is None:
            self.processing_uuid = response.uuid
            self.processing_audio = bytearray()
        elif self.processing_uuid != response.uuid: # 如果uuid不同，说明是新的消息了，重置状态
            self.logger.warning(f"Received message with new uuid (old={self.processing_uuid}, new={response.uuid}), resetting processing state.")
            self.processing_uuid = response.uuid
            self.processing_audio = bytearray()

        if response.text:
            self.response_signal(response.uuid, response.text)

        if response.expression and self.model:
            self.model.set_expression_by_cmd(response.expression)

        if response.audio:
            self.multimedia_stream.feed(response.audio)
            try:
                chunk_bytes = base64.b64decode(response.audio)
                self.processing_audio.extend(chunk_bytes)
            except Exception as exc:
                self.logger.error(f"Failed to decode audio chunk (uuid={response.uuid}): {exc}")

        if response.is_final_package:
            self.multimedia_stream.finish_one_sentense()
            # 将最终的音频结果保存到本地
            saved_uuid = self.processing_uuid
            ret = self._save_audio_to_temp(self.processing_audio, saved_uuid, ".wav")
            self.processing_audio = bytearray()
            self.processing_uuid = None
            if ret and self.update_bubble_signal:
                # 通知UI对应的气泡有本地音频可播放
                try:
                    self.update_bubble_signal(saved_uuid, "has_audio")
                except Exception as exc:
                    self.logger.error(f"Failed to emit update_bubble_signal for audio (uuid={saved_uuid}): {exc}")

    def _send_loop(self):
        while self._running:
            with self._send_cond:
                while self._running and not self._send_queue:
                    self._send_cond.wait(timeout=0.5)
                if not self._running:
                    return
                item = self._send_queue[0]

            self.update_bubble_signal(item.local_id, "waiting")
            ack = self._send_one(item)
            if ack.get("ok", False):
                with self._send_cond:
                    if self._send_queue and self._send_queue[0] is item:
                        self._send_queue.popleft()
                item.result = ack
                item.done_event.set()
                self.update_bubble_signal(item.local_id, "submitted")
                continue

            error_text = str(ack.get("error") or "")
            self.logger.error(f"Failed to send message (local_id={item.local_id}): {error_text}")
            if self._is_terminal_send_error(error_text) or ack.get("drop", False):
                with self._send_cond:
                    if self._send_queue and self._send_queue[0] is item:
                        self._send_queue.popleft()
                item.result = ack
                item.done_event.set()
                self.update_bubble_signal(item.local_id, "failed")
                continue
            self.update_bubble_signal(item.local_id, "waiting")
            # Retransmit head item after 1s when ack timeout/disconnect occurs.
            time.sleep(1.0)

    def feed_agent_msg(self, payload: AgentMessage): # 接收WS传来的消息，放入队列等待处理
        self._event_queue.put(payload)
    
    def change_agent_state(self, state: str):
        if self.agent_thinking_signal:
            self.agent_thinking_signal(state)

    def set_signals(
        self,
        response_signal: Callable[[str, str], None],
        update_bubble_signal: Callable[[str, str], None],
        agent_thinking_signal: Callable[[str], None],
        local_tts_state_signal: Callable[[str, str], None] | None = None,
    ):
        self.response_signal = response_signal
        self.update_bubble_signal = update_bubble_signal
        self.agent_thinking_signal = agent_thinking_signal
        self.local_tts_state_signal = local_tts_state_signal

    def _on_local_tts_state(self, event: str, conv_uuid: str):
        if self.local_tts_state_signal:
            self.local_tts_state_signal(event, conv_uuid)

    def set_model(self, model: Live2dModel):
        self.model = model
        self.multimedia_stream.model = model

    def _listen_ws_events(self): # 处理线程
        while self._running:
            payload = self._event_queue.get()
            if payload is None:
                break
            self.process_transport_message(payload)

    def _next_local_id(self, prefix: str) -> str:
        self._reply_counter += 1
        return f"{prefix}_{int(time.time() * 1000)}_{self._reply_counter}"



    def _send_one(self, item: OutgoingMessage) -> dict:
        if item.kind == "text":
            return self.send_text_func(item.payload["text"], ack_timeout=1.0)
        if item.kind == "image":
            return self.send_image_func(
                image_base64=item.payload["image_base64"],
                mime_type=item.payload["mime_type"],
                image_client_path=item.payload["image_client_path"],
                ack_timeout=5.0,
            )
        if item.kind == "typing":
            return self.send_typing_func(text_length=item.payload["text_length"], ack_timeout=1.0)
        if item.kind == "touch":
            return self.send_touch_func(touch_area=item.payload["touch_area"], ack_timeout=1.0)
        return {"ok": False, "request_id": None, "error": f"Unknown outgoing kind: {item.kind}", "drop": True}

    def _prepare_image_payload(self, image_path: str) -> dict:
        try:
            with open(image_path, "rb") as f:
                image_data = f.read()
            postfix = os.path.splitext(image_path)[1]
            new_file_path = self._save_image_to_temp(image_data, postfix)
        except Exception as exc:
            return {"ok": False, "error": f"Failed to read image file: {exc}", "drop": True}

        mime_type = "image/png"
        if postfix.lower() in [".jpg", ".jpeg"]:
            mime_type = "image/jpeg"
        elif postfix.lower() == ".gif":
            mime_type = "image/gif"

        return {
            "ok": True,
            "image_base64": base64.b64encode(image_data).decode("utf-8"),
            "mime_type": mime_type,
            "image_client_path": new_file_path,
        }
    
    def _save_audio_to_temp(self, audio_data: bytes, uuid: str | None, postfix: str) -> str:
        try:
            cwd = os.getcwd()
            safe_uuid = uuid or datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            new_file_path = os.path.join(
                cwd,
                "temp",
                "tts_output",
                safe_uuid + postfix,
            )
            os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
            with open(new_file_path, "wb") as f:
                f.write(audio_data)
            return new_file_path
        except Exception as exc:
            self.logger.error(f"Failed to save audio to temp: {exc}")
            return ""

    @staticmethod
    def _save_image_to_temp(image_data: bytes, postfix: str) -> str:
        cwd = os.getcwd()
        new_file_path = os.path.join(
            cwd,
            "temp",
            "images",
            datetime.datetime.now().strftime("%Y%m%d%H%M%S") + postfix,
        )
        os.makedirs(os.path.dirname(new_file_path), exist_ok=True)
        with open(new_file_path, "wb") as f:
            f.write(image_data)
        return new_file_path

    @staticmethod
    def _is_terminal_send_error(error_text: str) -> bool:
        text = error_text.lower()
        if "not logged in" in text:
            return True
        if "failed to read image file" in text:
            return True
        return False


    