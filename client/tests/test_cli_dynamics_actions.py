import threading

import pytest

from src.cli.actions import ActionExecutor, ExitCode
from src.session import HeadlessSession, SessionNotReadyError, SessionState


class FakeSession:
    def __init__(self):
        self.state = SessionState.READY
        self.pages = {}
        self.default_page = {"items": [], "next_cursor": None, "has_more": False}
        self.comments = {}
        self.mark_calls = 0
        self.mark_result = {"ok": True}
        self.created = []
        self.create_result = {"ok": True, "dynamic_id": "d-new"}
        self.get_calls = []
        self.comment_calls = []

    def get_dynamics(self, limit=50, cursor=None):
        self.get_calls.append({"limit": limit, "cursor": cursor})
        key = cursor if cursor is not None else "__first__"
        return dict(self.pages.get(key, self.default_page))

    def get_dynamic_comments(self, dynamic_id, limit=100, cursor=None):
        self.comment_calls.append({"dynamic_id": dynamic_id, "limit": limit, "cursor": cursor})
        return dict(
            self.comments.get(
                dynamic_id,
                {"comments": [], "next_cursor": None, "has_more": False},
            )
        )

    def create_dynamic(self, content):
        self.created.append(content)
        return dict(self.create_result)

    def mark_dynamics_read(self):
        self.mark_calls += 1
        return dict(self.mark_result)

    def close(self):
        self.state = SessionState.CLOSED


def _executor(session):
    executor = ActionExecutor(
        session_factory=lambda **_kwargs: session,
        session_id="session-dynamics",
    )
    executor._session = session
    return executor


def _action(executor, action, **params):
    return executor.execute({"action": action, "params": params})


def test_dynamics_open_stores_view_and_marks_read():
    session = FakeSession()
    session.pages["__first__"] = {
        "items": [{"id": "d1", "content": "one"}, {"id": "d2", "content": "two"}],
        "next_cursor": "c1",
        "has_more": True,
    }
    executor = _executor(session)

    record, exit_code = _action(executor, "dynamics.open")

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["count"] == 2
    assert record["data"]["has_more"] is True
    assert record["data"]["marked_read"] is True
    assert record["data"]["mark_error"] is None
    assert [item["id"] for item in record["data"]["items"]] == ["d1", "d2"]
    assert session.mark_calls == 1


def test_dynamics_open_reports_mark_read_failure_separately():
    session = FakeSession()
    session.pages["__first__"] = {
        "items": [{"id": "d1", "content": "one"}],
        "next_cursor": None,
        "has_more": False,
    }
    session.mark_result = {"ok": False, "error": "mark endpoint down"}
    executor = _executor(session)

    record, exit_code = _action(executor, "dynamics.open")

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["count"] == 1
    assert record["data"]["marked_read"] is False
    assert "mark endpoint down" in record["data"]["mark_error"]


def test_dynamics_load_appends_with_dedupe_and_reaches_end_of_feed():
    session = FakeSession()
    session.pages["__first__"] = {
        "items": [{"id": "d1"}, {"id": "d2"}],
        "next_cursor": "c1",
        "has_more": True,
    }
    session.pages["c1"] = {
        "items": [{"id": "d1"}, {"id": "d3"}],
        "next_cursor": None,
        "has_more": False,
    }
    executor = _executor(session)
    assert _action(executor, "dynamics.open")[1] == ExitCode.SUCCESS

    record, exit_code = _action(executor, "dynamics.load")

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["appended"] == 1
    assert record["data"]["count"] == 3
    assert record["data"]["end_of_feed"] is True
    assert [item["id"] for item in record["data"]["items"]] == ["d1", "d2", "d3"]

    page_calls = len(session.get_calls)
    record2, exit_code2 = _action(executor, "dynamics.load")
    assert exit_code2 == ExitCode.SUCCESS
    assert record2["data"]["end_of_feed"] is True
    assert len(session.get_calls) == page_calls


def test_dynamics_load_without_open_is_rejected():
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _action(executor, "dynamics.load")

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "DYNAMICS_NOT_OPENED"
    assert session.get_calls == []


def test_dynamics_read_returns_comments_and_loaded_post():
    session = FakeSession()
    session.pages["__first__"] = {
        "items": [{"id": "d1", "content": "one"}],
        "next_cursor": None,
        "has_more": False,
    }
    session.comments["d1"] = {
        "comments": [{"id": "c1", "content": "hi"}],
        "next_cursor": None,
        "has_more": False,
    }
    executor = _executor(session)
    assert _action(executor, "dynamics.open")[1] == ExitCode.SUCCESS

    record, exit_code = _action(executor, "dynamics.read", dynamic_id="d1")

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["dynamic_id"] == "d1"
    assert record["data"]["post"]["content"] == "one"
    assert record["data"]["comment_count"] == 1
    assert record["data"]["comments"][0]["id"] == "c1"


