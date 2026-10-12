from src.network.agreement import validate_agreement_payload
from src.network.auth import AuthApi

VALID_PAYLOAD = {
    "version": "terms-2026-10-v2",
    "title": "用户协议",
    "format": "agreement.richtext.v1",
    "blocks": [
        {
            "font_size": 16,
            "align": "justify",
            "runs": [{"text": "甲  乙\n丙", "bold": True}],
        }
    ],
}


class Response:
    status_code = 200

    def __init__(self, payload):
        self.payload = payload

    def json(self):
        return self.payload


class Session:
    def __init__(self, payload):
        self.payload = payload

    def get(self, *_args, **_kwargs):
        return Response(self.payload)


def make_api(payload):
    api = AuthApi.__new__(AuthApi)
    api.base_url = "https://example.invalid"
    api.verify_ssl = True
    api.session = Session(payload)
    return api


def test_validate_agreement_payload_preserves_content():
    assert validate_agreement_payload(VALID_PAYLOAD) == VALID_PAYLOAD


def test_fetch_current_agreement_accepts_valid_payload():
    assert make_api(VALID_PAYLOAD).fetch_current_agreement() == (True, "", VALID_PAYLOAD)


def test_fetch_current_agreement_rejects_non_object_payload():
    assert make_api(["invalid"]).fetch_current_agreement() == (False, "Failed to load agreement", {})


def test_fetch_current_agreement_rejects_invalid_fields():
    invalid = {
        **VALID_PAYLOAD,
        "blocks": [{"font_size": 16, "align": "left", "runs": [{"text": "正文"}]}],
    }

    assert make_api(invalid).fetch_current_agreement() == (False, "Failed to load agreement", {})
