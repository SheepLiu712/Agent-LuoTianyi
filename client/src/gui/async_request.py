"""动态角标的单个只读后台请求；结果由 GUI 计时器消费。"""

from queue import Full, Queue
from threading import Thread

from ..network.network_client import DynamicUnreadRequest
from ..utils.http_client import HttpClientFactory


def _fetch_dynamic_unread(request: DynamicUnreadRequest, results: Queue) -> None:
    try:
        with HttpClientFactory.create_session() as session:
            result = request.fetch(session)
    except Exception:
        result = DynamicUnreadRequest.failure("Unread request failed")
    # 会话已经关闭。窗口即使已销毁，worker 也不持 Qt 对象且不会等消费者。
    try:
        results.put_nowait(result)
    except Full:
        pass


def start_dynamic_unread_request(request: DynamicUnreadRequest) -> tuple[Thread, Queue]:
    results = Queue(maxsize=1)
    thread = Thread(target=_fetch_dynamic_unread, args=(request, results), name="dynamic-unread", daemon=True)
    thread.start()
    return thread, results
