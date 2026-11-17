"""Physical WebSocket I/O shared by both authenticated adapter endpoints."""

import asyncio

from fastapi import WebSocketDisconnect

MAX_MESSAGE_BYTES = 16 * 1024 * 1024


async def _receive_message(websocket) -> str | bytes:
    event = await websocket.receive()
    if event.get("type") == "websocket.disconnect":
        raise WebSocketDisconnect(event.get("code", 1000))
    text, binary = event.get("text"), event.get("bytes")
    if (
        event.get("type") != "websocket.receive"
        or (text is None) == (binary is None)
        or (text is not None and not isinstance(text, str))
        or (binary is not None and not isinstance(binary, bytes))
    ):
        await websocket.close(code=1002, reason="invalid WebSocket message")
        raise WebSocketDisconnect(1002, "invalid WebSocket message")
    message = text if text is not None else binary
    size = len(message.encode("utf-8")) if isinstance(message, str) else len(message)
    if size > MAX_MESSAGE_BYTES:
        await websocket.close(code=1009, reason="message too large")
        raise WebSocketDisconnect(1009)
    return message


async def _reject_adapter_connection(websocket, error) -> None:
    try:
        if error.initial_message is not None:
            await websocket.send_text(error.initial_message)
        await websocket.close(code=error.close_code, reason=error.code[:123])
    except WebSocketDisconnect:
        pass


async def _send_pump(websocket, adapter, connection) -> None:
    while True:
        delivery = await adapter.next_output(connection)
        try:
            sending = (
                websocket.send_text(delivery.message)
                if isinstance(delivery.message, str)
                else websocket.send_bytes(delivery.message)
            )
            await asyncio.wait_for(sending, timeout=10.0)
        except BaseException as error:
            failure = error if isinstance(error, Exception) else ConnectionError("network send was cancelled")
            adapter.complete_output(connection, delivery.delivery_id, error=failure)
            raise
        else:
            adapter.complete_output(connection, delivery.delivery_id)


async def _receive_pump(websocket, adapter, connection) -> None:
    while True:
        await adapter.receive(connection, await _receive_message(websocket))


async def _serve_adapter(websocket, adapter, connection) -> None:
    tasks = (
        asyncio.create_task(_send_pump(websocket, adapter, connection), name="adapter-ws-send"),
        asyncio.create_task(_receive_pump(websocket, adapter, connection), name="adapter-ws-receive"),
    )
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await adapter.disconnect(connection)
