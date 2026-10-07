"""Real AAC media with controlled, same-length MP4 brand declarations."""

from pathlib import Path


def recorded_aac_bytes(brand: bytes = b"mp42") -> bytes:
    data = (Path(__file__).resolve().parents[1] / "fixtures" / "audio" / "aac-lc.m4a").read_bytes()
    size = int.from_bytes(data[:4], "big")
    assert data[4:8] == b"ftyp" and size == 28
    # Original payload has three compatible-brand slots; retain its exact size
    # so stco/co64 sample offsets still address the original AAC data.
    payload = brand + b"\0" * 4 + b"isom" + brand + b"mp42"
    return data[:8] + payload + data[size:]
