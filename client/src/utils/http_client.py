import ssl
from typing import Dict, Tuple

import requests
from requests.adapters import HTTPAdapter


class TLS12HttpAdapter(HTTPAdapter):
    def __init__(self, verify_ssl: bool = True, *args, **kwargs):
        self.verify_ssl = verify_ssl
        super().__init__(*args, **kwargs)

    def init_poolmanager(self, connections, maxsize, block=False, **pool_kwargs):
        ctx = ssl.create_default_context()
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2

        if not self.verify_ssl:
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

        pool_kwargs["ssl_context"] = ctx
        return super().init_poolmanager(connections, maxsize, block=block, **pool_kwargs)


class HttpClientFactory:
    _session_cache: Dict[Tuple[bool], requests.Session] = {}

    @classmethod
    def get_session(cls, verify_ssl: bool) -> requests.Session:
        key = (verify_ssl,)
        if key in cls._session_cache:
            return cls._session_cache[key]

        session = requests.Session()
        adapter = TLS12HttpAdapter(verify_ssl=verify_ssl)
        session.mount("https://", adapter)
        session.mount("http://", HTTPAdapter())
        cls._session_cache[key] = session
        return session
