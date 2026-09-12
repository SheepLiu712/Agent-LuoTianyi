"""Business extraction acceptance at fetcher/task with offline HTTP and SDK seams."""
import asyncio
import json
import sys
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher
from src.world.get_new_songs.task import VCPediaNewSongTask
from src.utils.llm_service import LLMService

# A fresh interpreter observes startup file loading, without mutating shared rules
# or the repository resource. Only filesystem and HTTP boundaries are replaced.
RESOURCE_RUNNER = r'''
import json, sys
from pathlib import Path
from unittest.mock import patch
import requests
payload = json.loads(sys.stdin.read())
read_text = Path.read_text
reads = []
def read(path, *args, **kwargs):
    if path.name == 'vcpedia_templates.json':
        reads.append(str(path))
        return read_text(Path(payload['resource']), encoding='utf-8')
    return read_text(path, *args, **kwargs)
def get(self, url, **kwargs):
    response = requests.Response()
    response.status_code = 200
    from urllib.parse import parse_qs, urlsplit
    body = kwargs.get('data', b'')
    query = parse_qs(body.decode('utf-8') if isinstance(body, bytes) and body else body or urlsplit(url).query)
    prop = query['prop'][0]
    response._content = json.dumps({'parse': {prop: {'*': payload['source'] if prop == 'wikitext' else '<poem>外部歌词</poem>'}}}).encode()
    return response
with patch.object(Path, 'read_text', read), patch.object(requests.Session, 'get', get), patch.object(requests.Session, 'post', get):
    from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher
    for i in range(2):
        obj = VCPediaFetcher({'activated': True, 'use_llm': False, 'data_dir': payload['cache']})
        try:
            data = obj.fetch_entity_description('配置验收')
        finally:
            obj.session.close()
    print('RESULT=' + json.dumps({'data': data, 'reads': reads}, ensure_ascii=False))
'''


def resource_result(tmp_path, rules, source):
    import os
    import subprocess
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[2]), PYTHONIOENCODING='utf-8')
    resource = tmp_path / 'custom-templates.json'
    resource.write_text(json.dumps(rules, ensure_ascii=False), encoding='utf-8')
    return subprocess.run([sys.executable, '-c', RESOURCE_RUNNER], input=json.dumps({
        'resource': str(resource), 'source': source, 'cache': str(tmp_path / 'cache')}, ensure_ascii=False),
        text=True, encoding='utf-8', capture_output=True, cwd=tmp_path, env=env)


@pytest.fixture
def template_resource():
    return {'description': '临时验收规则，不写仓库', 'templates': [
        {'kind': 'inline', 'names': ['测试行内', '測試行內', 'TESTINLINE', 'testinline'], 'text_params': ['2']},
        {'kind': 'wrapper', 'names': ['测试容器'], 'body_params': ['payload']},
        {'kind': 'lyrics', 'names': ['测试歌词'], 'original_params': ['main'], 'translated_params': ['trans'],
         'original_prefix': 'left-', 'translated_prefix': 'right-'},
        {'kind': 'songbox', 'names': ['测试信息框'], 'contains': ['songbox'], 'body_params': ['简介', '歌词']},
        {'kind': 'staff', 'names': ['测试人员'], 'group_prefix': 'role', 'list_prefix': 'people', 'exclude_params': ['hide']},
        {'kind': 'embed', 'names': ['测试嵌入']}],
        'field_aliases': {'作者别名': 'UP主'}, 'known_fields': ['UP主', '作词'],
        'presentation_params': ['装饰'], 'presentation_contains': ['style'],
        'field_exclude_params': ['简介', '歌词', '视频'], 'role_priority': ['演唱', '作词']}


def test_template_resource_changes_inline_and_body_without_code(tmp_path, template_resource):
    source = '== 简介 ==\n{{测试容器|payload=前{{測試行內|忽略|正文}}后}}\n== 歌词 ==\n<poem>{{testinline|忽略|唱词}}</poem>'
    result = resource_result(tmp_path, template_resource, source)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout.split('RESULT=')[1])
    assert actual['data'] == {'name': '配置验收', 'type': 'Song', 'infobox': {},
        'summary': ['前正文后'], 'lyrics': '唱词', 'spaced_lyrics': '唱词', 'short_summary': '前正文后'}
    assert len(actual['reads']) == 1
    assert Path(actual['reads'][0]) == Path(__file__).resolve().parents[2] / 'config/vcpedia_templates.json'


def test_template_resource_controls_lyrics_fields_and_staff(tmp_path, template_resource):
    source = '{{测试信息框|作者别名=发布者|装饰=不要|customstyle=不要|简介=介绍}}'
    source += '{{测试人员|role1=作词|people1=甲|people1=乙|hide=不要}}\n== 歌词 ==\n'
    source += '{{测试歌词|main=备用|left-2=第二段|right-1=译文|left-1=第一段}}'
    result = resource_result(tmp_path, template_resource, source)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout.split('RESULT=')[1])['data']
    assert actual['infobox'] == {'UP主': '发布者', '作词': '乙'}
    assert actual['lyrics'] == '第一段\n\n第二段'
    assert actual['summary'] == ['介绍']


def test_template_resource_embed_uses_shared_descriptor(tmp_path, template_resource):
    result = resource_result(tmp_path, template_resource, '== 歌词 ==\n{{测试嵌入|page=歌词}}')
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout.split('RESULT=')[1])['data']['lyrics'] == '外部歌词'


@pytest.mark.parametrize('bad', ['kind', 'param', 'conflict', 'script'], ids=['unknown-kind', 'bad-param', 'alias-conflict', 'script'])
def test_template_resource_rejects_invalid_description(tmp_path, template_resource, bad):
    if bad == 'kind':
        template_resource['templates'][0]['kind'] = 'execute'
    elif bad == 'param':
        template_resource['templates'][0]['text_params'] = [2]
    elif bad == 'conflict':
        template_resource['templates'][1]['names'].append('測試行內')
    else:
        template_resource['templates'][0]['script'] = 'print(1)'
    result = resource_result(tmp_path, template_resource, '== 歌词 ==\n<poem>正文</poem>')
    assert result.returncode != 0
    assert 'ValueError' in result.stderr and 'vcpedia_templates.json' in result.stderr
    assert 'templates' in result.stderr


@pytest.mark.parametrize('body, expected', [
    ('{{黑幕|1=旧|1=新}}{{color|red|正文}}{{ruby| |唱}}{{lj|目标|}}', '新正文唱'),
    ('{{Utawari|2=二#12##|1=一|2=末}}{{multiline lyric|2=乙|1=甲}}', '二#\n一\n末乙\n甲'),
    ('{{Lyrics|original=备用|lb-text2=二|lb-text1=一|rb-text1=译}}', '一\n\n二'),
], ids=['last-param-and-empty', 'numeric-source-order', 'lyric-column-order'])
def test_default_template_resource_preserves_parameter_semantics(http, tmp_path, body, expected):
    http.source = '{{VOCALOID Songbox|简介=介绍|歌词=' + body + '}}'
    data = crawler(tmp_path, None, use_llm=False).fetch_entity_description('配置验收')
    assert data['lyrics'] == expected


def test_template_resource_tabs_prefixes_and_local_unknown_structure(tmp_path, template_resource):
    template_resource['templates'].append({'kind': 'tabs', 'names': ['测试页签'],
        'body_prefixes': ['payload'], 'label_prefixes': ['caption']})
    source = '== 简介 ==\n{{测试页签|caption1=显示|payload1=首正文|payload2=次正文}}\n'
    source += '== 歌词 ==\n{{完全未知|payload=<poem>明确歌词</poem>}}'
    result = resource_result(tmp_path, template_resource, source)
    assert result.returncode == 0, result.stderr
    actual = json.loads(result.stdout.split('RESULT=')[1])['data']
    assert actual['summary'] == ['首正文']
    assert actual['lyrics'] == '明确歌词'


