import threading

from cli_client.session import HeadlessSession


class FakeWsTransport:
    def __init__(self):
        self._ready = threading.Event()
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
    def __init__(self, overwrite_result):
        self.ws_transport = FakeWsTransport()
        self.overwrite_result = overwrite_result
        self.overwrite_calls = []

    def login(self, username, password, request_token=False):
        return True, "ok"

    def overwrite_preferences(self, preferences):
        self.overwrite_calls.append(preferences)
        return self.overwrite_result


def _session(overwrite_result):
    network = FakeNetworkClient(overwrite_result)
    session = HeadlessSession(base_url="http://test", network_client=network)
    session.connect("user", "pass")
    return session, network


def test_overwrite_preferences_accepts_real_server_success_shape():
    session, network = _session({"status": "success", "message": "Preferences overwritten successfully"})

    result = session.overwrite_preferences({"theme": "light"})

    assert result.get("ok") is True
    assert network.overwrite_calls == [{"theme": "light"}]


def test_overwrite_preferences_reports_real_server_error_shape():
    session, _network = _session({"status": "error", "message": "HTTP 500"})

    result = session.overwrite_preferences({"theme": "light"})

    assert result.get("ok") is False
    assert result.get("error") == "HTTP 500"


def test_overwrite_preferences_reports_not_logged_in_shape():
    session, _network = _session({"status": "error", "message": "Not logged in"})

    result = session.overwrite_preferences({"theme": "light"})

    assert result.get("ok") is False
    assert result.get("error") == "Not logged in"


def test_overwrite_preferences_passes_through_ok_shape():
    session, _network = _session({"ok": True})

    result = session.overwrite_preferences({"theme": "light"})

    assert result.get("ok") is True


def test_overwrite_preferences_rejects_non_dict_response():
    session, _network = _session("unexpected")

    result = session.overwrite_preferences({})

    assert result.get("ok") is False
