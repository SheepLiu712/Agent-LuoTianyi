import argparse
from pathlib import Path


def transform_line(line: str) -> str:
    raw = line.rstrip("\n")
    if not raw or "=>" not in raw:
        return line

    left, right = raw.split("=>", 1)
    lyric = left.strip()
    songs = right.strip()

    if not lyric or not songs:
        return line

    first_song = songs.split("|", 1)[0].strip()
    if not first_song:
        return line

    replaced = f"{lyric}=>{lyric}是《{first_song}》的歌词"
    return replaced + "\n"


def rewrite_file(file_path: Path) -> tuple[int, int]:
    if not file_path.exists() or not file_path.is_file():
        raise FileNotFoundError(f"File not found: {file_path}")

    with file_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    updated = [transform_line(line) for line in lines]

    with file_path.open("w", encoding="utf-8", newline="\n") as f:
        f.writelines(updated)

    changed_count = sum(1 for a, b in zip(lines, updated) if a != b)
    return len(lines), changed_count


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Rewrite lyric keyword mapping values for FlashText file"
    )
    parser.add_argument(
        "--file",
        type=Path,
        default=Path("res") / "knowledge" / "song_lyric_keywords.txt",
        help="Target lyric keyword file path",
    )
    args = parser.parse_args()

    total, changed = rewrite_file(args.file)
    print("Rewrite completed")
    print(f"file={args.file}")
    print(f"total_lines={total}")
    print(f"changed_lines={changed}")


if __name__ == "__main__":
    main()