BASE_SUMMARY_PROMPT = '\n'.join([
    '请基于以下歌曲数据 JSON 总结为不超过 120 字的中文简介，只保留三类信息：',
    '1. 发布者、UP 主、演唱者、作词作曲等核心制作信息；',
    '2. 歌曲意义，例如所属系列、重要演出或传播节点；',
    '3. 歌曲主题与大意。', '', '不要输出无关统计信息，不要编造。', '',
    '歌曲数据：', '{{ song_data }}', '', '请直接输出摘要正文。'])


RAW = '{{VOCALOID Songbox|演唱=洛天依|作词=词作者|UP主=}}\n投稿者：发布甲\n== 歌词 ==\n'
ANSWER = {"short_summary": "独立摘要", "infobox": {"UP主": "发布甲", "演唱": "越界歌手", "作词": None},
          "summary": ["完整介绍第一段。", "完整介绍第二段。"], "lyrics": "第一行（和声）\n\n第二行"}


class Model:
    def __init__(self, result=None):
        self.calls = []
        self.result = ANSWER if result is None else result

    async def generate_response(self, **kwargs):
        self.calls.append(kwargs)
        if isinstance(self.result, Exception):
            raise self.result
        if 'needed' not in kwargs and isinstance(self.result, dict):
            return self.result.get('short_summary', '')
        return json.dumps(self.result, ensure_ascii=False) if isinstance(self.result, dict) else self.result


@pytest.fixture
def http(monkeypatch):
    state = SimpleNamespace(source=RAW, calls=[], html="", fail_render=False)
    def get(self, url, **kwargs):
        body = kwargs.get('data', b'')
        query = parse_qs(body.decode('utf-8') if isinstance(body, bytes) and body else body or urlsplit(url).query)
        state.calls.append(query)
        key = query["prop"][0]
        if key == "text" and state.fail_render:
            raise requests.Timeout("offline")
        result = requests.Response()
        result.status_code = 200
        result.encoding = "utf-8"
        result._content = json.dumps({"parse": {"title": "星空", "pageid": 42, "revid": 7,
            key: {"*": state.source if key == "wikitext" else state.html}}}, ensure_ascii=False).encode()
        return result
    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setattr(requests.Session, "post", get)
    return state


def crawler(tmp_path, model, **kwargs):
    return VCPediaFetcher({"activated": True, "use_llm": True,
        "data_dir": str(tmp_path / "cache"), "vcpedia": {"output_dir": str(tmp_path / "cache")},
        **kwargs}, llm_module=model, extraction_llm_module=model)


@pytest.mark.parametrize("slot", ["infobox", "summary", "lyrics", "poem"])
def test_text_conversion_nowiki_is_literal_in_every_field(http, tmp_path, slot):
    literal = "  繁體-{臺灣}-{{color|red|夢}}{{TextHover|繁體|替代|after|pic}}[[龍頁|龍]]\n 第二行  "
    value = "外側繁體<nowiki>" + literal + "</nowiki>結尾"
    slots = {"infobox": "演唱", "summary": "简介", "lyrics": "歌词"}
    if slot == "poem":
        http.source = '== 歌词 ==\n<poem><nowiki>' + literal + '</nowiki></poem>'
    else:
        http.source = '{{VOCALOID Songbox|' + slots[slot] + '=' + value + '}}'
    data = crawler(tmp_path, None, use_llm=False).fetch_entity_description("夢與樂")
    actual = data["infobox"]["演唱"] if slot == "infobox" else data["summary"][0] if slot == "summary" else data["lyrics"]
    assert actual == (literal if slot == "poem" else "外侧繁体" + literal + "结尾")
    if slot in {"lyrics", "poem"}:
        assert data["spaced_lyrics"] == actual
    assert data["name"] == "夢與樂"


def test_text_conversion_plain_fields_and_lc_fallback(http, tmp_path):
    http.source = '{{VOCALOID Songbox|演唱=樂師|简介=繁體-{臺灣}-介紹|歌词=夢裡，-{樂聲}-}}'
    data = crawler(tmp_path, None, use_llm=False).fetch_entity_description("夢與樂", source_title="龍頁")
    assert data == {"name": "夢與樂", "type": "Song", "infobox": {"演唱": "乐师"},
        "summary": ["繁体臺灣介绍"], "lyrics": "梦里，樂聲", "spaced_lyrics": "梦里\n樂聲",
        "short_summary": "繁体臺灣介绍"}
    assert http.calls[0]["page"] == ["龍頁"]


def test_material_is_normalized_and_model_answer_stored_verbatim(http, tmp_path):
    http.source = '{{VOCALOID Songbox|演唱=-{樂師}-|UP主=|简介=繁體-{臺灣}-介紹|歌词=}}'
    model = Model({"infobox": {"UP主": "龙臺夢灣"}, "lyrics": "繁体乐声夢，\n龍"})
    data = crawler(tmp_path, model).fetch_entity_description("夢與樂")
    # 本地路径：LC 保护字形保持原文用字，其余转 zh-cn
    assert data["infobox"]["演唱"] == "樂師"
    # 材料已由程序规范化，模型答案即最终用字，合并时不再转换
    assert data["infobox"]["UP主"] == "龙臺夢灣"
    assert data["lyrics"] == "繁体乐声夢，\n龍"
    assert data["spaced_lyrics"] == "繁体乐声夢\n龍"     # spaced 形式按标点断行
    assert data["short_summary"] == "繁体臺灣介绍"
    material = json.loads(model.calls[0]["materials"])["text"]
    # 材料已做一次字形转换：LC 覆盖的字形定稿、标记已去，其余已转 zh-cn
    assert "简介=繁体臺灣介绍" in material
    assert "-{" not in material and "nowiki" not in material.lower()


@pytest.mark.parametrize("response", ["繁體-{臺灣}-<nowiki>{{夢}}[[龍]]</nowiki>", TimeoutError("offline")], ids=["model", "fallback"])
def test_text_conversion_summary_model_or_error(http, tmp_path, response):
    http.source = '{{VOCALOID Songbox|简介=繁體-{臺灣}-<nowiki>{{夢}}[[龍]]</nowiki>|歌词=夢}}'
    obj = crawler(tmp_path, None)
    obj.llm_module = Model(response)
    data = obj.fetch_entity_description("夢")
    assert data["short_summary"] == "繁体臺灣{{夢}}[[龍]]"


def test_text_conversion_lc_executes_markup_but_preserves_visible_glyphs(http, tmp_path):
    http.source = '{{VOCALOID Songbox|演唱=-{[[雲宇光]]}-|简介=外側-{四方<br/>內域}-|歌词=-{{{color|red|夢}}{{ruby|體|ti}}}-}}'
    data = crawler(tmp_path, None, use_llm=False).fetch_entity_description("夢")
    assert data["infobox"] == {"演唱": "雲宇光"}
    assert data["summary"] == ["外侧四方內域"]
    assert data["lyrics"] == data["spaced_lyrics"] == "夢體"


def test_text_conversion_rendered_fragment_keeps_site_glyphs(http, tmp_path):
    http.source = '== 歌詞 ==\n{{Embed|page=龍/歌词}}'
    http.html = '<poem>繁體-{臺灣}-{{夢}}[[龍]]</poem>'
    data = crawler(tmp_path, None, use_llm=False).fetch_entity_description("夢")
    assert data["lyrics"] == "繁體-{臺灣}-{{夢}}[[龍]]"


