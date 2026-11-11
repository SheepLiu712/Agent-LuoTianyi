import asyncio
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))


class UnifiedStartupTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "config"
        self.config.mkdir()
        (self.config / "config.json").write_text(
            json.dumps(
                {
                    "is_debug": True,
                    "server": {"debug_port": 24523, "production_port": 15673},
                    "test_secret": "${AGENTLUO_TEST_SECRET}",
                }
            )
        )
        (self.config / "secrets.local.env").write_text("AGENTLUO_TEST_SECRET=synthetic-secret\n")
        self.env = {
            **os.environ,
            "AGENTLUO_CONFIG_DIR": str(self.config),
            "AGENTLUO_DATA_DIR": str(self.root / "data"),
            "AGENTLUO_RUNTIME_DIR": str(self.root / "runtime"),
            "AGENTLUO_PYTHON": sys.executable,
            "PYTHONDONTWRITEBYTECODE": "1",
        }

    def test_python_and_shell_launchers_use_same_instance_without_starting_services(self):
        commands = [
            [sys.executable, str(ROOT / "server_main.py"), "--check-startup"],
            ["bash", str(ROOT / "scripts/deploy/startup/start_linux.sh"), "--check-startup"],
            ["bash", str(ROOT / "scripts/start_production.sh"), "--check-startup"],
        ]
        for command in commands:
            result = subprocess.run(command, env=self.env, cwd=self.root, capture_output=True, text=True, timeout=40)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("port=24523", result.stdout)
            self.assertIn(str(self.config), result.stdout)
            self.assertNotIn("synthetic-secret", result.stdout + result.stderr)
        self.assertFalse((self.root / "data").exists())
        self.assertFalse((self.config / "admin_auth.json").exists())

    def test_secret_is_loaded_before_config_resolution_and_removal_restores_original_env(self):
        from src.application.startup import prepare_startup

        cwd = Path.cwd()
        try:
            with patch.dict(os.environ, self.env):
                os.environ.pop("AGENTLUO_TEST_SECRET", None)
                context = prepare_startup()
                self.assertEqual(context.config["test_secret"], "synthetic-secret")
                context.secrets.update({"AGENTLUO_TEST_SECRET": None})
                self.assertNotIn("AGENTLUO_TEST_SECRET", os.environ)
        finally:
            os.chdir(cwd)

    def test_invalid_port_fails_before_network_startup(self):
        (self.config / "config.json").write_text('{"is_debug": true, "server": {"debug_port": 0}}')
        result = subprocess.run(
            [sys.executable, str(ROOT / "server_main.py"), "--check-startup"],
            env=self.env,
            cwd=self.root,
            capture_output=True,
            text=True,
            timeout=40,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("debug_port", result.stderr)

    def test_admin_reuses_startup_secret_store(self):
        from src.application.admin.admin_shell import AdminShell
        from src.application.startup import prepare_startup

        cwd = Path.cwd()

        async def scenario():
            context = prepare_startup()
            shell = await AdminShell.initialize(root_dir=ROOT, secret_store=context.secrets)
            try:
                self.assertIs(shell.secret_store, context.secrets)
            finally:
                await shell.shutdown()

        try:
            with patch.dict(os.environ, self.env):
                asyncio.run(scenario())
        finally:
            os.chdir(cwd)


if __name__ == "__main__":
    unittest.main()
