"""头像按需同步：启动、前台与编辑入口检查，只有待上传修改做有限重试。"""

from queue import Empty, Queue
from threading import Event, Thread
from time import monotonic

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication

from ..avatars import AvatarStore
from ..utils.http_client import HttpClientFactory

FOREGROUND_CHECK_SECONDS = 5 * 60
UPLOAD_RETRY_MS = (10_000, 30_000, 120_000)


def _fetch(request, results, cancelled):
    try:
        with HttpClientFactory.create_session() as session:
            result = request.fetch(session, cancelled)
    except Exception as exc:
        result = {"ok": False, "message": str(exc)}
    results.put_nowait(result)


class AvatarController(QObject):
    changed = Signal()
    status_changed = Signal(str)

    def __init__(self, network_client, parent=None, store=None):
        super().__init__(parent)
        self.network = network_client
        self.store = store or AvatarStore()
        self.status = "头像待同步"
        self._context = None
        self._flight = None
        self._closed = False
        self._foreground = True
        self._last_success = None
        self._retry_count = 0
        self.retry_timer = QTimer(self)
        self.retry_timer.setSingleShot(True)
        self.retry_timer.timeout.connect(self._sync_next)
        self.result_timer = QTimer(self)
        self.result_timer.setInterval(25)
        self.result_timer.timeout.connect(self._collect)
        self.result_timer.start()
        QApplication.instance().applicationStateChanged.connect(self._on_application_state)
        self._check_account()
        QTimer.singleShot(0, self._start)

    def _start(self):
        # 若保存或编辑入口已发起过请求，不再追加启动检查。
        if self._last_success is None:
            self.refresh()

    @property
    def username(self):
        return self.store.username

    def image(self, side):
        return self.store.images.get(side)

    def _set_status(self, message):
        self.status = message
        self.status_changed.emit(message)

    def _check_account(self):
        context = self.network.account_context()
        if context == self._context:
            return False
        if self._flight:
            self._flight[3].set()
            self._flight = None
        self.retry_timer.stop()
        self._retry_count = 0
        self._last_success = None
        self._context = context
        self.store.activate(self.network.user_id, self.network.base_url)
        self._set_status("头像待同步" if self.username else "请先登录")
        self.changed.emit()
        return True

    def _on_application_state(self, state):
        self.set_foreground(state == Qt.ApplicationState.ApplicationActive)

    def set_foreground(self, foreground):
        if self._closed or foreground == self._foreground:
            return
        self._foreground = foreground
        if not foreground:
            self.retry_timer.stop()
            return
        self._check_account()
        if self.username and (
            self.store.server["pending"]
            or self._last_success is None
            or monotonic() - self._last_success >= FOREGROUND_CHECK_SECONDS
        ):
            self.refresh()

    def save(self, side, image, *, context=None):
        if self._closed:
            return
        self._check_account()
        if context is not None and context != self._context:
            raise ValueError("账号已变更，请重新选择头像")
        self.store.save(side, image)
        self._set_status("已保存到本地，等待同步")
        self.changed.emit()
        self.refresh()

    def refresh(self):
        """显式检查：编辑入口、手动重试或新保存可重新启用有限重试。"""
        if self._closed:
            return
        self._check_account()
        self.retry_timer.stop()
        self._retry_count = 0
        self._sync_next()

    def _sync_next(self):
        if self._closed or not self._foreground:
            return
        if self._flight or not self.username or not self.network.message_token:
            return
        request = self.store.request(self._context, self.network.message_token)
        results, cancelled = Queue(maxsize=1), Event()
        thread = Thread(target=_fetch, args=(request, results, cancelled), name="avatar-sync", daemon=True)
        self._flight = (thread, results, request, cancelled)
        self._set_status("已保存到本地，正在同步" if self.store.server["pending"] else "正在同步头像")
        thread.start()

    def _collect(self):
        if self._closed:
            return
        if self._check_account():
            self.refresh()
        if not self._flight:
            return
        thread, results, request, _cancelled = self._flight
        if thread.is_alive():
            return
        try:
            result = results.get_nowait()
        except Empty:
            return
        self._flight = None
        if request.context != self.network.account_context():
            self.refresh()
            return
        images_changed = self.store.apply(request, result)
        if not result["ok"]:
            pending = bool(self.store.server["pending"])
            can_retry = pending and self._foreground and self._retry_count < len(UPLOAD_RETRY_MS)
            if can_retry:
                self.retry_timer.start(UPLOAD_RETRY_MS[self._retry_count])
                self._retry_count += 1
            prefix = "已保存到本地，" if pending else ""
            hint = "将自动重试" if can_retry else "请重新打开头像编辑或返回前台重试"
            self._set_status(f"{prefix}头像同步失败，{hint}（{result.get('message', '请求失败')}）")
            return
        self._last_success = monotonic()
        if images_changed:
            self.changed.emit()
        if self.store.server["pending"]:
            # PUT 已返回完整快照；仅继续处理新的待上传修改，不额外 GET。
            self._sync_next()
        else:
            self._retry_count = 0
            self._set_status("头像已同步")

    def close(self):
        self._closed = True
        self.retry_timer.stop()
        self.result_timer.stop()
        if self._flight:
            self._flight[3].set()
            self._flight = None
