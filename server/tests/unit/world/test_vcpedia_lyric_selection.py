"""Single-version selection through real fetcher orchestration with fake HTTP/model boundaries."""

from __future__ import annotations

import json
from urllib.parse import parse_qs

import pytest
import requests

from src.world.get_new_songs.daily_new_song_fetcher import _fetch_candidate
from src.world.get_new_songs.source_extraction import collect_materials, merge_missing
from src.world.get_new_songs.text_conversion import spaced_from
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher
from src.world.get_new_songs.wikitext_parser import parse_details

INTRO = "== 简介 ==\n歌曲的独立简介。\n== 歌词 ==\n"


class Model:
    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def generate_response(self, **variables):
        self.calls.append({key: json.loads(value) for key, value in variables.items()})
        if isinstance(self.answer, Exception):
            raise self.answer
        return self.answer


def response(payload):
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps({"parse": payload}, ensure_ascii=False).encode("utf-8")
    result.encoding = "utf-8"
    return result


def setup_fetcher(monkeypatch, tmp_path, source, *, rendered=None, answer=None, **config):
    extractor = Model(answer if answer is not None else {"lyrics": "不应覆盖已完整的歌词"})
    summarizer = Model("独立短简介")
    fetcher = VCPediaFetcher(
        {"activated": True, "data_dir": str(tmp_path), **config},
        llm_module=summarizer,
        extraction_llm_module=extractor,
    )
    calls = {"get": [], "post": []}

    def get(url, **kwargs):
        calls["get"].append(url)
        return response({"wikitext": {"*": source}})

    def post(url, **kwargs):
        call = parse_qs(kwargs["data"].decode("utf-8"))["text"][0]
        calls["post"].append(call)
        assert rendered is not None and call in rendered, f"Unexpected lyric render: {call}"
        value = rendered[call]
        if isinstance(value, Exception):
            raise value
        return response({"text": {"*": value}})

    monkeypatch.setattr(fetcher.session, "get", get)
    monkeypatch.setattr(fetcher.session, "post", post)
    return fetcher, extractor, summarizer, calls


@pytest.mark.parametrize("first_complete", [True, False])
def test_any_rule_complete_version_prevents_all_lyric_supplements(monkeypatch, tmp_path, first_complete):
    complete = "<poem>第一句确定的歌词\n（重复副歌）\n\n（重复副歌）</poem>"
    broken = "<poem>另一版已知行{{embed|另一版未解行}}</poem>"
    bodies = [complete, broken] if first_complete else [broken, complete]
    fetcher, extractor, summarizer, calls = setup_fetcher(monkeypatch, tmp_path, INTRO + "\n".join(bodies))

    data = fetcher.fetch_entity_description("某歌")

    assert data["lyrics"] == "第一句确定的歌词\n（重复副歌）\n\n（重复副歌）"
    assert data["spaced_lyrics"] == spaced_from(data["lyrics"])
    assert calls["post"] == []
    assert extractor.calls == []
    assert summarizer.calls[0]["song_data"]["lyrics"] == data["lyrics"]


def test_multiple_complete_versions_choose_source_order_not_length_or_label(monkeypatch, tmp_path):
    source = INTRO + "<poem>短版完整歌词</poem>\n== 新版歌词 ==\n<poem>更长的新版完整歌词正文</poem>"
    fetcher, extractor, _, calls = setup_fetcher(monkeypatch, tmp_path, source)
    assert fetcher.fetch_entity_description("某歌")["lyrics"] == "短版完整歌词"
    assert extractor.calls == calls["post"] == []


def test_all_rule_candidates_run_before_render_and_all_render_before_selection(monkeypatch, tmp_path):
    source = INTRO + "<poem>{{embed|甲}}\n{{未知|缺口}}</poem><poem>乙开头\n{{embed|乙}}</poem>"
    fetcher, extractor, _, calls = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        rendered={"{{embed|甲}}": "<p>甲版片段</p>", "{{embed|乙}}": "<p>乙版结尾</p>"},
    )
    data = fetcher.fetch_entity_description("某歌")
    assert calls["post"] == ["{{embed|甲}}", "{{embed|乙}}"]
    assert extractor.calls == []
    assert data["lyrics"] == "乙开头\n乙版结尾"
    assert data["spaced_lyrics"] == spaced_from(data["lyrics"])


def test_all_render_complete_versions_still_choose_earliest_source(monkeypatch, tmp_path):
    source = INTRO + "<poem>{{embed|甲}}</poem><poem>{{embed|乙}}</poem>"
    fetcher, extractor, _, calls = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        rendered={"{{embed|甲}}": "<p>甲版完整</p>", "{{embed|乙}}": "<p>乙版完整</p>"},
    )
    assert fetcher.fetch_entity_description("某歌")["lyrics"] == "甲版完整"
    assert calls["post"] == ["{{embed|甲}}", "{{embed|乙}}"]
    assert extractor.calls == []


