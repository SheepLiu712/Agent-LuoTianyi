import argparse
import os
import sys
import time

cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if cwd not in sys.path:
    sys.path.append(cwd)

from network.network_client import NetworkClient
from src.utils.helpers import load_config


def build_client_from_config(config_path: str) -> NetworkClient:
    config = load_config(config_path)
    return NetworkClient(
        base_url=config.get("base_url"),
        verify_ssl=bool(config.get("verify_ssl", True)),
    )


def run_text_flow(args: argparse.Namespace) -> int:
    client = build_client_from_config(args.config)

    ok, msg = client.login(args.username, args.password, request_token=args.request_token)
    print(f"[login] ok={ok} msg={msg}")
    if not ok:
        return 1

    print(f"[chat] send: {args.message}")
    started = time.time()
    ack = client.send_chat(args.message)
    print(f"[ack] {ack}")

    elapsed = time.time() - started
    print(f"[chat] done in {elapsed:.2f}s")
    if not ack.get("ok", False):
        print("[chat] send not acknowledged")
        return 2
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="WebSocket network layer smoke test")
    parser.add_argument("--config", default=os.path.join(cwd, "config", "config.json"))
    parser.add_argument("--username", required=True)
    parser.add_argument("--password", required=True)
    parser.add_argument("--message", default="你好，测试网络层接口")
    parser.add_argument("--request-token", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(run_text_flow(parse_args()))
