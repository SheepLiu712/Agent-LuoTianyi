"""窗口单操作槽：纯数据 worker 与 UI-owned 有效结果接收。"""

from dataclasses import dataclass, field
from queue import Empty, Full, Queue
from threading import Event, Thread

from PySide6.QtCore import QObject, QTimer, Signal


@dataclass
class _Ticket:
    request: object
    cancelled: Event = field(default_factory=Event)
    consumed: bool = False


def _execute(request, cancelled: Event, results: Queue):
    try:
        result = request.execute(cancelled)
    except Exception as exc:
        result = (False, f"请求失败: {type(exc).__name__}", {})
    try:
        results.put_nowait(result)
    except Full:
        pass


class WindowOperation(QObject):
    completed = Signal(object, object)
    settled = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._active = None
        self._delivering = False
        self._closed = False
        self._cancellation = [None]
        self.destroyed.connect(lambda _obj=None, holder=self._cancellation: holder[0] is not None and holder[0].set())
        self._timer = QTimer(self)
        self._timer.setInterval(20)
        self._timer.timeout.connect(self._collect)

    @property
    def busy(self):
        return self._active is not None or self._delivering

    def start(self, request):
        if self.busy or self._closed:
            return False
        ticket = _Ticket(request)
        self._cancellation[0] = ticket.cancelled
        results = Queue(maxsize=1)
        thread = Thread(target=_execute, args=(request, ticket.cancelled, results), daemon=True, name="window-account")
        self._active = (thread, results, ticket)
        thread.start()
        self._timer.start()
        return ticket.cancelled

    def invalidate(self):
        if self._active is not None:
            self._active[2].cancelled.set()

    def close(self):
        self._closed = True
        self.invalidate()
        self._timer.stop()

    def _collect(self):
        if self._active is None or self._active[0].is_alive():
            return
        thread, results, ticket = self._active
        try:
            result = results.get_nowait()
        except Empty:
            return
        self._active = None
        self._cancellation[0] = None
        self._timer.stop()
        if not self._closed and not ticket.cancelled.is_set() and not ticket.consumed:
            # 在调用可能保存身份/启动 WS 的 UI apply 前先消费一次 ticket。
            ticket.consumed = True
            self._delivering = True
            try:
                self.completed.emit(ticket.request, result)
            finally:
                self._delivering = False
        if not self._closed:
            self.settled.emit()
