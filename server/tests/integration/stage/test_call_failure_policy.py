"""保留时限告知所用的语音合成测试替身；实时会话失败见 test_call_omni。"""

from collections import Counter
from types import SimpleNamespace
import src.domain.agent as d


class Speech:
    def __init__(self, *, failures=0):
        self.failures = failures
        self.calls = Counter()

    async def speak(self, invocation, *, text, tone, output_format):
        self.calls[text] += 1
        for _ in range(2):
            yield SimpleNamespace(data=b"\0\0" * 10, framing=d.AudioFraming.RAW_PCM)
        if self.calls[text] <= self.failures:
            raise RuntimeError("TTS failed after partial audio")
