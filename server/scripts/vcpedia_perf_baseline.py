"""Paired offline parsing only: full historical HTML extraction versus parse_details.

Reads, hashes, imports and initialization are outside timing. This measures neither
network transfer nor LLM latency. --check performs three complete controlled groups
of the selected reviewed sample set, each requiring new sum of medians < old.
There is no minimum margin or statistical significance guarantee; wall-clock checks
are deliberately not part of ordinary CI.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import statistics
import sys
import time
from importlib.metadata import version
from pathlib import Path

SERVER = Path(__file__).resolve().parents[1]
for root in (SERVER, SERVER / "tests"):
    if str(root) not in sys.path:
        sys.path.insert(0, str(root))

from support.vcpedia_legacy_html import parse_html  # noqa: E402
from support.vcpedia_samples import load_samples  # noqa: E402

from src.world.get_new_songs.wikitext_parser import parse_details  # noqa: E402

FIELDS = {"name", "type", "infobox", "summary", "lyrics", "spaced_lyrics"}
WARMUPS = 2
ROUNDS = 9


def validate_result(result, title):
    if not isinstance(result, dict) or not FIELDS <= result.keys() or result["name"] != title:
        raise ValueError(f"incomplete parser result: {title}")
    if not isinstance(result["infobox"], dict) or not isinstance(result["summary"], list):
        raise ValueError(f"invalid fields: {title}")


def prepare(manifest_path):
    """Validate the declared reviewed sample set before any warmup or timed invocation."""
    manifest, pairs = load_samples(manifest_path)
    root = Path(manifest_path).resolve().parent
    by_title = {p["title"]: p for p in manifest["pages"]}
    pages = []
    for title in manifest["benchmark_titles"]:
        entry = by_title[title]
        source, html = pairs[title]
        if html is None or not source:
            raise ValueError(f"missing pair: {title}")
        pages.append(
            {
                "title": title,
                "source": source,
                "html": html,
                "wikitext_bytes": (root / entry["file"]).stat().st_size,
                "html_bytes": len(html.encode("utf-8")),
                "source_sha256": entry["sha256"],
                "html_sha256": hashlib.sha256(html.encode("utf-8")).hexdigest(),
            }
        )
    return pages


def environment(manifest_path):
    """Hash the explicit local implementation/dependency set before timing, without Git or output files."""
    files = {
        "benchmark_script": SERVER / "scripts/vcpedia_perf_baseline.py",
        "sample_reader": SERVER / "tests/support/vcpedia_samples.py",
        "legacy_adapter": SERVER / "tests/support/vcpedia_legacy_html.py",
        "new_parser": SERVER / "src/world/get_new_songs/wikitext_parser.py",
        "template_rules": SERVER / "src/world/get_new_songs/template_rules.py",
        "text_conversion": SERVER / "src/world/get_new_songs/text_conversion.py",
        "config_rules": SERVER / "config/vcpedia_templates.json",
        "packaged_rules": SERVER / "src/world/get_new_songs/vcpedia_templates.json",
        "manifest": Path(manifest_path),
    }
    return {
        "python": sys.version,
        "platform": platform.platform(),
        "dependencies": {name: version(name) for name in ("beautifulsoup4", "mwparserfromhell", "zhconv")},
        "implementation_sha256": {name: hashlib.sha256(path.read_bytes()).hexdigest() for name, path in files.items()},
    }


def _invoke(side, page, parsers):
    value = page["html"] if side == "old" else page["source"]
    return parsers[side](value, page["title"])


def measure_page(page, page_index, parsers, clock):
    samples = []
    for iteration in range(WARMUPS + ROUNDS):
        order = ["old", "new"] if (iteration + page_index) % 2 == 0 else ["new", "old"]
        times = {}
        for side in order:
            if iteration < WARMUPS:
                result = _invoke(side, page, parsers)
            else:
                start = clock()
                result = _invoke(side, page, parsers)
                elapsed = clock() - start
                if elapsed <= 0:
                    raise ValueError("nonpositive clock sample")
                times[f"{side}_s"] = elapsed
            validate_result(result, page["title"])
        if iteration >= WARMUPS:
            samples.append({"round": iteration - WARMUPS, "order": order, **times})
    old = statistics.median(row["old_s"] for row in samples)
    new = statistics.median(row["new_s"] for row in samples)
    metadata = {k: v for k, v in page.items() if k not in {"source", "html"}}
    return {
        **metadata,
        "samples": samples,
        "old_median_s": old,
        "new_median_s": new,
        "paired_speedup": old / new,
        "file_bytes_ratio": page["html_bytes"] / page["wikitext_bytes"],
    }


def benchmark(pages, *, parsers=None, clock=time.perf_counter):
    if not pages or len({p["title"] for p in pages}) != len(pages):
        raise ValueError("empty/duplicate selected benchmark sample set")
    parsers = parsers or {"old": parse_html, "new": parse_details}
    rows = [measure_page(page, index, parsers, clock) for index, page in enumerate(pages)]
    old_sum = sum(row["old_median_s"] for row in rows)
    new_sum = sum(row["new_median_s"] for row in rows)
    fingerprint = [{k: p[k] for k in ("title", "source_sha256", "html_sha256")} for p in pages]
    return {
        "scope": "offline parse + complete field extraction, no network/LLM/IO/import/init",
        "warmups": WARMUPS,
        "rounds": ROUNDS,
        "sample_set_sha256": hashlib.sha256(json.dumps(fingerprint, sort_keys=True).encode("utf-8")).hexdigest(),
        "sample_set": fingerprint,
        "rows": rows,
        "median_paired_speedup": statistics.median(row["paired_speedup"] for row in rows),
        "sum_old_medians_s": old_sum,
        "sum_new_medians_s": new_sum,
        "sum_medians_group_ratio": old_sum / new_sum,
        "median_file_bytes_ratio": statistics.median(row["file_bytes_ratio"] for row in rows),
        "size_scope": "local UTF-8 file bytes, not network payload",
        "new_faster": new_sum < old_sum,
    }


def run(manifest_path, output, *, check=False, runner=benchmark):
    pages = prepare(manifest_path)
    context = environment(manifest_path)
    groups = [runner(pages) for _ in range(3 if check else 1)]
    passed = all(group["new_faster"] for group in groups)
    result = {**context, "check": check, "check_passed": passed if check else None, "groups": groups}
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0 if not check or passed else 1


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--check",
        action="store_true",
        help="three complete groups of the selected reviewed sample set; "
        "each new sum of medians < old; no minimum margin or statistical significance guarantee",
    )
    args = parser.parse_args(argv)
    try:
        status = run(args.manifest, args.output, check=args.check)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"benchmark failed (no page silently skipped): {exc}", file=sys.stderr)
        return 1
    print(json.dumps({"output": str(args.output), "exit_code": status}, ensure_ascii=False))
    return status


if __name__ == "__main__":
    raise SystemExit(main())
