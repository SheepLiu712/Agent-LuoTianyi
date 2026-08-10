from src.utils.llm import embedding as embedding_module
from src.utils.llm.embedding import SiliconFlowEmbeddings


def test_embedding_request_has_finite_connect_and_read_timeouts(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2]}]}

    def fake_post(_url, **kwargs):
        captured.update(kwargs)
        return Response()

    monkeypatch.setattr(embedding_module.requests, "post", fake_post)
    embeddings = SiliconFlowEmbeddings(
        api_key="test-key",
        connect_timeout_seconds=1.5,
        read_timeout_seconds=4.5,
    )

    assert embeddings.embed_query("hello") == [0.1, 0.2]
    assert captured["timeout"] == (1.5, 4.5)