def test_structural_normalization_requested_keys_and_material_converted(http, tmp_path):
    http.source = '{{VOCALOID Songbox|作詞=|異體欄=|演唱=樂師|UP主=龍作者|简介=繁體介紹|歌词=夢裡的聲音}}'
    # 材料已转 zh-cn，模型照抄材料因此返回简体值
    model = Model({"infobox": {"作詞": "词师", "異體欄": "原样"}})
    data = crawler(tmp_path, model).fetch_entity_description("夢與樂")
    payload = {"needed": json.loads(model.calls[0]["needed"]), "materials": json.loads(model.calls[0]["materials"]), "existing": json.loads(model.calls[0]["song_data"])}
    assert payload["needed"]["infobox"] == ["作词", "異體欄"]
    material = payload["materials"]["text"]
    assert "简介=繁体介绍" in material                 # 材料已做一次字形转换
    assert "{{VOCALOID Songbox|" in material           # 原有标记保留，是否照抄由提示词约束
    assert "-{" not in material                        # 字形标记随转换去除
    assert data["infobox"] == {"演唱": "乐师", "UP主": "龙作者", "作词": "词师", "異體欄": "原样"}


def test_structural_normalization_embed_heading_preserves_call(http, tmp_path):
    call = '{{嵌入片段|page=夢與樂/原文|field=original}}'
    http.source = '== 歌詞 ==\n' + call
    http.html = '<poem>夢裡聽見樂聲</poem>'
    data = crawler(tmp_path, None, use_llm=False).fetch_entity_description("夢與樂")
    assert data["lyrics"] == "夢裡聽見樂聲"
    assert http.calls[1]["text"] == [call]


def test_business_json_merges_requested_fields_without_semantic_grading(http, tmp_path):
    model = Model()
    data = crawler(tmp_path, model).fetch_entity_description("星空")
    assert data["infobox"] == {"演唱": "洛天依", "作词": "词作者", "UP主": "发布甲"}
    assert data["summary"] == ANSWER["summary"]
    assert data["lyrics"] == ANSWER["lyrics"]
    payload = {"needed": json.loads(model.calls[0]["needed"]), "materials": json.loads(model.calls[0]["materials"]), "existing": json.loads(model.calls[0]["song_data"])}
    assert payload["needed"] == {"infobox": ["UP主"], "summary": True, "lyrics": True}
    assert payload["existing"]["infobox"]["作词"] == "词作者"
    assert len(model.calls) == 2
    assert data["short_summary"] == ANSWER["short_summary"]


@pytest.mark.parametrize("response", ["bad JSON", "[]", TimeoutError("offline"), "x" * 24001, "", "null"],
                         ids=["malformed", "array", "timeout", "oversized", "empty", "null"])
def test_bad_response_preserves_rules(http, tmp_path, response):
    model = Model(response)
    data = crawler(tmp_path, model).fetch_entity_description("星空")
    assert data["infobox"]["演唱"] == "洛天依"
    assert not data["lyrics"]
    assert len(model.calls) == 2


@pytest.mark.parametrize("bad", [12, [], {}, True])
def test_invalid_field_type_does_not_discard_valid_other_fields(http, tmp_path, bad):
    model = Model({"infobox": {"UP主": "发布甲"}, "summary": bad, "lyrics": bad})
    data = crawler(tmp_path, model).fetch_entity_description("星空")
    assert data["infobox"]["UP主"] == "发布甲"
    assert not data["lyrics"] and not any(data["summary"])


def test_null_does_not_clear_values(http, tmp_path):
    model = Model({"infobox": {"演唱": None, "UP主": None}, "summary": None, "lyrics": None})
    data = crawler(tmp_path, model).fetch_entity_description("星空")
    assert data["infobox"]["演唱"] == "洛天依"
    assert not data["lyrics"]
    assert len(model.calls) == 2


@pytest.mark.parametrize("template", ["{{未知|id=1}}", "{{info|id=1}}", "{{TocHide}}", "{{Embed}}"])
def test_complete_page_still_summarizes_once_without_render_or_missing_materials(http, tmp_path, template):
    http.source = '{{VOCALOID Songbox|演唱=洛天依|UP主=发布甲}}\n== 简介 ==\n完整简介\n== 歌词 ==\n<poem>完整歌词</poem>\n' + template
    model = Model()
    data = crawler(tmp_path, model).fetch_entity_description("星空")
    assert data["lyrics"] == "完整歌词"
    assert len(model.calls) == 1 and len(http.calls) == 1
    assert set(model.calls[0]) == {"song_data"}
    assert data["short_summary"] == ANSWER["short_summary"]


def test_generic_structure_walk_fills_lyrics_then_summarizes_once_without_render(http, tmp_path):
    http.source = '{{VOCALOID Songbox|演唱=甲|简介=完整简介}}\n== 歌词 ==\n'
    http.source += '{{Panel93|mode=控制|payload={{Inner57|value=<poem>原文-{繁體}-</poem>}}}}'
    model = Model()
    obj = crawler(tmp_path, model)
    try:
        data = obj.fetch_entity_description('任意标题')
    finally:
        obj.session.close()
    assert data['lyrics'] == '原文繁體'
    assert len(model.calls) == 1 and len(http.calls) == 1
    assert set(model.calls[0]) == {"song_data"}
    assert data["short_summary"] == ANSWER["short_summary"]


def test_unknown_templates_do_not_render_even_when_fields_missing(http, tmp_path):
    http.source = '{{未知|id=1}}{{info|id=2}}{{TocHide}}{{Embed}}'
    model = Model({})
    crawler(tmp_path, model).fetch_entity_description("星空")
    # Unknown-only material has no confirmed business carrier: no supplementation.
    assert len(http.calls) == 1 and not model.calls


def test_only_two_target_embeds_render_and_rules_avoid_model(http, tmp_path):
    first = '{{Embed|page=星空/歌词|版本={{Embed|page=星空/歌词}}}}'
    second = '{{CollectCodeData|page=星空|field=lyrics}}'
    http.source = '{{info|id=1}}\n== 歌词 ==\n' + first + first + second + '{{Embed|page=星空/歌词3}}'
    http.html = '<nav>导航噪声</nav><p>完整歌词（和声）</p>'
    model = Model({"lyrics": "完整歌词（和声）"})
    crawler(tmp_path, model).fetch_entity_description("星空")
    renders = [q for q in http.calls if q["prop"] == ["text"]]
    assert len(renders) == 2
    if renders:
        assert renders[0]["text"] == [first]
    for query in renders:
        assert query["title"] == ["星空"] and "page" not in query
        assert query["contentmodel"] == ["wikitext"]
    assert len(model.calls) == 1


def test_oversized_complete_embed_never_renders_truncated_invocation(http, tmp_path):
    http.source = '== 歌词 ==\n{{Embed|page=星空/歌词|text=' + '长' * 25000 + '}}'
    crawler(tmp_path, Model({})).fetch_entity_description("星空")
    assert len(http.calls) == 1


def test_unrelated_embed_is_not_rendered(http, tmp_path):
    http.source = '{{Embed|page=导航/公告}}\n' + RAW
    model = Model({})
    crawler(tmp_path, model).fetch_entity_description("星空")
    assert len(http.calls) == 1


def test_render_failure_still_extracts_then_summarizes(http, tmp_path):
    http.source = '== 歌词 ==\n{{Embed|page=星空/歌词}}'
    http.fail_render = True
    model = Model({})
    data = crawler(tmp_path, model).fetch_entity_description("星空")
    assert not data["lyrics"] and len(model.calls) == 2


def test_disabled_llm_keeps_rules_and_empty_field_discards_nothing(http, tmp_path):
    http.source = ('{{VOCALOID Songbox|歌曲名称=测试曲|演唱=|P主=甲}}\n'
                   '== 简介 ==\n简介。\n== 歌词 ==\n<poem>歌词</poem>')
    model = Model()
    data = crawler(tmp_path, model, use_llm=False).fetch_entity_description("星空")
    assert data["infobox"] == {"歌曲名称": "测试曲", "P主": "甲"}
    assert data["summary"] == ["简介。"]
    assert data["lyrics"] == "歌词"
    assert not model.calls


