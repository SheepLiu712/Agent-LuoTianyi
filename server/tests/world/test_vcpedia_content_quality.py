"""Public fetcher regressions against the current content-quality contract."""
import json
from pathlib import Path
import sys

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher

import html_surface


@pytest.fixture
def fetch(monkeypatch, tmp_path):
    def run(source, title="测试曲"):
        def get(self, url, **kwargs):
            params = kwargs.get("params", {})
            assert params.get("prop", "wikitext") == "wikitext"
            response = requests.Response()
            response.status_code = 200
            response.encoding = "utf-8"
            response._content = json.dumps({"parse": {"title": title, "pageid": 1,
                "revid": 2, "wikitext": {"*": source}}}, ensure_ascii=False).encode()
            return response
        monkeypatch.setattr(requests.Session, "get", get)
        crawler = VCPediaFetcher({"activated": True, "use_llm": False,
            "data_dir": str(tmp_path / title), "vcpedia": {"output_dir": str(tmp_path / title)}})
        try:
            return crawler.fetch_entity_description(title)
        finally:
            crawler.session.close()
    return run


def test_texthover_visible_nested_text_and_protected_identity(fetch):
    visible = '{{textHover|1={{lj|目標|顯示}}[[連結|文字]]-{繁體}-夢|2=替代|3=before}}'
    data = fetch('{{VOCALOID Songbox|演唱=' + visible + '}}\n== 简介 ==\n' + visible +
                 '\n== 歌词 ==\n<poem>前' + visible + '后</poem>', '夢與樂')
    assert data['name'] == '夢與樂'
    assert data['infobox']['演唱'] == '显示文字繁體梦'
    assert data['summary'] == ['显示文字繁體梦']
    assert data['lyrics'] == '前显示文字繁體梦后'


@pytest.mark.parametrize('position', ['before', 'after'])
def test_texthover_named_parameters_ignore_display_structures(fetch, position):
    data = fetch('== 简介 ==\n前{{TextHover|1=正文|2=<poem>替代</poem>|3=' + position +
                 '|tag=span|htmltag=<h2>简介</h2>伪简介}}后\n== 歌词 ==\n<poem>'
                 '{{TextHover|1=唱词|2=替代|3=' + position + '|tag=span|htmltag=span}}</poem>')
    assert data['summary'] == ['前正文后']
    assert data['lyrics'] == '唱词'


@pytest.mark.parametrize('image', ['bare-file.png', '[[bare-file.png]]'])
def test_texthover_pic_never_leaks_through_structure_walk(fetch, image):
    hover = '{{TextHover|1=<poem>' + image + '</poem>|2=替代|4= PiC }}'
    data = fetch('== 简介 ==\n前' + hover + '后\n== 歌词 ==\n' + hover +
                 '<poem>前{{TextHover|' + image + '|替代|after|pic}}后</poem>')
    assert data['summary'] == ['前后']
    assert data['lyrics'] == '前后'
    assert 'bare-file' not in json.dumps(data, ensure_ascii=False)


@pytest.mark.parametrize("wrapper", ["PanelQ7", "Template:Pane_z19", "陌生布局丙"])
def test_generic_structure_walk_nested_parameter_order(fetch, wrapper):
    data = fetch('== 歌词 ==\n{{' + wrapper + '|mode=控制文字|payload={{DeepR8|style=宽度|2='
        '<poem>首行-{繁體}-\n次行</poem><poem>后候选</poem>}}|first=<poem>另候选</poem>}}')
    assert data['lyrics'] == '首行繁體\n次行'
    assert data['type'] == 'Song'
    assert data['summary'] == ['']


def test_generic_structure_walk_headings_are_parameter_local(fetch):
    data = fetch('{{PanelR|a=\n== 简介 ==\n首简介\n== 歌词 ==\n'
        '|b=控制文字不能成为简介或歌词|c={{Deeper|payload=\n== 歌词 ==\n<poem>首歌词</poem>}}'
        '|d=\n== 简介 ==\n后简介\n}}\n外层控制文字')
    assert data['summary'] == ['首简介']
    assert data['lyrics'] == '首歌词'


