"""Product regressions on checked-in examples; known omissions are reported, not required to persist."""

from __future__ import annotations

import ast
import hashlib
import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from support.vcpedia_corpus import oracle_support
from support.vcpedia_corpus.oracle_support import counts, normalized, score
from support.vcpedia_legacy_html import parse_html
from support.vcpedia_samples import load_samples

from src.world.get_new_songs.wikitext_parser import parse_details

CORPUS = Path(__file__).resolve().parents[2] / "support" / "vcpedia_corpus"
MANIFEST, PAIRS = load_samples(CORPUS / "manifest.json")
ORACLE = json.loads((CORPUS / "oracle.json").read_text(encoding="utf-8"))["pages"]


@pytest.fixture(autouse=True)
def prohibit_network(monkeypatch):
    import requests

    def fail(*args, **kwargs):
        raise AssertionError("corpus evaluation must not access network or LLM")

    monkeypatch.setattr(requests.sessions.Session, "request", fail)


def _historical_parser():
    raw = (CORPUS / "reference" / "vcpedia_fetcher.py.txt").read_bytes()
    blob = hashlib.sha1(b"blob " + str(len(raw)).encode() + b"\0" + raw).hexdigest()
    assert blob == "3208aae7a2f2dc74f9c77f2c8b7bcee680b596a5"
    tree = ast.parse(raw.decode("utf-8"))
    cls = next(node for node in tree.body if isinstance(node, ast.ClassDef))
    methods = [
        node
        for node in cls.body
        if isinstance(node, ast.FunctionDef) and node.name in {"_parse_page", "_get_data_from_infobox"}
    ]
    assert len(methods) == 2
    isolated = ast.Module(
        body=[ast.ClassDef(name="Reference", bases=[], keywords=[], body=methods, decorator_list=[])],
        type_ignores=[],
    )
    namespace = {"BeautifulSoup": BeautifulSoup, "re": re, "Dict": dict, "List": list, "Any": object}
    exec(compile(ast.fix_missing_locations(isolated), "frozen historical methods", "exec"), namespace)
    return namespace["Reference"]()._parse_page


@pytest.mark.parametrize("title", [title for title, (_, html) in PAIRS.items() if html is not None])
def test_full_legacy_adapter_equals_frozen_original_on_every_pair(title):
    assert parse_html(PAIRS[title][1], title) == _historical_parser()(PAIRS[title][1], title)


@pytest.mark.parametrize(
    "html",
    [
        "<h2>other</h2><p>fallback</p>",
        "<h2>简介</h2><p>hello<a>world</a></p><h3>stop</h3><p>not intro</p>",
        '<table class="moe-infobox infobox"><tr><td>作编曲</td></tr><tr><td>作者</td></tr></table>',
        '<h2>歌词</h2><div class="Tabs"><p>no poem</p></div><div class="poem"><p>ignored</p></div>',
        '<h2>歌词</h2><table class="navbox"></table><div class="poem"><p>A(和声)<span>B</span></p></div>',
    ],
)
def test_legacy_adapter_preserves_old_edge_behaviour(html):
    assert parse_html(html, "synthetic") == _historical_parser()(html, "synthetic")


@pytest.mark.parametrize("title", sorted(ORACLE))
def test_song_type_and_credit_fields_match_reviewed_content(title):
    data = parse_details(PAIRS[title][0], title)
    assert data["type"] == ORACLE[title]["type"]
    for key, value in ORACLE[title]["infobox"].items():
        assert normalized(data["infobox"].get(key, "")) == normalized(value), (title, key)


@pytest.mark.parametrize(
    "title",
    [
        "Estrus Cycle",
        "I LOVE YOU(Adaa)",
        "唱给雅音宫羽",
        "山塘恋雨",
        "普通DISCO",
        "横竖撇点折",
        "疑神疑鬼",
        "礼物pre-Sent",
        "神孽",
        "达拉崩吧",
        "长平传",
        "青麟雪",
        "飞跃乌托邦",
    ],
)
def test_supported_first_lyric_candidates_match_reviewed_text(title):
    data = parse_details(PAIRS[title][0], title)
    assert normalized(data["lyrics"]) == normalized(ORACLE[title]["lyrics"])