def test_disabled_llm_still_resolves_required_lyric_embed(http, tmp_path):
    http.source = '== 歌词 ==\n{{Embed|page=星空/歌词}}'
    http.html = '<poem>完整第一行（和声）\n完整第二行</poem>'
    model = Model()
    data = crawler(tmp_path, model, use_llm=False).fetch_entity_description("星空")
    assert data["lyrics"] == "完整第一行（和声）\n完整第二行"
    assert len(http.calls) == 2
    assert not model.calls


def test_rendered_fragment_is_never_passed_to_the_model_as_material(http, tmp_path):
    """A rendered fragment is merged locally; the model only ever receives raw source."""
    http.source = ('{{VOCALOID Songbox|歌曲名称=测试曲|演唱=|UP主=甲}}\n'
                   '== 歌词 ==\n{{Embed|page=星空/歌词}}')
    http.html = '<poem>完整第一行（和声）\n完整第二行</poem>'
    model = Model()
    data = crawler(tmp_path, model).fetch_entity_description("星空")
    assert data["lyrics"] == "完整第一行（和声）\n完整第二行"
    assert json.loads(model.calls[0]["needed"])["lyrics"] is False
    assert set(json.loads(model.calls[0]["materials"])) == {"text"}


@pytest.mark.parametrize("songbox,kept", [
    ('{{VOCALOID Songbox|歌曲名称=测试曲|演唱=|UP主=甲|再生={{bilibiliCount|id=av1}}'
     '|其他资料=2012年12月19日投稿原版，再生数为{{bilibiliCount|id=av1}}}}', "|UP主=甲"),
    ('{{VOCALOID Songbox\n|歌曲名称 = 测试曲\n|演唱 = \n|UP主 = 甲\n'
     '|再生 = {{bilibiliCount|id=av1}}\n'
     '|其他资料 = 2012年12月19日投稿原版，再生数为{{bilibiliCount|id=av1}}\n}}', "|UP主 = 甲"),
    # The real shape: a tabs wrapper whose parameter value spans many lines.
    ('{{tabs/core\n|label1 = 原版\n|text1 =\n{{VOCALOID Songbox\n|歌曲名称 = 测试曲\n|演唱 = \n'
     '|UP主 = 甲\n|再生 = {{bilibiliCount|id=av1}}\n'
     '|其他资料 = 2012年12月19日投稿原版，再生数为{{bilibiliCount|id=av1}}\n}}\n}}', "|UP主 = 甲")])
def test_material_drops_statistics_the_program_cannot_expand(http, tmp_path, songbox, kept):
    """Unresolvable counts leave the material: whole sentence in prose, counted clause in params."""
    http.source = (songbox + '\n'
                   '== 简介 ==\n'
                   "《'''测试曲'''》是[[甲]]于2012年12月19日投稿的歌曲。"
                   '[[VOCALOID中文殿堂曲|殿堂曲]]，截至现在已有{{bilibiliCount|id=av1}}次观看，'
                   '{{bilibiliCount|id=av1|type=4}}人收藏。\n'
                   '{{黑幕|隐藏说明}}\n'
                   '== 歌词 ==\n<poem>第一行\n第二行</poem>')
    model = Model({"infobox": {"UP主": "甲"}})
    crawler(tmp_path, model).fetch_entity_description("测试曲")
    material = json.loads(model.calls[0]["materials"])["text"]
    assert "《'''测试曲'''》是[[甲]]于2012年12月19日投稿的歌曲。" in material
    assert "殿堂曲" not in material
    assert "次观看" not in material and "人收藏" not in material and "bilibiliCount" not in material
    assert kept in material
    assert "2012年12月19日投稿原版" in material
    assert "{{黑幕|隐藏说明}}" in material
    assert "<poem>第一行\n第二行</poem>" in material


def test_public_input_and_response_budgets(http, tmp_path):
    # A definite unresolved lyric carrier, rather than arbitrary long prose.
    http.source = '== 歌词 ==\n{{LyricsKai|original={{待解析歌词|text=' + '原文' * 20000 + '}}}}'
    model = Model({})
    data = crawler(tmp_path, model, private_secret="DO_NOT_SEND").fetch_entity_description("星空")
    payload = {"needed": json.loads(model.calls[0]["needed"]), "materials": json.loads(model.calls[0]["materials"]), "existing": json.loads(model.calls[0]["song_data"])}
    assert len(payload["materials"]["text"]) == 24000
    assert "DO_NOT_SEND" not in json.dumps(model.calls[0])


@pytest.mark.asyncio
async def test_fetcher_inside_running_loop(http, tmp_path):
    data = crawler(tmp_path, Model()).fetch_entity_description("星空")
    assert data["infobox"]["UP主"] == "发布甲"


def test_original_summary_trigger_uses_plain_text_without_new_timeout(http, tmp_path):
    http.source = '== 简介 ==\n原介绍\n== 歌词 ==\n<poem>原歌词</poem>'
    class Summary(Model):
        async def generate_response(self, **kwargs):
            self.calls.append(kwargs)
            await asyncio.sleep(1.2)
            return "旧摘要正常完成"
    summary = Summary()
    obj = crawler(tmp_path, None)
    obj.llm_module = summary
    assert obj.fetch_entity_description("星空")["short_summary"] == "旧摘要正常完成"
    assert set(summary.calls[0]) == {"song_data"}


@pytest.mark.parametrize("use_json", [False, True], ids=["text-config", "json-config"])
@pytest.mark.parametrize("delegate_available", [True, False], ids=["client", "fallback"])
@pytest.mark.asyncio
async def test_task_preserves_independent_module_delegation_and_source_config(use_json, delegate_available):
    from copy import deepcopy

    class Provider:
        default_parameters = {}

        def __init__(self, name):
            self.name = name
            self.calls = []

        def get_interface_info(self):
            return {"type": "offline", "model": self.name}

        async def generate_response(self, prompt, **kwargs):
            self.calls.append((prompt, deepcopy(kwargs)))
            return {"content": self.name, "usage": {}}

    class Executor:
        def __init__(self):
            self.calls = []

        async def delegate(self, user_id, **kwargs):
            self.calls.append((user_id, deepcopy(kwargs)))
            return {"content": "client-answer", "usage": {}} if delegate_available else None

    def module_config(name, client_type, temperature):
        return {"prompt_name": "song_knowledge_crawler_prompt", "llm": {
            "name": name, "client_model_type": client_type,
            "use_json": use_json, "enable_thinking": True,
            "params": {"temperature": temperature, "max_tokens": 4321, "timeout": 17,
                       "tools": [{"type": "function"}], "tool_choice": "auto",
                       "functions": [{"name": "original"}], "function_call": "auto"}}}

    cfg = {"crawler": {"use_llm": True,
                       "llm_module": module_config("summary-provider", "summary-client", 0.7)}}
    cfg['crawler']['extraction_llm_module'] = module_config('extract-provider', 'extract-client', 0.2)
    cfg['crawler']['extraction_llm_module']['prompt_name'] = 'song_knowledge_extraction_prompt'
    cfg['crawler']['extraction_llm_module']['llm']['use_json'] = True
    original = deepcopy(cfg)
    selected = original["crawler"]["llm_module"]["llm"]
    executor = Executor()
    service = LLMService({"prompt_manager": {"template_dir": "res/agent/prompts"}}, client_llm_executor=executor)
    providers = {name: Provider(name) for name in ("summary-provider", "extract-provider")}
    service.llm_interfaces.update(providers)
    task = VCPediaNewSongTask(cfg)
    task.initialize(SimpleNamespace(llm_service=service))

    result = await task.llm_module.generate_response(song_data='{}', needed='{"lyrics": true}', materials='{"raw": "原材料"}')
    # Observe the actual external delegation seam, not only the registered dict.
    assert executor.calls, "task cleared client_model_type and bypassed delegation"
    delegated = executor.calls[0][1]
    assert delegated["model_type"] == selected["client_model_type"]
    assert delegated["module"] == "song_knowledge_crawler"
    assert delegated["model_kind"] == "llm"
    assert delegated["use_json"] is use_json and delegated["enable_thinking"] is True
    expected_params = selected["params"]
    assert delegated["params"] == expected_params
    assert result == ("client-answer" if delegate_available else selected["name"])
    assert len(providers[selected["name"]].calls) == (0 if delegate_available else 1)
    if not delegate_available:
        assert providers[selected["name"]].calls[0][1] == {
            "params": expected_params, "use_json": use_json, "enable_thinking": True}
    assert task.llm_module.prompt_template.name == "song_knowledge_crawler_prompt"
    extraction_result = await task.extraction_llm_module.generate_response(
        song_data='{}', needed='{"lyrics": true}', materials='{"raw": "原材料"}')
    extra = executor.calls[-1][1]
    extraction_cfg = original['crawler']['extraction_llm_module']['llm']
    assert extra['module'] == 'song_knowledge_extractor'
    assert extra['model_type'] == 'extract-client'
    assert extra['params'] == extraction_cfg['params']
    assert extra['use_json'] is True and extra['enable_thinking'] is True
    assert extraction_result == ('client-answer' if delegate_available else 'extract-provider')
    assert len(providers['extract-provider'].calls) == (0 if delegate_available else 1)
    if not delegate_available:
        assert providers['extract-provider'].calls[0][1] == {
            'params': extraction_cfg['params'], 'use_json': True, 'enable_thinking': True}
    assert set(service.llm_modules) == {"song_knowledge_crawler", "song_knowledge_extractor"}
    assert cfg == original