def test_generic_structure_walk_nested_first_box_and_staff(fetch):
    data = fetch('{{PanelK|payload={{InnerK|value={{VOCALOID Songbox|演唱=甲|简介=首简介|歌词=<poem>首歌词</poem>}}'
        '{{VOCALOID Songbox Introduction|作词=首词}}}}'
        '|next={{VOCALOID Songbox|演唱=乙|简介=后简介|歌词=<poem>后歌词</poem>}}'
        '{{VOCALOID Songbox Introduction|作词=后词}}}}')
    assert data['infobox'] == {'演唱': '甲', '作词': '首词'}
    assert data['summary'] == ['首简介']
    assert data['lyrics'] == '首歌词'


def test_generic_structure_walk_inside_intro_div_finds_local_headings(fetch):
    data = fetch('== 简介 ==\n开篇。<div>{{PanelDiv|payload=\n== 歌词 ==\n'
        '<poem>局部歌词</poem>}}</div>\n结尾。')
    assert data['lyrics'] == '局部歌词'
    assert data['summary'] == ['开篇。结尾。']


@pytest.mark.parametrize('nested', [False, True], ids=['direct', 'nested'])
def test_local_intro_discovery_does_not_preempt_started_outer_intro(fetch, nested):
    container = '<div>{{PanelDiv|payload=\n== 简介 ==\n局部简介\n}}</div>'
    if nested:
        container = '<div>' + container + '</div>'
    data = fetch('== 简介 ==\n开篇。' + container + '\n结尾。')
    assert data['summary'] == ['开篇。结尾。']


def test_local_intro_discovery_without_outer_intro_remains_readable(fetch):
    data = fetch('<div><div>{{PanelDiv|payload=\n== 简介 ==\n局部简介\n}}</div></div>')
    assert data['summary'] == ['局部简介']


def test_generic_structure_walk_known_original_before_translation(fetch):
    data = fetch('== 歌词 ==\n{{PanelV|payload={{LyricsKai|translated=<poem>译文</poem>'
        '|original=原文一\n原文二}}|other=<poem>后候选</poem>}}')
    assert data['lyrics'] == '原文一\n原文二'


def test_generic_structure_walk_opaque_and_plain_parameters(fetch):
    data = fetch('== 歌词 ==\n{{PanelOpaque|a=<nowiki><poem>伪歌词</poem>{{VOCALOID Songbox|演唱=伪}}</nowiki>'
        '|b=<!-- <poem>注释伪歌词</poem> -->|c=纯文本|d=<poem>真实歌词</poem>}}')
    assert data['lyrics'] == '真实歌词'
    assert data['infobox'] == {}
    assert data['summary'] == ['']


@pytest.mark.parametrize("prefix", [
    '{{Tabs|text1={{VOCALOID Songbox|演唱=甲}}|text2={{VOCALOID Songbox|演唱=乙}}}}',
    '{{VOCALOID Songbox|演唱=甲}}{{VOCALOID Songbox|演唱=乙}}',
    '<div>{{VOCALOID Songbox|演唱=甲}}</div>{{Tabs|text1=局部文字}}',
])
def test_independent_first_info_does_not_limit_public_body(fetch, prefix):
    data = fetch(prefix + '\n== 簡介 ==\n原版繁體介紹。\n=== 背景 ===\n完整背景。\n'
        '== 歌詞 ==\n<poem>公共第一行（和聲）\n公共第二行</poem>\n'
        '== 簡介 ==\n另一介紹。\n== 歌詞 ==\n<poem>另一歌詞</poem>')
    assert data['infobox'] == {'演唱': '甲'}
    assert data['summary'] == ['原版繁体介绍。\n完整背景。']
    assert data['lyrics'] == '公共第一行（和声）\n公共第二行'


@pytest.mark.parametrize("intro,lyric,staff,writer,wrapper,content", [
    ("简介", "歌词", "创作者名单", "作词", "隐藏", "内容"),
    ("簡介", "歌詞", "創作者名單", "作詞", "隱藏", "內容"),
])
def test_structural_normalization_converts_values_preserves_identity(fetch, intro, lyric, staff, writer, wrapper, content):
    source = ("{{VOCALOID Songbox|歌曲名称=夢與樂|演唱=[[樂師頁|樂師]]|UP主=龍作者|" + writer + "=詞師|異體欄=繁體值|圖片信息=不输出}}\n"
        "{{" + staff + "|作曲=曲師}}\n== " + intro + " ==\n夢與樂由樂師演唱，連結龍頁。\n== " + lyric + " ==\n"
        "{{" + wrapper + "|" + content + "={{" + lyric + "|" + lyric + "=夢裡聽見樂聲\n龍飛過臺灣}}}}")
    data = fetch(source, "夢與樂" + intro)
    assert data["infobox"] == {"歌曲名称": "梦与乐", "演唱": "乐师", "UP主": "龙作者", "作词": "词师", "作曲": "曲师", "異體欄": "繁体值"}
    assert data["summary"] == ["梦与乐由乐师演唱，连结龙页。"]
    assert data["lyrics"] == "梦里听见乐声\n龙飞过台湾"
    assert data["name"] == "夢與樂" + intro


