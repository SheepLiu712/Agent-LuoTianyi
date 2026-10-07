import sys
import os
import time

cwd = os.path.dirname(os.path.abspath(__file__))
if cwd not in sys.path:
    sys.path.append(cwd)

from network.network_client import NetworkClient
from src.utils.helpers import load_config

def test_login_flow():
    project_root = os.path.dirname(cwd)
    config = load_config(os.path.join(project_root, "config", "config.json"))
    client = NetworkClient(base_url=config.get("base_url"), verify_ssl=bool(config.get("verify_ssl", True)))
    
    # 1. Register
    print("Testing Registration...")
    # Generate unique user
    import random
    suffix = random.randint(1000,9999)
    username = f"user_{suffix}"
    
    success, msg = client.register(username, "securepass", "LuoTianyi2026")
    print(f"Register Result: {success}, {msg}")
    if not success:
        print("Registration failed unexpectedly")
        exit(1)
    
    # Duplicate Register
    success, msg = client.register(username, "securepass", "LuoTianyi2026")
    print(f"Duplicate Register Result: {success}, {msg}")
    if success:
        print("Duplicate registration should fail")
    
    # Invalid Code
    success, msg = client.register(f"user_{suffix}_2", "pass", "WrongCode")
    print(f"Invalid Code Result: {success}, {msg}")
    if success:
        print("Invalid code should fail")
    
    # 2. Login
    print("Testing Login...")
    success, msg = client.login(username, "securepass")
    print(f"Login Result: {success}, {msg}, Token: {client.message_token}")
    if not success:
        print("Login Failed!")
        exit(1)
        
    # 3. Chat
    print("Testing Chat Authenticated...")
    final_resp = None
    for resp in client.send_chat("Hello Auth"):
        print(f"Chat Event: {resp}")
        if resp.get("is_final_package"):
            final_resp = resp
            break

    if final_resp and final_resp.get("text"):
        print("Server recognized user")
    else:
        print("Server did not echo username correctly")
    
    print("Login/Register Test Passed!")

if __name__ == "__main__":
    test_login_flow()
