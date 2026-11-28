"""迁移专用的磁盘暂存内容；生命周期随引用释放，不按归档路径落盘。"""

import hashlib
import tempfile
from pathlib import Path

CHUNK_SIZE = 1024 * 1024


class FileBlob:
    def __init__(self, path, directory=None, on_close=None):
        self.path = Path(path)
        self._directory = directory
        self._stream = None
        self._on_close = on_close

    @property
    def stream(self):
        if self._stream is None:
            self._stream = self.path.open("r+b")
        return self._stream

    def seal(self):
        if self._stream is not None:
            self._stream.close()
            self._stream = None
        return self

    @classmethod
    def temporary(cls):
        directory = tempfile.TemporaryDirectory(prefix="agentluo-transfer-")
        path = Path(directory.name) / "content"
        path.touch(mode=0o600)
        return cls(path, directory)

    @classmethod
    def from_bytes(cls, data):
        result = cls.temporary()
        result.stream.write(data)
        return result.seal()

    @classmethod
    def open(cls, path, *, on_close=None):
        return cls(path, on_close=on_close)

    def __len__(self):
        if self._stream is not None:
            self._stream.flush()
        return self.path.stat().st_size

    def chunks(self):
        self.seal()
        with self.path.open("rb") as source:
            while chunk := source.read(CHUNK_SIZE):
                yield chunk

    def read(self):
        self.seal()
        return self.path.read_bytes()

    def close(self):
        self.seal()
        if self._directory is not None:
            self._directory.cleanup()
            self._directory = None

        if self._on_close is not None:
            release, self._on_close = self._on_close, None
            release()

    def __del__(self):
        self.close()

    def __deepcopy__(self, memo):
        return self


def content_bytes(value):
    return value.read() if isinstance(value, FileBlob) else value


def content_chunks(value):
    return value.chunks() if isinstance(value, FileBlob) else (value,)


def content_digest(value):
    digest = hashlib.sha256()
    for chunk in content_chunks(value):
        digest.update(chunk)
    return digest.hexdigest()
