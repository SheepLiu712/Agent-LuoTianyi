"""交互式用户数据工具的失败可观察性：删除失败必须体现在进程退出码上。"""

import importlib.util
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "database" / "user_db_tool.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("user_db_tool_under_test", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


class _FailingStore:
    def delete_user_records(self, user_id):
        raise RuntimeError("probe failure")


class _WorkingStore:
    def __init__(self):
        self.deleted = []

    def delete_user_records(self, user_id):
        self.deleted.append(user_id)
        return 3


class _Session:
    def __init__(self):
        self.closed = False
        self.queries = []
        self.commits = 0

    def query(self, *args, **kwargs):
        self.queries.append(args)
        return self

    def filter(self, *args, **kwargs):
        return self

    def first(self):
        return None

    def commit(self):
        self.commits += 1

    def close(self):
        self.closed = True


def _real_reset_service_with_failing_vectors(**_kwargs):
    """用真实 UserResetService：向量步骤失败应被映射成 vectors 失败步骤，而不是抛到调用方。"""
    from src.application.user.user_reset import UserResetService

    return UserResetService(
        conversation_service=SimpleNamespace(reset_user_conversations=lambda user_id: 0),
        vector_store=_FailingStore(),
        redis_buffer=SimpleNamespace(clear_user=lambda user_id: None),
        media_store=SimpleNamespace(
            delete_owned_by=lambda owner_user_id: SimpleNamespace(deleted_count=0, failures=())
        ),
    )


def _drive(monkeypatch, module, *, store, choices, capsys, session=None):
    """按给定菜单选择驱动 main()，返回执行后的状态。"""
    session = session if session is not None else _Session()
    answers = iter(choices)
    monkeypatch.setattr(module, "_init_databases", lambda: None)
    monkeypatch.setattr(module, "get_sql_session", lambda: session)
    monkeypatch.setattr(module, "get_redis_buffer", lambda: SimpleNamespace())
    monkeypatch.setattr(module, "get_vector_store", lambda: store)
    monkeypatch.setattr(module, "load_config", lambda *args, **kwargs: {})
    monkeypatch.setattr(module, "PermanentMediaStore", lambda *args, **kwargs: SimpleNamespace())
    # 真实数据库未初始化：只提供 _reset_user 构造服务时需要的占位组合根。
    monkeypatch.setattr(
        module,
        "database_service",
        SimpleNamespace(get_database_manager=lambda: SimpleNamespace(conversation_service=SimpleNamespace())),
    )
    monkeypatch.setattr(
        module, "_authenticate", lambda *args, **kwargs: SimpleNamespace(username="probe", uuid="user-1")
    )
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: next(answers))
    monkeypatch.setattr(module, "getpass", lambda *args, **kwargs: next(answers))
    module.main()
    return session, capsys.readouterr()


def test_delete_all_vector_records_reports_failure_with_traceback(monkeypatch, capsys):
    module = load_tool()
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "YES")

    assert module._delete_all_vector_records(_FailingStore(), SimpleNamespace(uuid="user-1")) is False

    captured = capsys.readouterr()
    assert "删除向量数据库记录失败：RuntimeError: probe failure" in captured.out
    # 保留调用栈，便于定位是 ChromaDB 的哪一层失败。
    assert "Traceback (most recent call last)" in captured.err + captured.out


def test_delete_all_vector_records_treats_cancellation_as_not_failed(monkeypatch, capsys):
    module = load_tool()
    monkeypatch.setattr("builtins.input", lambda *args, **kwargs: "no")

    assert module._delete_all_vector_records(_FailingStore(), SimpleNamespace(uuid="user-1")) is True

    assert "已取消删除。" in capsys.readouterr().out


def test_main_exits_nonzero_when_a_delete_fails(monkeypatch, capsys):
    module = load_tool()

    with pytest.raises(SystemExit) as caught:
        _drive(monkeypatch, module, store=_FailingStore(), choices=["probe", "secret", "4", "YES", "0"], capsys=capsys)

    assert caught.value.code == 1


def test_main_exits_zero_after_a_successful_delete(monkeypatch, capsys):
    module = load_tool()
    store = _WorkingStore()

    session, captured = _drive(
        monkeypatch, module, store=store, choices=["probe", "secret", "4", "YES", "0"], capsys=capsys
    )

    assert store.deleted == ["user-1"]
    assert "已删除 3 条向量数据库记录。" in captured.out
    assert "已退出。" in captured.out
    assert session.closed is True


def test_main_exits_nonzero_when_full_reset_fails_and_skips_profile_update(monkeypatch, capsys):
    module = load_tool()
    session = _Session()
    monkeypatch.setattr(module, "UserResetService", _real_reset_service_with_failing_vectors)

    with pytest.raises(SystemExit) as caught:
        _drive(
            monkeypatch,
            module,
            store=_WorkingStore(),
            choices=["probe", "secret", "6", "YES", "0"],
            capsys=capsys,
            session=session,
        )

    assert caught.value.code == 1
    assert session.closed is True
    # 完全重置失败时不得继续改画像：既不查询也不提交。
    assert session.queries == []
    assert session.commits == 0
    captured = capsys.readouterr()
    assert "完全重置失败" in captured.out
    assert "vectors" in captured.out