@pytest.mark.parametrize("heading", ["VOCALOID原创作者", "VOCALOID原創作者"])
def test_structural_normalization_creator_heading(fetch, heading):
    data = fetch("{{VOCALOID Songbox}}\n== " + heading + " ==\n樂師的完整介紹。\n== 歌詞 ==\n<poem>夢裡的聲音</poem>", heading)
    assert data["summary"] == ["乐师的完整介绍。"]
    assert data["lyrics"] == "梦里的声音"


def test_recorded_yishen_keeps_one_complete_intro_and_public_lyrics(fetch):
    source = (Path(__file__).parent / "fixtures" / "vcpedia_recorded_yishen.wikitext").read_text(encoding="utf-8")
    data = fetch(source, "疑神疑鬼")
    # Public lyrics outside the information tabs must be retained, and the first
    # complete introduction is published as exactly one entry. This case keeps
    # real material without pinning the page's own text as the expectation.
    assert len(data["summary"]) == 1 and data["summary"][0].strip()
    assert data["lyrics"].strip() and data["spaced_lyrics"].strip()
    assert "投稿时间" in data["infobox"]
    assert set(data) == {"name", "type", "infobox", "summary", "lyrics", "spaced_lyrics", "short_summary"}


@pytest.mark.parametrize("box", ["VOCALOID Songbox", "VOCALOID Small Songbox"])
@pytest.mark.parametrize("other", ["测试曲", "另一首"])
def test_first_candidate_derivative_never_overwrites_main(fetch, box, other):
    data = fetch("{{VOCALOID Songbox|歌曲名称=测试曲|P主=原作者}}\n"
        "== 简介 ==\n原作完整简介。\n== 歌词 ==\n<poem>原作第一行\n原作第二行</poem>\n"
        "== 二次创作 ==\n{{" + box + "|歌曲名称=" + other +
        "|UP主=二创作者|简介=二创简介。|歌词={{LyricsKai|original=二创歌词|translated=二创译文}}}}")
    assert data["infobox"] == {"歌曲名称": "测试曲", "P主": "原作者"}
    assert data["lyrics"] == "原作第一行\n原作第二行"


def test_first_candidate_small_can_be_main_and_roles_are_open(fetch):
    data = fetch("{{VOCALOID Small Songbox|歌曲名称=测试曲|P主=甲|其他资料=收录于专辑。"
        "|简介=完整简介。|歌词={{VOCALOID Songbox Introduction|吉他<br>混音=乙|group1=母带<br>统筹|list1=丙|LDC=yes}}"
        "{{LyricsKai|original=第一行\n第二行|translated=译一\n译二}}}}")
    assert data["lyrics"] == "第一行\n第二行"
    assert data["summary"] == ["完整简介。"]
    assert data["infobox"]["混音"] == "乙"
    assert data["infobox"]["统筹"] == "丙"
    assert "UP主" not in data["infobox"] and "LDC" not in data["infobox"]


@pytest.mark.parametrize("box_title", ["完全不同", "字面(括号)", "显示♡名字"])
def test_ordered_first_box_and_staff_stay_together(fetch, box_title):
    data = fetch("{{VOCALOID Songbox Introduction|作词=前置}}"
        "{{VOCALOID Songbox|歌曲名称=" + box_title + "|演唱=甲|简介=第一简介|歌词={{LyricsKai|original=第一行\n第二行|translated=译文}}}}"
        "{{VOCALOID Songbox Introduction|作曲=第一作者}}"
        "{{VOCALOID Songbox|歌曲名称=" + box_title + "|演唱=乙|简介=第二简介|歌词={{LyricsKai|original=另版}}}}"
        "{{VOCALOID Songbox Introduction|作曲=第二作者}}", "请求[字面](限定)")
    assert data["name"] == "请求[字面](限定)"
    assert data["infobox"] == {"歌曲名称": box_title, "演唱": "甲", "作词": "前置", "作曲": "第一作者"}
    assert data["summary"] == ["第一简介"]
    assert data["lyrics"] == "第一行\n第二行"


