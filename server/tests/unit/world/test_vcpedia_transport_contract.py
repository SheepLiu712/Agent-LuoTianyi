"""VCPedia 传输层契约：请求形状、传输身份、挑战兜底与失败语义。

外部边界只替换 requests 与 curl 进程；断言的是公开入口（详情与列表）观察到的结果。
样例是人工构造的固定响应，不是真实站点采样。
"""

from __future__ import annotations

import json
import shutil
import subprocess
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import pytest
import requests

from src.world.get_new_songs.daily_new_song_fetcher import fetch_song_list_from_template
from src.world.get_new_songs.vcpedia_fetcher import VCPediaFetcher
from src.world.get_new_songs.wiki_api import user_agent

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
    state = SimpleNamespace(
        body="", status=200, curl_body=None, curl_status=200, curl_code=0,
        curl_exists=True, calls=[], curls=[],
    )

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
    return VCPediaFetcher({"activated": True, "use_llm": False, "data_dir": str(tmp_path / "cache"), **config})


def assert_api(call, title):
    url, kwargs = call
    parsed = urlsplit(url)
    query = parse_qs(parsed.query)
    query.update({k: [str(v)] for k, v in kwargs.get("params", {}).items()})
    assert parsed.path == "/api.php"
    assert query == {
        "action": ["parse"], "prop": ["wikitext"], "redirects": ["1"],
        "format": ["json"], "page": [title],
    }


def test_requests_use_the_application_user_agent(wire, tmp_path):
    """传输身份是应用自述 UA：请求头与 curl 兜底必须一致，不得伪装浏览器。"""
    wire.body = payload("== 简介 ==\n正文")
    fetcher(tmp_path).fetch_entity_description("歌曲")

    _, kwargs = wire.calls[0]
    assert kwargs["headers"]["User-Agent"] == user_agent()
    assert "Mozilla" not in user_agent()

    # 第二次访问：同一次挑战兜底，请求头与 curl 参数必须是同一身份。
    wire.status, wire.body = 403, "challenge"
    wire.curl_body = payload("== 简介 ==\n正文")
    assert fetcher(tmp_path).fetch_entity_description("歌曲")["summary"] == ["正文"]
    assert wire.curls, "挑战未被兜底处理"
    args, _ = wire.curls[0]
    assert args[args.index("--user-agent") + 1] == user_agent()


@pytest.mark.parametrize("entry", ["list", "detail"])
@pytest.mark.parametrize("status", [200, 403])
def test_both_entries_recover_challenge_through_curl(wire, tmp_path, entry, status):
    wire.status, wire.body = status, "<html>Making sure you're not a bot! Anubis</html>"
    wire.curl_body = payload("[[歌曲]]" if entry == "list" else "== 简介 ==\n正文")
    result = (
        fetch_song_list_from_template(TEMPLATE, 7)
        if entry == "list"
        else fetcher(tmp_path).fetch_entity_description("歌曲")
    )
    if entry == "list":
        assert result == ["歌曲"]
    else:
        assert result["summary"] == ["正文"]
    args, kwargs = wire.curls[0]
    assert "--max-time" in args and "--fail" in args
    assert "--user-agent" in args
    assert kwargs.get("shell", False) is False
    assert_api((args[-1], {}), "Template:洛天依/2038" if entry == "list" else "歌曲")


@pytest.mark.parametrize("entry", ["list", "detail"])
@pytest.mark.parametrize(
    "failure",
    ["no_curl", "curl_exit", "curl_http", "empty", "challenge", "json", "api_error", "missing", "wrong_type", "http"],
)
def test_failures_are_not_successful_empty_pages(wire, tmp_path, entry, failure):
    wire.body = "Anubis challenge"
    wire.curl_body = payload("[[歌曲]]")
    if failure == "no_curl":
        wire.curl_exists = False
    elif failure == "curl_exit":
        wire.curl_code = 28
    elif failure == "curl_http":
        wire.curl_status = 503
    elif failure == "empty":
        wire.curl_body = ""
    elif failure == "challenge":
        wire.curl_body = "Anubis challenge"
    else:
        wire.body = {
            "json": "not JSON",
            "api_error": '{"error":{"code":"missingtitle"}}',
            "missing": '{"parse":{}}',
            "wrong_type": '{"parse":{"wikitext":[]}}',
            "http": "failure",
        }[failure]
        if failure == "http":
            wire.status = 500

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
@pytest.mark.parametrize(
    "body,status,error",
    [
        ("null", 200, ValueError),
        ("[]", 200, ValueError),
        ('"Anubis"', 200, ValueError),
        (payload("[[Anubis]]"), 500, requests.HTTPError),
        ("not JSON", 500, requests.HTTPError),
    ],
)
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


def test_disabled_fetcher_does_not_touch_the_network(wire, tmp_path):
    """关闭时不发请求，返回值语义保持原样（空字符串）。"""
    assert VCPediaFetcher({"activated": False, "data_dir": str(tmp_path)}).fetch_entity_description("歌曲") == ""
    assert not wire.calls
