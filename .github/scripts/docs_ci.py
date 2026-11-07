"""识别纯文档改动，检查修改文档及其他 Markdown 对这些文档的引用。"""

import argparse
import os
import re
import subprocess
from pathlib import Path


def git_paths(command: str, *args: str) -> list[Path]:
    output = subprocess.check_output(["git", command, "-z", *args])
    return [Path(os.fsdecode(name)) for name in output.split(b"\0") if name]


def check_links(paths: list[Path]) -> None:
    common = [
        "lychee",
        "--no-progress",
        "--include-fragments=anchor-only",
        "--root-dir",
        ".",
    ]
    edited = [path for path in paths if path.is_file()]
    if edited:
        subprocess.run([*common, "--exclude-all-private", "--", *edited], check=True)

    # 重命名、删除文件或修改标题，也可能破坏未修改文档中的链接。
    unchanged = sorted(set(git_paths("ls-files", "--", "*.md")) - set(paths))
    if unchanged:
        targets = "|".join(re.escape(path.absolute().as_uri()) for path in paths)
        subprocess.run(
            [
                *common,
                "--offline",
                "--exclude",
                ".*",
                "--include",
                f"^(?:{targets})(?:[#?]|$)",
                "--",
                *unchanged,
            ],
            check=True,
        )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=["classify", "check"])
    parser.add_argument("base")
    args = parser.parse_args()
    # 将重命名视为删除和新增，跨出或移入 docs 的改动都必须走完整检查。
    paths = git_paths("diff", "--name-only", "--no-renames", args.base, "HEAD")
    docs_only = bool(paths) and all(
        path.parts[0] == "docs" and path.suffix == ".md" for path in paths
    )
    if args.command == "classify":
        print("docs_only=" + str(docs_only).lower())
    elif docs_only:
        check_links(paths)
    else:
        raise SystemExit("此次改动需要执行完整检查")


if __name__ == "__main__":
    main()