def test_model_receives_only_best_candidate_and_final_keywords_follow_it(monkeypatch, tmp_path):
    source = (
        INTRO + "<poem>被舍弃版{{未知|被舍弃的待提取歌词内容很长很长}}</poem>"
        "<poem>被选择版本的已知歌词\n{{embed|被选择版渲染}}\n{{未知|尾}}</poem>"
    )
    final = "被选择版本的最终歌词\n重复副歌不能删除\n重复副歌不能删除"
    fetcher, extractor, summarizer, calls = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        rendered={"{{embed|被选择版渲染}}": "<p>该版渲染的歌词行</p>"},
        answer={"lyrics": final},
    )
    candidate = _fetch_candidate(fetcher, "某歌")
    assert calls["post"] == ["{{embed|被选择版渲染}}"]
    assert len(extractor.calls) == 1
    variables = extractor.calls[0]
    assert "被舍弃" not in json.dumps(variables, ensure_ascii=False)
    materials = variables["materials"]["lyrics"]
    assert materials["rule_result"] == "被选择版本的已知歌词"
    assert materials["rendered"] == [{"source": "{{embed|被选择版渲染}}", "text": "该版渲染的歌词行"}]
    assert materials["gaps"] == ["{{未知|尾}}"]
    assert "该版渲染的歌词行" in variables["song_data"]["lyrics"]
    assert candidate.lyrics == final
    assert candidate.lyric_keywords == ("被选择版本的最终歌词", "重复副歌不能删除", "重复副歌不能删除")
    assert summarizer.calls[0]["song_data"]["lyrics"] == final


def test_rendered_repetitions_and_protected_glyphs_survive(monkeypatch, tmp_path):
    source = INTRO + "<poem>开头\n{{embed|副歌}}\n\n{{embed|副歌}}\n结尾</poem>"
    fetcher, extractor, _, _ = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        rendered={"{{embed|副歌}}": "<p>臺灣（和声）<br/>第二行</p>"},
    )
    data = fetcher.fetch_entity_description("某歌")
    assert data["lyrics"] == "开头\n臺灣（和声）\n第二行\n\n臺灣（和声）\n第二行\n结尾"
    assert data["spaced_lyrics"] == spaced_from(data["lyrics"])
    assert extractor.calls == []


@pytest.mark.parametrize("answer", ["not JSON", [], {}, {"lyrics": " "}, {"lyrics": []}, RuntimeError("failed")])
def test_unsuccessful_model_does_not_submit_partial_lyrics(monkeypatch, tmp_path, answer):
    source = INTRO + "<poem>已知部分歌词{{未知|剩余部分}}</poem>"
    fetcher, extractor, summarizer, _ = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        answer=answer,
        merge_rendered_fragments=False,
    )
    assert _fetch_candidate(fetcher, "某歌") is None
    assert len(extractor.calls) == len(summarizer.calls) == 1
    assert summarizer.calls[0]["song_data"]["lyrics"] == "已知部分歌词"


@pytest.mark.parametrize("value", [None, "", " \n ", [], 42, {"lyrics": "wrong shape"}])
def test_invalid_lyric_value_never_clears_needed(value):
    data = {"infobox": {}, "summary": [], "lyrics": "已有部分", "spaced_lyrics": "已有部分"}
    needed = {"infobox": [], "summary": False, "lyrics": True}
    merge_missing(data, {"lyrics": value}, needed)
    assert needed["lyrics"] is True
    assert data["lyrics"] == data["spaced_lyrics"] == "已有部分"


@pytest.mark.parametrize(
    "html",
    [
        "",
        "<p> </p>",
        '<strong class="error">模板错误</strong>',
        '<a class="new">Template:missing</a>',
        '<div class="poem">甲版</div><div class="poem">乙版</div>',
        '<div class="Tabs"><div class="TabContentText">甲版</div>'
        '<div class="TabContentText"><div class="poem">乙版</div></div></div>',
        '<div class="tabber"><div class="tabbertab">旧版</div><div class="tabbertab">新版</div></div>',
        '<div class="Lyrics"><div class="Lyrics-original">原文</div>' '<div class="Lyrics-translated">译文</div></div>',
        "<table><tr><td>原文</td><td>译文</td></tr></table>",
        "<p>" + "字" * 12001 + "</p>",
    ],
    ids=[
        "empty",
        "whitespace",
        "render-error",
        "missing-template",
        "multi-version",
        "tabs",
        "tabber",
        "translation",
        "columns",
        "too-long",
    ],
)
def test_failed_or_ambiguous_render_does_not_mark_a_version_complete(monkeypatch, tmp_path, html):
    source = INTRO + "<poem>可保留部分{{embed|待渲染}}</poem>"
    fetcher, extractor, _, _ = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        rendered={"{{embed|待渲染}}": html},
        answer={"lyrics": "单版模型最终歌词"},
    )
    assert fetcher.fetch_entity_description("某歌")["lyrics"] == "单版模型最终歌词"
    assert len(extractor.calls) == 1
    assert extractor.calls[0]["materials"]["lyrics"]["gaps"] == ["{{embed|待渲染}}"]


