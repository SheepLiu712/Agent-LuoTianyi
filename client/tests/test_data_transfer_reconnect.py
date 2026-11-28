"""真实本地 WebSocket 验证迁移解绑后的重新鉴权与消息 ACK。"""

import asyncio
import json

from websockets.legacy.server import serve

from src.network.ws_transport import WsTransport


def test_migration_reconnect_reauthenticates_live_socket_without_restarting_thread(monkeypatch):
    monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")

    async def scenario():
        connections = []
        authentications = []
        delivered = []
        second_auth_waiting = asyncio.Event()
        release_second_auth = asyncio.Event()
        state = {"unbound": False}

        async def handler(ws):
            connections.append(ws)
            connection_number = len(connections)
            await ws.send(json.dumps({"type": "system_ready", "payload": {}}))
            auth = json.loads(await ws.recv())
            assert auth["type"] == "user_auth"
            authentications.append(auth["payload"])
            if connection_number == 2:
                second_auth_waiting.set()
                await release_second_auth.wait()
            await ws.send(json.dumps({"type": "auth_ok", "payload": {}}))
            async for raw in ws:
                message = json.loads(raw)
                if message["type"] != "user_text":
                    continue
                # 复现真实迁移：旧 stage 已解绑，但旧物理 socket 没关闭，不能处理聊天。
                if connection_number == 1 and state["unbound"]:
                    continue
                delivered.append((connection_number, message["payload"]["message"]))
                await ws.send(
                    json.dumps({"type": "server_ack", "payload": {"ok": True}, "reply_to": message["client_msg_id"]})
                )

        async with serve(handler, "127.0.0.1", 0) as server:
            port = server.sockets[0].getsockname()[1]
            transport = WsTransport(
                f"http://127.0.0.1:{port}", lambda: "synthetic-user", lambda: "synthetic-token", heartbeat_interval=60
            )
            transport.start()
            original_thread = transport._thread
            try:
                assert await asyncio.to_thread(transport.wait_until_ready, 5)
                assert len(connections) == 1 and connections[0].open
                state["unbound"] = True
                transport.request_reconnect()
                assert not transport.is_ready()
                # 新连接的鉴权故意不完成，API 必须已经返回，原运行线程继续负责连接。
                await asyncio.wait_for(second_auth_waiting.wait(), timeout=5)
                assert transport._thread is original_thread and original_thread.is_alive()
                assert not transport._stop_event.is_set()
                assert not transport.is_ready()
                assert not connections[0].open
                release_second_auth.set()
                assert await asyncio.to_thread(transport.wait_until_ready, 5)
                result = await asyncio.to_thread(
                    transport.submit_user_text,
                    "synthetic after migration",
                    ack_timeout=3,
                    client_msg_id="migration-test",
                )
                assert result["ok"] is True
                assert delivered == [(2, "synthetic after migration")]
                assert len(authentications) == 2
                assert authentications[1]["username"] == "synthetic-user"
                assert authentications[1]["token"] == "synthetic-token"
            finally:
                release_second_auth.set()
                transport.stop()
                await asyncio.to_thread(original_thread.join, 5)
                assert not original_thread.is_alive()

    asyncio.run(scenario())
