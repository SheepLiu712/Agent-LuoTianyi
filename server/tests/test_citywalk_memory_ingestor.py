from datetime import datetime

from src.plugins.citywalk.memory_ingestor import CitywalkMemoryIngestor
from src.plugins.citywalk.types import CitywalkEvent, CitywalkSessionResult, POI, RouteResult


class FakeVectorStore:
    def __init__(self):
        self.docs = []

    def add_documents(self, documents):
        self.docs.extend(documents)
        return [str(i) for i in range(len(documents))]


class _FakeCompletions:
    def create(self, **kwargs):
        class Msg:
            content = '{"timeline":["10:00 南锣鼓巷 看了街头表演","10:30 咖啡店 喝了拿铁"]}'

        class Choice:
            message = Msg()

        class Resp:
            choices = [Choice()]

        return Resp()


class _FakeChat:
    completions = _FakeCompletions()


class FakeLLMClient:
    chat = _FakeChat()


def _build_session_result() -> CitywalkSessionResult:
    poi = POI(poi_id="1", name="南锣鼓巷", location="116.4,39.9", type_name="景点")
    route = RouteResult(reachable=True, distance_m=120, duration_s=180)
    event = CitywalkEvent(
        timestamp=datetime(2026, 4, 27, 10, 0),
        poi=poi,
        route=route,
        poi_content={},
        moving_activity="步行约3分钟到达南锣鼓巷",
        poi_activity="看了街头表演",
        energy_before=90,
        energy_after=85,
        mood_before=70,
        mood_after=80,
        fullness_before=60,
        fullness_after=58,
        travel_min=3,
        activity_min=20,
        llm_reason="想感受胡同氛围",
    )
    return CitywalkSessionResult(
        city="北京",
        start_location="116.3,39.9",
        end_location="116.4,39.9",
        total_distance_m=120,
        total_duration_minutes=23,
        energy_left=85,
        events=[event],
        created_at=datetime(2026, 4, 27, 12, 0),
        diary_text="今天在南锣鼓巷看了街头表演。",
    )


def test_ingest_session_with_llm_split():
    vector_store = FakeVectorStore()
    cfg = {"decision": {"llm": {"api_key": "test_key"}}}
    ingestor = CitywalkMemoryIngestor(cfg, vector_store, llm_client=FakeLLMClient())

    count = ingestor.ingest_session(_build_session_result())

    assert count == 2
    assert len(vector_store.docs) == 2
    metadata = vector_store.docs[0].get_metadata()
    assert metadata["is_citywalk_data"] is True
    assert metadata["citywalk_date"] == "2026-04-27"
    assert metadata["source"] == "citywalk"


def test_ingest_session_fallback_without_llm():
    vector_store = FakeVectorStore()
    cfg = {"decision": {"llm": {"api_key": ""}}}
    ingestor = CitywalkMemoryIngestor(cfg, vector_store, llm_client=None)

    count = ingestor.ingest_session(_build_session_result())

    assert count >= 1
    assert "南锣鼓巷" in vector_store.docs[0].get_content()
