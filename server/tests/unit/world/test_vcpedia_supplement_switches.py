"""补提链路的开关与契约：片段合并、模型调用、材料的构造时机。

外部边界替换 HTTP POST 与补提模型；断言的是配置组合下观察到的行为。
"""

from __future__ import annotations

import json

import pytest
import requests

from src.world.get_new_songs import vcpedia_fetcher as fetcher_module
from src.world.get_new_songs.source_extraction import collect_materials, decode_extraction_response
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher

EMBED_SOURCE = "== 简介 ==\n{{embed|1=可渲染片段}}\n"


def fake_response(payload):
    result = requests.Response()
    result.status_code = 200
    result._content = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    result.encoding = "utf-8"
    return result


def fake_post(payload):
    calls = []

    def post(url, **kwargs):
        calls.append((url, kwargs))
        return fake_response(payload)

    return post, calls


def needed_summary():
    return {"infobox": [], "summary": True, "lyrics": False}


class FakeExtractionModule:
    """补提模型的替身：记录调用，返回预置答案。"""

    def __init__(self, answer):
        self.answer = answer
        self.calls = []

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        return self.answer


def test_collect_materials_merges_fragments_when_enabled():
    post, calls = fake_post({"parse": {"text": {"*": "<p>站点渲染的简介内容</p>"}}})
    data = {"summary": []}

    materials = collect_materials(
        data, needed_summary(), EMBED_SOURCE, "https://vcpedia.cn", "某歌", post=post, merge_fragments=True
    )

    assert data["summary"] == ["站点渲染的简介内容"]
    assert len(calls) == 1
    assert materials["text"]


def test_collect_materials_skips_fragments_when_disabled():
    post, calls = fake_post({"parse": {"text": {"*": "<p>不应被请求</p>"}}})
    data = {"summary": []}

    materials = collect_materials(
        data, needed_summary(), EMBED_SOURCE, "https://vcpedia.cn", "某歌", post=post, merge_fragments=False
    )

    assert calls == []
    assert data["summary"] == []
    assert materials["text"], "关闭片段合并后模型材料仍须构造"


def test_collect_materials_does_nothing_without_needs():
    post, calls = fake_post({"parse": {"text": {"*": "<p>x</p>"}}})

    materials = collect_materials(
        {"summary": []},
        {"infobox": [], "summary": False, "lyrics": False},
        EMBED_SOURCE,
        "https://vcpedia.cn",
        "某歌",
        post=post,
    )

    assert materials == {}
    assert calls == []


def test_fetcher_gates_fragment_merge_by_config(monkeypatch, tmp_path):
    monkeypatch.setattr(fetcher_module, "fetch_wikitext", lambda *a, **k: "== 简介 ==\n正文")
    seen = []
    monkeypatch.setattr(
        fetcher_module, "collect_materials", lambda *a, **k: seen.append(k.get("merge_fragments")) or {}
    )

    fetcher = fetcher_module.VCPediaFetcher(
        {"activated": True, "use_llm": False, "data_dir": str(tmp_path / "cache"), "merge_rendered_fragments": False}
    )
    fetcher.fetch_entity_description("某歌")
    assert seen == [], "片段合并与补提模型全关时，不得进入 collect_materials"

    fetcher_default = fetcher_module.VCPediaFetcher(
        {"activated": True, "use_llm": False, "data_dir": str(tmp_path / "cache2")}
    )
    fetcher_default.fetch_entity_description("某歌")
    assert seen == [True], "默认配置保持片段合并打开"


def test_fetcher_extract_missing_merges_model_answer(monkeypatch, tmp_path):
    fake = FakeExtractionModule(json.dumps({"summary": ["模型补全的简介"]}, ensure_ascii=False))
    monkeypatch.setattr(
        fetcher_module, "fetch_wikitext", lambda *a, **k: "{{VOCALOID_Songbox|演唱=洛天依}}\n== 简介 ==\n"
    )

    fetcher = fetcher_module.VCPediaFetcher(
        {"activated": True, "use_llm": True, "data_dir": str(tmp_path / "cache")}, extraction_llm_module=fake
    )
    data = fetcher.fetch_entity_description("某歌")

    assert len(fake.calls) == 1
    assert json.loads(fake.calls[0]["needed"])["summary"] is True
    assert data["summary"] == ["模型补全的简介"]


