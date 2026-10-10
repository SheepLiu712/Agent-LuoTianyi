"""Offline CNG/DPAPI verification; imports the existing server decrypt function."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile
from support.interop_crypto import server_crypto

PROJECT = Path(__file__).resolve().parents[1]

def run(godot: str) -> None:
    account = server_crypto()
    account.generate_keys()
    passwords = ["local-test-password", "测试密码 🎵", "x" * 190, "same-input", "same-input"]
    with tempfile.TemporaryDirectory(prefix="godot-security-") as directory:
        fixture = Path(directory) / "fixture.json"
        fixture.write_text(json.dumps({"public_key": account.get_public_key_pem(), "passwords": passwords}), encoding="utf-8")
        result = subprocess.run([godot, "--headless", "--path", str(PROJECT), "--script",
                                 "res://tests/test_windows_security.gd", "--", f"--fixture={fixture}"],
                                capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=45)
        print(result.stdout)
        if result.returncode or "ERROR:" in result.stdout + result.stderr:
            raise RuntimeError("Godot native contract failed; no server decryption attempted")
        ciphertexts = json.loads(Path(str(fixture) + ".out").read_text(encoding="utf-8"))
        assert len(ciphertexts) == len(passwords)
        for cipher, expected in zip(ciphertexts, passwords):
            assert account.decrypt_password(cipher) == expected, "Server decrypt mismatch"
        assert ciphertexts[-1] != ciphertexts[-2], "OAEP must be randomized"
    print("Existing Python decrypt_password interoperability: PASS")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--godot", required=True)
    arguments = parser.parse_args()
    run(arguments.godot)
