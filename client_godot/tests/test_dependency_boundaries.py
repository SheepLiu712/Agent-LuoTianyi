"""Source-level architecture contracts, independent of renderer/native plugins."""
from pathlib import Path
import re
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]


def code(path):
    # Keep only code: a forbidden name in a comment or string is not a call.
    return re.sub(r'"""[\s\S]*?"""|\'\'\'[\s\S]*?\'\'\'|"(?:\\.|[^"\\])*"|\'(?:\\.|[^\'\\])*\'|#[^\n]*', '', path.read_text(encoding='utf-8'))


class DependencyBoundaries(unittest.TestCase):
    def assert_no_calls(self, paths, expression):
        hits = []
        for path in paths:
            for match in re.finditer(expression, code(path)):
                hits.append(f'{path.relative_to(ROOT)}: {match.group()}')
        self.assertEqual(hits, [], '\n'.join(hits))

    def test_configuration_is_not_ui_or_framing_io(self):
        paths = [ROOT / 'src/application.gd', ROOT / 'src/avatar/avatar_framing.gd']
        paths += list((ROOT / 'src/ui').glob('*.gd')) + list((ROOT / 'src/preview').glob('*.gd'))
        self.assert_no_calls(paths, r'\b(?:ConfigFile|FileAccess|DirAccess)\b')

    def test_input_does_not_call_display_server(self):
        self.assert_no_calls([ROOT/'src/ui/composer_input.gd', ROOT/'src/ui/log_window.gd'], r'\bDisplayServer\s*\.')

    def test_media_does_not_open_files_or_native_classes(self):
        self.assert_no_calls((ROOT/'src/media').glob('*.gd'), r'\b(?:FileAccess|DirAccess|ClassDB)\b')

    def test_platform_calls_are_behind_adapters(self):
        paths = [ROOT/'src/application.gd']
        for directory in ['domain', 'network', 'ui', 'session', 'avatar', 'preview', 'application']:
            paths += list((ROOT/'src'/directory).rglob('*.gd'))
        self.assert_no_calls(paths, r'\b(?:OS|DisplayServer|ClassDB|FileAccess|DirAccess|ConfigFile|JavaClassWrapper|JavaScriptBridge)\b')

    def test_domain_and_network_do_not_import_platform(self):
        paths = list((ROOT / 'src' / 'domain').rglob('*.gd'))
        paths += list((ROOT / 'src' / 'network').rglob('*.gd'))
        self.assert_no_calls(paths, r'(?:load|preload)\("res://src/platform/')

    def test_business_consumers_do_not_instantiate_native_extensions(self):
        paths = []
        for directory in ['domain', 'network', 'ui', 'session', 'media', 'avatar', 'preview', 'application']:
            paths += list((ROOT / 'src' / directory).rglob('*.gd'))
        self.assert_no_calls(paths, r'\bClassDB\s*\.\s*(?:class_exists|instantiate)\s*\(')

    def test_storage_does_not_import_network(self):
        for path in (ROOT/'src/storage').rglob('*.gd'):
            self.assertNotRegex(path.read_text(encoding='utf-8'), r'(?:load|preload)\("res://src/network/')

    def test_production_does_not_import_preview(self):
        for directory in ['ui', 'session', 'network', 'media', 'storage', 'avatar']:
            for path in (ROOT/'src'/directory).rglob('*.gd'):
                self.assertNotRegex(path.read_text(encoding='utf-8'), r'(?:load|preload)\("res://src/preview/')

    def test_consumers_do_not_create_concrete_platform_or_storage(self):
        for directory in ['domain', 'network', 'ui', 'session', 'avatar', 'preview', 'application']:
            for path in (ROOT/'src'/directory).rglob('*.gd'):
                source = path.read_text(encoding='utf-8')
                self.assertNotRegex(source, r'(?:load|preload)\("res://src/platform/(?:godot_|windows_|native_|desktop_|cubism_)')
                self.assertNotRegex(source, r'(?:load|preload)\("res://src/storage/(?:godot_|history_images|audio_cache|model_store|credential_store|reading_position)')
                self.assert_no_calls([path], r'\bWindow\s*\.\s*MODE_|\bImage\s*\.\s*load_from_file')


if __name__ == '__main__':
    unittest.main(testRunner=unittest.TextTestRunner(stream=sys.stdout))
