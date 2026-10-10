from concurrent.futures import ThreadPoolExecutor

from src.stage.interaction_lease import InteractionLease, InteractionLeaseRegistry, InteractionSource


class ManualClock:
    def __init__(self) -> None:
        self.now = 100.0

    def __call__(self) -> float:
        return self.now


def _lease(interaction_id: str, source: InteractionSource = InteractionSource.CHAT) -> InteractionLease:
    return InteractionLease("user", "luotianyi", interaction_id, source)


def test_claim_is_atomic_for_same_user_and_character():
    registry = InteractionLeaseRegistry()
    leases = [_lease(f"interaction-{index}") for index in range(24)]

    with ThreadPoolExecutor(max_workers=len(leases)) as executor:
        results = list(executor.map(registry.claim, leases))

    assert sum(results) == 1


def test_release_requires_exact_owner():
    registry = InteractionLeaseRegistry()
    owner = _lease("owner")
    assert registry.claim(owner)
    assert not registry.release(_lease("other"))
    assert registry.release(owner)
    assert registry.claim(_lease("replacement"))


def test_transition_intent_is_bound_one_shot_and_ten_seconds():
    clock = ManualClock()
    registry = InteractionLeaseRegistry(monotonic=clock)
    owner = _lease("chat-1")
    registry.claim(owner)

    intent = registry.prepare_call_transition(lease=owner, client_request_id="request-1")
    assert intent.expires_at == 110.0
    assert (
        registry.consume_call_transition(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id="chat-1",
            client_request_id="wrong",
        )
        is None
    )
    assert (
        registry.consume_call_transition(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id="chat-1",
            client_request_id="request-1",
        )
        == intent
    )
    assert (
        registry.consume_call_transition(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id="chat-1",
            client_request_id="request-1",
        )
        is None
    )


def test_transition_intent_can_be_consumed_by_only_one_racer():
    registry = InteractionLeaseRegistry()
    owner = _lease("chat-1")
    registry.claim(owner)
    registry.prepare_call_transition(lease=owner, client_request_id="request-1")

    def consume():
        return registry.consume_call_transition(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id="chat-1",
            client_request_id="request-1",
        )

    with ThreadPoolExecutor(max_workers=16) as executor:
        results = list(executor.map(lambda _index: consume(), range(16)))

    assert sum(result is not None for result in results) == 1


def test_transition_intent_expires_at_boundary():
    clock = ManualClock()
    registry = InteractionLeaseRegistry(monotonic=clock)
    owner = _lease("chat-1")
    registry.claim(owner)
    registry.prepare_call_transition(lease=owner, client_request_id="request-1")
    clock.now = 110.0

    assert (
        registry.consume_call_transition(
            user_id="user",
            character_id="luotianyi",
            source_interaction_id="chat-1",
            client_request_id="request-1",
        )
        is None
    )
