"""Internal MediaWiki transport shared by template and detail fetching."""
import json
import shutil
import subprocess
from typing import Callable
from urllib.parse import urlencode

from requests import Response

from src.utils.logger import get_logger

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/122.0 Safari/537.36"
_LOG = get_logger(__name__)


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


def fetch_wikitext(
    base_url: str, title: str, get: Callable[..., Response], timeout: float
) -> str:
    url = base_url.rstrip("/") + "/api.php?" + urlencode({
        "action": "parse", "prop": "wikitext", "redirects": 1,
        "format": "json", "page": title,
    })
    response = get(url, headers={"User-Agent": _USER_AGENT},
                   timeout=timeout, allow_redirects=True)
    body = response.text
    document, decode_error = _decode_body(body)
    if _is_challenge(response.status_code, body, decode_error):
        curl = shutil.which("curl") or shutil.which("curl.exe")
        if not curl:
            raise RuntimeError("VCPedia challenge: curl is unavailable")
        _LOG.warning("VCPedia API requests 命中反爬挑战，尝试 curl 兜底")
        result = subprocess.run(
            [curl, "-sS", "-L", "--fail", "--max-time", str(timeout),
             "--user-agent", _USER_AGENT, "--write-out", "\n%{http_code}", url],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            check=False, timeout=timeout + 5,
        )
        if result.returncode:
            raise RuntimeError(f"curl fallback failed: {result.stderr.strip()}")
        body, separator, status = result.stdout.rpartition("\n")
        if not separator or not status.isdigit() or not 200 <= int(status) < 300:
            raise RuntimeError("curl fallback returned invalid/failed HTTP status")
        document, decode_error = _decode_body(body)
        if not body.strip() or _is_challenge(int(status), body, decode_error):
            raise RuntimeError("curl fallback returned empty response or challenge")
    else:
        response.raise_for_status()
    if decode_error is not None:
        raise decode_error
    if not isinstance(document, dict) or "error" in document:
        raise ValueError("VCPedia API error response")
    parsed = document.get("parse")
    source = parsed.get("wikitext") if isinstance(parsed, dict) else None
    if isinstance(source, dict):
        source = source.get("*")
    if not isinstance(source, str):
        raise ValueError("VCPedia API response has no string wikitext")
    return source
