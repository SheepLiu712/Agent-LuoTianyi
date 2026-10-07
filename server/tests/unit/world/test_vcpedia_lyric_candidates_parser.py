"""Candidate-local lyrics, ordered selection and protection at the parser boundary."""

import pytest

from src.world.get_new_songs.wikitext_parser import (
    LyricCandidate,
    original_lyrics_source,
    parse_details,
    parse_extraction,
    parse_lyric_candidate,
    rendered_lyrics_text,
    select_lyrics,
)


def extract(body):
    return parse_extraction("== 歌词 ==\n" + body, "候选测试")


def test_candidates_are_independent_and_first_complete_wins():
    broken = "<poem>已有{{未知|original=遗漏}}</poem>"
    first = "<poem>首个完整</poem>"
    last = "{{lyrics|original=后一个完整|translated={{未知|译文}}}}"
    data, needed, candidates = extract(broken + first + last)

    assert [item.source for item in candidates] == [broken, first, last]
    assert [item.text for item in candidates] == ["已有", "首个完整", "后一个完整"]
    assert candidates[0].gaps == {"{{未知|original=遗漏}}"}
    assert candidates[1].gaps == candidates[2].gaps == set()
    assert data["lyrics"] == data["spaced_lyrics"] == "首个完整"
    assert needed == {"infobox": [], "summary": False, "lyrics": False}
    assert select_lyrics(candidates) is candidates[1]
    assert set(data) == {"name", "type", "infobox", "summary", "lyrics", "spaced_lyrics"}
    candidates[0].rendered.append({"source": "call", "text": "text"})
    assert candidates[1].rendered == []


def test_later_broken_candidate_cannot_pollute_first_complete():
    data, needed, candidates = extract("<poem>先完整</poem><poem>后{{未知|text=缺口}}</poem>")
    assert data["lyrics"] == "先完整"
    assert not needed["lyrics"]
    assert not candidates[1].complete


@pytest.mark.parametrize(
    "body",
    [
        "已有{{未知|1=遗漏}}尾声",
        "已有{{embed|片段}}尾声",
        "已有{{color|red|{{未知|text=遗漏}}}}尾声",
        "已有<div>{{未知|text=遗漏}}</div>尾声",
    ],
)
def test_direct_body_does_not_flush_before_unexpanded_content(body):
    data, needed, candidates = parse_extraction("{{VOCALOID Small Songbox|歌词=" + body + "}}", "直接正文")
    assert len(candidates) == 1
    assert candidates[0].source == body
    assert candidates[0].gaps
    assert not candidates[0].complete
    assert data["lyrics"].startswith("已有")
    assert data["lyrics"].endswith("尾声")
    assert needed["lyrics"]


@pytest.mark.parametrize("template", ["tabs|tab1=已有{{未知|1=遗漏}}|tab2=好版本", "hide|2=好版本"])
def test_documented_content_slots_form_separate_candidates(template):
    data, needed, candidates = extract("{{" + template + "}}")
    assert data["lyrics"] == "好版本"
    assert not needed["lyrics"]
    assert all("tab2=" not in candidate.source for candidate in candidates)
    if template.startswith("tabs"):
        assert [item.source for item in candidates] == ["已有{{未知|1=遗漏}}", "好版本"]


def test_unknown_original_is_one_unexpanded_call_not_a_complete_parameter():
    call = "{{未知歌词容器|original=看似完整的子参数|歌词=另一子参数}}"
    data, needed, candidates = extract(call)
    assert len(candidates) == 1
    assert candidates[0].source == call
    assert candidates[0].gaps == {call}
    assert candidates[0].text == ""
    assert data["lyrics"] == "" and needed["lyrics"]


def test_unknown_container_can_still_discover_real_poem():
    data, needed, candidates = extract("{{陌生容器|original=<poem>实际结构</poem>}}")
    assert candidates[0].gaps == {"{{陌生容器|original=<poem>实际结构</poem>}}"}
    assert candidates[1].source == "<poem>实际结构</poem>"
    assert data["lyrics"] == "实际结构"
    assert not needed["lyrics"]


def test_top_level_embed_is_a_candidate_even_with_no_parameters():
    for call in ("{{embed|片段}}", "{{embed}}"):
        data, needed, candidates = extract(call)
        assert len(candidates) == 1
        assert candidates[0].source == call
        assert candidates[0].gaps == {call}
        assert not candidates[0].complete
        assert data["lyrics"] == "" and needed["lyrics"]


@pytest.mark.parametrize("body", ["<poem></poem>", "{{lyrics|translated=只有译文}}", "{{未知|original=}}"])
def test_empty_and_unknown_candidates_remain_available_for_supplement(body):
    _, needed, candidates = extract(body)
    assert len(candidates) == 1
    assert candidates[0].source == body
    assert not candidates[0].complete
    assert needed["lyrics"]


