"""交互输出与撤销绑定的窄接口。"""

import asyncio
from typing import Protocol

from .output import StageOutput


class StageOutputSink(Protocol):
    def submit_output(self, output: StageOutput) -> asyncio.Future[None]: ...
