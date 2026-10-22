from src.stage.call_stage import CallIngressReceipt

"""驱动真实 Session/Delivery 的协议与 Stage 测试夹具，不复制协议算法。"""
from types import SimpleNamespace
from src.adapter.websocket.call_v1._session import Session
from src.adapter.websocket.call_v1._binding import Binding
from src.adapter.websocket.call_v1.errors import CallTransportError
from src.adapter.websocket.call_v1._protocol_translate import parse_message


class ProtocolDriver:
    def __init__(self, *, call_id, user_id, character_id, sink, config=None, call_metrics=None):
        stage = SimpleNamespace(
            call_id=call_id, user_id=user_id, character_id=character_id, client_request_id="request"
        )
        self.session = Session(stage, config=config, call_metrics=call_metrics)
        self._sink = sink
        if isinstance(sink, StageOutputDriver):
            sink.session = self
            self.session._delivery._deliver = sink.emit
        else:

            async def accept(frame, fingerprint):
                return await sink.accept(frame, CallIngressReceipt(call_id, "client_to_server", frame.seq, fingerprint))

            self.session._accept = accept

    def __getattr__(self, name):
        if name == "client_cursor":
            return self.session._client_cursor
        if hasattr(self.session, name):
            return getattr(self.session, name)
        return getattr(self.session._delivery, name)

    async def receive_text(self, raw):
        frame = parse_message(raw)
        message = frame.control
        if message["type"] == "ack":
            self.session._delivery.acknowledge_server(int(message["ack_seq"]))
            return []
        if message["type"] == "nack":
            return self.session._delivery.replay_missing(int(message["missing_seq"]))
        if message["type"] == "call.resume":
            return self.resume(message)
        self.session._delivery.validate_client_control(message)
        return await self.session._receive_ordered(frame)

    async def receive_binary(self, raw):
        return await self.session._receive_ordered(parse_message(raw))

    async def receive_start(self, raw):
        frame = parse_message(raw)
        if frame.control["type"] != "call.start":
            raise CallTransportError("INVALID_CALL_START")
        binding = Binding(self.session, connection_id=object())
        binding.is_ready = True
        self.session._binding = binding
        # This unit-level probe observes only the receipt, excluding initial state output.
        await self.session._receive_start(binding, frame)
        import json

        outputs = []
        while not binding._outbox._queue.empty():
            item = await binding.next_output()
            binding.complete_output(item.delivery_id)
            if json.loads(item.message)["type"] == "ack":
                from src.adapter.websocket.call_v1._messages import WireOutput

                outputs.append(WireOutput(text=item.message))
        return outputs

    def resume(self, message):
        if message["call_id"] != self.call_id or message["character_id"] != self.character_id:
            raise CallTransportError("RESUME_OWNERSHIP_MISMATCH")
        cursor = int(message["last_contiguous_server_seq"])
        outputs = self.session._preview_resume(cursor)
        self.session._delivery.acknowledge_server(cursor)
        return outputs

    def close(self):
        self.session._closed = True
        self.session._pending.clear()
        self.session._client_fingerprints.clear()
        self.session._delivery.close()


class StageOutputDriver:
    def __init__(self, *, call_id, deliver, output_queue=None):
        self.call_id = call_id
        self.emit = deliver
        self.session = None

    def bind(self, *, stage, session):
        self.session = session
        session.session._stage = stage

    def __getattr__(self, name):
        return getattr(self.session.session._delivery, name)
