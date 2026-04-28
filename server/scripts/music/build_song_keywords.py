import argparse
import json
import re
import unicodedata
from pathlib import Path
from typing import Iterable


LEFT_TO_RIGHT = {
    "[": "]",
    "【": "】",
    "(": ")",
    "（": "）",
    "{": "}",
    "《": "》",
    "<": ">",
    "〈": "〉",
    "「": "」",
    "『": "』",
}

MAJOR_SPLIT_PUNCT = set("，。！？,.!?")

STRIP_CHARS = set(
    "\"'“”‘’「」『』《》()（）[]【】{}<>〈〉"
)


def is_punctuation_char(ch: str) -> bool:
    return unicodedata.category(ch).startswith("P")


def remove_square_bracket_content_if_partial(s: str) -> str:
    """
    Rule a:
    - If [] or 【】 appears and the whole sentence is NOT exactly inside one bracket pair,
      remove the bracketed content.
    """
    text = s
    for left, right in (("[", "]"), ("【", "】")):
        stripped = text.strip()
        if stripped.startswith(left) and stripped.endswith(right):
            # Whole sentence wrapped: keep content for now; brackets are removed in later rule.
            continue
        pattern = re.escape(left) + r"[^" + re.escape(right) + r"]*" + re.escape(right)
        text = re.sub(pattern, "", text)
    return text


def cut_at_unmatched_left_bracket(s: str) -> str:
    """
    Rule b:
    - If there is an unmatched left bracket, delete that left bracket and all following content.
    """
    stack: list[tuple[str, int]] = []
    for idx, ch in enumerate(s):
        if ch in LEFT_TO_RIGHT:
            stack.append((ch, idx))
            continue

        if ch in LEFT_TO_RIGHT.values() and stack:
            left_ch, _pos = stack[-1]
            if LEFT_TO_RIGHT[left_ch] == ch:
                stack.pop()

    if not stack:
        return s

    cut_pos = min(pos for _, pos in stack)
    return s[:cut_pos]


def split_on_major_punct_if_long_enough(s: str) -> list[str]:
    """
    Rule d (part):
    - Try split on comma/period/exclamation/question if both sides are >7 chars.
    """
    text = s.strip()
    if not text:
        return []

    for idx, ch in enumerate(text):
        if ch not in MAJOR_SPLIT_PUNCT:
            continue
        left = text[:idx].strip()
        right = text[idx + 1 :].strip()
        if len(left) > 7 and len(right) > 7:
            return split_on_major_punct_if_long_enough(left) + split_on_major_punct_if_long_enough(right)

    return [text]


def normalize_lyric_piece(piece: str) -> str:
    """Apply rule b/c/d cleanup to one lyric piece."""
    text = cut_at_unmatched_left_bracket(piece)

    # Rule c: delete quotes/brackets/book-title marks.
    text = "".join(ch for ch in text if ch not in STRIP_CHARS)

    # Rule d (part): delete all punctuation.
    text = "".join(ch for ch in text if not is_punctuation_char(ch))

    return text.strip()


def extract_lyric_keywords(lyrics_text: str) -> Iterable[str]:
    """Extract lyric keywords according to cleaning rules and length constraint (>7)."""
    for raw in re.split(r"\s+", lyrics_text):
        token = raw.strip()
        if not token:
            continue

        # Rule a first: remove partial []/【】 inner content.
        token = remove_square_bracket_content_if_partial(token)
        if not token.strip():
            continue

        # Rule d split attempt on major punctuation.
        split_parts = split_on_major_punct_if_long_enough(token)
        for part in split_parts:
            normalized = normalize_lyric_piece(part)
            if len(normalized) > 7:
                yield normalized


def extract_string_values(value) -> Iterable[str]:
    """Recursively extract string values from a JSON value."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from extract_string_values(item)
    elif isinstance(value, dict):
        for item in value.values():
            yield from extract_string_values(item)


def collect_keywords(song_dir: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Collect song-name keywords and lyric keywords mapped to source song names."""
    song_names: set[str] = set()
    lyric_to_songs: dict[str, set[str]] = {}

    json_files = sorted(song_dir.glob("*.json"))
    for json_file in json_files:
        # 1) Song name keyword from file stem
        song_name = json_file.stem.strip()
        if song_name:
            song_names.add(song_name)

        # 2) Lyric keywords from json['lyrics'] when it contains strings
        try:
            with json_file.open("r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            # Skip unreadable/broken json files
            continue

        if not isinstance(data, dict) or "lyrics" not in data:
            continue

        for lyrics_text in extract_string_values(data.get("lyrics")):
            for kw in extract_lyric_keywords(lyrics_text):
                lyric_to_songs.setdefault(kw, set()).add(song_name)

    return song_names, lyric_to_songs


def write_song_names(output_path: Path, song_names: set[str]) -> None:
    """Write one song-name keyword per line for FlashText add_keyword_from_file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for kw in sorted(song_names):
            f.write(f"{kw}\n")


def write_lyric_keywords_with_source(output_path: Path, lyric_to_songs: dict[str, set[str]]) -> None:
    """
    Write lyric keywords with source song names.
    Format per line: lyric_keyword=>song1|song2|...
    This format is compatible with FlashText add_keyword_from_file (mapped clean name).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8", newline="\n") as f:
        for lyric_kw in sorted(lyric_to_songs):
            source = "|".join(sorted(lyric_to_songs[lyric_kw]))
            f.write(f"{lyric_kw}=>{source}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Build song/lyrics keywords for FlashText")
    parser.add_argument(
        "--song-dir",
        type=Path,
        default=Path("res") / "knowledge" / "歌曲合集",
        help="Directory containing song json files",
    )
    parser.add_argument(
        "--song-output",
        type=Path,
        default=Path("res") / "knowledge" / "song_name_keywords.txt",
        help="Output txt path for song-name keywords",
    )
    parser.add_argument(
        "--lyric-output",
        type=Path,
        default=Path("res") / "knowledge" / "song_lyric_keywords.txt",
        help="Output txt path for lyric keywords with source songs",
    )
    args = parser.parse_args()

    if not args.song_dir.exists() or not args.song_dir.is_dir():
        raise SystemExit(f"song-dir does not exist or is not a directory: {args.song_dir}")

    song_names, lyric_to_songs = collect_keywords(args.song_dir)
    write_song_names(args.song_output, song_names)
    write_lyric_keywords_with_source(args.lyric_output, lyric_to_songs)

    lyric_source_rows = sum(len(v) for v in lyric_to_songs.values())

    print("Build completed")
    print(f"song_dir={args.song_dir}")
    print(f"song_output={args.song_output}")
    print(f"lyric_output={args.lyric_output}")
    print(f"song_name_keywords={len(song_names)}")
    print(f"lyric_unique_keywords={len(lyric_to_songs)}")
    print(f"lyric_keyword_song_links={lyric_source_rows}")


if __name__ == "__main__":
    main()