@pytest.mark.parametrize("complete", [False, True], ids=["missing", "full"])
@pytest.mark.parametrize("extraction", [False, True], ids=["summary-only", "two-configs"])
def test_task_real_registration_uses_independent_prompts_and_settings(http, tmp_path, complete, extraction):
    from copy import deepcopy
    from src.utils.llm.llm_api_interface import OpenAIAPIInterface
    if complete:
        http.source = '{{VOCALOID Songbox|演唱=甲|简介=原简介|歌词=原歌词}}'
    calls = []
    service = LLMService({"prompt_manager": {"template_dir": "res/agent/prompts"}})
    def provider(name, answer):
        def create(**kwargs):
            calls.append((name, kwargs))
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))], usage=None)
        interface = OpenAIAPIInterface({"api_key": "", "max_retries": 1,
            "can_use_json": True, "can_enable_thinking": True})
        interface.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        service.llm_interfaces[name] = interface
    provider('summary', '独立摘要')
    provider('extract', json.dumps(ANSWER, ensure_ascii=False))
    cfg = {"crawler": {"use_llm": True, "llm_module": {"llm": {
        "name": "summary", "enable_thinking": True, "use_json": False,
        "params": {"max_tokens": 5000, "temperature": 0.7}},
        "prompt_name": "song_knowledge_crawler_prompt"}}}
    if extraction:
        cfg['crawler']['extraction_llm_module'] = {"llm": {
            "name": "extract", "enable_thinking": False, "use_json": True,
            "params": {"max_tokens": 3000, "temperature": 0.2}},
            "prompt_name": "song_knowledge_extraction_prompt"}
    original = deepcopy(cfg)
    task = VCPediaNewSongTask(cfg)
    task.initialize(SimpleNamespace(llm_service=service))
    template = task.llm_module.prompt_template
    assert template.get_variables() == ['song_data']
    with pytest.raises(ValueError, match='song_data'):
        template.render()
    assert template.render(song_data='{}') == BASE_SUMMARY_PROMPT.replace('{{ song_data }}', '{}')
    obj = VCPediaFetcher({'activated': True, 'use_llm': True, 'data_dir': str(tmp_path / 'cache')},
        llm_module=task.llm_module, extraction_llm_module=task.extraction_llm_module)
    try:
        data = obj.fetch_entity_description('星空')
    finally:
        obj.session.close()
    assert cfg == original
    assert [name for name, _ in calls] == (['extract', 'summary'] if extraction and not complete else ['summary'])
    summary = calls[-1][1]
    assert summary['max_tokens'] == 5000 and summary['temperature'] == 0.7
    assert summary.get('response_format') is None and summary.get('timeout') is None
    assert summary['extra_body'] == {'enable_thinking': True}
    prompt = summary['messages'][0]['content']
    song_data = json.dumps({k: v for k, v in data.items() if k != 'short_summary'}, ensure_ascii=False)
    assert prompt == BASE_SUMMARY_PROMPT.replace('{{ song_data }}', song_data)
    for token in ('needed', 'materials', '示例', '补提', 'task_block', 'request_json'):
        assert token not in prompt
    assert data['short_summary'] == '独立摘要'
    if extraction and not complete:
        assert data['infobox']['UP主'] == '发布甲' and data['lyrics'] == ANSWER['lyrics']
        request = calls[0][1]
        assert request['max_tokens'] == 3000 and request['temperature'] == 0.2
        assert request['response_format'] == {'type': 'json_object'}
        assert request['extra_body'] == {'enable_thinking': False}
        extra_prompt = request['messages'][0]['content']
        assert 'short_summary' not in extra_prompt and '材料不足' in extra_prompt
        objects = [json.loads(line) for line in extra_prompt.splitlines() if line.startswith('{')]
        assert {'infobox': ['UP主'], 'summary': True, 'lyrics': True} in objects
        materials_object = next(obj for obj in objects if "text" in obj)
        assert materials_object["text"] and "歌词" in materials_object["text"]
        assert any(obj.get('lyrics', 'absent') is None for obj in objects)
    assert set(service.llm_modules) == ({'song_knowledge_crawler', 'song_knowledge_extractor'} if extraction else {'song_knowledge_crawler'})


def test_task_run_once_business_json_reaches_database_and_keywords(http, tmp_path, monkeypatch):
    from src.utils.llm.llm_api_interface import OpenAIAPIInterface
    from src.world.get_new_songs import daily_new_song_fetcher as daily
    import src.subconscious.music_knowledge.song_database as database
    from sqlalchemy.orm import Session
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        content = json.dumps(ANSWER, ensure_ascii=False) if '本次缺项 needed' in kwargs['messages'][0]['content'] else ANSWER['short_summary']
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))], usage=None)
    interface = OpenAIAPIInterface({"api_key": "", "max_retries": 1})
    interface.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    service = LLMService({"prompt_manager": {"template_dir": "res/agent/prompts"}})
    service.llm_interfaces["fake"] = interface
    original_get = requests.Session.get
    def get(self, url, **kwargs):
        if "page=Template" in url:
            result = requests.Response()
            result.status_code = 200
            result._content = json.dumps({"parse": {"wikitext": {"*": "[[星空]]"}}}).encode()
            return result
        return original_get(self, url, **kwargs)
    monkeypatch.setattr(requests.Session, "get", get)
    monkeypatch.setattr(requests, "get", lambda url, **kw: requests.Session().get(url, **kw))
    monkeypatch.setattr(database, "engine", None)
    monkeypatch.setattr(database, "SessionLocal", None)
    monkeypatch.setattr(daily, "KNOWLEDGE_DIR", tmp_path)
    monkeypatch.setattr(daily, "SONG_NAME_KEYWORDS_FILE", tmp_path / "names.txt")
    monkeypatch.setattr(daily, "SONG_LYRIC_KEYWORDS_FILE", tmp_path / "lyrics.txt")
    task = VCPediaNewSongTask({
        "song_database": {"db_folder": str(tmp_path), "db_file": "songs.db"},
        "crawler": {"activated": True, "use_llm": True, "data_dir": str(tmp_path / "cache"),
                    "vcpedia": {"output_dir": str(tmp_path / "cache")},
                    "llm_module": {"llm": {"name": "fake"}, "prompt_name": "song_knowledge_crawler_prompt"},
                    "extraction_llm_module": {"llm": {"name": "fake", "use_json": True}, "prompt_name": "song_knowledge_extraction_prompt"}}})
    task.initialize(SimpleNamespace(llm_service=service))
    try:
        result = task.run_once()
        assert result.ok and result.data["added"] == ["星空"]
        with Session(database.engine) as db:
            song = db.query(database.Song).one()
            assert song.singers == "洛天依" and song.uploader == "发布甲"
            assert song.lyrics == ANSWER["lyrics"]
            assert song.introduction == ANSWER["short_summary"]
        assert "第一行（和声）=>" in (tmp_path / "lyrics.txt").read_text(encoding="utf-8")
        assert len(calls) == 2
    finally:
        if database.engine is not None:
            database.engine.dispose()


