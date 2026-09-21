"""Deterministic WAV samples shared by independent loopback fixtures."""
import io
import math
import struct
import wave


def tone(seconds, rate=24000):
    target = io.BytesIO()
    with wave.open(target, "wb") as output:
        output.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        output.writeframes(b"".join(struct.pack("<h", int(math.sin(i * math.tau * 440 / rate) * 8000))
                                  for i in range(int(rate * seconds))))
    return target.getvalue()

