from typing import Dict, Tuple

import certifi
import requests
from requests.adapters import HTTPAdapter

from .tls import create_default_ssl_context


class TLS12HttpAdapter(HTTPAdapter):
    def __init__(self, verify_ssl: bool = True, *args, **kwargs):
        self.verify_ssl = verify_ssl
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = create_default_ssl_context()

        pool_kwargs["ssl_context"] = ctx
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)

    def cert_verify(self, conn, url, verify, cert):
        # HTTP 与 WebSocket 使用同一信任来源，不接受环境变量或 verify=False 降级。
        return super().cert_verify(conn, url, certifi.where(), cert)


class HttpClientFactory:
    _session_cache: Dict[Tuple[bool], requests.Session] = {}

    @classmethod
    def get_session(cls, verify_ssl: bool) -> requests.Session:
        verify_ssl = True
        key = (verify_ssl,)
        if key in cls._session_cache:
            return cls._session_cache[key]

        session = requests.Session()
        adapter = TLS12HttpAdapter(verify_ssl=verify_ssl)
        session.mount("https://", adapter)
        session.mount("http://", HTTPAdapter())
        cls._session_cache[key] = session
        return session
