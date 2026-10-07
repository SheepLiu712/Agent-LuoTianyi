import sys
import os
import time

# Ensure src is in path
cwd = os.path.dirname(os.path.abspath(__file__))
if cwd not in sys.path:
    sys.path.append(cwd)

from network.network_client import NetworkClient
from src.utils.helpers import load_config

def test_communication():
    project_root = os.path.dirname(cwd)
    config = load_config(os.path.join(project_root, "config", "config.json"))
    client = NetworkClient(base_url=config.get("base_url"), verify_ssl=bool(config.get("verify_ssl", True)))
    username = os.environ.get("LTY_TEST_USER")
    password = os.environ.get("LTY_TEST_PASS")
    if not username or not password:
        print("Skip test: set LTY_TEST_USER and LTY_TEST_PASS")
        return

    ok, msg = client.login(username, password, request_token=False)
    if not ok:
        print(f"Login failed: {msg}")
        exit(1)
    
    # Test Chat
    print("Testing Chat...")
    final_resp = None
    for resp in client.send_chat("Hello Server"):
        print(f"Chat Event: {resp}")
        if resp.get("is_final_package"):
            final_resp = resp
            break

    if final_resp and final_resp.get("text"):
        print("Chat Test Passed")
    else:
        print("Chat Test Failed")
        exit(1)
    
    # Test History
    print("Testing History...")
    history, start_index = client.get_history(10, -1)
    print(f"History: {history}")
    if len(history) > 0:
        print("History Test Passed")
    else:
        print("History Test Warning: No history returned")
    
    print("All Communication Tests Passed!")

if __name__ == "__main__":
    test_communication()