@pytest.mark.parametrize("short_summary", [True, False])
def test_complete_page_never_overwrites_fields_and_preserves_summary_trigger(http, tmp_path, short_summary):
    http.source = '{{VOCALOID Songbox|演唱=甲|简介=原简介|歌词=原歌词}}'
    model = Model({"short_summary": "新-{臺灣}-<nowiki>{{夢}}</nowiki>",
                   "infobox": {"演唱": "越界"}, "summary": ["越界"], "lyrics": "越界"})
    data = crawler(tmp_path, model).fetch_entity_description("星空", short_summary=short_summary)
    assert data["infobox"] == {"演唱": "甲"}
    assert data["summary"] == ["原简介"] and data["lyrics"] == "原歌词"
    assert data["short_summary"] == "新臺灣{{夢}}"
    assert len(model.calls) == 1 and set(model.calls[0]) == {"song_data"}


def test_cache_hit_returns_original_payload_without_http_or_model(http, tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    expected = {"name": "星空", "type": "Song", "summary": ["繁體"], "short_summary": "原摘要"}
    (cache / "星空.json").write_text(json.dumps(expected), encoding="utf-8")
    model = Model()
    assert crawler(tmp_path, model).fetch_entity_description("星空") == expected
    assert not model.calls and not http.calls


def test_person_missing_existing_field_is_supplemented_without_summary_or_reclassification(http, tmp_path):
    http.source = '{{VOCALOID Songbox|演唱=|简介=人物正文}}'
    model = Model({"infobox": {"演唱": "甲"}, "short_summary": "不添加人物摘要"})
    data = crawler(tmp_path, model).fetch_entity_description("人物")
    assert data["type"] == "Person" and "short_summary" not in data
    assert data["infobox"] == {"演唱": "甲"}
    assert len(model.calls) == 1


def test_person_without_missing_fields_never_summarizes(http, tmp_path):
    http.source = '== 简介 ==\n人物正文'
    model = Model()
    data = crawler(tmp_path, model).fetch_entity_description("人物")
    assert data["type"] == "Person" and "short_summary" not in data
    assert not model.calls


def test_missing_module_keeps_song_fallback_without_second_conversion(http, tmp_path):
    http.source = '{{VOCALOID Songbox|简介=-{臺灣}-|歌词=}}'
    data = crawler(tmp_path, None).fetch_entity_description("星空")
    assert data["short_summary"] == "臺灣"


@pytest.mark.parametrize("value", [None, "", [], 12])
def test_invalid_short_summary_uses_first_100_completed_characters(http, tmp_path, value):
    http.source = '{{VOCALOID Songbox|简介=-{臺灣}-' + '介' * 120 + '|歌词=原歌词}}'
    model = Model({"short_summary": value, "summary": ["不覆盖"]})
    data = crawler(tmp_path, model).fetch_entity_description("星空")
    assert data["short_summary"] == "臺灣" + "介" * 98
    assert data["summary"] == ["臺灣" + "介" * 120]
    assert len(model.calls) == 1


@pytest.mark.parametrize('response', ['新-{臺灣}-摘要'])
def test_complete_page_accepts_plain_summary_string(http, tmp_path, response):
    http.source = '{{VOCALOID Songbox|简介=原简介|歌词=原歌词}}'
    model = Model(response)
    data = crawler(tmp_path, model).fetch_entity_description('星空')
    assert data['short_summary'] == '新臺灣摘要'
    assert len(model.calls) == 1


def test_unconfigured_supplement_registers_only_crawler(http, tmp_path, monkeypatch):
    import builtins
    from src.utils.llm.llm_api_interface import OpenAIAPIInterface
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    root = Path('res/agent/prompts')
    (prompts / 'song_knowledge_crawler_prompt.json').write_bytes((root / 'song_knowledge_crawler_prompt.json').read_bytes())
    service = LLMService({'prompt_manager': {'template_dir': str(prompts)}})
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content='正常摘要'))], usage=None)
    interface = OpenAIAPIInterface({'api_key': '', 'max_retries': 1})
    interface.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    service.llm_interfaces['fake'] = interface
    cfg = {'crawler': {'use_llm': True, 'llm_module': {'llm': {'name': 'fake'},
        'prompt_name': 'song_knowledge_crawler_prompt'}}}
    reads = []
    original_open = builtins.open
    def open_file(file, *args, **kwargs):
        if 'extraction_prompt' in str(file) or 'missing_fields' in str(file):
            reads.append(str(file))
            raise OSError('supplement resource unavailable')
        return original_open(file, *args, **kwargs)
    monkeypatch.setattr(builtins, 'open', open_file)
    task = VCPediaNewSongTask(cfg)
    task.initialize(SimpleNamespace(llm_service=service))
    obj = VCPediaFetcher({'activated': True, 'use_llm': True, 'data_dir': str(tmp_path / 'cache')},
        llm_module=task.llm_module, extraction_llm_module=task.extraction_llm_module)
    try:
        data = obj.fetch_entity_description('星空')
    finally:
        obj.session.close()
    assert data['short_summary'] == '正常摘要' and len(calls) == 1
    assert set(service.llm_modules) == {'song_knowledge_crawler'}
    assert task.extraction_llm_module is None
    assert not reads


def test_configured_supplement_without_prompt_fails_initialization(tmp_path):
    """Configured supplement needs a loadable prompt; its absence fails, never degrades."""
    from src.utils.llm.llm_api_interface import OpenAIAPIInterface
    prompts = tmp_path / 'prompts'
    prompts.mkdir()
    root = Path('res/agent/prompts')
    (prompts / 'song_knowledge_crawler_prompt.json').write_bytes((root / 'song_knowledge_crawler_prompt.json').read_bytes())
    service = LLMService({'prompt_manager': {'template_dir': str(prompts)}})
    service.llm_interfaces['fake'] = OpenAIAPIInterface({'api_key': '', 'max_retries': 1})
    cfg = {'crawler': {'use_llm': True,
        'llm_module': {'llm': {'name': 'fake'}, 'prompt_name': 'song_knowledge_crawler_prompt'},
        'extraction_llm_module': {'llm': {'name': 'fake', 'use_json': True},
            'prompt_name': 'song_knowledge_extraction_prompt'}}}
    task = VCPediaNewSongTask(cfg)
    with pytest.raises(ValueError, match='song_knowledge_extraction_prompt'):
        task.initialize(SimpleNamespace(llm_service=service))


def test_bad_missing_json_does_not_prevent_independent_summary(http, tmp_path):
    http.source = '{{VOCALOID Songbox|简介=-{臺灣}-' + '介' * 120 + '|歌词=}}'
    model = Model('不是JSON')
    data = crawler(tmp_path, model).fetch_entity_description('星空')
    assert data['short_summary'] == '不是JSON'
    assert data['lyrics'] == '' and len(model.calls) == 2


