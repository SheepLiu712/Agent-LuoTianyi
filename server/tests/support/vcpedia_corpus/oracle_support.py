"""Content checks against a separately reviewed oracle, not parser-derived expectations."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from zhconv import convert


def normalized(text):
    """Convert only to zh-cn and remove whitespace; preserve other text differences."""
    return re.sub(r"\s+", "", convert(str(text), "zh-cn"))


def ordered_lines(text, lines):
    value, offset = normalized(text), 0
    for line in lines:
        position = value.find(normalized(line), offset)
        if position < 0:
            return False
        offset = position + len(normalized(line))
    return True


def score(data, oracle):
    """Keep per-field diagnostics, including correlated exact/representative lyric checks."""
    lyrics = oracle["lyrics"]
    lines = lyrics.splitlines()
    representative = [lines[0], lines[len(lines) // 2], lines[-1]]
    info = data.get("infobox", {})
    summary = "\n".join(data.get("summary", []))
    return {
        "type": data.get("type") == oracle["type"],
        "lyrics_exact": normalized(data.get("lyrics", "")) == normalized(lyrics),
        "lyrics_representative_order": ordered_lines(data.get("lyrics", ""), representative),
        "infobox": {
            key: normalized(info.get(key, "")) == normalized(value) for key, value in oracle["infobox"].items()
        },
        "summary_facts": {fact: normalized(fact) in normalized(summary) for fact in oracle["summary_facts"]},
    }


def compare(pairs, old_parse, new_parse, oracle_path=None):
    path = oracle_path or Path(__file__).with_name("oracle.json")
    oracle = json.loads(Path(path).read_text(encoding="utf-8"))
    rows = {}
    for title, expected in oracle["pages"].items():
        source, html = pairs[title]
        rows[title] = {"old": score(old_parse(html, title), expected), "new": score(new_parse(source, title), expected)}
    return {
        "scope": "selected first-candidate content checks against a reviewed oracle; " "not whole-song/global accuracy",
        "counts_semantics": "Correlated boolean check slots, not independent defects or accuracy; "
        "exact and representative lyric checks overlap. Lyrics page counts are separate; "
        "normalization only converts to zh-cn and removes whitespace.",
        "old_24_song_claim": "unverified: this is cache21 + random10, not the historical daily first24",
        "rows": rows,
    }


def counts(rows):
    """Count correlated boolean check slots, not distinct defects or an accuracy score."""
    result = {}
    for side in ("old", "new"):
        flat = []
        for row in rows.values():
            values = row[side]
            flat.extend([values["type"], values["lyrics_exact"], values["lyrics_representative_order"]])
            flat.extend(values["infobox"].values())
            flat.extend(values["summary_facts"].values())
        exact = sum(row[side]["lyrics_exact"] for row in rows.values())
        result[side] = {
            "check_slots": len(flat),
            "matched_slots": sum(flat),
            "unmatched_slots": len(flat) - sum(flat),
            "lyrics_pages": len(rows),
            "lyrics_exact_pages": exact,
            "lyrics_nonexact_pages": len(rows) - exact,
        }
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--check", action="store_true", help="fail when any selected content check is unmet")
    args = parser.parse_args(argv)
    server = Path(__file__).resolve().parents[3]
    sys.path[:0] = [str(server), str(server / "tests")]
    from support.vcpedia_legacy_html import parse_html
    from support.vcpedia_samples import load_samples

    from src.world.get_new_songs.wikitext_parser import parse_details

    try:
        manifest, pairs = load_samples(args.manifest)
        report = compare(pairs, parse_html, parse_details, args.manifest.parent / "oracle.json")
        if not manifest["selected_titles"]:
            raise ValueError("No selected content examples")
        selected = {title: report["rows"][title] for title in manifest["selected_titles"]}
        report["selected_titles"] = manifest["selected_titles"]
        report["selected_counts"] = counts(selected)
        report["extended_counts"] = counts(report["rows"])
        report["effect_complete"] = report["selected_counts"]["new"]["unmatched_slots"] == 0
        report["check_policy"] = "Unmet selected checks are reported, never required to remain false."
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"content comparison failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report["selected_counts"], ensure_ascii=False))
    return int(args.check and not report["effect_complete"])


if __name__ == "__main__":
    raise SystemExit(main())
