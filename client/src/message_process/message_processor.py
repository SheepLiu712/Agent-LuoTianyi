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
from typing import Callable
from ..network.event_types import AgentMessage

@dataclass
class OutgoingMessage:
    local_id: str
    kind: str
    payload: dict
    done_event: threading.Event
    result: dict | None = None

class MessageProcessor:
    def __init__(self,
                send_text_func: Callable[[str], dict],
                send_image_func: Callable[..., dict],
                send_typing_func: Callable[[], dict],
                message_listener_setter: Callable[[Callable[[AgentMessage], None] | None], None]):
        self._event_queue: queue.Queue = queue.Queue()
        self._send_queue: deque[OutgoingMessage] = deque()
        self._send_cond = threading.Condition()
        self._listener_thread = threading.Thread(target=self._listen_ws_events, daemon=True)
        self._sender_thread = threading.Thread(target=self._send_loop, daemon=True)
        self.model: Live2dModel | None = None
        self.response_signal: Callable[[str], None] | None = None # 为ui增加一条回复信息
        self.update_bubble_signal: Callable[[str, str], None] | None = None # 更新气泡信息

        self._reply_counter = 0
        self._running = True
        self._last_typing_time = None

        self.multimedia_stream: MultiMediaStream | None = MultiMediaStream()

        message_listener_setter(self.feed_agent_msg)
        self.send_text_func = send_text_func
        self.send_image_func = send_image_func
        self.send_typing_func = send_typing_func
        self.start()

    def start(self):
        self._listener_thread.start()
        self._sender_thread.start()
        self.multimedia_stream.start()

    def send_typing_event(self):
        # 1. 如果队列中有未发送的消息，不发送输入状态事件，避免过于频繁
        with self._send_cond:
            if self._send_queue:
                return
        # 2. 如果上次发送输入状态事件的时间距离现在不足0.5秒，也不发送，避免过于频繁
        if self._last_typing_time and time.time() - self._last_typing_time < 0.5:
            return
        # 3. 发送输入状态事件
        self._last_typing_time = time.time()
        local_id = self._next_local_id("typing")
        item = OutgoingMessage(
            local_id=local_id,
            kind="typing",
            payload={},
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

    def process_transport_message(self, response: AgentMessage): # 真正处理消息的函数

        if response.text:
            self.response_signal(response.text)

        if response.expression and self.model:
            self.model.set_expression_by_cmd(response.expression)

        if response.audio:
            self.multimedia_stream.feed(response.audio)

        if response.is_final_package:
            self.multimedia_stream.finish_one_sentense()

    def _send_loop(self):
        while self._running:
            with self._send_cond:
                while self._running and not self._send_queue:
                    self._send_cond.wait(timeout=0.5)
                if not self._running:
                    return
                item = self._send_queue[0]

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

    def set_signals(self, response_signal: Callable[[str], None], update_bubble_signal: Callable[[str, str], None]):
        self.response_signal = response_signal
        self.update_bubble_signal = update_bubble_signal

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
                ack_timeout=1.0,
            )
        if item.kind == "typing":
            return self.send_typing_func(ack_timeout=1.0)
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


    