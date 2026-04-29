import argparse
from pathlib import Path


def should_keep_line(line: str) -> bool:
    raw = line.rstrip("\n")
    if not raw or "=>" not in raw:
        return True

    lyric, _ = raw.split("=>", 1)
    return len(lyric.strip()) >= 6


def clean_file(file_path: Path) -> tuple[int, int]:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    kept_lines = [line for line in lines if should_keep_line(line)]
    removed_count = len(lines) - len(kept_lines)

    with file_path.open("w", encoding="utf-8", newline="\n") as f:
        f.writelines(kept_lines)

    return len(lines), removed_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Remove lyric keyword lines whose lyric part before => is shorter than 6 characters"
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("res") / "knowledge" / "song_lyric_keywords.txt",
        help="Target lyric keyword file path",
    )
    args = parser.parse_args()

    total, removed = clean_file(args.file)
    print("Cleanup completed")
    print(f"file={args.file}")
    print(f"total_lines={total}")
    print(f"removed_lines={removed}")
    print(f"kept_lines={total - removed}")


if __name__ == "__main__":
    main()
