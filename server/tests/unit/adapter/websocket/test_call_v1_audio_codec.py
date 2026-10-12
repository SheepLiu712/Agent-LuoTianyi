"""Contract tests for the pure call.v1 binary audio-frame codec."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.adapter.websocket.call_v1 import (
    AudioFrameCodec,
    AudioFrameCodecError,
    BinaryAudioFrameCodec,
    WireAudioFrame,
)

FIXTURE_PATH = Path(__file__).parents[5] / "contracts" / "call_v1" / "fixtures" / "audio_frames.json"
CONTRACT = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _hex_from_pattern(pattern: dict[str, object]) -> str:
    return str(pattern["prefix"]) + str(pattern["repeat_hex"]) * int(pattern["count"])


def _encoded_hex(case: dict[str, object]) -> str:
    if "encoded_hex" in case:
        return str(case["encoded_hex"])
    return _hex_from_pattern(case["encoded_hex_pattern"])


def _payload(frame: dict[str, object]) -> bytes:
    if "payload_hex" in frame:
        return bytes.fromhex(str(frame["payload_hex"]))
    pattern = frame["payload_pattern"]
    return bytes.fromhex(str(pattern["repeat_hex"]) * int(pattern["count"]))


def _frame(data: dict[str, object]) -> WireAudioFrame:
    return WireAudioFrame(
        version=data["version"],
        route=CONTRACT["constants"]["routes"][data["route"]],
        flags=sum(CONTRACT["constants"]["flags"][flag] for flag in data["flags"]),
        stream_id=data["stream_id"],
        seq=data["seq"],
        payload=_payload(data),
    )


@pytest.mark.parametrize("case", CONTRACT["valid"], ids=lambda case: case["id"])
def test_valid_fixture_encodes_to_exact_golden_and_round_trips(case: dict[str, object]) -> None:
    codec = BinaryAudioFrameCodec()
    expected = bytes.fromhex(_encoded_hex(case))
    frame = _frame(case["frame"])

    assert codec.encode(frame) == expected
    assert codec.decode(expected) == frame


@pytest.mark.parametrize(
    "case",
    [case for case in CONTRACT["invalid"] if case["operation"] == "decode"],
    ids=lambda case: case["id"],
)
def test_invalid_decode_fixture_uses_stable_error_code(case: dict[str, object]) -> None:
    encoded = bytes.fromhex(_encoded_hex(case))

    with pytest.raises(AudioFrameCodecError, match=f"^{case['error']}$") as raised:
        BinaryAudioFrameCodec().decode(encoded)

    assert raised.value.code == case["error"]


@pytest.mark.parametrize(
    "case",
    [case for case in CONTRACT["invalid"] if case["operation"] == "encode"],
    ids=lambda case: case["id"],
)
def test_invalid_encode_fixture_uses_stable_error_code(case: dict[str, object]) -> None:
    with pytest.raises(AudioFrameCodecError, match=f"^{case['error']}$") as raised:
        BinaryAudioFrameCodec().encode(_frame(case["frame"]))

    assert raised.value.code == case["error"]


@pytest.mark.parametrize("field", ["version", "route", "flags", "stream_id", "seq"])
@pytest.mark.parametrize("value", [True, 1.0, "1"])
def test_encode_rejects_boolean_float_and_string_integer_fields(field: str, value: object) -> None:
    fields: dict[str, object] = {"version": 1, "route": 2, "flags": 0, "stream_id": 1, "seq": 1}
    fields[field] = value
    frame = WireAudioFrame(payload=b"\x00\x01", **fields)

    with pytest.raises(AudioFrameCodecError, match="^INVALID_FIELD_TYPE$") as raised:
        BinaryAudioFrameCodec().encode(frame)

    assert raised.value.code == "INVALID_FIELD_TYPE"


@pytest.mark.parametrize("value", [-1, 4_294_967_296])
def test_encode_rejects_out_of_range_uint32_sequence(value: int) -> None:
    frame = WireAudioFrame(1, 2, 0, 1, value, b"\x00\x01")

    with pytest.raises(AudioFrameCodecError, match="^FIELD_OUT_OF_RANGE$") as raised:
        BinaryAudioFrameCodec().encode(frame)

    assert raised.value.code == "FIELD_OUT_OF_RANGE"


@pytest.mark.parametrize("payload", [bytearray(b"\x00\x01"), memoryview(b"\x00\x01"), "0001"])
def test_encode_rejects_non_bytes_payload(payload: object) -> None:
    frame = WireAudioFrame(1, 2, 0, 1, 1, payload)

    with pytest.raises(AudioFrameCodecError, match="^INVALID_FIELD_TYPE$"):
        BinaryAudioFrameCodec().encode(frame)


@pytest.mark.parametrize("encoded", [bytearray(b"\x00" * 15), memoryview(b"\x00" * 15), "not bytes"])
def test_decode_rejects_non_bytes(encoded: object) -> None:
    with pytest.raises(AudioFrameCodecError, match="^INVALID_FIELD_TYPE$"):
        BinaryAudioFrameCodec().decode(encoded)


def test_encode_rejects_odd_payload_and_accepts_maximum_payload() -> None:
    codec = BinaryAudioFrameCodec()
    with pytest.raises(AudioFrameCodecError, match="^PCM_ALIGNMENT_ERROR$"):
        codec.encode(WireAudioFrame(1, 2, 0, 1, 1, b"\x00"))

    maximum = WireAudioFrame(1, 2, 0, 1, 1, b"\x00\x01" * 8192)
    assert codec.decode(codec.encode(maximum)) == maximum


def test_decode_rejects_trailing_payload_bytes() -> None:
    encoded = bytes.fromhex("0102000000000100000001000000020001") + b"\x00\x00"

    with pytest.raises(AudioFrameCodecError, match="^PAYLOAD_LENGTH_MISMATCH$"):
        BinaryAudioFrameCodec().decode(encoded)


@pytest.mark.parametrize(
    "header,error_code",
    [
        ("020200000000010000000100000002", "UNSUPPORTED_VERSION"),
        ("010200000000010000000100010000", "PAYLOAD_TOO_LARGE"),
    ],
    ids=["unsupported-version", "payload-over-limit"],
)
def test_decode_rejects_large_invalid_input_before_copying_payload(
    monkeypatch: pytest.MonkeyPatch,
    header: str,
    error_code: str,
) -> None:
    def fail_if_copied(_: bytes) -> bytes:
        raise AssertionError("payload must not be copied before validation succeeds")

    monkeypatch.setattr(BinaryAudioFrameCodec, "_copy_payload", staticmethod(fail_if_copied))
    encoded = bytes.fromhex(header) + b"\x00" * 65_536

    with pytest.raises(AudioFrameCodecError, match=f"^{error_code}$"):
        BinaryAudioFrameCodec().decode(encoded)


def test_decode_copies_valid_payload_into_its_own_bytes_object() -> None:
    encoded = bytes.fromhex("0102000000000100000001000000020001")

    decoded = BinaryAudioFrameCodec().decode(encoded)

    assert decoded.payload == b"\x00\x01"
    assert decoded.payload is not encoded


def test_protocol_can_be_satisfied_by_a_local_alternative_codec() -> None:
    class FakeCodec:
        def encode(self, frame: WireAudioFrame) -> bytes:
            return frame.payload

        def decode(self, encoded: bytes) -> WireAudioFrame:
            return WireAudioFrame(1, 2, 0, 0, 1, encoded)

    codec: AudioFrameCodec = FakeCodec()
    assert isinstance(codec, AudioFrameCodec)
    assert codec.decode(codec.encode(WireAudioFrame(1, 2, 0, 0, 1, b"\x00\x01"))).payload == b"\x00\x01"