def test_fetcher_extract_missing_survives_bad_model_answer(monkeypatch, tmp_path):
    fake = FakeExtractionModule("这不是JSON")
    monkeypatch.setattr(
        fetcher_module, "fetch_wikitext", lambda *a, **k: "{{VOCALOID_Songbox|演唱=洛天依}}\n== 简介 ==\n"
    )

    fetcher = fetcher_module.VCPediaFetcher(
        {"activated": True, "use_llm": True, "data_dir": str(tmp_path / "cache")}, extraction_llm_module=fake
    )
    data = fetcher.fetch_entity_description("某歌")

    # 页面标题下无正文，基抽取产出 [""]；非法模型答案不得替换或合并进结果。
    assert data["summary"] == [""]


def test_fetcher_without_llm_never_calls_model(monkeypatch, tmp_path):
    fake = FakeExtractionModule("{}")
    monkeypatch.setattr(
        fetcher_module, "fetch_wikitext", lambda *a, **k: "{{VOCALOID_Songbox|演唱=洛天依}}\n== 简介 ==\n"
    )

    fetcher = fetcher_module.VCPediaFetcher(
        {"activated": True, "use_llm": False, "data_dir": str(tmp_path / "cache")}, extraction_llm_module=fake
    )
    fetcher.fetch_entity_description("某歌")

    assert fake.calls == [], "use_llm 关闭时不得调用补提模型"


class RecordingModel:
    def __init__(self, label, events, response):
        self.label = label
        self.events = events
        self.response = response
        self.calls = []

    async def generate_response(self, **kwargs):
        self.events.append(self.label)
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


@pytest.mark.parametrize("merge_fragments", [None, True, False])
@pytest.mark.parametrize("use_llm", [None, True, False])
def test_public_fetch_flow_orders_independent_stages(monkeypatch, tmp_path, merge_fragments, use_llm):
    source = "{{VOCALOID_Songbox|演唱=洛天依}}\n" + EMBED_SOURCE + "== 歌词 ==\n{{未知模板|original=原歌词}}"
    monkeypatch.setattr(fetcher_module, "fetch_wikitext", lambda *a, **k: source)
    events = []

    def post(url, **kwargs):
        events.append("fragment")
        return fake_response({"parse": {"text": {"*": "<p>站点简介</p>"}}})

    extractor = RecordingModel("extract", events, '{"summary":["补提简介"],"lyrics":"补提歌词"}')
    summarizer = RecordingModel("summary", events, "最终短介绍")
    config = {"activated": True, "data_dir": str(tmp_path / "cache")}
    config.update(
        {
            key: value
            for key, value in (
                ("merge_rendered_fragments", merge_fragments),
                ("use_llm", use_llm),
            )
            if value is not None
        }
    )
    fetcher = VCPediaFetcher(config, llm_module=summarizer, extraction_llm_module=extractor)
    monkeypatch.setattr(fetcher.session, "post", post)

    data = fetcher.fetch_entity_description("某歌")

    assert events == (["fragment"] if merge_fragments is not False else []) + (
        ["extract", "summary"] if use_llm is not False else []
    )
    if use_llm is not False:
        extracted_input = json.loads(extractor.calls[0]["song_data"])
        expected_intro = ["站点简介"] if merge_fragments is not False else [""]
        assert extracted_input["summary"] == expected_intro
        assert json.loads(extractor.calls[0]["needed"])["summary"] == (merge_fragments is False)
        assert data["summary"] == (["补提简介"] if merge_fragments is False else ["站点简介"])
        assert data["lyrics"] == "补提歌词"
        summarized_input = json.loads(summarizer.calls[0]["song_data"])
        assert summarized_input["summary"] == data["summary"]
        assert summarized_input["lyrics"] == "补提歌词"
        assert set(summarizer.calls[0]) == {"song_data"}
        assert data["short_summary"] == "最终短介绍"
    else:
        assert data is None, "未得到完整单版歌词时，不将歌曲提交给 Agent"


def test_missing_extractor_does_not_borrow_summary_model(monkeypatch, tmp_path):
    source = "{{VOCALOID_Songbox|演唱=洛天依}}\n== 简介 ==\n== 歌词 ==\n<poem>完整歌词</poem>"
    monkeypatch.setattr(fetcher_module, "fetch_wikitext", lambda *a, **k: source)
    model = FakeExtractionModule("仅供总结")
    fetcher = VCPediaFetcher(
        {"activated": True, "merge_rendered_fragments": False, "data_dir": str(tmp_path / "cache")},
        llm_module=model,
    )

    data = fetcher.fetch_entity_description("某歌")

    assert len(model.calls) == 1
    assert set(model.calls[0]) == {"song_data"}
    assert data["summary"] == [""]
    assert data["short_summary"] == "仅供总结"


