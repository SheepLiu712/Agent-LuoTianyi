"""Drive raw adapter messages and network feedback for protocol fixture tests."""

import json

from src.adapter.websocket.chat._binding import Binding
from src.adapter.websocket.connection import AdapterConnection


async def receive_events(runtime, connection):
    adapter = runtime.chat_adapter
    handle = AdapterConnection()
    peer = Binding(connection.user_uuid, object(), connection.capabilities, adapter._config)
    adapter._bindings[handle] = peer
    if connection.stage is not None:
        await adapter._bind(connection.stage, peer)
    peer.release_business_outputs()
    try:
        while True:
            raw = await connection.websocket.receive_json()
            await adapter.receive(handle, json.dumps(raw, ensure_ascii=False))
            while not peer._outbox._queue.empty():
                delivery = await adapter.next_output(handle)
                await connection.websocket.send_json(json.loads(delivery.message))
                adapter.complete_output(handle, delivery.delivery_id)
    finally:
        await adapter.disconnect(handle)