def test_first_candidate_same_name_boxes_do_not_limit_public_body(fetch):
    data = fetch("{{VOCALOID Songbox|歌曲名称=测试曲|演唱=甲}}"
        "{{VOCALOID Songbox|歌曲名称=测试曲|演唱=乙}}\n== 简介 ==\n完整简介。\n== 歌词 ==\n<poem>完整歌词</poem>")
    assert data["infobox"] == {"歌曲名称": "测试曲", "演唱": "甲"}
    assert data["summary"] == ["完整简介。"]
    assert data["lyrics"] == "完整歌词"


@pytest.mark.parametrize("template,label,content", [("Tabs", "bt", "tab"), ("Tabs/core", "label", "text")])
def test_first_candidate_tabs_select_original_without_translation(fetch, template, label, content):
    data = fetch("== 歌词 ==\n{{" + template + "|" + label + "1=原版|" + content +
        "1={{Lyrics|lb-text2=原文二|rb-text2=译二|lb-text1=原文一|rb-text1=译一}}|" + label +
        "2=翻唱版|" + content + "2={{LyricsKai|original=翻唱全文|translated=翻唱译文}}}}")
    assert data["lyrics"] == "原文一\n\n原文二"


def test_first_candidate_complete_tab_selects_all_fields_together(fetch):
    data = fetch("{{Tabs|bt1=原版|tab1={{VOCALOID Songbox|歌曲名称=测试曲|演唱=甲}}\n== 简介 ==\n原版简介。\n== 歌词 ==\n<poem>原版歌词</poem>"
        "|bt2=翻唱版|tab2={{VOCALOID Songbox|歌曲名称=测试曲|演唱=乙}}\n== 歌词 ==\n<poem>翻唱歌词</poem>}}")
    assert data["infobox"]["演唱"] == "甲"
    assert data["summary"] == ["原版简介。"]
    assert data["lyrics"] == "原版歌词"


def test_first_candidate_unlabelled_small_beside_full_box_is_not_main(fetch):
    data = fetch("{{VOCALOID Songbox|歌曲名称=测试曲|演唱=甲}}"
        "{{VOCALOID Small Songbox|演唱=乙|简介=归属未知|歌词=<poem>未知版本</poem>}}"
        "\n== 简介 ==\n主简介\n== 歌词 ==\n<poem>主歌词</poem>")
    assert data["infobox"]["演唱"] == "甲"
    assert data["lyrics"] == "未知版本"


def test_plain_container_songbox_keeps_full_main_fields(fetch):
    data = fetch('<div>{{VOCALOID Songbox|歌曲名称=测试曲|演唱=甲}}</div>\n'
        '== 简介 ==\n主简介\n== 歌词 ==\n<poem>第一行完整歌词\n第二行完整歌词</poem>')
    assert data["infobox"] == {"歌曲名称": "测试曲", "演唱": "甲"}
    assert data["summary"] == ["主简介"]
    assert data["lyrics"] == "第一行完整歌词\n第二行完整歌词"


def test_nested_containers_keep_first_fields_and_body(fetch):
    data = fetch('<section><div>{{VOCALOID Songbox|歌曲名称=首框|演唱=甲|简介=首简介|歌词=<poem>首歌词</poem>}}'
        '<section>{{VOCALOID Songbox Introduction|作词=首词}}</section></div>'
        '{{VOCALOID Songbox Introduction|作曲=首曲}}'
        '<div><section>{{VOCALOID Songbox|歌曲名称=后框|演唱=乙|简介=后简介|歌词=<poem>后歌词</poem>}}'
        '{{VOCALOID Songbox Introduction|作词=后词}}</section></div></section>'
        '{{VOCALOID Songbox Introduction|作曲=后曲}}')
    assert data["infobox"] == {"歌曲名称": "首框", "演唱": "甲", "作词": "首词", "作曲": "首曲"}
    assert data["summary"] == ["首简介"] and data["lyrics"] == "首歌词"


def test_small_direct_lyric_slot_keeps_markup_without_poem(fetch):
    data = fetch("{{VOCALOID Small Songbox|歌曲名称=字面|简介=简介|歌词=第一行{{Ruby|字|zi}}\n第二行（和声）}}")
    assert data["lyrics"] == "第一行字\n第二行（和声）"
    assert data["infobox"] == {"歌曲名称": "字面"}


