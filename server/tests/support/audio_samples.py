"""Real AAC media with controlled, same-length MP4 brand declarations."""

import struct
from pathlib import Path


def recorded_aac_bytes(brand: bytes = b"mp42", *, android_metadata: bool = False) -> bytes:
    data = (Path(__file__).resolve().parents[1] / "fixtures" / "audio" / "aac-lc.m4a").read_bytes()
    size = int.from_bytes(data[:4], "big")
    assert data[4:8] == b"ftyp" and size == 28
    # Original payload has three compatible-brand slots; retain its exact size
    # so stco/co64 sample offsets still address the original AAC data.
    payload = brand + b"\0" * 4 + b"isom" + brand + b"mp42"
    data = data[:8] + payload + data[size:]
    if android_metadata:
        # Reproduce Android's non-FullBox meta before trak using synthetic,
        # non-personal metadata. In this fixture moov follows mdat, so adding
        # metadata does not move any encoded AAC samples or invalidate stco.
        offset = 0
        while data[offset + 4 : offset + 8] != b"moov":
            offset += int.from_bytes(data[offset : offset + 4], "big")
        moov_size = int.from_bytes(data[offset : offset + 4], "big")
        assert offset + moov_size == len(data)
        handler = struct.pack(">I4s", 33, b"hdlr") + b"\0" * 8 + b"mdta" + b"\0" * 13
        metadata = struct.pack(">I4s", len(handler) + 8, b"meta") + handler
        data = data[:offset] + struct.pack(">I4s", moov_size + len(metadata), b"moov") + metadata + data[offset + 8 :]
    return data
