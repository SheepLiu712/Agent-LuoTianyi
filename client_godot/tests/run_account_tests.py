"""Exercise Godot's real HTTPRequest + native encryption against a loopback fixture."""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
from support.interop_crypto import server_crypto

PROJECT = Path(__file__).resolve().parents[1]


def run(godot, script="res://tests/test_account_api.gd", gpu=False):
    crypto = server_crypto()
    crypto.generate_keys()
    protocol_errors = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, status, payload):
            encoded = json.dumps(payload).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            try:
                self.wfile.write(encoded)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

        def do_GET(self):
            if self.path.startswith("/slow/"):
                time.sleep(0.5)
            if self.path.startswith("/redirect/"):
                self.send_response(302)
                self.send_header("Location", "/auth/public_key")
                self.end_headers()
                return
            if self.path.startswith("/badjson/"):
                self.reply(200, [])
                return
            self.reply(200, {"public_key": "bad-key" if self.path.startswith("/badkey/") else crypto.get_public_key_pem()})

        def do_POST(self):
            fields = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if self.path.startswith("/slowpost/"):
                time.sleep(0.5)
            operation = self.path.rsplit("/", 1)[-1]
            allowed = {"login":{"username", "password", "request_token"}, "register":{"username", "password", "invite_code"},
                       "reset_account":{"invite_code", "new_username", "new_password"}, "auto_login":{"username", "token"}}
            try:
                assert set(fields) == allowed[operation], "request field mismatch"
                if operation != "auto_login":
                    encrypted = fields["new_password" if operation == "reset_account" else "password"]
                    assert crypto.decrypt_password(encrypted) == "synthetic-password", "encrypted password mismatch"
                else:
                    if fields["token"] == "invalid":
                        self.reply(401, {"detail":"expired login token"})
                        return
                    assert fields["token"] in {"login-test", "login-rotated"}, "wrong token type"
            except Exception as error:
                protocol_errors.append(type(error).__name__)
                self.reply(400, {"detail":"fixture protocol mismatch"})
                return
            username = fields.get("username", "test")
            if username in {"reject", "busy"}:
                self.reply(401 if username == "reject" else 503, {"detail":"fixture rejection"})
            elif operation in {"login", "auto_login"}:
                self.reply(200, {"user_id":username, "login_token":"login-rotated" if operation == "auto_login" else "login-test", "message_token":"" if username == "empty_token" else "message-test"})
            elif operation == "register":
                self.reply(200, {"message":"registered", "user_id":"test"})
            else:
                self.reply(200, {"message":"reset", "username":"test"})

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        # Every invocation receives disposable Windows user-data roots. A
        # previous run must not satisfy this contract through persisted
        # account history, credentials, or Godot settings.
        with tempfile.TemporaryDirectory(prefix="agentluo-account-") as isolated:
            appdata = Path(isolated) / "appdata"
            local_appdata = Path(isolated) / "localappdata"
            appdata.mkdir()
            local_appdata.mkdir()
            env = {
                **os.environ,
                "APPDATA": str(appdata),
                "LOCALAPPDATA": str(local_appdata),
                "GODOT_TEST_SERVER": f"http://127.0.0.1:{server.server_port}",
            }
            result = subprocess.run([godot, *([] if gpu else ["--headless"]), "--path", str(PROJECT), "--script", script],
                                    env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=40)
        output = result.stdout + result.stderr
        print(output)
        if result.returncode != 0 or "ERROR:" in output or "FAIL:" in output or ": FAIL" in output or ": PASS" not in output or protocol_errors:
            raise RuntimeError("Account contract failed (exit %s): %s" % (result.returncode, result.stderr))
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
    print("Loopback account HTTP contract: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", required=True)
    parser.add_argument("--script", default="res://tests/test_account_api.gd")
    parser.add_argument("--gpu", action="store_true", help="Use a native window for layout/size validation")
    args = parser.parse_args()
    run(args.godot, args.script, args.gpu)
