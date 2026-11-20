"""无需登录即可导出客户端 TLS 连接诊断。"""

import asyncio
import hashlib
import json
import platform
import ssl

import certifi
import websockets

from .tls import create_default_ssl_context


async def diagnose():
    host = "www-api.u3493359.nyat.app"
    url = f"wss://{host}:11664/chat_ws"
    report = {
        "python": platform.python_version(),
        "openssl": ssl.OPENSSL_VERSION,
        "certifi": certifi.__version__,
        "ca_file": certifi.where(),
        "url": url,
        "attempts": [],
    }
    for name, factory in (
        ("client_bundle", create_default_ssl_context),
        ("system_default", ssl.create_default_context),
    ):
        result = {"trust_source": name}
        try:
            context = factory()
            result["ca_count"] = len(context.get_ca_certs())
            result["relevant_cas"] = [
                cert["subject"]
                for cert in context.get_ca_certs()
                if any(word in str(cert["subject"]) for word in ("Root R46", "AAA Certificate", "emSign"))
            ]
            async with websockets.connect(url, ssl=context, open_timeout=15, close_timeout=3) as ws:
                peer = ws.transport.get_extra_info("ssl_object")
                result.update(
                    status="connected",
                    peer_certificate=peer.getpeercert(),
                    peer_sha256=hashlib.sha256(peer.getpeercert(binary_form=True)).hexdigest(),
                )
        except Exception as exc:
            result.update(status="failed", error_type=type(exc).__name__, error=str(exc))
            if isinstance(exc, ssl.SSLCertVerificationError):
                result["verify_code"] = exc.verify_code
                result["verify_message"] = exc.verify_message
        report["attempts"].append(result)
    return report


def main():
    report = asyncio.run(diagnose())
    print(json.dumps(report, ensure_ascii=True, indent=2))
    return 0 if report["attempts"][0]["status"] == "connected" else 1
