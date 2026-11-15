"""Bounded embedding transport shared by retrieval and memory projection."""

import asyncio
import math
from concurrent.futures import ThreadPoolExecutor

import httpx
from chromadb.api.types import Documents, EmbeddingFunction, Embeddings


class EmbeddingUnavailable(RuntimeError):
    """Provider failure; safe diagnostic contains no input or credentials."""

    def __init__(self, reason, *, attempts=0, status_code=None):
        self.reason = reason
        self.attempts = attempts
        self.status_code = status_code
        super().__init__(f"embedding unavailable reason={reason} attempts={attempts} status={status_code}")


class SiliconFlowEmbeddings(EmbeddingFunction):
    def __init__(
        self,
        model="BAAI/bge-m3",
        api_key=None,
        base_url="https://api.siliconflow.cn/v1",
        connect_timeout_seconds=5.0,
        read_timeout_seconds=10.0,
        request_timeout_seconds=10.0,
        total_timeout_seconds=30.0,
        max_attempts=3,
    ):
        if not api_key:
            raise ValueError("API key for SiliconFlowEmbeddings cannot be None.")
        self.model, self.api_key = model, api_key
        self.base_url = base_url.rstrip("/")
        for value in (connect_timeout_seconds, read_timeout_seconds, request_timeout_seconds, total_timeout_seconds):
            if not math.isfinite(value) or value <= 0:
                raise ValueError("embedding timeouts must be positive and finite")
        if type(max_attempts) is not int or not 1 <= max_attempts <= 5:
            raise ValueError("embedding max_attempts must be between 1 and 5")
        self.timeout = httpx.Timeout(read_timeout_seconds, connect=connect_timeout_seconds)
        self.request_timeout = request_timeout_seconds
        self.total_timeout = total_timeout_seconds
        self.max_attempts = max_attempts

    def __call__(self, input: Documents) -> Embeddings:
        return self.embed_documents(input)

    def embed_documents(self, texts):
        if not texts:
            return []

        def run():
            return asyncio.run(self.aembed_documents(list(texts)))

        # Chroma exposes a synchronous protocol, also used by synchronous callers in an event loop.
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return run()
        with ThreadPoolExecutor(max_workers=1) as executor:
            return executor.submit(run).result()

    def embed_query(self, *args, **kwargs):
        value = kwargs.get("input", args[0] if args else None)
        return self.embed_documents(value) if isinstance(value, list) else self.embed_documents([value])[0]

    async def aembed_documents(self, texts):
        if not texts:
            return []
        state = {"attempts": 0}
        try:
            return await asyncio.wait_for(self._request(texts, state), timeout=self.total_timeout)
        except asyncio.TimeoutError as exc:
            raise EmbeddingUnavailable("total_timeout", attempts=state["attempts"]) from exc

    async def _request(self, texts, state):
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for attempt in range(1, self.max_attempts + 1):
                state["attempts"] = attempt
                try:
                    response = await asyncio.wait_for(
                        client.post(
                            self.base_url + "/embeddings",
                            headers={"Authorization": f"Bearer {self.api_key}"},
                            json={"model": self.model, "input": texts},
                        ),
                        timeout=self.request_timeout,
                    )
                    response.raise_for_status()
                    return self._vectors(response, len(texts))
                except httpx.HTTPStatusError as exc:
                    status = exc.response.status_code
                    failure = EmbeddingUnavailable("http_status", attempts=attempt, status_code=status)
                    if status not in (408, 429, 500, 502, 503, 504):
                        raise failure from exc
                except (httpx.TransportError, asyncio.TimeoutError) as exc:
                    failure = EmbeddingUnavailable(type(exc).__name__, attempts=attempt)
                if attempt == self.max_attempts:
                    raise failure
                await asyncio.sleep(0.25 * 2 ** (attempt - 1))
        raise AssertionError("unreachable")

    @staticmethod
    def _vectors(response, count):
        try:
            rows = sorted(response.json()["data"], key=lambda row: row["index"])
            if [row["index"] for row in rows] != list(range(count)):
                raise ValueError("embedding count or index mismatch")
            vectors = [row["embedding"] for row in rows]
            if any(
                not isinstance(v, list)
                or not v
                or any(not isinstance(n, (int, float)) or not math.isfinite(n) for n in v)
                for v in vectors
            ):
                raise ValueError("invalid embedding")
            return vectors
        except (KeyError, ValueError, TypeError) as exc:
            raise EmbeddingUnavailable("invalid_response") from exc

    @staticmethod
    def name() -> str:
        return "SiliconFlowEmbeddings"
