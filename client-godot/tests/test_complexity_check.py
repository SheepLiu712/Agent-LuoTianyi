import contextlib
import io
import json
import shutil
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock



SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import check_complexity
import complexity
from complexity import cpp, gdscript, python


class DependencyVersionTests(unittest.TestCase):
    def test_unexpected_version_fails_closed(self):
        with mock.patch("complexity.version", return_value="0.0.0"), self.assertRaises(RuntimeError):
            complexity.require_version("complexity-test-package", "1.0.0")


class GDScriptComplexityTests(unittest.TestCase):
    def records(self, body):
        return gdscript.analyze(body, "sample.gd")

    def test_straight_line_and_comment_strings(self):
        source = 'extends Node\nfunc run():\n\tvar text = "if and or while"\n\t# if and or\n\treturn text\n'
        self.assertEqual(self.records(source)[0]["cc"], 1)

    def test_ten_passes_eleven_fails(self):
        for branches, expected in [(9, 10), (10, 11)]:
            with self.subTest(branches=branches):
                source = 'extends Node\nfunc run():\n' + '\tif true: pass\n' * branches
                self.assertEqual(self.records(source)[0]["cc"], expected)

    def test_short_circuit_and_ternary(self):
        source = 'extends Node\nfunc run():\n\tif true and false or true: pass\n\treturn 1 if true else 2\n'
        self.assertEqual(self.records(source)[0]["cc"], 5)

    def test_match_default_is_not_a_branch(self):
        source = 'extends Node\nfunc run(value):\n\tmatch value:\n\t\t1: pass\n\t\t2, 3: pass\n\t\t_: pass\n'
        self.assertEqual(self.records(source)[0]["cc"], 3)

    def test_guarded_match(self):
        source = 'extends Node\nfunc run(value):\n\tmatch value:\n\t\t1 when true and false: pass\n\t\t_: pass\n'
        self.assertEqual(self.records(source)[0]["cc"], 4)

    def test_lambda_is_not_counted_twice(self):
        source = 'extends Node\nfunc run():\n\tvar callback = func():\n\t\tif true and false: pass\n\treturn callback\n'
        records = self.records(source)
        self.assertEqual([record["cc"] for record in records], [1, 3, 1])

    def test_inline_lambda_if(self):
        source = 'extends Node\nfunc run():\n\tsignal_name.connect(func(): if true: pass)\n'
        self.assertEqual([record["cc"] for record in self.records(source)], [1, 2, 1])

    def test_property_accessors(self):
        source = 'extends Node\nvar value: int:\n\tset(next):\n\t\tif next > 0: value = next\n\tget:\n\t\treturn value\n'
        self.assertEqual([record["cc"] for record in self.records(source)], [2, 1, 1])

    def test_assert_call_only_counts_boolean_argument(self):
        source = 'extends Node\nfunc run():\n\tassert(true and false)\n'
        self.assertEqual(self.records(source)[0]["cc"], 2)


    def test_top_level_initializers_exclude_callback_body(self):
        source = 'extends Node\nvar value = 1 if true and false else 2\nvar callback = func():\n\tif true: pass\n'
        self.assertEqual([record["cc"] for record in self.records(source)], [2, 3])

    def test_top_level_threshold(self):
        source = 'extends Node\n' + 'var value_%s = 1 if true else 2\n' * 10
        self.assertEqual(self.records(source % tuple(range(10)))[0]["cc"], 11)

    def test_inner_class_initialization_is_independent(self):
        source = 'extends Node\nvar value = 1 if true else 2\nclass Inner:\n\tvar nested = 1 if true and false else 2\n'
        self.assertEqual([record["cc"] for record in self.records(source)], [3, 2])

class PythonComplexityTests(unittest.TestCase):
    def records(self, source):
        return python.analyze(source, "sample.py")

    def test_nested_function_and_lambda(self):
        source = 'def outer():\n    def inner():\n        if True: pass\n    return lambda: 1 if True else 2\n'
        self.assertEqual([record["cc"] for record in self.records(source)], [1, 2, 2, 1])

    def test_assert_catch_and_comprehension(self):
        source = 'def run(values):\n    assert values and True\n    try:\n        return [value for value in values if value]\n    except ValueError:\n        return []\n'
        self.assertEqual(self.records(source)[0]["cc"], 6)

    def test_match_default(self):
        source = 'def run(value):\n    match value:\n        case 1: return True\n        case _: return False\n'
        self.assertEqual(self.records(source)[0]["cc"], 2)

    def test_top_level_script(self):
        self.assertEqual(self.records('if True:\n    pass\n')[0]["cc"], 2)


