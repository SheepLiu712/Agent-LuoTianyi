import os
import sys
import threading
from typing import Dict

cwd = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if cwd not in sys.path:
    sys.path.append(cwd)

from network.network_client import NetworkClient
from src.utils.helpers import load_config


def _run_one(client: NetworkClient, text: str, out: Dict[str, dict]) -> None:
    out[text] = client.send_chat(text)


def main() -> int:
    config = load_config(os.path.join(cwd, "config", "config.json"))
    client = NetworkClient(
        base_url=config.get("base_url"),
        verify_ssl=bool(config.get("verify_ssl", True)),
    )

    username = os.environ.get("LTY_TEST_USER", "Dpon")
    password = os.environ.get("LTY_TEST_PASS", "123456")

    ok, msg = client.login(username, password, request_token=False)
    print(f"[login] ok={ok} msg={msg}")
    if not ok:
        return 1

    results: Dict[str, dict] = {}
    t1 = threading.Thread(target=_run_one, args=(client, "并发消息A", results), daemon=True)
    t2 = threading.Thread(target=_run_one, args=(client, "并发消息B", results), daemon=True)

    t1.start()
    t2.start()
    t1.join(timeout=30)
    t2.join(timeout=30)

    print(f"[result] keys={list(results.keys())}")
    print(f"[result] A={results.get('并发消息A')}")
    print(f"[result] B={results.get('并发消息B')}")

    if "并发消息A" not in results or "并发消息B" not in results:
        print("[fail] concurrent result missing")
        return 2

    if not results["并发消息A"].get("ok") or not results["并发消息B"].get("ok"):
        print("[fail] concurrent ack failed")
        return 3

    print("[pass] concurrent send ack ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
