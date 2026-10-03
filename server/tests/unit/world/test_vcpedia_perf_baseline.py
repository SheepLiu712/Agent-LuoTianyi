"""Deterministic statistics/exit-code tests, never wall-clock speed assertions in CI."""

from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

import pytest

from scripts import vcpedia_perf_baseline as perf

CORPUS = Path(__file__).resolve().parents[2] / "support" / "vcpedia_corpus"
IMPLEMENTATION_FILES = {
    "benchmark_script": "scripts/vcpedia_perf_baseline.py",
    "sample_reader": "tests/support/vcpedia_samples.py",
    "legacy_adapter": "tests/support/vcpedia_legacy_html.py",
    "new_parser": "src/world/get_new_songs/wikitext_parser.py",
    "template_rules": "src/world/get_new_songs/template_rules.py",
    "text_conversion": "src/world/get_new_songs/text_conversion.py",
    "config_rules": "config/vcpedia_templates.json",
    "packaged_rules": "src/world/get_new_songs/vcpedia_templates.json",
}


def page(title):
    return {
        "title": title,
        "html": "html",
        "source": "wiki",
        "html_bytes": 120,
        "wikitext_bytes": 10,
        "source_sha256": "a",
        "html_sha256": "b",
    }


def complete(title):
    return {"name": title, "type": "Song", "infobox": {}, "summary": [], "lyrics": "", "spaced_lyrics": ""}


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.calls = 0

    def __call__(self):
        self.calls += 1
        return self.now


def deterministic_benchmark(pages, *, old_s=4, new_s=2):
    """Exercise report generation with fake parsers and a fake clock, never wall-clock timing."""
    clock = FakeClock()

    def parser(elapsed):
        def parse(value, title):
            clock.now += elapsed
            return complete(title)

        return parse

    return perf.benchmark(pages, parsers={"old": parser(old_s), "new": parser(new_s)}, clock=clock)


@pytest.mark.parametrize(("new_s", "faster"), [(1 - 2**-20, True), (1, False), (1 + 2**-20, False)])
def test_new_faster_requires_strictly_lower_sum_without_minimum_margin(new_s, faster):
    result = deterministic_benchmark([page("selected")], old_s=1, new_s=new_s)
    assert result["sum_old_medians_s"] == 1
    assert result["sum_new_medians_s"] == new_s
    assert result["new_faster"] is faster


def test_warmup_alternation_all_samples_and_paired_statistics():
    clock, calls = FakeClock(), []

    def parser(side):
        def parse(value, title):
            calls.append((side, title, value))
            clock.now += 4 if side == "old" else 2
            return complete(title)

        return parse

    result = perf.benchmark([page("a"), page("b")], parsers={s: parser(s) for s in ("old", "new")}, clock=clock)
    assert len(calls) == 2 * (2 + 9) * 2
    assert clock.calls == 2 * 9 * 2 * 2
    assert [side for side, _, _ in calls[:6]] == ["old", "new", "new", "old", "old", "new"]
    assert calls[22][0] == "new"
    assert all(len(row["samples"]) == 9 for row in result["rows"])
    assert result["rows"][0]["samples"][0]["order"] == ["old", "new"]
    assert result["rows"][1]["samples"][0]["order"] == ["new", "old"]
    assert result["sum_old_medians_s"] == 8
    assert result["sum_new_medians_s"] == 4
    assert result["sum_medians_group_ratio"] == result["median_paired_speedup"] == 2
    assert result["median_file_bytes_ratio"] == 12
    assert result["new_faster"]


def test_medians_not_best_case_or_ratio_of_unpaired_medians():
    clock, counters = FakeClock(), {("old", "a"): 0, ("new", "a"): 0, ("old", "b"): 0, ("new", "b"): 0}
    samples = {
        ("old", "a"): [99, 99, 1, 10, 10, 10, 10, 10, 10, 10, 100],
        ("new", "a"): [99, 99] + [2] * 9,
        ("old", "b"): [99, 99] + [3] * 9,
        ("new", "b"): [99, 99] + [6] * 9,
    }

    def parser(side):
        def parse(value, title):
            key = side, title
            clock.now += samples[key][counters[key]]
            counters[key] += 1
            return complete(title)

        return parse

    pages = [page("a"), {**page("b"), "html_bytes": 30}]
    result = perf.benchmark(pages, parsers={s: parser(s) for s in ("old", "new")}, clock=clock)
    assert result["rows"][0]["old_median_s"] == 10
    assert result["median_paired_speedup"] == (5 + 0.5) / 2
    assert result["sum_medians_group_ratio"] == 13 / 8
    assert result["median_file_bytes_ratio"] == (12 + 3) / 2


