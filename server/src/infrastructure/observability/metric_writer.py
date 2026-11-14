"""Batch telemetry in the parent process; never wait for SQLite on the audio path."""

import queue
import threading
from contextlib import nullcontext

from src.utils.logger import get_logger


class MetricWriter:
    def __init__(self, transaction=nullcontext):
        self._queue = queue.Queue()
        self._lock = threading.Lock()
        self._closed = False
        self._transaction = transaction
        self._thread = threading.Thread(target=self._run, name="metrics-writer", daemon=True)
        self._thread.start()

    def is_writer(self):
        return threading.current_thread() is self._thread

    def submit(self, function, *args, **kwargs):
        with self._lock:
            if self._closed:
                return False
            self._queue.put((function, args, kwargs))
            return True

    def _run(self):
        while True:
            batch = [self._queue.get()]
            while batch[-1] is not None and len(batch) < 256:
                try:
                    batch.append(self._queue.get_nowait())
                except queue.Empty:
                    break
            self._write(batch)
            if batch[-1] is None:
                return

    def _write(self, batch):
        try:
            with self._transaction():
                for item in batch:
                    if item is not None:
                        function, args, kwargs = item
                        try:
                            function(*args, **kwargs)
                        except Exception as error:
                            get_logger(__name__).warning("Metric write failed type=%s", type(error).__name__)
        except Exception as error:
            get_logger(__name__).warning("Metric commit failed type=%s", type(error).__name__)

    def flush(self):
        if self.is_writer():
            return
        reached = threading.Event()
        if self.submit(reached.set):
            reached.wait()
        else:
            self._thread.join()

    def close(self):
        with self._lock:
            if not self._closed:
                self._closed = True
                self._queue.put(None)
        self._thread.join()