@pytest.mark.parametrize(
    "answer",
    [
        "不是JSON",
        "[]",
        "x" * 24001,
        RuntimeError("model failed"),
        '{"lyrics":NaN}',
        {"lyrics": float("inf")},
        {"lyrics": "字" * 24000},
    ],
)
def test_failed_extraction_still_runs_summary(monkeypatch, tmp_path, answer):
    source = "{{VOCALOID_Songbox|演唱=洛天依}}\n== 简介 ==\n== 歌词 ==\n<poem>完整歌词</poem>"
    monkeypatch.setattr(fetcher_module, "fetch_wikitext", lambda *a, **k: source)
    events = []
    extractor = RecordingModel("extract", events, answer)
    summarizer = RecordingModel("summary", events, "失败后仍总结")
    fetcher = VCPediaFetcher(
        {"activated": True, "merge_rendered_fragments": False, "data_dir": str(tmp_path / "cache")},
        llm_module=summarizer,
        extraction_llm_module=extractor,
    )

    data = fetcher.fetch_entity_description("某歌")

    assert events == ["extract", "summary"]
    assert data["summary"] == [""]
    assert data["lyrics"] == "完整歌词"
    assert data["short_summary"] == "失败后仍总结"


def test_nonempty_partial_lyrics_are_supplemented_when_gap_remains(monkeypatch, tmp_path):
    source = "{{VOCALOID Small Songbox|简介=完整简介|歌词=已有歌词{{未知模板|1=遗漏歌词}}}}"
    monkeypatch.setattr(fetcher_module, "fetch_wikitext", lambda *a, **k: source)
    extractor = FakeExtractionModule('{"lyrics":"已有歌词及遗漏歌词"}')
    fetcher = VCPediaFetcher(
        {"activated": True, "merge_rendered_fragments": False, "data_dir": str(tmp_path / "cache")},
        extraction_llm_module=extractor,
    )

    data = fetcher.fetch_entity_description("某歌")

    assert json.loads(extractor.calls[0]["song_data"])["lyrics"] == "已有歌词"
    assert json.loads(extractor.calls[0]["needed"])["lyrics"] is True
    assert data["lyrics"] == "已有歌词及遗漏歌词"


@pytest.mark.parametrize("reply", [[], 1, None, "[]", "null", '"text"'])
def test_shared_response_validation_rejects_nonobjects(reply):
    with pytest.raises(ValueError, match="JSON object"):
        decode_extraction_response(reply)


@pytest.mark.parametrize("reply", ["invalid", "```json\n{}\n```"])
def test_shared_response_validation_preserves_json_errors(reply):
    with pytest.raises(json.JSONDecodeError):
        decode_extraction_response(reply)


def test_shared_response_validation_keeps_str_dict_and_raw_size_contract():
    payload = {"lyrics": "歌词"}
    assert decode_extraction_response(payload) is payload
    assert decode_extraction_response(json.dumps(payload)) == payload
    assert decode_extraction_response(" " * 23998 + "{}") == {}
    with pytest.raises(ValueError, match="24000"):
        decode_extraction_response(" " * 23999 + "{}")


@pytest.mark.parametrize("value", ["<nowiki></nowiki>", "-{}-", " \t ", "<nowiki> \t </nowiki>", "-{ \t }-"])
@pytest.mark.parametrize("placement", ["songbox", "same_staff", "later_staff"])
def test_fetcher_uses_visible_empty_staff_values_and_does_not_request_filled_fields(
    monkeypatch,
    tmp_path,
    value,
    placement,
):
    base = "{{VOCALOID Small Songbox|简介=固定简介|歌词=完整歌词"
    source = {
        "songbox": base + "|演唱=" + value + "}}{{VOCALOID Songbox Introduction|演唱=关联歌手}}",
        "same_staff": base
        + "}}{{VOCALOID Songbox Introduction|group1=演唱|list1="
        + value
        + "|group2=演唱|list2=关联歌手}}",
        "later_staff": base
        + "}}{{VOCALOID Songbox Introduction|演唱="
        + value
        + "}}{{VOCALOID Songbox Introduction|演唱=关联歌手}}",
    }[placement]
    monkeypatch.setattr(fetcher_module, "fetch_wikitext", lambda *a, **k: source)
    extractor = FakeExtractionModule("{}")
    fetcher = VCPediaFetcher(
        {"activated": True, "merge_rendered_fragments": False, "data_dir": str(tmp_path / "cache")},
        extraction_llm_module=extractor,
    )

    data = fetcher.fetch_entity_description("某歌")

    assert data["infobox"] == {"演唱": "关联歌手"}
    assert data["short_summary"] == "固定简介"
    assert data["lyrics"] == "完整歌词"
    assert extractor.calls == []


