import asyncio
import datetime
import ssl
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import certifi
import pytest
import requests
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
from websockets.legacy.client import connect
from websockets.legacy.server import serve

from src.network.ws_transport import WsTransport
from src.utils.http_client import HttpClientFactory


@pytest.fixture
def tls_server(tmp_path, monkeypatch):
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")])
    now = datetime.datetime.utcnow()
    certificate = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .sign(key, hashes.SHA256())
    )
    ca = tmp_path / "ca.pem"
    private_key = tmp_path / "key.pem"
    ca.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    private_key.write_bytes(
        key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption())
    )
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(ca, private_key)
    yield context, ca
    for session in HttpClientFactory._session_cache.values():
        session.close()
    HttpClientFactory._session_cache.clear()


@pytest.mark.parametrize("case", ["trusted", "wrong_hostname", "untrusted"])
def test_wss_certificate_validation(tls_server, monkeypatch, case):
    context, ca = tls_server
    if case != "untrusted":
        monkeypatch.setattr(certifi, "where", lambda: str(ca))
    monkeypatch.setenv("SSL_CERT_FILE", "missing-ca.pem")

    async def run():
        async def handler(ws, path):
            await ws.send("connected")

        async with serve(handler, "127.0.0.1", 0, ssl=context) as server:
            port = server.sockets[0].getsockname()[1]
            host = "127.0.0.1" if case == "wrong_hostname" else "localhost"
            base = f"https://{host}:{port}"
            transport = WsTransport(base, lambda: None, lambda: None)
            async with connect(
                transport._build_ws_url(base), ssl=transport._build_ssl_context(base), open_timeout=3
            ) as ws:
                assert await ws.recv() == "connected"

    if case == "trusted":
        asyncio.run(run())
    else:
        with pytest.raises(ssl.SSLCertVerificationError):
            asyncio.run(run())


@pytest.mark.parametrize("case", ["trusted", "wrong_hostname", "untrusted"])
def test_https_certificate_validation(tls_server, monkeypatch, case):
    context, ca = tls_server
    if case != "untrusted":
        monkeypatch.setattr(certifi, "where", lambda: str(ca))
    monkeypatch.setenv("REQUESTS_CA_BUNDLE", "missing-ca.pem")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b"connected")

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        host = "127.0.0.1" if case == "wrong_hostname" else "localhost"
        session = HttpClientFactory.get_session(False)
        # 保留代理环境配置能力，但本地测试不使用代理。
        monkeypatch.setenv("NO_PROXY", "localhost,127.0.0.1")
        url = f"https://{host}:{server.server_port}/"
        if case == "trusted":
            assert session.get(url, timeout=3).text == "connected"
        else:
            with pytest.raises(requests.exceptions.SSLError):
                session.get(url, verify=False, timeout=3)
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)
