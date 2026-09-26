"""Internal MediaWiki transport shared by template and detail fetching."""
import json
import shutil
import subprocess
from typing import Callable
from urllib.parse import urlencode

from requests import Response

from src.utils.logger import get_logger

_USER_AGENT = "AgentLuo/1.0 (+https://github.com/SheepLiu712/Agent-LuoTianyi)"


def user_agent() -> str:
    """调用方（含 requests.Session 默认头）复用的传输身份。"""
    return _USER_AGENT
_LOG = get_logger(__name__)


def fetch_wikitext(
    base_url: str, title: str, get: Callable[..., Response], timeout: float
) -> str:
    return _fetch_parse(base_url, {"action": "parse", "prop": "wikitext", "redirects": 1,
                                  "format": "json", "page": title}, get, timeout)


def render_fragment(base_url, title, source, post, timeout):
    return _fetch_parse(base_url, {"action": "parse", "prop": "text", "format": "json",
                                  "text": source, "title": title,
                                  "contentmodel": "wikitext"}, post, timeout, post=True)


def _fetch_parse(base_url, params, request, timeout, *, post=False):
    url = _api_url(base_url, params, post)
    document, decode_error = _request_document(url, params, request, timeout, post)
    return _parse_document(document, decode_error, params)


def _api_url(base_url, params, post):
    """GET carries the parameters in the query string; POST moves them into the body."""
    return base_url.rstrip("/") + "/api.php" + ("" if post else "?" + urlencode(params))


def _request_document(url, params, request, timeout, post):
    """One direct request; a challenged exchange is retried through curl instead."""
    encoded = urlencode(params)
    response = request(url, headers=_request_headers(post), timeout=timeout,
                       allow_redirects=True, **_request_body(encoded, post))
    body = response.text
    document, decode_error = _decode_body(body)
    if _is_challenge(response.status_code, body, decode_error):
        return _challenge_fallback_document(url, encoded, timeout, post)
    response.raise_for_status()
    return document, decode_error


def _request_headers(post):
    headers = {"User-Agent": _USER_AGENT}
    if post:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    return headers


def _request_body(encoded, post):
    return {"data": encoded.encode("utf-8")} if post else {}


def _challenge_fallback_document(url, encoded, timeout, post):
    """Retry the challenged exchange with curl under the same transport identity."""
    curl = shutil.which("curl") or shutil.which("curl.exe")
    if not curl:
        raise RuntimeError("VCPedia challenge: curl is unavailable")
    _LOG.warning("VCPedia API requests 命中反爬挑战，尝试 curl 兜底")
    status, body = _run_curl(curl, url, encoded, timeout, post)
    document, decode_error = _decode_body(body)
    if not body.strip() or _is_challenge(status, body, decode_error):
        raise RuntimeError("curl fallback returned empty response or challenge")
    return document, decode_error


def _run_curl(curl, url, encoded, timeout, post):
    args = [curl, "-sS", "-L", "--fail", "--max-time", str(timeout),
            "--user-agent", _USER_AGENT, "--write-out", "\n%{http_code}"]
    stdin = {}
    if post:
        args.extend(["--header", "Content-Type: application/x-www-form-urlencoded",
                     "--data-binary", "@-"])
        stdin["input"] = encoded
    result = subprocess.run(
        args + [url], capture_output=True, text=True, encoding="utf-8", errors="replace",
        check=False, timeout=timeout + 5, **stdin,
    )
    if result.returncode:
        raise RuntimeError(f"curl fallback failed: {result.stderr.strip()}")
    body, separator, status = result.stdout.rpartition("\n")
    if not separator or not status.isdigit() or not 200 <= int(status) < 300:
        raise RuntimeError("curl fallback returned invalid/failed HTTP status")
    return int(status), body


def _parse_document(document, decode_error, params):
    if decode_error is not None:
        raise decode_error
    if not isinstance(document, dict) or "error" in document:
        raise ValueError("VCPedia API error response")
    parsed = document.get("parse")
    source = parsed.get(params["prop"]) if isinstance(parsed, dict) else None
    if isinstance(source, dict):
        source = source.get("*")
    if not isinstance(source, str):
        raise ValueError(f"VCPedia API response has no string {params['prop']}")
    return source


def _decode_body(body):
    try:
        return json.loads(body), None
    except (ValueError, TypeError) as error:
        return None, error


def _is_challenge(status, body, decode_error):
    if status == 403:
        return True
    # Even valid JSON null/string may mention Anubis without being a challenge.
    if decode_error is None:
        return False
    text = (body or "").lower()
    return any(marker in text for marker in (
        "making sure you're not a bot", "正在确认你是不是机器",
        "within.website", "xess.min.css", "anubis", "techaro"))