def test_empty_candidate_does_not_outrank_unknown_lyric_evidence():
    call = "{{未知歌词|original=待补歌词}}"
    _, needed, candidates = extract("<poem></poem>{{lyrics|translated=只有译文}}" + call)
    assert len(candidates) == 3
    assert select_lyrics(candidates) is candidates[2]
    assert candidates[2].gaps == {call} and needed["lyrics"]
    assert select_lyrics(candidates[:2]) is candidates[0]


def test_empty_direct_slot_stays_a_candidate():
    _, needed, candidates = parse_extraction("{{VOCALOID Songbox|歌词=}}", "空槽")
    assert len(candidates) == 1
    assert candidates[0].source == candidates[0].text == ""
    assert not candidates[0].complete
    assert needed["lyrics"]


def test_coverage_ratio_beats_absolute_length():
    low = parse_lyric_candidate("甲" * 80 + "{{未知|text=" + "缺" * 320 + "}}")
    high = parse_lyric_candidate("乙" * 9 + "{{未知|text=缺}}")
    assert low.rank[0] == pytest.approx(0.2)
    assert high.rank[0] == pytest.approx(0.9)
    assert select_lyrics([low, high]) is high


def test_coverage_ignores_parameter_markup_and_whitespace():
    candidate = parse_lyric_candidate("<b>甲乙</b>\n{{未知|original=<b>缺</b> [[目标|失]] \t}}")
    assert candidate.rank[0] == pytest.approx(0.5)


def test_ties_prefer_fewer_gaps_then_source_order_and_rank_is_dynamic():
    two = parse_lyric_candidate("甲乙{{甲缺|缺}}{{乙缺|缺}}")
    one = parse_lyric_candidate("甲乙{{缺|缺失}}")
    same = parse_lyric_candidate("丙丁{{另缺|缺失}}")
    assert two.rank[0] == one.rank[0] == same.rank[0] == 0.5
    assert select_lyrics([two, one, same]) is one
    assert select_lyrics([same, one]) is same
    two.gaps.clear()
    assert two.complete and two.rank == (1.0, 0)
    assert select_lyrics([two, one]) is two
    assert select_lyrics([]) is None


def test_page_selects_best_incomplete_candidate_and_reports_its_gap():
    data, needed, candidates = extract("<poem>甲{{未甲|缺少很多正文}}</poem><poem>甲乙丙{{未乙|缺}}</poem>")
    assert data["lyrics"] == "甲乙丙"
    assert needed["lyrics"]
    assert select_lyrics(candidates) is candidates[1]
    assert candidates[1].gaps == {"{{未乙|缺}}"}


@pytest.mark.parametrize("wrapper", ["<poem>{}</poem>", "{{{{VOCALOID Small Songbox|歌词={}}}}}"])
def test_poem_and_direct_protection_round_trip_without_glyph_loss(wrapper):
    text = "普通臺灣 <NoWiki >臺灣{{假模板}}</NOWIKI > -{臺灣}-"
    source = wrapper.format(text)
    data, needed, candidates = extract(source)
    assert len(candidates) == 1
    candidate = candidates[0]
    expected_source = source if source.startswith("<poem>") else text
    assert candidate.source == expected_source
    assert candidate.text == "普通台湾 臺灣{{假模板}} 臺灣"
    assert data["lyrics"] == candidate.text
    assert candidate.complete and not needed["lyrics"]
    assert parse_lyric_candidate(candidate.source) == candidate


def test_gap_source_restores_original_nowiki_markup():
    call = "{{未知|original=<nowiki>臺灣</nowiki>}}"
    candidate = parse_lyric_candidate("<poem>已有" + call + "</poem>")
    assert candidate.gaps == {call}
    assert call in candidate.source


def test_repeated_chorus_harmony_and_empty_verses_are_not_deduplicated():
    source = "<poem>副歌（和声）\n副歌（和声）\n\n{{歌词并列|主唱|主唱|和声}}</poem>"
    candidate = parse_lyric_candidate(source)
    assert candidate.text == "副歌（和声）\n副歌（和声）\n\n主唱\n主唱\n和声"
    assert candidate.spaced_lyrics == "副歌（和声）\n副歌（和声）\n主唱\n主唱\n和声"


def test_lyric_subheadings_inherit_but_navigation_is_not_lyrics():
    data, needed, candidates = extract(
        "=== 初版 ===\n导航文字\n{{navbox|list1=导航列表}}\n<poem>原版</poem>\n"
        "=== 新版 ===\n<poem>新版</poem>\n== 导航 ==\n<poem>非歌词</poem>"
    )
    assert [item.text for item in candidates] == ["原版", "新版"]
    assert data["lyrics"] == "原版" and not needed["lyrics"]


