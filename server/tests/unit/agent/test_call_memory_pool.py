from src.agent.call import CallMemory, CallMemoryPool


def test_default_capacity_is_ten_and_eviction_is_deterministic():
    pool = CallMemoryPool()
    for index in range(11):
        pool.remember(CallMemory(str(index), f"memory-{index}"))

    assert [memory.memory_id for memory in pool.snapshot()] == [str(index) for index in range(1, 11)]


def test_repeated_hit_moves_memory_to_lru_tail_and_updates_content():
    pool = CallMemoryPool(capacity=3)
    pool.remember(CallMemory("a", "old"))
    pool.remember(CallMemory("b", "second"))
    pool.remember(CallMemory("c", "third"))
    pool.remember(CallMemory("a", "new"))
    pool.remember(CallMemory("d", "fourth"))

    assert pool.snapshot() == (
        CallMemory("c", "third"),
        CallMemory("a", "new"),
        CallMemory("d", "fourth"),
    )
    pool.clear()
    assert pool.snapshot() == ()
