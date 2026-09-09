"""Synthetic fixed source samples; all network/process seams are offline."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.world.get_new_songs.daily_new_song_fetcher import fetch_song_list_from_template, do_one_song
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher
from src.world.get_new_songs import daily_new_song_fetcher as daily
from src.subconscious.music_knowledge.song_database import Song

FIXTURES = Path(__file__).parent / "fixtures"
TEMPLATE = "https://vcpedia.cn/Template:%E6%B4%9B%E5%A4%A9%E4%BE%9D/2038"


def response(text, status=200):
    result = requests.Response()
    result.status_code = status
    result._content = text.encode("utf-8")
    result.encoding = "utf-8"
    return result


def payload(source):
    return json.dumps({"parse": {"title": "重定向目标", "wikitext": {"*": source}}}, ensure_ascii=False)


@pytest.fixture
def wire(monkeypatch):
    state = SimpleNamespace(body="", status=200, curl_body=None, curl_status=200,
                            curl_code=0, curl_exists=True, calls=[], curls=[])

    def get(url, **kwargs):
        state.calls.append((url, kwargs))
        return response(state.body, state.status)

    def run(args, **kwargs):
        state.curls.append((args, kwargs))
        body = state.body if state.curl_body is None else state.curl_body
        if "--write-out" in args:
            body += "\n" + str(state.curl_status)
        return SimpleNamespace(returncode=state.curl_code, stdout=body, stderr="fake curl failure")

    monkeypatch.setattr(requests, "get", get)
    monkeypatch.setattr(requests.Session, "get", lambda self, url, **kw: get(url, **kw))
    monkeypatch.setattr(shutil, "which", lambda name: "curl" if state.curl_exists else None)
    monkeypatch.setattr(subprocess, "run", run)
    return state


def fetcher(tmp_path, **config):
    return VCPediaFetcher({"activated": True, "use_llm": False,
                           "data_dir": str(tmp_path / "cache"), **config})


def assert_api(call, title):
    url, kwargs = call
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    query.update({k: [str(v)] for k, v in kwargs.get("params", {}).items()})
    assert parsed.path == "/api.php"
    assert query == {"action": ["parse"], "prop": ["wikitext"], "redirects": ["1"],
                     "format": ["json"], "page": [title]}


# Hand-matched rendered HTML/source, not captured live pages. Expected values
# were checked through the two HEAD public entries before implementation.
LIST_SOURCE = """{{Navbox|title=[[洛天依]]|group1=[[原创曲]]|list1=
[[真名|显示名*]] [[另一页|显示名]] {{lj|目标|别名}} [[殿堂曲之梦]]
[[Help:说明|说明]] [[歌曲#歌词|锚点]] [[#五月|五月]] [[2026]]
[[Category:歌曲|分类显示]] [[Template:文档|模板显示]] [[普通|首页]]
[https://example.org 外部曲] [[用户:甲]] [[正常曲]]}}"""
LIST_HTML = """<div id="mw-content-text">
<a href="/洛天依">洛天依</a><a href="/原创曲">原创曲</a>
<a href="/真名">显示名*</a><a href="/另一页">显示名</a><a href="/目标">别名</a>
<a href="/殿堂曲之梦">殿堂曲之梦</a><a href="/Help:说明">说明</a>
<a href="/歌曲#歌词">锚点</a><a href="#五月">五月</a><a href="/2026">2026</a>
<a href="/Category:歌曲">分类显示</a><a href="/Template:文档">模板显示</a>
<a href="/普通">首页</a><a href="https://example.org">外部曲</a>
<a href="/用户:甲">用户:甲</a><a href="/正常曲">正常曲</a></div>"""
LIST_EXPECTED = ["显示名", "别名", "说明", "锚点", "外部曲", "用户:甲", "正常曲"]


def test_template_preserves_head_display_names_and_filters(wire):
    wire.body = payload(LIST_SOURCE)
    assert fetch_song_list_from_template(TEMPLATE) == LIST_EXPECTED
    assert_api(wire.calls[0], "Template:洛天依/2038")


HEAD_DETAIL_CASES = [
    ("{{VOCALOID_Songbox|演唱=洛天依|image=cover.jpg|width=300|style=red}}\n== 简介 ==\n人物正文。",
     '<table class="moe-infobox infobox"><tr><td>演唱</td><td>洛天依</td></tr></table><h2>简介</h2><p>人物正文。</p>',
     {"type": "Person", "infobox": {"演唱": "洛天依"}, "summary": ["人物正文。"], "lyrics": "", "spaced_lyrics": ""}),
    ("== 简介 ==\n正文。\n{{创作者名单|group1=PV|list1=作者}}\n=== 背景 ===\n不可追加\n== 歌词 ==\n<poem>散文<span>第一句歌词</span><span>第二句歌词（副歌）</span>尾声</poem>\n<poem>第二版本</poem>",
     '<h2>简介</h2><p>正文。</p><div><table><tr><td>PV</td><td>作者</td></tr></table></div><h3>背景</h3><p>不可追加</p><h2>歌词</h2><div class="poem"><p>散文<span>第一句歌词</span><span>第二句歌词（副歌）</span>尾声</p></div><div class="poem"><p>第二版本</p></div>',
     {"type": "Song", "infobox": {"PV": "作者"}, "summary": ["正文。"], "lyrics": "第一句歌词 第二句歌词", "spaced_lyrics": "第一句歌词 第二句歌词", "short_summary": "正文。"}),
    ("== 简介 ==\n开头。截至现在有123次播放，45次收藏。结尾。\n== 歌词 ==\n普通正文并非poem\n<poem>甲（副歌）<br/>乙</poem>",
     '<h2>简介</h2><p>开头。截至现在有123次播放，45次收藏。结尾。</p><h2>歌词</h2><p>普通正文并非poem</p><div class="poem"><p>甲（副歌）<br/>乙</p></div>',
     {"type": "Song", "infobox": {}, "summary": ["开头。。结尾。"], "lyrics": "甲乙", "spaced_lyrics": "甲乙", "short_summary": "开头。。结尾。"}),
    ("<poem>无标题歌词</poem>\n=== 歌词 ===\n<poem>三级标题</poem>",
     '<div class="poem"><p>无标题歌词</p></div><h3>歌词</h3><div class="poem"><p>三级标题</p></div>',
     {"type": "Person", "infobox": {}, "summary": [], "lyrics": "", "spaced_lyrics": ""}),
    ("== 歌词 ==\n<poem>旧版</poem>\n== 新版歌词 ==\n<poem>新版一\n新版二</poem>",
     '<h2>歌词</h2><div class="poem"><p>旧版</p></div><h2>新版歌词</h2><div class="poem"><p>新版一\n新版二</p></div>',
     {"type": "Song", "infobox": {}, "summary": [""], "lyrics": "新版一 新版二", "spaced_lyrics": "新版一 新版二", "short_summary": ""}),
]


@pytest.mark.parametrize("source,html,expected", HEAD_DETAIL_CASES)
def test_head_detail_equivalent_samples(wire, tmp_path, source, html, expected):
    wire.body = payload(source)
    assert fetcher(tmp_path).fetch_entity_description("固定样例") == {"name": "固定样例", **expected}


# Artificial corresponding source/HTML pairs, not real-site captures.
HEAD_REPAIR_LYRICS = [
    (f'<div class="{container}"><div><div class="poem"><p>这是第一句完整歌词</p><p>不采第二段</p></div></div><div class="poem"><p>不采第二版</p></div></div>',
     f'<div class="{container}"><div><div class="poem"><p>这是第一句完整歌词</p><p>不采第二段</p></div></div><div class="poem"><p>不采第二版</p></div></div>',
     "这是第一句完整歌词")
    for container in ("Tabs", "tabLabelTop")
] + [
    ('<div class="Tabs">无歌词</div><div class="poem"><p>不可继续查找</p></div>',
     '<div class="Tabs">无歌词</div><div class="poem"><p>不可继续查找</p></div>', ""),
    ('<div class="other"><div class="poem"><p>不可任意递归</p></div></div><poem>同级歌词</poem>',
     '<div class="other"><div class="poem"><p>不可任意递归</p></div></div><div class="poem"><p>同级歌词</p></div>', "同级歌词"),
    ('<poem><span>第一句<br/>第二句</span></poem>',
     '<div class="poem"><p><span>第一句<br/>第二句</span></p></div>', "第一句第二句"),
    ('<poem><span>第一句<br/>第二句</span><span>第三句<br/>第四句</span></poem>',
     '<div class="poem"><p><span>第一句<br/>第二句</span><span>第三句<br/>第四句</span></p></div>', "第一句第二句 第三句第四句"),
]


@pytest.mark.parametrize("source,html,expected", HEAD_REPAIR_LYRICS)
def test_head_repair_lyrics(wire, tmp_path, source, html, expected):
    wire.body = payload("== 简介 ==\n正文\n== 歌词 ==\n" + source)
    data = fetcher(tmp_path).fetch_entity_description("固定样例")
    assert data == {"name": "固定样例", "type": "Song", "infobox": {},
                    "summary": ["正文"], "short_summary": "正文",
                    "lyrics": expected, "spaced_lyrics": expected}


HEAD_REPAIR_LINKS = [
    ('== 简介 ==\n由[[User:甲|作者甲]]创作。',
     '<h2>简介</h2><p>由<a>作者甲</a>创作。</p>',
     {"type": "Person", "infobox": {}, "summary": ["由作者甲创作。"], "lyrics": "", "spaced_lyrics": ""}),
    ('{{VOCALOID_Songbox|演唱=[[用户:甲|作者甲]]}}\n== 简介 ==\n[[Help:说明|说明]][[User:乙]][[File:封面.jpg|封面]][[Category:歌曲]][[:File:封面.jpg|文件链接]][[:Category:歌曲|分类链接]][[:User:丙]]\n== 歌词 ==\n<poem>[[User:甲|第一句完整歌词]]</poem>',
     '<table class="moe-infobox infobox"><tr><td>演唱</td><td><a>作者甲</a></td></tr></table><h2>简介</h2><p><a>说明</a><a>User:乙</a><img src="封面.jpg"><a>文件链接</a><a>分类链接</a><a>User:丙</a></p><h2>歌词</h2><div class="poem"><p><a>第一句完整歌词</a></p></div>',
     {"type": "Song", "infobox": {"演唱": "作者甲"}, "summary": ["说明User:乙文件链接分类链接User:丙"], "short_summary": "说明User:乙文件链接分类链接User:丙", "lyrics": "第一句完整歌词", "spaced_lyrics": "第一句完整歌词"}),
]


@pytest.mark.parametrize("source,html,expected", HEAD_REPAIR_LINKS)
def test_head_repair_links(wire, tmp_path, source, html, expected):
    wire.body = payload(source)
    assert fetcher(tmp_path).fetch_entity_description("固定样例") == {"name": "固定样例", **expected}


HEAD_REPAIR_TABLES = [
    ('<table class="moe-infobox infobox"><tr><td>演唱</td><td>洛天依</td></tr></table>\n== 简介 ==\n正文',
     '<table class="moe-infobox infobox"><tr><td>演唱</td><td>洛天依</td></tr></table><h2>简介</h2><p>正文</p>',
     {"type": "Person", "infobox": {"演唱": "洛天依"}, "summary": ["正文"], "lyrics": "", "spaced_lyrics": ""}),
]
_TABLE_ROWS = ('<tr style="display:none"><td>隐藏</td><td>不可采</td></tr>'
               '<tr><th>演唱</th><td><span> 洛天依 </span><br/><a> 乐正绫 </a></td></tr>'
               '<tr><td>作词人员</td></tr><tr><td class="infobox-image-container">图片</td></tr>'
               '<tr><td> </td></tr><tr><td>甲<br/>乙</td></tr>'
               '<tr><td>未知标题</td></tr><tr><td>PV</td></tr><tr><td>作者丙</td></tr>')
for _location in ("main", "intro", "lyrics"):
    _table = '<table' + (' class="moe-infobox infobox"' if _location == "main" else '') + '>' + _TABLE_ROWS + '</table>'
    _source = (_table + '\n== 简介 ==\n正文' if _location == "main" else
               '== 简介 ==\n正文\n' + ('<div>' + _table + '</div>\n=== 背景 ===\n<div><table><tr><td>忽略</td><td>值</td></tr></table></div>' if _location == "intro" else '== 歌词 ==\n' + _table + '\n<poem>第一句完整歌词</poem>'))
    _html = (_table + '<h2>简介</h2><p>正文</p>' if _location == "main" else
             '<h2>简介</h2><p>正文</p>' + ('<div>' + _table + '</div><h3>背景</h3><div><table><tr><td>忽略</td><td>值</td></tr></table></div>' if _location == "intro" else '<h2>歌词</h2>' + _table + '<div class="poem"><p>第一句完整歌词</p></div>'))
    _expected = {"type": "Song" if _location == "lyrics" else "Person",
                 "infobox": {"演唱": "洛天依,乐正绫", **({"作词": "甲乙", "PV": "作者丙"} if _location != "lyrics" else {})},
                 "summary": ["正文"], "lyrics": "第一句完整歌词" if _location == "lyrics" else "",
                 "spaced_lyrics": "第一句完整歌词" if _location == "lyrics" else ""}
    if _location == "lyrics":
        _expected["short_summary"] = "正文"
    HEAD_REPAIR_TABLES.append((_source, _html, _expected))


# Exact class order, first table selection and direct/nested navbox stopping
# follow HEAD, even where a more permissive parser might collect more fields.
for _prefix, _expected_box in [
    ('<table class="infobox moe-infobox"><tr><td>演唱</td><td>忽略</td></tr></table>', {}),
    ('<table class="navbox"></table><table><tr><td>演唱</td><td>忽略</td></tr></table>', {}),
    ('<div><table class="navbox"></table></div><table><tr><td>演唱</td><td>洛天依</td></tr></table><table><tr><td>演唱</td><td>忽略</td></tr></table>', {"演唱": "洛天依"}),
]:
    # The reversed-class table is outside the lyrics sibling scan.
    _outside = _prefix.startswith('<table class="infobox')
    HEAD_REPAIR_TABLES.append((
        (_prefix + '\n== 简介 ==\n正文\n== 歌词 ==\n' if _outside else '== 简介 ==\n正文\n== 歌词 ==\n' + _prefix) + '<poem>完整歌词</poem>',
        (_prefix + '<h2>简介</h2><p>正文</p><h2>歌词</h2>' if _outside else '<h2>简介</h2><p>正文</p><h2>歌词</h2>' + _prefix) + '<div class="poem"><p>完整歌词</p></div>',
        {"type": "Song", "infobox": _expected_box, "summary": ["正文"], "short_summary": "正文", "lyrics": "完整歌词", "spaced_lyrics": "完整歌词"},
    ))


@pytest.mark.parametrize("source,html,expected", HEAD_REPAIR_TABLES)
def test_head_repair_tables(wire, tmp_path, source, html, expected):
    wire.body = payload(source)
    assert fetcher(tmp_path).fetch_entity_description("固定样例") == {"name": "固定样例", **expected}


# Expectations calibrated against HEAD public entry with matching rendered HTML.
@pytest.mark.parametrize("source", [
    '<h2>简介</h2><p>正文</p><h2>歌词</h2><div class="poem"><p>完整歌词</p></div>',
    '<div>\n== 简介 ==\n正文\n== 歌词 ==\n<poem>完整歌词</poem>\n</div>',
    '{{tabs|text1=\n== 简介 ==\n正文\n== 歌词 ==\n<poem>完整歌词</poem>}}',
    '<div><h2>简介</h2><p>正文</p><h3>背景</h3><p>忽略</p><h2>歌词</h2><div class="poem"><p>完整歌词</p></div></div><div class="poem"><p>外部忽略</p></div>',
])
def test_compat2_global_headers_local_siblings(wire, tmp_path, source):
    wire.body = payload(source)
    assert fetcher(tmp_path).fetch_entity_description("固定样例") == {
        "name": "固定样例", "type": "Song", "infobox": {},
        "summary": ["正文"], "short_summary": "正文",
        "lyrics": "完整歌词", "spaced_lyrics": "完整歌词"}


@pytest.mark.parametrize("source,expected", [
    ('[[歌曲]]<noinclude>[[附加歌曲]]</noinclude>', ["歌曲", "附加歌曲"]),
    ('[[歌曲]]<includeonly>[[隐藏歌曲]]</includeonly>', ["歌曲"]),
    ('[[歌曲]]<onlyinclude>[[附加歌曲]]</onlyinclude>[[末曲]]', ["歌曲", "附加歌曲", "末曲"]),
])
def test_compat2_direct_template_context(wire, source, expected):
    wire.body = payload(source)
    assert fetch_song_list_from_template(TEMPLATE) == expected


@pytest.mark.parametrize("extra", [
    '<div>额外内容</div>', '<table><tr><td>额外内容</td></tr></table>',
])
def test_compat2_intro_node_whitelist(wire, tmp_path, extra):
    wire.body = payload('== 简介 ==\n正文\n' + extra)
    assert fetcher(tmp_path).fetch_entity_description("固定样例") == {
        "name": "固定样例", "type": "Person", "infobox": {},
        "summary": ["正文"], "lyrics": "", "spaced_lyrics": ""}


def test_compat2_list_text_nodes_join_without_separator(wire):
    wire.body = payload('[[歌曲|甲<span> 乙 </span>丙]]')
    assert fetch_song_list_from_template(TEMPLATE) == ["甲乙丙"]


@pytest.mark.parametrize("source,expected", [
    ('== 简介 ==\n甲<span> 乙 </span>丙<br/>丁', '甲乙丙丁'),
    ('<h2>简介</h2><p>甲<span> 乙 </span>丙<br/>丁</p>', '甲乙丙丁'),
    ('== 简介 ==\n正文\n<ul><li>甲<span> 乙 </span>丙</li><li>丁</li></ul><p>末段</p>', '正文\n甲乙丙\n丁\n末段'),
    ('== 简介 ==\n正文\n* 甲<span> 乙 </span>丙\n* 丁\n\n末段', '正文\n甲乙丙\n丁\n末段'),
    ('<h2>简介</h2><p>正文</p><a>甲</a><a>乙</a><p>末段</p>', '正文甲乙末段'),
])
def test_compat2_intro_text_nodes_join(wire, tmp_path, source, expected):
    wire.body = payload(source)
    assert fetcher(tmp_path).fetch_entity_description("固定样例") == {
        "name": "固定样例", "type": "Person", "infobox": {},
        "summary": [expected], "lyrics": "", "spaced_lyrics": ""}


# Matched rendered HTML calibrated through HEAD's public detail entry.
HEAD_TABS_SCOPE = [
    ('{{tabs|text1=<h2>歌词</h2>}}<poem>外部歌词</poem>',
     '<div class="Tabs"><div><h2>歌词</h2></div></div><div class="poem"><p>外部歌词</p></div>',
     {"type": "Song", "summary": [""], "short_summary": "", "lyrics": "", "spaced_lyrics": ""}),
    ('{{tabs|text1=<h2>简介</h2>}}<p>外部简介</p>',
     '<div class="Tabs"><div><h2>简介</h2></div></div><p>外部简介</p>',
     {"type": "Person", "summary": [""], "lyrics": "", "spaced_lyrics": ""}),
    ('{{tabs|text1=<h2>简介</h2><p>内部简介</p><h2>歌词</h2><poem>内部歌词</poem>}}<p>外部简介</p><poem>外部歌词</poem>',
     '<div class="Tabs"><div><h2>简介</h2><p>内部简介</p><h2>歌词</h2><div class="poem"><p>内部歌词</p></div></div></div><p>外部简介</p><div class="poem"><p>外部歌词</p></div>',
     {"type": "Song", "summary": ["内部简介"], "short_summary": "内部简介", "lyrics": "内部歌词", "spaced_lyrics": "内部歌词"}),
    ('{{tabs|text1=<h2>歌词</h2>|text2=<poem>另页签歌词</poem>}}',
     '<div class="Tabs"><div><h2>歌词</h2></div><div><div class="poem"><p>另页签歌词</p></div></div></div>',
     {"type": "Song", "summary": [""], "short_summary": "", "lyrics": "", "spaced_lyrics": ""}),
]


@pytest.mark.parametrize("source,html,expected", HEAD_TABS_SCOPE)
def test_tabs_heading_keeps_parameter_sibling_scope(wire, tmp_path, source, html, expected):
    wire.body = payload(source)
    assert fetcher(tmp_path).fetch_entity_description("固定样例") == {
        "name": "固定样例", "infobox": {}, **expected}


def test_details_keep_requested_identity_and_ignore_summary_flag(wire, tmp_path):
    source, _, expected = HEAD_DETAIL_CASES[1]
    wire.body = payload(source)
    assert fetcher(tmp_path).fetch_entity_description("测试曲 & A?", False) == {
        "name": "测试曲 & A?", **expected}
    assert_api(wire.calls[0], "测试曲 & A?")


@pytest.mark.parametrize("container", ["<poem>{}</poem>", "<div class=poem><p>{}</p></div>"])
def test_explicit_poem_br_keeps_head_get_text_format(wire, tmp_path, container):
    wire.body = payload("== 歌词 ==\n" + container.format("第一段完整歌词<br/>第二段完整歌词"))
    data = fetcher(tmp_path).fetch_entity_description("歌")
    # Matched HTML: <h2>歌词</h2><div class=poem><p>第一段完整歌词<br/>第二段完整歌词</p></div>
    assert data["lyrics"] == "第一段完整歌词第二段完整歌词"
    assert data["spaced_lyrics"] == data["lyrics"]


@pytest.mark.parametrize("entry", ["list", "detail"])
@pytest.mark.parametrize("status", [200, 403])
def test_both_entries_recover_challenge_through_curl(wire, tmp_path, entry, status):
    wire.status, wire.body = status, "<html>Making sure you're not a bot! Anubis</html>"
    wire.curl_body = payload("[[歌曲]]" if entry == "list" else "== 简介 ==\n正文")
    result = (fetch_song_list_from_template(TEMPLATE, 7) if entry == "list"
              else fetcher(tmp_path).fetch_entity_description("歌曲"))
    assert result == ["歌曲"] if entry == "list" else result["summary"] == ["正文"]
    args, kwargs = wire.curls[0]
    assert "--max-time" in args and "--fail" in args
    assert "--user-agent" in args
    assert kwargs.get("shell", False) is False
    assert_api((args[-1], {}), "Template:洛天依/2038" if entry == "list" else "歌曲")


@pytest.mark.parametrize("entry", ["list", "detail"])
@pytest.mark.parametrize("failure", ["no_curl", "curl_exit", "curl_http", "empty", "challenge", "json", "api_error", "missing", "wrong_type", "http"])
def test_failures_are_not_successful_empty_pages(wire, tmp_path, entry, failure):
    wire.body = "Anubis challenge"
    wire.curl_body = payload("[[歌曲]]")
    if failure == "no_curl": wire.curl_exists = False
    elif failure == "curl_exit": wire.curl_code = 28
    elif failure == "curl_http": wire.curl_status = 503
    elif failure == "empty": wire.curl_body = ""
    elif failure == "challenge": wire.curl_body = "Anubis challenge"
    else:
        wire.body = {"json": "not JSON", "api_error": '{"error":{"code":"missingtitle"}}',
                     "missing": '{"parse":{}}', "wrong_type": '{"parse":{"wikitext":[]}}',
                     "http": "failure"}[failure]
        if failure == "http": wire.status = 500
    if entry == "list":
        with pytest.raises(Exception):
            fetch_song_list_from_template(TEMPLATE)
    else:
        assert fetcher(tmp_path).fetch_entity_description("歌曲") is None


def test_valid_json_with_challenge_word_is_not_challenged(wire, tmp_path):
    wire.body = payload("== 简介 ==\nAnubis 是曲名。")
    assert fetcher(tmp_path).fetch_entity_description("歌曲")["summary"] == ["Anubis 是曲名。"]
    assert not wire.curls


@pytest.mark.parametrize("entry", ["list", "detail"])
@pytest.mark.parametrize("via_curl", [False, True])
@pytest.mark.parametrize("body,status,error", [
    ("null", 200, ValueError),
    ("[]", 200, ValueError),
    ('"Anubis"', 200, ValueError),
    (payload("[[Anubis]]"), 500, requests.HTTPError),
    ("not JSON", 500, requests.HTTPError),
])
def test_json_and_http_failures_keep_entry_semantics(wire, tmp_path, entry, via_curl, body, status, error):
    wire.body, wire.status = body, status
    if via_curl:
        wire.body, wire.status = "Anubis challenge", 403
        wire.curl_body, wire.curl_status = body, status
        if status != 200:
            error = RuntimeError
    if entry == "list":
        with pytest.raises(error):
            fetch_song_list_from_template(TEMPLATE)
    else:
        assert fetcher(tmp_path).fetch_entity_description("歌曲") is None
    assert bool(wire.curls) == via_curl


@pytest.mark.parametrize("entry", ["list", "detail"])
def test_403_valid_json_still_uses_curl(wire, tmp_path, entry):
    wire.status, wire.body = 403, payload("[[不可采用]]")
    wire.curl_body = payload("[[Anubis]]" if entry == "list" else "== 简介 ==\nAnubis")
    if entry == "list":
        assert fetch_song_list_from_template(TEMPLATE) == ["Anubis"]
    else:
        assert fetcher(tmp_path).fetch_entity_description("歌曲")["summary"] == ["Anubis"]
    assert len(wire.curls) == 1


def test_empty_template_and_index_title_url(wire):
    wire.body = payload("")
    assert fetch_song_list_from_template("https://vcpedia.cn/index.php?title=Template:洛天依/2038") == []
    assert_api(wire.calls[0], "Template:洛天依/2038")


@pytest.mark.parametrize("entry", ["list", "detail"])
def test_requests_timeout_is_a_failure(monkeypatch, wire, tmp_path, entry):
    def timeout(*args, **kwargs):
        raise requests.Timeout("offline timeout")
    monkeypatch.setattr(requests, "get", timeout)
    monkeypatch.setattr(requests.Session, "get", timeout)
    if entry == "list":
        with pytest.raises(requests.Timeout):
            fetch_song_list_from_template(TEMPLATE)
    else:
        assert fetcher(tmp_path).fetch_entity_description("歌曲") is None


def test_named_tabs_under_sections_keep_intro_and_lyrics(wire, tmp_path):
    wire.body = payload("== 简介 ==\n{{tabs/core|label1=原版|text1=原版的简介正文}}"
                        "\n== 歌词 ==\n{{tabs/core|label1=原版|text1=<poem>完整原版歌词</poem>"
                        "|label2=新版|text2={{Lyrics|完整新版歌词}}}}")
    data = fetcher(tmp_path).fetch_entity_description("歌曲")
    assert data["summary"] == ["原版的简介正文"]
    # HEAD picks the first poem inside the rendered Tabs container.
    assert data["lyrics"] == "完整原版歌词"


@pytest.mark.parametrize("source,expected", [
    ("{{Lyrics|第一段完整歌词}}\n<poem>第二段完整歌词</poem>", ""),
    ("{{Lyrics|章节之前完整歌词}}\n== 歌词 ==\n<poem>章节之内完整歌词</poem>\n== 其他 ==\n{{Lyrics|章节之后完整歌词}}", "章节之内完整歌词"),
    ("== 歌词 ==\n<poem>{{Lyrics|只应出现一次歌词}}</poem>", "只应出现一次歌词"),
])
def test_mixed_lyrics_keep_head_header_and_first_poem_selection(wire, tmp_path, source, expected):
    wire.body = payload(source)
    data = fetcher(tmp_path).fetch_entity_description("歌曲")
    assert data["lyrics"] == expected
    assert data["spaced_lyrics"] == expected


def test_dynamic_counter_does_not_delete_surrounding_sentence(wire, tmp_path):
    wire.body = payload("== 简介 ==\n这是一首关于星空的歌曲。\n"
                        "截至现在已有{{bilibiliCount|id=1}}次播放。\n由作者甲创作。")
    data = fetcher(tmp_path).fetch_entity_description("歌曲")
    # HEAD only removes 截至...收藏, not this whole sentence. The remote
    # counter value is unknowable from this source and is not claimed equal.
    assert data["summary"] == ["这是一首关于星空的歌曲。\n截至现在已有次播放。\n由作者甲创作。"]


def test_h3_is_not_an_independent_intro_or_song_header(wire, tmp_path):
    wire.body = payload("== 简介 ==\n正文\n=== 简介 ===\n不可追加\n"
                        "=== 歌词 ===\n<poem>不可采集</poem>")
    data = fetcher(tmp_path).fetch_entity_description("歌曲")
    assert data == {"name": "歌曲", "type": "Person", "infobox": {},
                    "summary": ["正文"], "lyrics": "", "spaced_lyrics": ""}


def test_disabled_and_cached_details_do_not_access_network(wire, tmp_path):
    assert fetcher(tmp_path, activated=False).fetch_entity_description("歌曲") == ""
    cache = tmp_path / "cache"
    cache.mkdir()
    cached = {"name": "歌曲", "lyrics": "旧缓存", "summary": ["旧简介"]}
    (cache / "歌曲.json").write_text(json.dumps(cached), encoding="utf-8")
    assert fetcher(tmp_path).fetch_entity_description("歌曲") == cached
    assert not wire.calls


@pytest.mark.parametrize("lyric_source,expected", [
    ('<div class="Tabs"><div class="poem"><p>这是第一句完整歌词</p></div></div>', "这是第一句完整歌词"),
    ('<poem><span>第一句<br/>第二句</span></poem>', "第一句第二句"),
])
def test_repaired_details_preserve_database_singers_and_keywords(wire, tmp_path, monkeypatch, lyric_source, expected):
    wire.body = payload('<table class="moe-infobox infobox"><tr><td>演唱</td><td>[[User:甲|洛天依]]</td></tr></table>\n'
                        '== 简介 ==\n由[[User:甲|作者甲]]创作。\n== 歌词 ==\n' + lyric_source)
    monkeypatch.setattr(daily, "KNOWLEDGE_DIR", tmp_path)
    monkeypatch.setattr(daily, "SONG_NAME_KEYWORDS_FILE", tmp_path / "names.txt")
    monkeypatch.setattr(daily, "SONG_LYRIC_KEYWORDS_FILE", tmp_path / "lyrics.txt")
    engine = create_engine("sqlite:///:memory:")
    Song.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            assert do_one_song(db, fetcher(tmp_path), "修复曲")
            song = db.query(Song).one()
            assert song.singers == "洛天依"
            assert song.introduction == "由作者甲创作。"
            assert song.lyrics == expected
        assert (tmp_path / "lyrics.txt").read_text(encoding="utf-8") == f"{expected}=>{expected}是《修复曲》的歌词\n"
    finally:
        engine.dispose()


def test_public_ingestion_keeps_sqlite_and_keyword_contract(wire, tmp_path, monkeypatch):
    wire.body = payload("[[真实页面|显示歌名]]")
    song_name = fetch_song_list_from_template(TEMPLATE)[0]
    wire.body = payload("{{VOCALOID_Songbox|演唱=洛天依|UP主=作者甲}}\n== 简介 ==\n正文。\n== 歌词 ==\n<poem><span>这是第一句完整歌词</span><span>这是第二句完整歌词</span></poem>")
    monkeypatch.setattr(daily, "KNOWLEDGE_DIR", tmp_path)
    monkeypatch.setattr(daily, "SONG_NAME_KEYWORDS_FILE", tmp_path / "names.txt")
    monkeypatch.setattr(daily, "SONG_LYRIC_KEYWORDS_FILE", tmp_path / "lyrics.txt")
    engine = create_engine("sqlite:///:memory:")
    Song.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            crawler = fetcher(tmp_path)
            assert do_one_song(db, crawler, song_name)
            assert_api(wire.calls[-1], "显示歌名")
            song = db.query(Song).one()
            assert song.name == song.safe_name == "显示歌名"
            assert song.singers == "洛天依" and song.uploader == "作者甲"
            assert song.lyrics == "这是第一句完整歌词 这是第二句完整歌词"
            assert song.introduction == "正文。"
            assert not do_one_song(db, crawler, song_name)
        assert (tmp_path / "names.txt").read_text(encoding="utf-8") == "显示歌名\n"
        assert "这是第一句完整歌词=>这是第一句完整歌词是《显示歌名》的歌词" in (tmp_path / "lyrics.txt").read_text(encoding="utf-8")
    finally:
        engine.dispose()
