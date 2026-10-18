"""Drive raw adapter messages and network feedback for protocol fixture tests."""

import json

from src.adapter.websocket.chat._peer import _ChatPeer
from src.adapter.websocket.connection import AdapterConnection


async def receive_events(runtime, connection):
    adapter = runtime.chat_adapter
    handle = AdapterConnection()
    peer = _ChatPeer(connection.user_uuid, object(), connection.capabilities, adapter._config)
    adapter._peers[handle] = peer
    stages = [b.stage for b in adapter._routes.values() if b.connection is connection]
    for stage in stages:
        await adapter._bind(stage, peer)
    peer._release_business_outputs()
    try:
        while True:
            raw = await connection.websocket.receive_json()
            await adapter.receive(handle, json.dumps(raw, ensure_ascii=False))
            while not peer.outbox._queue.empty():
                delivery = await adapter.next_output(handle)
                await connection.websocket.send_json(json.loads(delivery.message))
                adapter.complete_output(handle, delivery.delivery_id)
    finally:
        await adapter.disconnect(handle)