def test_first_candidate_first_different_name_box_is_complete_main(fetch):
    data = fetch("{{VOCALOID Songbox|歌曲名称=另一首|演唱=乙|简介=另一首简介|歌词=<poem>另一首歌词</poem>}}")
    assert data["infobox"] == {"歌曲名称": "另一首", "演唱": "乙"}
    assert data["lyrics"] == "另一首歌词"
    assert data["summary"] == ["另一首简介"]


def test_first_candidate_linked_title_identifies_main(fetch):
    data = fetch("{{VOCALOID Songbox|歌曲名称=[[测试曲|显示别名]]|演唱=甲}}\n== 歌词 ==\n<poem>主歌词</poem>")
    assert data["infobox"]["演唱"] == "甲"


def test_first_candidate_tabs_project_first_without_label_scoring(fetch):
    data = fetch("== 歌词 ==\n{{Tabs|bt1=甲版|tab1=<poem>甲歌词</poem>|bt2=乙版|tab2=<poem>乙歌词</poem>}}")
    assert data["lyrics"] == "甲歌词"


@pytest.mark.parametrize("body,expected", [
    ("{{MultiLine Lyric|主唱（互动）|和声|size=20}}", "主唱（互动）\n和声"),
    ("{{歌词并列/重唱|甲|乙|丙|丁|AC=red|gap=2em}}", "甲\n乙\n丙\n丁"),
    ("{{Utawari|主#2唱|和声##2|mainLineNum=1|newline=html}}", "主唱\n和声#2"),
    ("{{Unknown|不应拼接|mode=正文}}第一行\n第二行", "第一行\n第二行"),
])
def test_text_documented_multiline_parameters(fetch, body, expected):
    data = fetch("== 歌词 ==\n<poem>" + body + "</poem>")
    assert data["lyrics"] == expected


def test_first_introduction_keeps_prose_around_local_tabs(fetch):
    data = fetch('== 简介 ==\n开篇。\n{{Tabs|text1=原版完整介绍。|text2=另一版介绍。}}\n'
                 '结尾。\n== 歌词 ==\n<poem>完整歌词</poem>')
    assert data['summary'] == ['开篇。\n原版完整介绍。\n结尾。']


@pytest.mark.parametrize("container", [
    '<div>{{黑幕|正文不可删除。}}</div>',
    '<div><div>{{黑幕|正文不可删除。}}</div></div>',
])
def test_intro_plain_container_keeps_continuous_prose(fetch, container):
    data = fetch('== 简介 ==\n开篇。' + container + '\n结尾。\n'
                 '== 歌词 ==\n<poem>歌词</poem>')
    assert data['summary'] == ['开篇。正文不可删除。结尾。']
    assert data['lyrics'] == '歌词'


@pytest.mark.parametrize("second", [
    '\n== 简介 ==\n第二简介不可混入。',
    '<div><h2>简介</h2><p>第二简介不可混入。</p></div>',
])
def test_intro_plain_container_stops_at_second_introduction(fetch, second):
    data = fetch('== 简介 ==\n开篇。<div><div>{{黑幕|正文不可删除。}}</div></div>\n结尾。'
                 + second + '\n== 歌词 ==\n<poem>歌词</poem>')
    assert data['summary'] == ['开篇。正文不可删除。结尾。']
    assert data['lyrics'] == '歌词'


def test_text_intro_keeps_div_body_and_all_paragraphs(fetch):
    data = fetch("== 简介 ==\n开篇。<div>正文不可删除。</div>\n第二段。\n== 歌词 ==\n<poem>歌词</poem>")
    assert "正文不可删除。" in "".join(data["summary"])
    assert "第二段。" in "".join(data["summary"])


def test_text_statistics_remove_whole_sentence_only(fetch):
    data = fetch("== 简介 ==\n这是殿堂曲。至今已有123次播放。\n"
        "截至现在有{{bilibiliCount|id=1}}次播放，是殿堂曲，{{bilibiliCount|id=1|type=5}}次收藏。"
        "正文没有缺词。\n=== 背景 ===\n完整背景也要保留。\n== 歌词 ==\n<poem>完整歌词</poem>")
    assert "\n".join(data["summary"]) == "这是殿堂曲。至今已有123次播放。\n正文没有缺词。\n完整背景也要保留。"


