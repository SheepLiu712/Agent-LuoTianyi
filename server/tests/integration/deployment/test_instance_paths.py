import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from src.utils.server_paths import ServerPaths


class InstancePathsTests(unittest.TestCase):
    def test_roots_are_independent_of_cwd_and_absolute_paths_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = ServerPaths.from_environment(
                root / "code",
                env={
                    "AGENTLUO_DATA_DIR": str(root / "instance/data"),
                    "AGENTLUO_CONFIG_DIR": str(root / "instance/config"),
                    "AGENTLUO_ASSET_DIR": str(root / "assets"),
                },
            )
            self.assertEqual(paths.resolve("data/knowledge"), root / "instance/data/knowledge")
            self.assertEqual(paths.resolve("res/agent/prompts"), root / "code/res/agent/prompts")
            self.assertEqual(paths.resolve("res/tts/gsv"), root / "assets/tts/gsv")
            self.assertEqual(paths.resolve("/custom/file"), Path("/custom/file"))
            with self.assertRaises(ValueError):
                paths.resolve("data/../production")

    def test_config_resolution_does_not_rewrite_text_or_bare_database_filename(self):
        paths = ServerPaths.from_environment("/code", env={"AGENTLUO_DATA_DIR": "/instance"})
        raw = {"root": "data/media", "sql_db_file": "luotianyi.db", "prompt": "data/media is a directory"}
        resolved = paths.resolve_config(raw)
        self.assertEqual(resolved["root"], "/instance/media")
        self.assertEqual(raw["root"], "data/media")
        self.assertEqual(resolved["sql_db_file"], "luotianyi.db")
        self.assertEqual(resolved["prompt"], raw["prompt"])

    def test_config_store_writes_only_selected_instance_and_keeps_raw_paths(self):
        from src.infrastructure.config.store import ConfigStore

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for instance in ("test", "production"):
                (root / instance).mkdir()
                (root / instance / "config.json").write_text('{"root": "data/media"}')
            with patch.dict(
                os.environ, {"AGENTLUO_CONFIG_DIR": str(root / "test"), "AGENTLUO_DATA_DIR": str(root / "test-data")}
            ):
                paths = ServerPaths.from_environment(root / "code")
                store = ConfigStore(paths.resolve("config/config.json"), root_dir=paths.code_root)
                self.assertEqual(store.read_resolved()["root"], str(root / "test-data/media"))
                store.write_raw({"root": "data/new-media"})
                self.assertEqual(json.loads((root / "test/config.json").read_text())["root"], "data/new-media")
                self.assertEqual(json.loads((root / "production/config.json").read_text())["root"], "data/media")

    def test_tts_yaml_model_paths_use_asset_root(self):
        from src.agent.skills.expression.speaking.tts_server import _extract_model_paths_from_yaml

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "tts.yaml"
            config.write_text(
                "custom:\n  pretrained_models_path: res/tts/gsv\n  t2s_weights_path: res/tts/voice.ckpt\n"
            )
            with patch.dict(os.environ, {"AGENTLUO_ASSET_DIR": str(root / "assets")}):
                result = _extract_model_paths_from_yaml(str(config))
            self.assertEqual(result["gpt_model_path"], str(root / "assets/tts/voice.ckpt"))
            self.assertEqual(result["pretrained_models_path"], str(root / "assets/tts/gsv"))


if __name__ == "__main__":
    unittest.main()