def test_summary_supplement_cannot_overwrite_complete_lyrics(monkeypatch, tmp_path):
    source = (
        "{{VOCALOID Songbox|演唱=洛天依}}\n== 简介 ==\n{{未知|待补简介}}\n== 歌词 ==\n"
        "<poem>确定的完整歌词</poem><poem>被舍弃版{{未知|未解歌词}}</poem>"
    )
    fetcher, extractor, _, calls = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        answer={"summary": ["补好简介"], "lyrics": "错误覆盖"},
    )
    data = fetcher.fetch_entity_description("某歌")
    assert data["lyrics"] == "确定的完整歌词"
    assert data["summary"] == ["补好简介"]
    assert extractor.calls[0]["needed"]["lyrics"] is False
    assert "lyrics" not in extractor.calls[0]["materials"]
    assert "被舍弃" not in json.dumps(extractor.calls[0], ensure_ascii=False)
    assert calls["post"] == []


@pytest.mark.parametrize("body", ["", "<poem> </poem>", "{{lyrics|translated=只有译文}}"])
def test_without_any_lyric_candidate_model_is_not_asked_to_invent_one(monkeypatch, tmp_path, body):
    fetcher, extractor, _, _ = setup_fetcher(monkeypatch, tmp_path, INTRO + body, answer={"lyrics": "没有材料却补提"})
    assert fetcher.fetch_entity_description("某歌") is None
    assert extractor.calls == []


@pytest.mark.parametrize("cache_type", [None, "Song", "Person", "Unknown"])
def test_existing_song_cache_cannot_bypass_single_version_extraction(monkeypatch, tmp_path, cache_type):
    cache = tmp_path / "某歌.json"
    old = {"lyrics": "甲版混乙版", "spaced_lyrics": "旧关键词", "short_summary": "旧简介"}
    if cache_type is not None:
        old["type"] = cache_type
    cache.write_text(json.dumps(old, ensure_ascii=False), encoding="utf-8")
    fetcher, _, _, calls = setup_fetcher(monkeypatch, tmp_path, INTRO + "<poem>新的单版完整歌词</poem>")
    result = fetcher.fetch_entity_description("某歌")
    assert result["lyrics"] == "新的单版完整歌词"
    assert result["spaced_lyrics"] == "新的单版完整歌词"
    assert len(calls["get"]) == 1
    assert json.loads(cache.read_text(encoding="utf-8")) == old


def test_old_song_cache_is_not_a_fallback_for_failed_fetch(monkeypatch, tmp_path):
    old = {"type": "Song", "lyrics": "未经验证的多版旧歌词", "summary": ["旧简介"]}
    path = tmp_path / "某歌.json"
    path.write_text(json.dumps(old), encoding="utf-8")
    fetcher, _, _, _ = setup_fetcher(monkeypatch, tmp_path, "unused")

    def fail(*args, **kwargs):
        raise requests.Timeout("offline timeout")

    monkeypatch.setattr(fetcher.session, "get", fail)
    assert fetcher.fetch_entity_description("某歌") is None
    assert json.loads(path.read_text(encoding="utf-8")) == old


def test_render_budget_is_per_candidate_and_stops_exhausted_version(monkeypatch, tmp_path):
    source = INTRO + "<poem>{{embed|large}}{{embed|skip}}</poem><poem>{{embed|second}}</poem>"
    fetcher, extractor, _, calls = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        rendered={"{{embed|large}}": "<p>" + "字" * 12000 + "</p>", "{{embed|second}}": "<p>第二版完整歌词</p>"},
    )
    assert fetcher.fetch_entity_description("某歌")["lyrics"] == "第二版完整歌词"
    assert calls["post"] == ["{{embed|large}}", "{{embed|second}}"]
    assert extractor.calls == []


def test_render_rejects_oversized_source_and_html_without_claiming_complete(monkeypatch, tmp_path):
    huge_call = "{{embed|" + "x" * 8000 + "}}"
    source = INTRO + "<poem>甲" + huge_call + "</poem><poem>乙{{embed|too-much-html}}</poem>"
    fetcher, extractor, _, calls = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        rendered={"{{embed|too-much-html}}": "<!--" + "x" * 100001 + "--><p>不采用</p>"},
        answer={"lyrics": "成功的单版最终歌词"},
    )
    assert fetcher.fetch_entity_description("某歌")["lyrics"] == "成功的单版最终歌词"
    assert calls["post"] == ["{{embed|too-much-html}}"]
    assert len(extractor.calls) == 1
    assert extractor.calls[0]["materials"]["lyrics"]["gaps"]