class NativeComplexityTests(unittest.TestCase):
    def test_cpp_short_circuit_ternary_and_switch(self):
        source = 'int run(int value) { if (value && value > 1) return value ? 1 : 2; switch(value) { case 1: return 0; default: return 1; } }'
        self.assertEqual(cpp.analyze(source, "sample.cpp")[0]["cc"], 5)

    def test_preprocessor_branches(self):
        source = 'int run() {\n#ifdef _WIN32\nreturn 1;\n#elif defined(__unix__)\nreturn 2;\n#endif\nreturn 0;\n}'
        self.assertEqual(cpp.analyze(source, "sample.cpp")[0]["cc"], 3)

    def test_shader(self):
        self.assertEqual(cpp.analyze('void fragment() { COLOR.a = 1.0; }', "sample.gdshader")[0]["cc"], 1)


    def test_cpp_lambdas_are_independent(self):
        source = 'int run() { auto callback = [](int value) { if (value && value > 1) return 1; return 0; }; return callback(1); }'
        records = cpp.analyze(source, "sample.cpp")
        self.assertEqual([record["cc"] for record in records], [1, 3])
        self.assertEqual(records[1]["kind"], "lambda")

    def test_nested_cpp_lambdas_and_strings(self):
        source = 'int run() { auto callback = [value=1](auto item) mutable -> int { auto inner = [&] { return item ? 1 : 2; }; const char* text = "[] { if && }"; if (value) return inner(); return 0; }; return 0; }'
        self.assertEqual([record["cc"] for record in cpp.analyze(source, "sample.cpp")], [1, 2, 2])

    def test_cpp_lambda_threshold(self):
        source = 'int run() { auto callback = [] { ' + 'if (true) {} ' * 10 + '}; return 0; }'
        self.assertEqual([record["cc"] for record in cpp.analyze(source, "sample.cpp")], [1, 11])

    def test_cpp_array_subscript_is_not_lambda(self):
        source = 'int run(int* values) { int result = values[0]; if (result) { return values[1]; } return 0; }'
        self.assertEqual([record["cc"] for record in cpp.analyze(source, "sample.cpp")], [2])

    def test_cpp_unclosed_body_fails(self):
        with self.assertRaises(ValueError):
            cpp.analyze('int run() {', "sample.cpp")


    def test_shader_uniform_hints_do_not_hide_body_branches(self):
        source = 'shader_type canvas_item; uniform vec4 tint : source_color = vec4(1.0); uniform float radius : hint_range(0.0, 12.0) = 4.0; void fragment() { if (radius > 0.0) { COLOR = tint; } }'
        self.assertEqual(cpp.analyze(source, "sample.gdshader")[0]["cc"], 2)

    def test_invalid_shader_fails_closed(self):
        with self.assertRaises(ValueError):
            cpp.analyze('void fragment() { if ( }', "sample.gdshader")

    def test_cpp_operator_lambda_is_independent(self):
        source = 'int run() { auto callback = +[] { if (true) {} }; return 0; }'
        self.assertEqual([record["cc"] for record in cpp.analyze(source, "sample.cpp")], [1, 2])

    def test_cpp_invalid_declaration_fails(self):
        with self.assertRaises(ValueError):
            cpp.analyze('int value = ;', "sample.cpp")

class ScanTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="agentluo-complexity-test-")
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def write(self, relative, source):
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")

    def test_third_party_and_generated_directories_are_excluded(self):
        for path in ['native/godot-cpp/source.cpp', 'addons/gd_cubism/test.gd', 'dist/test.py', '.godot/test.gd']:
            self.write(path, 'invalid source')
        self.write('src/test.gd', 'extends Node\nfunc run(): pass\n')
        report = check_complexity.scan(self.root)
        self.assertEqual(report["source_files"], 1)
        self.assertEqual(report["errors"], [])

    def test_invalid_source_fails_closed(self):
        self.write('src/test.gd', 'func broken(\n')
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual(check_complexity.main(['--root', str(self.root)]), 1)

    def test_json_and_threshold_exit_codes(self):
        self.write('src/test.gd', 'extends Node\nfunc run():\n' + '\tif true: pass\n' * 10)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(check_complexity.main(['--root', str(self.root), '--format', 'json']), 1)
        self.assertEqual(json.loads(output.getvalue())["violations"][0]["cc"], 11)

    def test_threshold_cannot_be_relaxed(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            check_complexity.arguments(['--limit', '11'])

    def test_powershell_function_and_scriptblock_are_independent(self):
        self.write('scripts/test.ps1', 'function Test-Branch { if ($true -and $false) { return } }\n$block = { if ($true) { return } }\n')
        report = check_complexity.scan(self.root)
        self.assertEqual(report["errors"], [])
        self.assertEqual([record["cc"] for record in report["records"]], [1, 3, 2])

    def test_nested_native_sources_are_included(self):
        self.write('native/support/owned.cpp', 'int run() { return 0; }')
        self.assertEqual(check_complexity.scan(self.root)["source_files"], 1)

    def test_shader_and_native_extension_scope(self):
        self.write('assets/ui/nested/owned.gdshader', 'void fragment() { COLOR.a = 1.0; }')
        self.write('native/support/owned.cc', 'int run() { return 0; }')
        self.assertEqual(check_complexity.scan(self.root)["source_files"], 2)

    def test_powershell_switch_default(self):
        self.write('scripts/test.ps1', 'switch ($value) { 1 { return } default { return } }')
        report = check_complexity.scan(self.root)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["records"][0]["cc"], 2)

    @unittest.skipUnless(shutil.which("pwsh"), "PowerShell 7 is not installed")
    def test_powershell_ternary_and_pipeline_chain(self):
        self.write('scripts/test.ps1', '$value = $true ? 1 : 2; Write-Output 1 && Write-Output 2 || Write-Output 3')
        report = check_complexity.scan(self.root)
        self.assertEqual(report["errors"], [])
        self.assertEqual(report["records"][0]["cc"], 4)

    def test_powershell_parse_error_fails_closed(self):
        self.write('scripts/test.ps1', 'if (')
        self.assertEqual(len(check_complexity.scan(self.root)["errors"]), 1)


if __name__ == "__main__":
    unittest.main()
