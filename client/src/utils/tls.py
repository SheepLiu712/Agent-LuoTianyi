"""TLS/CA helpers for desktop networking."""

from __future__ import annotations

import os
import ssl
from pathlib import Path

import certifi


_CA_FILE_ENV_VARS = ("REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE")
_CA_DIR_ENV_VARS = ("SSL_CERT_DIR",)


def sanitize_tls_certificate_environment() -> None:
    """Remove stale TLS CA env vars that point to missing local files.

    requests and ssl.create_default_context both consult process environment
    variables. After the desktop client is deleted and installed again, those
    variables may still point to a certificate file under the old install path,
    which makes requests fail before it can use the default CA store.
    """
    for env_name in _CA_FILE_ENV_VARS:
        value = os.environ.get(env_name)
        if value and not Path(value).is_file():
            os.environ.pop(env_name, None)

    for env_name in _CA_DIR_ENV_VARS:
        value = os.environ.get(env_name)
        if value and not Path(value).is_dir():
            os.environ.pop(env_name, None)


def create_default_ssl_context() -> ssl.SSLContext:
    """使用随客户端更新的 CA 包，保留证书链和域名校验。"""
    context = ssl.create_default_context(cafile=certifi.where())
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    return context
