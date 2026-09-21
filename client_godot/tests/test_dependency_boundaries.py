"""Source-level architecture contracts, independent of renderer/native plugins."""
from pathlib import Path
import re
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
        for directory in ['ui', 'session', 'avatar', 'preview']:
            paths += list((ROOT/'src'/directory).rglob('*.gd'))
        self.assert_no_calls(paths, r'\b(?:OS|DisplayServer|ClassDB|FileAccess|DirAccess|ConfigFile|JavaClassWrapper|JavaScriptBridge)\b')

    def test_storage_does_not_import_network(self):
        for path in (ROOT/'src/storage').rglob('*.gd'):
            self.assertNotRegex(path.read_text(encoding='utf-8'), r'(?:load|preload)\("res://src/network/')

    def test_production_does_not_import_preview(self):
        for directory in ['ui', 'session', 'network', 'media', 'storage', 'avatar']:
            for path in (ROOT/'src'/directory).rglob('*.gd'):
                self.assertNotRegex(path.read_text(encoding='utf-8'), r'(?:load|preload)\("res://src/preview/')


if __name__ == '__main__':
    unittest.main()
