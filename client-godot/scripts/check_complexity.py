import argparse
import json
from pathlib import Path
import sys

from complexity import cpp, gdscript, powershell, python


SOURCE_PATTERNS = (
    "src/**/*.gd", "tests/**/*.gd", "scripts/**/*.py", "tests/**/*.py",
    "scripts/**/*.ps1", "native/**/*.cpp", "native/**/*.cc", "native/**/*.cxx", "native/**/*.c",
    "native/**/*.h", "native/**/*.hpp", "native/SConstruct", "assets/**/*.gdshader",
)
ANALYZERS = {".gd": gdscript.analyze, ".py": python.analyze, ".cpp": cpp.analyze,
             ".h": cpp.analyze, ".hpp": cpp.analyze, ".cc": cpp.analyze, ".cxx": cpp.analyze,
             ".c": cpp.analyze, ".gdshader": cpp.analyze, "": python.analyze}


def source_files(root):
    paths = set()
    for pattern in SOURCE_PATTERNS:
        paths.update(root.glob(pattern))
    return sorted(path for path in paths if "godot-cpp" not in path.relative_to(root).parts and path.is_file())


def analyze_file(path, root):
    return ANALYZERS[path.suffix](path.read_text(encoding="utf-8-sig"), path.relative_to(root).as_posix())


def scan(root):
    records, errors, shell_paths = [], [], []
    paths = source_files(root)
    for path in paths:
        if path.suffix == ".ps1":
            shell_paths.append(path)
            continue
        try:
            records.extend(analyze_file(path, root))
        except Exception as error:
            errors.append({"path": path.relative_to(root).as_posix(), "error": str(error)})
    scan_powershell(shell_paths, root, records, errors)
    return {"source_files": len(paths), "records": records, "errors": errors}


def scan_powershell(paths, root, records, errors):
    if not paths:
        return
    try:
        result = powershell.analyze_files(paths, root)
        records.extend(result["records"])
        errors.extend(result["errors"])
    except Exception as error:
        errors.append({"path": "scripts/**/*.ps1", "error": str(error)})


def arguments(argv):
    parser = argparse.ArgumentParser(description="Check all self-maintained client code with strict cyclomatic complexity")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--limit", type=int, choices=[10], default=10)
    parser.add_argument("--format", choices=["text", "json"], default="text")
    return parser.parse_args(argv)


def print_report(report, violations, output_format):
    if output_format == "json":
        print(json.dumps({**report, "limit": 10, "violations": violations}, ensure_ascii=False, indent=2))
        return
    for record in violations:
        print(f'{record["path"]}:{record["line"]}: {record["name"]}: CC={record["cc"]} > 10')
    for error in report["errors"]:
        print(f'{error["path"]}: PARSE ERROR: {error["error"]}', file=sys.stderr)
    print(f'{report["source_files"]} files, {len(report["records"])} units, '
          f'{len(violations)} violations, {len(report["errors"])} parse errors')


def main(argv=None):
    options = arguments(argv)
    report = scan(options.root.resolve())
    violations = [record for record in report["records"] if record["cc"] > options.limit]
    print_report(report, violations, options.format)
    return int(bool(violations) or bool(report["errors"]))


if __name__ == "__main__":
    sys.exit(main())