def test_person_cache_without_lyrics_still_works(monkeypatch, tmp_path):
    old = {"type": "Person", "summary": ["人物介绍"], "lyrics": ""}
    (tmp_path / "某人.json").write_text(json.dumps(old), encoding="utf-8")
    fetcher, extractor, summarizer, calls = setup_fetcher(monkeypatch, tmp_path, "unused")
    assert fetcher.fetch_entity_description("某人") == old
    assert extractor.calls == summarizer.calls == calls["get"] == []


@pytest.mark.parametrize("lyrics", [None, "", " \n\t "])
@pytest.mark.parametrize("person", [True, False])
def test_song_candidate_requires_lyrics_even_with_an_introduction(monkeypatch, tmp_path, lyrics, person):
    fetcher = VCPediaFetcher({"activated": True, "data_dir": str(tmp_path)})
    data = {"summary": ["可用介绍"]}
    if person:
        data["type"] = "Person"
    if lyrics is not None:
        data["lyrics"] = lyrics
    monkeypatch.setattr(fetcher, "fetch_entity_description", lambda _: data)
    assert _fetch_candidate(fetcher, "某歌") is None
    data.update(lyrics="非空单版本歌词", spaced_lyrics="非空单版本歌词")
    assert _fetch_candidate(fetcher, "某歌").lyrics == "非空单版本歌词"


def test_rendered_punctuation_drives_final_keyword_boundaries(monkeypatch, tmp_path):
    source = INTRO + "<poem>前方六字歌词{{embed|片段}}后方六字歌词</poem>"
    fetcher, _, _, _ = setup_fetcher(
        monkeypatch,
        tmp_path,
        source,
        rendered={"{{embed|片段}}": "<span>，重复副歌，</span>"},
    )
    data = fetcher.fetch_entity_description("某歌")
    assert data["lyrics"] == "前方六字歌词，重复副歌，后方六字歌词"
    assert data["spaced_lyrics"] == spaced_from(data["lyrics"])


@pytest.mark.parametrize("nested", [False, True])
def test_lyric_free_material_retains_credit_templates_inside_lyrics_section(nested):
    source = (
        "{{VOCALOID Songbox|演唱=洛天依}}\n"
        + INTRO
        + "{{VOCALOID Songbox Introduction|group1=作词|list1={{未知|作者甲}}}}"
        "<poem>完整首版歌词</poem><poem>不应泄漏的第二版歌词</poem>"
    )
    if nested:
        source = "{{VOCALOID Small Songbox|简介=固定简介|歌词=" + source.split("== 歌词 ==\n")[1] + "}}"
    data, needed = parse_details(source, "某歌", with_missing=True)
    assert needed["infobox"] == ["作词"]
    materials = collect_materials(data, needed, source, "https://vcpedia.cn", "某歌", merge_fragments=False)
    assert "作者甲" in materials["text"]
    assert "不应泄漏" not in json.dumps(materials, ensure_ascii=False)
    assert "完整首版歌词" not in materials["text"]


def test_non_content_tags_cannot_leak_other_lyric_versions_into_materials():
    source = (
        "== 简介 ==\n{{未知|简介事实}}<ref><poem>附注版歌词{{未知|尾}}</poem></ref>"
        "<nowiki>臺灣字面简介</nowiki>\n== 歌词 ==\n<poem>正版已知歌词{{未知|尾}}</poem>"
    )
    data, needed = parse_details(source, "某歌", with_missing=True)
    materials = collect_materials(data, needed, source, "https://vcpedia.cn", "某歌", merge_fragments=False)
    assert "附注版" not in json.dumps(materials, ensure_ascii=False)
    assert "臺灣字面简介" in materials["text"]
    assert "正版" in materials["lyrics"]["source"]


def test_materials_exclude_translations_other_tabs_and_nested_lyric_sources():
    source = (
        "{{VOCALOID Small Songbox|简介={{未知|简介事实}}|歌词={{tabs|bt1=甲|tab1="
        "<poem>第一版{{未知|第一版缺口长长长长}}</poem>|bt2=乙|tab2="
        "{{Lyrics|original=第二版较多已知歌词{{未知|尾}}|translated=不得泄漏的译文}}}}}}"
    )
    data, needed = parse_details(source, "某歌", with_missing=True)
    materials = collect_materials(data, needed, source, "https://vcpedia.cn", "某歌", merge_fragments=False)
    encoded = json.dumps(materials, ensure_ascii=False)
    assert "简介事实" in materials["text"]
    assert "第一版" not in encoded
    assert "不得泄漏的译文" not in encoded
    assert "第二版" in materials["lyrics"]["source"]