def test_json_object_response_merges_before_independent_summary(http, tmp_path):
    class ObjectModel(Model):
        async def generate_response(self, **kwargs):
            self.calls.append(kwargs)
            return ANSWER if 'needed' in kwargs else ANSWER['short_summary']
    model = ObjectModel()
    data = crawler(tmp_path, model).fetch_entity_description("星空")
    assert data["infobox"]["UP主"] == "发布甲"
    assert data["short_summary"] == ANSWER["short_summary"]
    assert len(model.calls) == 2


@pytest.mark.parametrize('failure', ['bad-json', 'null', 'timeout', 'summary-timeout', 'closed', 'cached'])
def test_task_real_service_failure_boundaries_and_zero_calls(http, tmp_path, failure):
    from src.utils.llm.llm_api_interface import OpenAIAPIInterface
    service = LLMService({'prompt_manager': {'template_dir': 'res/agent/prompts'}})
    calls = []
    for name in ('summary', 'extract'):
        def create(name=name, **kwargs):
            calls.append((name, kwargs))
            if (name == 'extract' and failure == 'timeout') or (name == 'summary' and failure == 'summary-timeout'):
                raise TimeoutError('offline SDK timeout')
            answer = ('not json' if failure == 'bad-json' else 'null' if failure == 'null'
                      else json.dumps(ANSWER, ensure_ascii=False)) if name == 'extract' else '独立摘要'
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=answer))], usage=None)
        interface = OpenAIAPIInterface({'api_key': '', 'max_retries': 1})
        interface.client = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        service.llm_interfaces[name] = interface
    cfg = {'crawler': {'activated': True, 'use_llm': failure != 'closed',
        'data_dir': str(tmp_path / 'cache'),
        'llm_module': {'llm': {'name': 'summary'}, 'prompt_name': 'song_knowledge_crawler_prompt'},
        'extraction_llm_module': {'llm': {'name': 'extract', 'use_json': True},
                                  'prompt_name': 'song_knowledge_extraction_prompt'}}}
    task = VCPediaNewSongTask(cfg)
    task.initialize(SimpleNamespace(llm_service=service))
    if failure == 'cached':
        cache = tmp_path / 'cache'
        cache.mkdir()
        expected = {'name': '星空', 'type': 'Song', 'short_summary': '原繁體'}
        (cache / '星空.json').write_text(json.dumps(expected), encoding='utf-8')
    obj = VCPediaFetcher(cfg['crawler'], task.llm_module, extraction_llm_module=task.extraction_llm_module)
    try:
        data = obj.fetch_entity_description('星空')
    finally:
        obj.session.close()
    if failure in ('closed', 'cached'):
        assert not calls
        if failure == 'cached':
            assert data == expected and not http.calls
    else:
        assert [name for name, _ in calls] == ['extract', 'summary']
        if failure == 'summary-timeout':
            assert data['short_summary'] == '\n'.join(ANSWER['summary'])[:100]
            assert data['lyrics'] == ANSWER['lyrics']
        else:
            assert data['short_summary'] == '独立摘要' and data['lyrics'] == ''
            assert data['infobox'] == {'演唱': '洛天依', '作词': '词作者'}


@pytest.mark.parametrize('body', [
    '<poem>开头{{columns-list|2|{{color|red|未提正文}}}}结尾</poem>',
    '<poem>开头{{交叉颜色N|red|未提正文}}结尾</poem>',
    '{{LyricsKai/hover|original=English words}}\n{{LyricsKai|original=Japanese words}}',
], ids=['poem-wrapper', 'poem-inline', 'later-success'])
def test_target_gap_survives_nonempty_lyrics(http, tmp_path, body):
    http.source = '{{VOCALOID Songbox|简介=完整简介}}\n== 歌词 ==\n' + body
    model = Model('null')
    data = crawler(tmp_path, model).fetch_entity_description('缺口')
    assert data['lyrics'] == ('Japanese words' if 'Japanese' in body else '开头结尾')
    assert json.loads(model.calls[0]['needed']) == {'infobox': [], 'summary': False, 'lyrics': True}
    material = json.loads(model.calls[0]['materials'])['text']
    # 材料是转换后的源码：歌词区域可见，字形标记已去
    assert '歌词' in material
    assert '-{' not in material
    assert json.loads(model.calls[0]['song_data'])['lyrics'] == data['lyrics']


def test_target_gap_partial_intro_and_requested_replacement(http, tmp_path):
    http.source = '{{VOCALOID Songbox|简介=开篇{{jk|压线}}结尾|歌词=完整歌词}}'
    model = Model({'summary': ['补齐正文'], 'lyrics': '禁止覆盖'})
    data = crawler(tmp_path, model).fetch_entity_description('缺口')
    assert json.loads(model.calls[0]['needed']) == {'infobox': [], 'summary': True, 'lyrics': False}
    assert json.loads(model.calls[0]['song_data'])['summary'] == ['开篇结尾']
    assert data['summary'] == ['补齐正文'] and data['lyrics'] == '完整歌词'


@pytest.mark.parametrize('ignored', ['{{资料清单}}', '{{未知|id=1}}', '{{TextHover|正文|替代|after|pic}}', '{{未知|text=}}'])
def test_target_gap_does_not_invent_content_from_control_or_empty(http, tmp_path, ignored):
    http.source = '{{VOCALOID Songbox|简介=完整简介|歌词=<poem>完整歌词' + ignored + '</poem>}}'
    model = Model('摘要')
    data = crawler(tmp_path, model).fetch_entity_description('无缺口')
    assert data['lyrics'] == '完整歌词'
    assert len(model.calls) == 1 and set(model.calls[0]) == {'song_data'}


@pytest.mark.parametrize('prefix', [
    '{{Embed|page=帮助/歌词编辑说明}}',
    '{{未知|a=<h2>歌词</h2>|b={{Embed|page=帮助/歌词编辑说明}}}}',
    '{{VOCALOID Songbox|视频={{Embed|page=帮助/歌词编辑说明}}|简介=完整简介}}',
], ids=['lead', 'sibling', 'nonbody'])
def test_embed_context_never_comes_from_page_text(http, tmp_path, prefix):
    http.source = prefix + '\n== 歌词 ==\n'
    http.html = '<p>编辑帮助不是歌词</p>'
    model = Model('null')
    data = crawler(tmp_path, model).fetch_entity_description('归属')
    assert data['lyrics'] == ''
    assert len(http.calls) == 1
    assert json.loads(model.calls[0]['needed'])['lyrics'] is True


@pytest.mark.parametrize('slot', ['简介', '歌词'])
def test_embed_context_inherits_known_body_slot(http, tmp_path, slot):
    call = '{{Embed|page=外部正文}}'
    http.source = '{{VOCALOID Songbox|' + slot + '={{隐藏|内容=' + call + '}}}}'
    http.html = '<p>明确正文</p>'
    data = crawler(tmp_path, None, use_llm=False).fetch_entity_description('归属')
    assert (data['summary'] if slot == '简介' else data['lyrics']) == (['明确正文'] if slot == '简介' else '明确正文')
    assert http.calls[1]['text'] == [call]


@pytest.mark.parametrize('roles', ['视频=视频作者|作词=', 'group1=视频|list1=视频作者|group2=作词|list2='])
def test_staff_video_and_empty_role_are_business_fields(http, tmp_path, roles):
    http.source = '{{VOCALOID Songbox|视频=展示内容|简介=完整简介|歌词=完整歌词}}{{staff|' + roles + '|group3=|list3=不归属|style=|group4=style|list4=}}'
    model = Model({'infobox': {'作词': '补提词作者', '视频': '不覆盖', 'style': '不加入'}})
    data = crawler(tmp_path, model).fetch_entity_description('人员')
    assert data['infobox'] == {'视频': '视频作者', '作词': '补提词作者'}
    assert json.loads(model.calls[0]['needed']) == {'infobox': ['作词'], 'summary': False, 'lyrics': False}


