import argparse
import asyncio
import base64
import json
import ssl
import time
import uuid
from typing import Any

import requests
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding

try:
    import websockets
except ImportError as exc:
    raise SystemExit(
        "Missing dependency: websockets. Install with: pip install websockets"
    ) from exc

public_key = None
def get_public_key(
    base_url: str = "http://127.0.0.1:8000",
    timeout: float = 10.0,
    verify: bool | str = True,
):
    global public_key
    if public_key:
        return public_key
    try:
        resp = requests.get(f"{base_url}/auth/public_key", verify=verify, timeout=timeout)
        if resp.status_code == 200:
            pem = resp.json().get("public_key")
            public_key = serialization.load_pem_public_key(pem.encode('utf-8'))
            return public_key
    except Exception as e:
        print(f"Error fetching public key: {e}")
    return None

def encrypt_password_with_server_public_key(
    base_url: str = "http://127.0.0.1:8000",
    password: str = "123456",
    timeout: float = 10.0,
    verify: bool | str = True,
) -> str | None:
    key = get_public_key(base_url=base_url, timeout=timeout, verify=verify)
    if not key:
        return None
    try:
        encrypted = key.encrypt(
            password.encode('utf-8'),
            padding.OAEP(
                mgf=padding.MGF1(algorithm=hashes.SHA256()),
                algorithm=hashes.SHA256(),
                label=None
            )
        )
        return base64.b64encode(encrypted).decode('utf-8')
    except Exception as e:
        print(f"Encryption error: {e}")
        return None


def login_get_message_token(
    base_url: str,
    username: str,
    password: str,
    timeout: float = 10.0,
    verify: bool | str = True,
) -> str:
    encrypted_password = encrypt_password_with_server_public_key(
        base_url,
        password,
        timeout=timeout,
        verify=verify,
    )
    payload = {
        "username": username,
        "password": encrypted_password,
        "request_token": True,
    }
    resp = requests.post(f"{base_url}/auth/login", json=payload, timeout=timeout, verify=verify)
    resp.raise_for_status()
    data = resp.json()
    token = data.get("message_token")
    if not token:
        raise RuntimeError(f"Login succeeded but message_token not found. response={data}")
    return token


def build_tls_options(base_url: str, ca_cert: str | None, insecure_skip_verify: bool) -> tuple[bool | str, ssl.SSLContext | None]:
    # HTTP plaintext mode does not use TLS settings.
    if not base_url.startswith("https://"):
        return True, None

    if insecure_skip_verify:
        # For local debugging only.
        insecure_ctx = ssl._create_unverified_context()
        return False, insecure_ctx

    if ca_cert:
        tls_ctx = ssl.create_default_context(cafile=ca_cert)
        return ca_cert, tls_ctx

    # Strict verification against system trust store by default.
    return True, ssl.create_default_context()


def build_ws_url(base_url: str) -> str:
    if base_url.startswith("https://"):
        return "wss://" + base_url[len("https://") :].rstrip("/") + "/chat_ws"
    if base_url.startswith("http://"):
        return "ws://" + base_url[len("http://") :].rstrip("/") + "/chat_ws"
    raise ValueError("base_url must start with http:// or https://")


async def send_heartbeats(ws: websockets.WebSocketClientProtocol, interval: float, stop_evt: asyncio.Event) -> None:
    ping_id = 0
    while not stop_evt.is_set():
        ping_id += 1
        hb_event = {
            "type": "hb_ping",
            "client_msg_id": f"ping-{ping_id}-{uuid.uuid4().hex[:8]}",
            "ts": int(time.time() * 1000),
            "payload": {"ping_id": ping_id},
        }
        await ws.send(json.dumps(hb_event, ensure_ascii=False))
        await asyncio.sleep(interval)


async def recv_loop(ws: websockets.WebSocketClientProtocol, stop_evt: asyncio.Event) -> None:
    while not stop_evt.is_set():
        try:
            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
        except asyncio.TimeoutError:
            continue
        except websockets.ConnectionClosed:
            print("[recv] websocket closed")
            break
        print(f"[recv] {raw}")


async def run_client(
    base_url: str,
    username: str,
    password: str,
    message_text: str,
    heartbeat_interval: float,
    wait_seconds: float,
    ca_cert: str | None,
    insecure_skip_verify: bool,
) -> None:
    req_verify, ws_ssl_ctx = build_tls_options(base_url, ca_cert, insecure_skip_verify)

    print("[info] logging in and requesting message_token")
    message_token = login_get_message_token(base_url, username, password, verify=req_verify)
    ws_url = build_ws_url(base_url)
    print(f"[info] token acquired. connecting to {ws_url}")

    stop_evt = asyncio.Event()

    async with websockets.connect(ws_url, max_size=8 * 1024 * 1024, ssl=ws_ssl_ctx) as ws:
        initial_msg = await ws.recv()
        print(f"[recv] {initial_msg}")

        auth_event = {
            "type": "auth",
            "client_msg_id": f"auth-{uuid.uuid4().hex[:8]}",
            "ts": int(time.time() * 1000),
            "payload": {
                "username": username,
                "token": message_token,
            },
        }
        await ws.send(json.dumps(auth_event, ensure_ascii=False))
        print(f"[send] {json.dumps(auth_event, ensure_ascii=False)}")

        recv_task = asyncio.create_task(recv_loop(ws, stop_evt))
        hb_task = asyncio.create_task(send_heartbeats(ws, heartbeat_interval, stop_evt))

        user_text_event = {
            "type": "user_text",
            "client_msg_id": f"msg-{uuid.uuid4().hex[:8]}",
            "ts": int(time.time() * 1000),
            "payload": {
                "message": message_text,
            },
        }
        await ws.send(json.dumps(user_text_event, ensure_ascii=False))
        print(f"[send] {json.dumps(user_text_event, ensure_ascii=False)}")

        print(f"[info] waiting {wait_seconds}s for server events")
        await asyncio.sleep(wait_seconds)

        stop_evt.set()
        await asyncio.gather(hb_task, recv_task, return_exceptions=True)



def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Simple WebSocket client for Agent-Luo server")
    parser.add_argument("--base-url", default="https://127.0.0.1:60030", help="Server base URL")
    parser.add_argument("--username", default="Dpon", help="Login username")
    parser.add_argument("--password", default="123456", help="Login password")
    parser.add_argument("--message", default="你好，测试一下 websocket 新链路", help="Test message text")
    parser.add_argument("--heartbeat-interval", type=float, default=5.0, help="Heartbeat interval seconds")
    parser.add_argument("--wait-seconds", type=float, default=20.0, help="How long to wait for server replies")
    parser.add_argument(
        "--ca-cert",
        default=None,
        help="Path to self-signed server cert (PEM) to trust for HTTPS/WSS",
    )
    parser.add_argument(
        "--insecure-skip-verify",
        action="store_true",
        help="Disable TLS certificate verification (debug only)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    asyncio.run(
        run_client(
            base_url=args.base_url,
            username=args.username,
            password=args.password,
            message_text=args.message,
            heartbeat_interval=args.heartbeat_interval,
            wait_seconds=args.wait_seconds,
            ca_cert=args.ca_cert,
            insecure_skip_verify=args.insecure_skip_verify,
        )
    )