@pytest.mark.parametrize("value", ["<nowiki></nowiki>", "-{}-", "<nowiki> \t </nowiki>", "-{ \t }-"])
def test_fetcher_requests_visible_empty_field_if_no_staff_fills_it(monkeypatch, tmp_path, value):
    source = "{{VOCALOID Small Songbox|简介=固定简介|歌词=完整歌词|演唱=" + value + "}}"
    monkeypatch.setattr(fetcher_module, "fetch_wikitext", lambda *a, **k: source)
    extractor = FakeExtractionModule('{"infobox":{"演唱":"补提歌手"}}')
    fetcher = VCPediaFetcher(
        {"activated": True, "merge_rendered_fragments": False, "data_dir": str(tmp_path / "cache")},
        extraction_llm_module=extractor,
    )

    data = fetcher.fetch_entity_description("某歌")

    assert json.loads(extractor.calls[0]["needed"]) == {"infobox": ["演唱"], "summary": False, "lyrics": False}
    assert data["infobox"] == {"演唱": "补提歌手"}


@pytest.mark.parametrize(
    "value,expected",
    [
        ("<nowiki>臺灣</nowiki>", "臺灣"),
        ("-{臺灣}-", "臺灣"),
        ("<nowiki>-{}-</nowiki>", "-{}-"),
        ("<nowiki>{{未知模板}}</nowiki>", "{{未知模板}}"),
    ],
)
@pytest.mark.parametrize("placement", ["songbox", "same_staff", "later_staff"])
def test_fetcher_keeps_nonempty_protected_first_values(monkeypatch, tmp_path, value, expected, placement):
    base = "{{VOCALOID Small Songbox|简介=固定简介|歌词=完整歌词"
    source = {
        "songbox": base + "|演唱=" + value + "}}{{VOCALOID Songbox Introduction|演唱=后歌手}}",
        "same_staff": base
        + "}}{{VOCALOID Songbox Introduction|group1=演唱|list1="
        + value
        + "|group2=演唱|list2=后歌手}}",
        "later_staff": base
        + "}}{{VOCALOID Songbox Introduction|演唱="
        + value
        + "}}{{VOCALOID Songbox Introduction|演唱=后歌手}}",
    }[placement]
    monkeypatch.setattr(fetcher_module, "fetch_wikitext", lambda *a, **k: source)
    extractor = FakeExtractionModule("{}")
    fetcher = VCPediaFetcher(
        {"activated": True, "merge_rendered_fragments": False, "data_dir": str(tmp_path / "cache")},
        extraction_llm_module=extractor,
    )

    data = fetcher.fetch_entity_description("某歌")

    assert data["infobox"] == {"演唱": expected}
    assert extractor.calls == []


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity", "1e10000"])
def test_shared_response_validation_rejects_nonfinite_json_numbers(constant):
    with pytest.raises(ValueError):
        decode_extraction_response('{"nested":{"values":[' + constant + "]}}")


@pytest.mark.parametrize("number", [float("nan"), float("inf"), float("-inf")])
def test_shared_response_validation_rejects_nonfinite_dict_values(number):
    with pytest.raises(ValueError, match="finite JSON"):
        decode_extraction_response({"nested": {"values": [number]}})


def test_shared_response_validation_bounds_dicts_by_serialized_character_length():
    overhead = len(json.dumps({"lyrics": ""}, ensure_ascii=False))
    payload = {"lyrics": "字" * (24000 - overhead)}
    assert decode_extraction_response(payload) is payload
    with pytest.raises(ValueError, match="24000"):
        decode_extraction_response({"lyrics": payload["lyrics"] + "字"})


@pytest.mark.parametrize("value", [object(), {"set"}])
def test_shared_response_validation_rejects_non_json_dict_values(value):
    with pytest.raises(ValueError, match="JSON-compatible"):
        decode_extraction_response({"lyrics": value})