@pytest.mark.parametrize("title", ["煌", "普通DISCO", "达拉崩吧"])
def test_recorded_real_source_matches_lyric_html(fetch, title):
    folder = Path(__file__).parent / "fixtures"
    payload = json.loads((folder / "vcpedia_recorded_lyrics.json").read_text(encoding="utf-8"))[title]
    data = fetch(payload["wikitext"], title)
    # The contract uses displayed rb, retaining rt only where rb is blank (actual singing).
    expected = "".join("".join(html_surface.surface_lines(payload["lyrics_html"], section_id=None)).split())
    actual = "".join(data["lyrics"].split())
    assert expected
    assert actual == expected
    assert len(data["lyrics"].splitlines()) >= 25
    assert "殿堂曲，。" not in "".join(data["summary"])
    if title in {"达拉崩吧", "普通DISCO"}:
        assert data["infobox"]["UP主"] == "ilem"
        assert data["infobox"]["演唱"] == "洛天依、言和"


@pytest.mark.parametrize("title", ["作品(作者)", "作品（作者）"])
def test_disambiguated_main_keeps_same_name_derivative_separate(fetch, title):
    data = fetch("{{标题格式化}}{{VOCALOID Songbox|歌曲名称=作品|UP主=原作}}"
        "\n== 简介 ==\n原作简介。\n== 歌词 ==\n<poem>歌名(括号)与‘真的引号’</poem>"
        "\n== 二次创作 ==\n{{VOCALOID Songbox|歌曲名称=作品|UP主=二创}}", title)
    assert data["infobox"]["UP主"] == "原作"
    assert data["lyrics"] == "歌名(括号)与‘真的引号’"


def test_documented_ruby_surface_and_unknown_control_are_not_lyrics(fetch):
    data = fetch("== 简介 ==\n{{Dead|姓名|未知控制}}参与。\n== 歌词 ==\n"
        "<poem>{{Ruby|字|zì}}（和声）\n{{Ruby|　|啦啦}}\n"
        "{{Unknown|数字控制|2=不要拼接}}'真实单引号'\n"
        "<ruby><rb>表层</rb><rt>biǎo</rt></ruby></poem>")
    assert data["lyrics"] == "字（和声）\n啦啦\n'真实单引号'\n表层"
    assert data["summary"] == ["姓名参与。"]


@pytest.mark.parametrize("ruby,expected", [
    ("<ruby>字<rt>zi</rt></ruby>", "字"),
    ("<ruby>字<rp>（</rp><rt>zi</rt><rp>）</rp></ruby>", "字"),
    ("<ruby><span>表层</span><br>正文<rt>reading</rt></ruby>", "表层\n\n正文"),
    ("<ruby><rb>　</rb><rp>（</rp><rt>啦啦</rt><rp>）</rp></ruby>", "啦啦"),
    ("<ruby>　<rp>（</rp><rt>啦啦</rt><rp>）</rp></ruby>", "啦啦"),
], ids=["implicit-base", "implicit-with-rp", "span-and-br", "empty-rb", "empty-implicit"])
def test_html_ruby_implicit_base_before_reading_fallback(fetch, ruby, expected):
    data = fetch("== 简介 ==\n完整简介。\n== 歌词 ==\n<poem>" + ruby + "</poem>")
    assert data["lyrics"] == expected


def test_other_information_drops_count_clauses_and_keeps_other_clauses(fetch):
    """Other information removes only unresolved count clauses; never resolves them offline."""
    data = fetch('{{VOCALOID Songbox|歌曲名称=测试曲|演唱=甲|其他资料=收录于专辑《测试专辑》，'
                 '{{bilibiliCount|id=1}}次播放，2012年12月19日投稿原版}}')
    assert data["infobox"]["其他资料"] == "收录于专辑《测试专辑》，2012年12月19日投稿原版"


def test_first_box_name_does_not_lose_main_and_introduction_supplements_staff(fetch):
    data = fetch("{{VOCALOID Songbox|歌曲名称=别的作品|UP主=别的作者}}"
        "\n== 简介 ==\n简介。\n== 歌词 ==\n"
        "{{VOCALOID Songbox Introduction|作词=作词者}}<poem>完整歌词</poem>")
    assert data["infobox"] == {"歌曲名称": "别的作品", "UP主": "别的作者", "作词": "作词者"}
    assert data["lyrics"] == "完整歌词"