@pytest.mark.parametrize(
    ("title", "fact"),
    [
        ("Foxy", "九尾妖狐阿狸"),
        ("I LOVE YOU(Adaa)", "第六作"),
        ("唱给雅音宫羽", "雅音宫羽组曲第一作"),
        ("山塘恋雨", "洛梦江南系列-姑苏篇"),
        ("普通DISCO", "2015年3月21日"),
    ],
)
def test_summary_preserves_reviewed_facts(title, fact):
    data = parse_details(PAIRS[title][0], title)
    assert normalized(fact) in normalized("\n".join(data["summary"]))


@pytest.mark.parametrize(
    ("title", "literal"),
    [
        ("长平传", "馝花紡裰擾蚙蠰"),
        ("达拉崩吧", "啦啦达拉崩巴"),
        ("礼物pre-Sent", "（怎敢跳脱程序 直白将爱提起）"),
    ],
)
def test_raw_protected_glyph_ruby_and_parenthetical_witnesses(title, literal):
    assert literal in parse_details(PAIRS[title][0], title)["lyrics"]


@pytest.mark.parametrize(
    ("lyrics", "exact", "representative"),
    [
        ("first\nsecond\nmiddle\nfourth\nlast", True, True),
        ("first\nmiddle\nlast", False, True),
        ("", False, False),
    ],
)
def test_lyric_slots_preserve_correlated_exact_and_representative_diagnostics(lyrics, exact, representative):
    expected = {"type": "Song", "lyrics": "first\nsecond\nmiddle\nfourth\nlast", "infobox": {}, "summary_facts": []}
    checks = score({"type": "Song", "lyrics": lyrics}, expected)
    assert checks["lyrics_exact"] is exact
    assert checks["lyrics_representative_order"] is representative
    totals = counts({"sample": {"old": checks, "new": checks}})["new"]
    assert totals["check_slots"] == 3
    assert totals["matched_slots"] == 1 + exact + representative
    assert totals["unmatched_slots"] == (not exact) + (not representative)
    assert totals["lyrics_pages"] == 1
    assert totals["lyrics_exact_pages"] == int(exact)


def test_normalization_only_converts_zh_cn_and_removes_whitespace():
    assert normalized(" 歌詞\tＡa（合聲）!\n") == "歌词Ａa（合声）!"


@pytest.mark.parametrize(("matches", "selected"), [(False, True), (True, True), (True, False)])
def test_content_cli_checks_correctness_instead_of_requiring_previous_errors(tmp_path, monkeypatch, matches, selected):
    import support.vcpedia_legacy_html as legacy
    import support.vcpedia_samples as samples

    import src.world.get_new_songs.wikitext_parser as parser

    expected = {"type": "Song", "lyrics": "甲\n乙\n丙", "infobox": {}, "summary_facts": []}
    (tmp_path / "oracle.json").write_text(json.dumps({"pages": {"example": expected}}), encoding="utf-8")
    monkeypatch.setattr(
        samples,
        "load_samples",
        lambda _: (
            {"selected_titles": ["example"] if selected else []},
            {"example": ("source", "html")},
        ),
    )
    monkeypatch.setattr(legacy, "parse_html", lambda *_: {**expected, "summary": []})
    monkeypatch.setattr(
        parser,
        "parse_details",
        lambda *_: {
            **expected,
            "summary": [],
            "lyrics": expected["lyrics"] if matches else "wrong",
        },
    )
    output = tmp_path / "report.json"
    assert oracle_support.main(
        [
            "--manifest",
            str(tmp_path / "manifest.json"),
            "--output",
            str(output),
            "--check",
        ]
    ) == (0 if matches and selected else 1)
    if not selected:
        assert not output.exists()
        return
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["effect_complete"] is matches
    assert report["rows"]["example"]["new"]["lyrics_exact"] is matches
