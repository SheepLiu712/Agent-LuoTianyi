"""Keep owned review entrypoints, local links and version metadata consistent."""
import json
from pathlib import Path
import re
import unittest
from urllib.parse import unquote


PROJECT = Path(__file__).resolve().parents[1]
DOCUMENTS = [PROJECT / "README.md", PROJECT / "PREVIEW.md", PROJECT / "tests/README.md",
             *sorted((PROJECT / "docs").glob("*.md")), *sorted((PROJECT / "architecture").glob("*.md"))]


class ReviewDocumentationTests(unittest.TestCase):
    def test_owned_local_links_resolve(self):
        missing = []
        for document in DOCUMENTS:
            for target in re.findall(r"\[[^\]]*\]\(([^)]+)\)", document.read_text(encoding="utf-8")):
                self.check_target(document, target, missing)
        self.assertEqual(missing, [])

    def check_target(self, document, target, missing):
        if target.startswith(("https://", "http://", "#", "mailto:")):
            return
        destination = unquote(target.split("#", 1)[0])
        if destination and not (document.parent / destination).exists():
            missing.append(f"{document.relative_to(PROJECT)}: {target}")

    def test_current_commands_use_real_directory_name(self):
        for document in DOCUMENTS:
            blocks = re.findall(r"```(?:powershell|bash|shell)?\n(.*?)```",
                                document.read_text(encoding="utf-8"), re.S)
            for block in blocks:
                self.assertNotIn("client_godot", block, str(document))

    def test_shared_fixture_is_local_and_preserves_events(self):
        runner = (PROJECT / "tests/run_websocket_tests.py").read_text(encoding="utf-8")
        self.assertIn('PROJECT / "tests/fixtures/chat/reply_events.json"', runner)
        self.assertNotIn('PROJECT.parent / "contracts/', runner)
        events = json.loads((PROJECT / "tests/fixtures/chat/reply_events.json").read_text(encoding="utf-8"))
        self.assertEqual(len(events), 9)
        messages = [event["payload"] for event in events if event["type"] == "agent_message"]
        self.assertTrue(any(not message["display_in_chat"] for message in messages))
        self.assertTrue(any(message["is_ephemeral"] for message in messages))
        self.assertTrue(any(message.get("audio_error") for message in messages))

    def test_release_and_executable_versions_match(self):
        version = json.loads((PROJECT / "release.json").read_text(encoding="utf-8"))["version"]
        project = (PROJECT / "project.godot").read_text(encoding="utf-8")
        preset = (PROJECT / "export_presets.cfg").read_text(encoding="utf-8")
        native = version + ".0" if len(version.split(".")) == 3 else version
        self.assertIn(f'config/version="{version}"', project)
        for field in ("file_version", "product_version"):
            self.assertIn(f'application/{field}="{native}"', preset)
        self.assertIn(f"## {version} 当前源码", (PROJECT / "PREVIEW.md").read_text(encoding="utf-8"))
        self.assertIn("docs/*", preset)

    def test_import_metadata_has_local_lf_policy(self):
        attributes = (PROJECT / ".gitattributes").read_text(encoding="utf-8")
        self.assertIn("*.import text eol=lf", attributes.splitlines())
        imports = [*PROJECT.joinpath("assets").rglob("*.import"), *PROJECT.joinpath("addons").rglob("*.import")]
        self.assertTrue(imports)
        for path in imports:
            self.assertNotIn(b"\r\n", path.read_bytes(), str(path.relative_to(PROJECT)))


if __name__ == "__main__":
    unittest.main()
