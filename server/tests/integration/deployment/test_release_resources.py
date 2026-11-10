import hashlib
import importlib.util
import json
import tempfile
import unittest
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
spec = importlib.util.spec_from_file_location("check_resources", ROOT / "scripts/deploy/check_resources.py")
checker = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checker)


class ReleaseResourcesTests(unittest.TestCase):
    def test_all_release_resources_match_manifest(self):
        self.assertEqual(checker.verify(ROOT, ROOT / "scripts/deploy/resources.lock.json"), [])

    def test_prepared_audio_manifest_references_nonempty_wave_files(self):
        manifest = ROOT / "res/agent/prepared_speech/luotianyi/manifest.json"
        for entry in json.loads(manifest.read_text()):
            audio = (manifest.parent / entry["audio_path"]).resolve()
            self.assertTrue(audio.is_relative_to(manifest.parent.resolve()))
            with wave.open(str(audio)) as stream:
                self.assertGreater(stream.getnframes(), 0)

    def test_missing_or_modified_asset_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manifest = root / "manifest.json"
            manifest.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "files": [{"path": "model.bin", "size": 3, "sha256": hashlib.sha256(b"abc").hexdigest()}],
                    }
                )
            )
            self.assertEqual(checker.verify(root, manifest), ["missing: model.bin"])
            (root / "model.bin").write_bytes(b"xyz")
            self.assertEqual(checker.verify(root, manifest), ["changed: model.bin"])
            (root / "model.bin").write_bytes(b"abc")
            self.assertEqual(checker.verify(root, manifest), [])


if __name__ == "__main__":
    unittest.main()