def test_parser_failures_are_never_silently_skipped():
    def broken(value, title):
        raise ValueError("parse failed")

    with pytest.raises(ValueError, match="parse failed"):
        perf.benchmark([page("bad")], parsers={"old": broken, "new": broken})
    with pytest.raises(ValueError, match="incomplete"):
        perf.benchmark([page("bad")], parsers={"old": lambda *_: None, "new": lambda *_: None})
    with pytest.raises(ValueError, match="empty/duplicate"):
        perf.benchmark([])


def test_controlled_check_runs_three_whole_groups_and_writes_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(perf, "prepare", lambda _: [page("selected")])
    monkeypatch.setattr(perf, "environment", lambda _: {"probe": "中文报告"})
    called = []

    def run_group(pages):
        called.append(pages)
        return {"new_faster": len(called) != 2}

    output = tmp_path / "performance.json"
    assert perf.run("unused", output, check=True, runner=run_group) == 1
    assert len(called) == 3
    assert all(pages == [page("selected")] for pages in called)
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["check_passed"] is False
    assert report["probe"] == "中文报告"


def test_report_identifies_the_samples_actually_selected(tmp_path):
    source = tmp_path / "inputs"
    shutil.copytree(CORPUS, source, ignore=shutil.ignore_patterns("results", "__pycache__"))
    path = source / "manifest.json"
    original = deterministic_benchmark(perf.prepare(path))
    value = json.loads(path.read_text(encoding="utf-8"))
    value["benchmark_titles"].pop()
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    pages = perf.prepare(path)
    assert [item["title"] for item in pages] == value["benchmark_titles"]
    output = tmp_path / "replacement-performance.json"
    assert perf.run(path, output, runner=deterministic_benchmark) == 0
    group = json.loads(output.read_text(encoding="utf-8"))["groups"][0]
    assert group["sample_set"] == original["sample_set"][:-1]
    assert group["sample_set_sha256"] != original["sample_set_sha256"]


def test_missing_declared_sample_is_not_silently_skipped(tmp_path):
    source = tmp_path / "inputs"
    shutil.copytree(CORPUS, source, ignore=shutil.ignore_patterns("results", "__pycache__"))
    path = source / "manifest.json"
    value = json.loads(path.read_text(encoding="utf-8"))
    entry = next(page for page in value["pages"] if page["title"] == value["benchmark_titles"][0])
    (source / entry["file"]).unlink()
    output = tmp_path / "report.json"
    assert perf.main(["--manifest", str(path), "--output", str(output)]) == 1
    assert not output.exists()


def test_environment_hashes_explicit_local_implementation_files():
    path = CORPUS / "manifest.json"
    expected = {
        name: hashlib.sha256((perf.SERVER / relative).read_bytes()).hexdigest()
        for name, relative in IMPLEMENTATION_FILES.items()
    }
    expected["manifest"] = hashlib.sha256(path.read_bytes()).hexdigest()
    assert perf.environment(path)["implementation_sha256"] == expected


@pytest.mark.parametrize("dependency", ["template_rules", "text_conversion"])
def test_transitive_dependency_change_updates_hash_without_git(tmp_path, monkeypatch, dependency):
    server = tmp_path / "exported-server"
    for relative in IMPLEMENTATION_FILES.values():
        target = server / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(perf.SERVER / relative, target)
    path = server / "manifest.json"
    shutil.copyfile(CORPUS / "manifest.json", path)
    monkeypatch.setattr(perf, "SERVER", server)
    assert not (server / ".git").exists()
    before = perf.environment(path)["implementation_sha256"]
    changed = server / IMPLEMENTATION_FILES[dependency]
    changed.write_bytes(changed.read_bytes() + b"\n# changed dependency\n")
    after = perf.environment(path)["implementation_sha256"]
    assert {name for name in before if before[name] != after[name]} == {dependency}
    assert after[dependency] == hashlib.sha256(changed.read_bytes()).hexdigest()


def test_environment_hashes_are_recorded_before_runner(tmp_path, monkeypatch):
    events = []
    original_environment = perf.environment

    def prepare(_):
        events.append("prepare")
        return [page("selected")]

    def environment(path):
        events.append("environment")
        return original_environment(path)

    def runner(pages):
        assert events == ["prepare", "environment"]
        events.append("runner")
        return deterministic_benchmark(pages)

    monkeypatch.setattr(perf, "prepare", prepare)
    monkeypatch.setattr(perf, "environment", environment)
    output = tmp_path / "performance.json"
    assert perf.run(CORPUS / "manifest.json", output, runner=runner) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert events == ["prepare", "environment", "runner"]
    assert report["implementation_sha256"] == original_environment(CORPUS / "manifest.json")["implementation_sha256"]


def test_cli_missing_manifest_returns_real_failure_code(tmp_path):
    output = tmp_path / "never.json"
    assert perf.main(["--manifest", str(tmp_path / "missing.json"), "--output", str(output), "--check"]) == 1
    assert not output.exists()
