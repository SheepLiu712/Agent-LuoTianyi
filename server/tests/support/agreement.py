"""真实 HTTP 验收中，用当前协议构造新客户端的注册同意字段。"""

from uuid import uuid4


def registration_agreement(http, url):
    response = http.get(url + "/auth/agreement", timeout=5)
    response.raise_for_status()
    return {
        "agreement_version": response.json()["version"],
        "registration_request_id": str(uuid4()),
        "accepted": True,
    }