@pytest.mark.parametrize('container', ['<div>{{隐藏|内容=中段。}}</div>', '<div><div>{{隐藏|内容=中段。}}</div></div>'])
def test_intro_wrapper_keeps_same_section_tail(http, tmp_path, container):
    http.source = '== 简介 ==\n开篇。' + container + '结尾。\n== 简介 ==\n真正第二简介。\n== 歌词 ==\n<poem>完整歌词</poem>'
    model = Model('摘要')
    data = crawler(tmp_path, model).fetch_entity_description('连续简介')
    assert ''.join(data['summary'][0].split()) == '开篇。中段。结尾。'
    assert len(data['summary']) == 1
    assert len(model.calls) == 1 and set(model.calls[0]) == {'song_data'}


@pytest.mark.parametrize('failure', ['none', 'challenge', 'http', 'curl-http', 'curl-challenge'])
def test_fragment_long_source_uses_post_body_and_curl_stdin(monkeypatch, tmp_path, failure):
    import shutil
    import subprocess
    call = '{{Embed|page=正文|text=' + '长中文材料' * 800 + '}}'
    source = '== 歌词 ==\n' + call
    requests_seen, curls = [], []
    def request(self, method, url, **kwargs):
        requests_seen.append((method, url, kwargs))
        query = parse_qs(urlsplit(url).query)
        response = requests.Response()
        response.status_code = 200
        if query.get('prop') == ['wikitext']:
            body = json.dumps({'parse': {'wikitext': {'*': source}}})
        elif failure == 'http':
            response.status_code, body = 500, 'server error'
        elif failure != 'none':
            response.status_code, body = 403, 'Anubis challenge'
        else:
            body = json.dumps({'parse': {'text': {'*': '<p>局部正文</p>'}}})
        response._content = body.encode('utf-8')
        return response
    def run(args, **kwargs):
        curls.append((args, kwargs))
        body = ('Anubis challenge' if failure == 'curl-challenge' else json.dumps({'parse': {'text': {'*': '<p>局部正文</p>'}}}))
        return SimpleNamespace(returncode=0, stdout=body + ('\n503' if failure == 'curl-http' else '\n200'), stderr='')
    monkeypatch.setattr(requests.Session, 'request', request)
    monkeypatch.setattr(shutil, 'which', lambda _: 'curl')
    monkeypatch.setattr(subprocess, 'run', run)
    model = Model('null')
    data = crawler(tmp_path, model).fetch_entity_description('长材料')
    assert requests_seen[0][0].upper() == 'GET'
    method, url, kwargs = requests_seen[1]
    assert method.upper() == 'POST' and not urlsplit(url).query
    body = kwargs['data']
    assert parse_qs(body.decode('utf-8') if isinstance(body, bytes) else body)['text'] == [call]
    assert kwargs['headers']['Content-Type'] == 'application/x-www-form-urlencoded'
    assert data['lyrics'] == ('局部正文' if failure in {'none', 'challenge'} else '')
    if failure not in {'none', 'http'}:
        args, curl_kwargs = curls[0]
        assert args[args.index('--data-binary') + 1] == '@-'
        assert '--write-out' in args and '%{http_code}' in args[args.index('--write-out') + 1]
        assert 'Content-Type: application/x-www-form-urlencoded' in args
        assert len(' '.join(args)) < 2000 and call not in ' '.join(args)
        assert parse_qs(curl_kwargs['input'])['text'] == [call]
    else:
        assert not curls
    if failure in {'http', 'curl-http', 'curl-challenge'}:
        assert json.loads(model.calls[0]['needed'])['lyrics'] is True


def test_target_gap_section_tail_catalog_is_not_target_body(http, tmp_path):
    http.source = '== 简介 ==\n完整简介\n== 歌词 ==\n<poem>完整歌词</poem>\n{{资料清单|1=作品分类}}'
    model = Model('摘要')
    data = crawler(tmp_path, model).fetch_entity_description('尾部资料')
    assert data['lyrics'] == '完整歌词'
    assert len(model.calls) == 1 and set(model.calls[0]) == {'song_data'}


@pytest.mark.parametrize('markup', ['template', 'html', 'implicit-html'])
@pytest.mark.parametrize('base, reading, expected, needed', [
    ('完整歌词', '{{未知|注音}}', '完整歌词', False),
    ('', '{{未知|注音}}', '', True),
    ('{{未知|表层}}', '实际唱词', '实际唱词', False),
    ('表层{{未知|缺字}}', '注音', '表层', True),
], ids=['unused-reading', 'selected-unknown-reading', 'selected-fallback', 'selected-partial-base'])
def test_ruby_gaps_follow_selected_text(http, tmp_path, markup, base, reading, expected, needed):
    if markup == 'template':
        ruby = '{{ruby|' + base + '|' + reading + '}}'
    elif markup == 'html':
        ruby = '<ruby><rb>' + base + '</rb><rt>' + reading + '</rt></ruby>'
    else:
        ruby = '<ruby>' + base + '<rt>' + reading + '</rt></ruby>'
    http.source = '== 简介 ==\n完整简介\n== 歌词 ==\n<poem>前句' + ruby + '后句</poem>'
    model = Model('null')
    data = crawler(tmp_path, model).fetch_entity_description('Ruby缺口')
    assert data['lyrics'] == '前句' + expected + '后句'
    assert len(model.calls) == (2 if needed else 1)
    if needed:
        assert json.loads(model.calls[0]['needed']) == {'infobox': [], 'summary': False, 'lyrics': True}
        material = json.loads(model.calls[0]['materials'])['text']
        assert material and '歌词' in material
        assert '-{' not in material
    else:
        assert set(model.calls[0]) == {'song_data'}


def test_extraction_prompt_keeps_only_documented_contract():
    """The supplement prompt is checked for its documented shape, never for wording.

    Spec 补提契约要求：输入变量 song_data/needed/materials 均必填、不请求 short_summary、
    提供正向示例与"材料不足填 null"示例。措辞、以及模型是否照抄标记或统计句这类行为，
    都不在这里断言——行为是非确定性的，由 scripts/vcpedia_prompt_lab.py 真实调用验证。
    """
    service = LLMService({'prompt_manager': {'template_dir': 'res/agent/prompts'}})
    template = service.prompt_manager.get_template('song_knowledge_extraction_prompt')
    assert sorted(template.get_variables()) == ['materials', 'needed', 'song_data']
    prompt = template.render(song_data='{}', needed='{}', materials='{}')
    assert 'short_summary' not in prompt
    objects = [json.loads(line) for line in prompt.splitlines() if line.startswith('{')]
    assert any(isinstance(obj.get('infobox'), dict) for obj in objects)
    assert any(obj.get('lyrics', 'absent') is None for obj in objects)


def test_configuration_template_declares_independent_optional_modules():
    config = json.loads(Path('config/config.json.template').read_text(encoding='utf-8'))
    crawler_cfg = config['world']['song_knowledge']['crawler']
    assert crawler_cfg['llm_module'] == {'llm': {'name': 'qwen3.5-plus', 'enable_thinking': False},
                                         'prompt_name': 'song_knowledge_crawler_prompt'}
    extraction = crawler_cfg['extraction_llm_module']
    assert extraction == {'llm': {'name': 'qwen3.5-plus', 'enable_thinking': False, 'use_json': True},
                          'prompt_name': 'song_knowledge_extraction_prompt'}
    service = LLMService({'prompt_manager': {'template_dir': 'res/agent/prompts'}})
    template = service.prompt_manager.get_template(extraction['prompt_name'])
    assert set(template.get_variables()) == {'song_data', 'needed', 'materials'}
    for missing in template.get_variables():
        args = {'song_data': '{}', 'needed': '{}', 'materials': '{}'}
        del args[missing]
        with pytest.raises(ValueError, match=missing):
            template.render(**args)
