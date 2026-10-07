"""幂等完成记录（`_completed`）必须有界。

条目本身只保存参数与 sha256 摘要，但**条数**必须有界：否则单个认证账号可以用大量
upload_id 反复 finalize，把服务端的完成记录字典无限撑大（内存放大）。
这里直接验证淘汰规则本身（全局上限 + 每用户上限 + 按最旧淘汰）。
"""

from src.adapter.websocket.voice_upload import (
    MAX_COMPLETED_UPLOADS,
    MAX_COMPLETED_UPLOADS_PER_USER,
    VoiceUploadAssembler,
    _Completed,
)


def _assembler() -> VoiceUploadAssembler:
    return VoiceUploadAssembler(None)


def _entry(completed_at: float) -> _Completed:
    return _Completed(
        parameters=("char", "audio/mp4", "mp4", "aac", 10, 1),
        chunk_digests=(b"x" * 32,),
        message_uuid="message",
        duration_ms=1000,
        completed_at=completed_at,
        persisted=True,
    )


def _fill(assembler: VoiceUploadAssembler, user_id: str, count: int, start: float = 0.0) -> None:
    for index in range(count):
        assembler._completed[(user_id, f"u{index}")] = _entry(start + index)


def test_global_cap_evicts_oldest_first():
    """全局上限：多个用户各自未超每用户上限时，仍要淘汰最旧条目。"""
    assembler = _assembler()
    users = MAX_COMPLETED_UPLOADS // MAX_COMPLETED_UPLOADS_PER_USER + 2  # 18 × 16 = 288 > 256
    stamp = 0.0
    for user in range(users):
        for index in range(MAX_COMPLETED_UPLOADS_PER_USER):
            assembler._completed[(f"user-{user}", f"u{index}")] = _entry(stamp)
            stamp += 1
    assert len(assembler._completed) > MAX_COMPLETED_UPLOADS

    assembler._evict_completed()

    assert len(assembler._completed) == MAX_COMPLETED_UPLOADS
    # 最旧的两个用户（各 16 条）被全局淘汰，其后的用户完整保留。
    assert not [key for key in assembler._completed if key[0] in {"user-0", "user-1"}]
    assert ("user-2", "u0") in assembler._completed


def test_per_user_cap_bounds_a_single_account():
    assembler = _assembler()
    _fill(assembler, "greedy-user", MAX_COMPLETED_UPLOADS_PER_USER + 4)

    assembler._evict_completed()

    assert len(assembler._completed) == MAX_COMPLETED_UPLOADS_PER_USER
    remaining = {key[1] for key in assembler._completed}
    # 最旧的 4 条（u0..u3）被淘汰，其余保留。
    assert remaining == {f"u{index}" for index in range(4, MAX_COMPLETED_UPLOADS_PER_USER + 4)}


def test_per_user_cap_does_not_touch_other_users():
    assembler = _assembler()
    _fill(assembler, "user-a", MAX_COMPLETED_UPLOADS_PER_USER)
    _fill(assembler, "user-b", MAX_COMPLETED_UPLOADS_PER_USER)

    assembler._evict_completed()

    assert len([key for key in assembler._completed if key[0] == "user-a"]) == MAX_COMPLETED_UPLOADS_PER_USER
    assert len([key for key in assembler._completed if key[0] == "user-b"]) == MAX_COMPLETED_UPLOADS_PER_USER


def test_production_insert_path_keeps_the_cache_bounded():
    """生产写入路径（`_remember_completion`）必须自带淘汰——只测算法会漏掉"忘了调用"。"""
    assembler = _assembler()
    for index in range(MAX_COMPLETED_UPLOADS_PER_USER + 5):
        assembler._remember_completion(("greedy-user", f"u{index}"), _entry(float(index)))

    assert len(assembler._completed) == MAX_COMPLETED_UPLOADS_PER_USER


def test_under_the_caps_nothing_is_evicted():
    assembler = _assembler()
    _fill(assembler, "user-a", MAX_COMPLETED_UPLOADS_PER_USER - 1)

    assembler._evict_completed()

    assert len(assembler._completed) == MAX_COMPLETED_UPLOADS_PER_USER - 1