def test_dynamics_read_without_loaded_view_outputs_post_null():
    session = FakeSession()
    session.comments["d9"] = {
        "comments": [],
        "next_cursor": None,
        "has_more": False,
    }
    executor = _executor(session)

    record, exit_code = _action(executor, "dynamics.read", dynamic_id="d9")

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["post"] is None
    assert record["data"]["comment_count"] == 0


def test_dynamics_read_requires_dynamic_id():
    session = FakeSession()
    executor = _executor(session)

    record, exit_code = _action(executor, "dynamics.read")

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "INVALID_INPUT"
    assert session.comment_calls == []


def test_dynamics_post_confirms_visibility_and_does_not_repeat():
    session = FakeSession()
    session.pages["__first__"] = {
        "items": [{"id": "d-new", "content": "hello world"}],
        "next_cursor": None,
        "has_more": False,
    }
    executor = _executor(session)

    record, exit_code = _action(executor, "dynamics.post", content="hello world")

    assert exit_code == ExitCode.SUCCESS
    assert record["data"]["visible"] is True
    assert record["data"]["dynamic_id"] == "d-new"
    assert record["data"]["content_length"] == len("hello world")
    assert record["data"]["preview"] == "hello world"
    assert session.created == ["hello world"]


def test_dynamics_post_created_but_not_visible_fails():
    session = FakeSession()
    session.pages["__first__"] = {"items": [], "next_cursor": None, "has_more": False}
    executor = _executor(session)

    record, exit_code = _action(executor, "dynamics.post", content="ghost post")

    assert exit_code == ExitCode.ASSERTION_FAILED
    assert record["error"]["code"] == "DYNAMICS_NOT_VISIBLE"
    assert session.created == ["ghost post"]


@pytest.mark.parametrize("content", [None, "", "   "])
def test_dynamics_post_requires_non_empty_content(content):
    session = FakeSession()
    executor = _executor(session)
    params = {} if content is None else {"content": content}

    record, exit_code = executor.execute({"action": "dynamics.post", "params": params})

    assert exit_code == ExitCode.INPUT_ERROR
    assert record["error"]["code"] == "INVALID_INPUT"
    assert session.created == []


class FakeWsTransport:
    def __init__(self, *, ready=True):
        self._ready = threading.Event()
        if ready:
            self._ready.set()
        self.listener = None
        self.state_listener = None

    def set_agent_message_listener(self, listener, state_listener, system_listener=None):
        self.listener = listener
        self.state_listener = state_listener

    def wait_until_ready(self, timeout):
        return self._ready.wait(timeout)

    def is_ready(self):
        return self._ready.is_set()

    def stop(self):
        self._ready.clear()


class FakeNetworkClient:
    def __init__(self, *, ready=True):
        self.ws_transport = FakeWsTransport(ready=ready)
        self.dynamics_calls = []
        self.comment_calls = []
        self.create_calls = []
        self.mark_calls = 0

    def login(self, username, password, request_token=False):
        return True, "ok"

    def get_dynamics(self, limit=50, cursor=None):
        self.dynamics_calls.append({"limit": limit, "cursor": cursor})
        return {"items": [], "next_cursor": None, "has_more": False}

    def get_dynamic_comments(self, dynamic_id, limit=100, cursor=None):
        self.comment_calls.append({"dynamic_id": dynamic_id, "limit": limit, "cursor": cursor})
        return {"comments": [], "next_cursor": None, "has_more": False}

    def create_dynamic(self, content):
        self.create_calls.append(content)
        return {"ok": True, "dynamic_id": "d-x"}

    def mark_dynamics_read(self):
        self.mark_calls += 1
        return {"ok": True}


def test_facade_dynamics_methods_delegate_and_require_ready():
    network = FakeNetworkClient(ready=True)
    session = HeadlessSession(base_url="http://test", network_client=network)
    session.connect("user", "pass")

    assert session.get_dynamics(limit=5, cursor="c9") == {
        "items": [],
        "next_cursor": None,
        "has_more": False,
    }
    session.get_dynamic_comments("d1", limit=7)
    session.create_dynamic("hi")
    session.mark_dynamics_read()

    assert network.dynamics_calls == [{"limit": 5, "cursor": "c9"}]
    assert network.comment_calls == [{"dynamic_id": "d1", "limit": 7, "cursor": None}]
    assert network.create_calls == ["hi"]
    assert network.mark_calls == 1

    cold = HeadlessSession(base_url="http://test", network_client=FakeNetworkClient(ready=False))
    with pytest.raises(SessionNotReadyError):
        cold.get_dynamics()