def test_original_and_translation_columns_keep_gaps_separate():
    candidate = parse_lyric_candidate(
        "{{lyrics|lb-text1=原一|rb-text1=译一{{未知|缺译}}|lb-text2=原二|rb-text2=译二}}"
    )
    assert candidate.text == "原一\n\n原二" and candidate.complete
    assert not candidate.gaps
    source = original_lyrics_source(candidate.source)
    assert "rb-text" not in source and "译" not in source
    assert parse_lyric_candidate(source).text == candidate.text


def test_original_material_preserves_protected_markup_and_removes_translation():
    source = "{{lyrics|original=<nowiki>{{lyrics|translated=字面原文}}</nowiki>|translated=译文|width=100}}"
    original = original_lyrics_source(source)
    assert original == "{{lyrics|original=<nowiki>{{lyrics|translated=字面原文}}</nowiki>|width=100}}"
    assert parse_lyric_candidate(original).text == "{{lyrics|translated=字面原文}}"


def test_rendered_html_has_no_glyph_conversion_and_keeps_ruby_entities_and_lines():
    html = "<poem>臺<b>灣</b>&amp;<br/>第二行\n\n<ruby>漢<rt>han</rt></ruby>（和聲）</poem>"
    assert rendered_lyrics_text(html) == "臺灣&\n第二行\n\n漢（和聲）"


@pytest.mark.parametrize("container", ["tabs|tab1={first}|tab2={second}", "hide|2={first}|content={second}"])
def test_nested_version_slots_keep_common_context_but_never_other_versions(container):
    first = "初版{{未识别|缺}}"
    second = "完整次版"
    call = "{{" + container.format(first=first, second=second) + "}}"
    data, needed, candidates = extract("<poem>共同开头\n" + call + "\n共同结尾</poem>")
    assert [item.source for item in candidates] == [
        "<poem>共同开头\n" + first + "\n共同结尾</poem>",
        "<poem>共同开头\n" + second + "\n共同结尾</poem>",
    ]
    assert candidates[0].gaps == {"{{未识别|缺}}"}
    assert data["lyrics"] == "共同开头\n完整次版\n共同结尾" and not needed["lyrics"]
    assert parse_lyric_candidate(candidates[1].source) == candidates[1]


def test_nested_versions_inside_original_template_do_not_read_translation_versions():
    source = "{{lyrics|original=前{{tabs|tab1=甲|tab2=乙}}后|translated={{tabs|tab1=译甲|tab2=译乙}}}}"
    data, _, candidates = extract(source)
    assert len(candidates) == 2
    assert [item.text for item in candidates] == ["前甲后", "前乙后"]
    assert data["lyrics"] == "前甲后"
    assert "译" not in original_lyrics_source(candidates[0].source)
    assert parse_lyric_candidate(source).text == "前甲后"


def test_nested_versions_keep_protected_original_glyphs():
    _, _, candidates = extract("<poem><nowiki>臺灣</nowiki>{{tabs|tab1=甲|tab2=乙}}</poem>")
    assert [item.text for item in candidates] == ["臺灣甲", "臺灣乙"]
    assert [item.source for item in candidates] == [
        "<poem><nowiki>臺灣</nowiki>甲</poem>", "<poem><nowiki>臺灣</nowiki>乙</poem>"
    ]


def test_display_controls_and_footnotes_are_not_missing_sung_text():
    data, needed, candidates = extract(
        "<poem>{{Photrans/button}}歌词{{refn|name=脚注|长篇注释正文}}</poem><poem>后版</poem>"
    )
    assert candidates[0].complete
    assert data["lyrics"] == "歌词" and not needed["lyrics"]


def test_slot_notes_before_explicit_poem_do_not_become_a_lyric_candidate():
    _, _, candidates = extract("{{tabs|tab1={{LDC|类型=歌词}}*版式说明\n<poem>歌词</poem>}}")
    assert len(candidates) == 1
    assert candidates[0].source == "<poem>歌词</poem>"


def test_direct_songbox_nested_tabs_keep_prefix_suffix_in_each_candidate():
    body = "共同开头{{tabs|tab1=甲版{{缺|遗漏}}|tab2=乙版}}共同结尾"
    data, needed, candidates = parse_extraction("{{VOCALOID Songbox|歌词=" + body + "}}", "直接分槽")
    assert [item.source for item in candidates] == ["共同开头甲版{{缺|遗漏}}共同结尾", "共同开头乙版共同结尾"]
    assert not candidates[0].complete
    assert data["lyrics"] == "共同开头乙版共同结尾" and not needed["lyrics"]


def test_parse_details_keeps_business_signature():
    source = "== 歌词 ==\n<poem>完整</poem>"
    data, needed, _ = parse_extraction(source, "兼容")
    assert parse_details(source, "兼容") == data
    assert parse_details(source, "兼容", with_missing=True) == (data, needed)
    assert not LyricCandidate("", " \t", "", set()).complete
