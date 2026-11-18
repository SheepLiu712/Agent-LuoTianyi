"""Run with unittest as well as pytest; all data belongs to temporary fixtures."""

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts/deploy/release/migrate_resource_layout.py"
spec = importlib.util.spec_from_file_location("migrate_resource_layout", SCRIPT)
migration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migration)


class ResourceMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "config").mkdir()
        (self.root / "config/config.json").write_text(
            json.dumps({"song": "res/sing_song/luotianyi", "custom": "/custom"})
        )
        (self.root / "res/sing_song/luotianyi").mkdir(parents=True)
        (self.root / "res/sing_song/luotianyi/metadata.json").write_text('{"wished_songs": ["song"]}')

    def test_plan_does_not_write_and_apply_preserves_original(self):
        migration.migrate(self.root)
        self.assertFalse((self.root / "data").exists())
        migration.migrate(self.root, apply=True)
        original = self.root / "res/sing_song/luotianyi/metadata.json"
        copied = self.root / "data/singing/luotianyi/metadata.json"
        self.assertEqual(original.read_bytes(), copied.read_bytes())
        config = json.loads((self.root / "config/config.json").read_text())
        self.assertEqual(config, {"song": "data/singing/luotianyi", "custom": "/custom"})
        self.assertTrue((self.root / "config/config.before-resource-layout.json").exists())

    def test_existing_destination_is_never_overwritten(self):
        (self.root / "data/singing").mkdir(parents=True)
        before = (self.root / "config/config.json").read_bytes()
        with self.assertRaises(FileExistsError):
            migration.migrate(self.root, apply=True)
        self.assertEqual(before, (self.root / "config/config.json").read_bytes())

    def test_active_launcher_lock_refuses_migration(self):
        (self.root / ".runtime").mkdir()
        with (self.root / ".runtime/server.lock").open("a") as lock:
            migration.fcntl.flock(lock, migration.fcntl.LOCK_EX)
            with self.assertRaises(BlockingIOError):
                migration.migrate(self.root, apply=True)
        self.assertFalse((self.root / "data").exists())


if __name__ == "__main__":
    unittest.main()
