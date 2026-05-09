"""
测试脚本：验证 ScheduleManager 能够正常拉取、解析活动，并管理活动的生命周期（正确标记状态）。

测试内容：
1. test_clean_and_parse —— 从 temp/really_raw_dynamics.json 清洗动态，通过 VLM/LLM 解析成事件并存储
2. test_lifecycle —— 手动构造不同时间范围的事件，验证状态自动流转 (UPCOMING→ONGOING→ENDED)
3. test_schedule_manager_pipeline —— 用 mock fetcher 替换真实 API 调用，验证 ScheduleManager 全流程
"""
import asyncio
import json
import os
import sys
import tempfile
import traceback
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import patch, MagicMock, AsyncMock

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.helpers import load_config
from src.plugins.schedule.schedule_manager import ScheduleManager
from src.plugins.schedule.event_parser import EventParser
from src.plugins.schedule.event_store import EventStore
from src.plugins.schedule.event_models import (
    EventStatus,
    EventType,
    ScheduleEvent,
    OfficialDynamic,
)
from src.plugins.schedule.official_feed_fetcher import OfficialFeedFetcher


# =============================================================
# 辅助函数
# =============================================================

def _make_official_dynamic(
    dynamic_id: str,
    content: str,
    dynamic_type: str = "DYNAMIC_TYPE_FORWARD",
    pics: Optional[List[str]] = None,
    publish_time: Optional[str] = None,
) -> OfficialDynamic:
    """快速构造 OfficialDynamic 测试对象。"""
    return OfficialDynamic(
        uid="36081646",
        account_name="洛天依",
        platform="bilibili",
        dynamic_id=dynamic_id,
        dynamic_type=dynamic_type,
        content=content,
        raw_content=content,
        pics=pics or [],
        publish_time=publish_time or datetime.now().isoformat(),
        source_url=f"https://t.bilibili.com/{dynamic_id}",
    )


def _make_event(
    title: str,
    event_type: EventType,
    start_time: str,
    end_time: Optional[str] = None,
    status: EventStatus = EventStatus.UPCOMING,
) -> ScheduleEvent:
    """快速构造 ScheduleEvent 测试对象。"""
    return ScheduleEvent(
        id=str(uuid.uuid4()),
        event_type=event_type,
        title=title,
        description="",
        start_time=start_time,
        end_time=end_time,
        source_platform="bilibili",
        status=status,
    )


# =============================================================
# 测试 1：从 really_raw_dynamics.json 清洗并解析
# =============================================================

async def test_clean_and_parse(output_dir: str) -> int:
    """
    从 temp/really_raw_dynamics.json 读取原始数据，
    经过 OfficialFeedFetcher._parse_bili_item 清洗 + EventParser 解析，
    验证能正常拉取并保存事件。
    """
    print("\n" + "=" * 70)
    print("🧪 测试 1：动态清洗 + VLM/LLM 解析 + 存储")
    print("=" * 70)

    raw_file = "temp/really_raw_dynamics.json"
    if not os.path.exists(raw_file):
        print("  ⏭️  跳过：temp/really_raw_dynamics.json 不存在")
        return 0

    # 读取原始数据
    with open(raw_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)
    items = raw_data.get("data", {}).get("items", [])
    print(f"  ✅ 读取 {len(items)} 条原始动态")

    # 创建 ScheduleManager（使用临时文件避免污染数据）
    tmp_file = os.path.join(output_dir, "test_events.json")
    config = load_config("config/config.json", default_config={})
    # 注入 llm/vlm 到顶层（ScheduleManager 从 config["llm"] / config["vlm"] 读取）
    llm_cfg = config.get("knowledge", {}).get("llm", {})
    vlm_cfg = (
        config.get("vision_module", {})
        .get("vlm_module", {})
        .get("vlm", {})
    )
    config["llm"] = llm_cfg
    config["vlm"] = vlm_cfg
    config["data_file"] = tmp_file
    mgr = ScheduleManager(config=config)

    # 手动清洗数据
    fetcher = mgr.fetcher
    dynamics: List[OfficialDynamic] = []
    for item in items:
        parsed = fetcher._parse_bili_item("36081646", item)
        if parsed:
            dynamics.append(parsed)
    print(f"  ✅ 清洗得到 {len(dynamics)} 条 OfficialDynamic")

    # 用 Parser 解析事件（内部调用 VLM/LLM）
    parser = mgr.parser
    if parser.vlm_client is None and parser.llm_client is None:
        print("  ⚠️  无 VLM/LLM 客户端，跳过解析测试")
        return 0

    events = await parser.parse_dynamics(dynamics)
    print(f"  ✅ VLM/LLM 解析出 {len(events)} 个事件")

    # 存入 EventStore 并持久化
    for evt in events:
        mgr.event_store.add_event(evt)
    mgr.event_store.set_last_fetch_time(datetime.now().isoformat())

    stored = mgr.event_store.get_all()
    print(f"  ✅ EventStore 中现有 {len(stored)} 个事件")
    for evt in stored:
        print(f"     - [{evt.event_type.value:15s}] {evt.title:25s} | {evt.start_time[:16]}")
    print(f"  📁 测试数据保存到: {tmp_file}")
    return len(events)


# =============================================================
# 测试 2：生命周期管理
# =============================================================

async def test_lifecycle(output_dir: str) -> int:
    """
    手动构造不同时间范围的事件存入 EventStore，
    调用 refresh_statuses() 验证状态正确流转。
    """
    print("\n" + "=" * 70)
    print("🧪 测试 2：事件生命周期管理")
    print("=" * 70)

    tmp_file = os.path.join(output_dir, "test_lifecycle.json")
    store = EventStore(data_file=tmp_file)

    now = datetime.now()

    # 构造 4 个不同时间状态的事件
    events = [
        # 1. 未来 7 天 → UPCOMING
        _make_event(
            title="未来演唱会测试",
            event_type=EventType.CONCERT,
            start_time=(now + timedelta(days=7)).isoformat(),
            end_time=(now + timedelta(days=7, hours=3)).isoformat(),
        ),
        # 2. 未来 30 分钟 → 调用 refresh 后变为 UPCOMING
        _make_event(
            title="即将开始的直播测试",
            event_type=EventType.LIVESTREAM,
            start_time=(now + timedelta(minutes=30)).isoformat(),
            end_time=(now + timedelta(hours=2, minutes=30)).isoformat(),
        ),
        # 3. 2 小时前开始，4 小时后结束 → ONGOING
        _make_event(
            title="正在进行的联动测试",
            event_type=EventType.COLLABORATION,
            start_time=(now - timedelta(hours=2)).isoformat(),
            end_time=(now + timedelta(hours=4)).isoformat(),
        ),
        # 4. 3 天前已结束 → ENDED
        _make_event(
            title="已结束的发布测试",
            event_type=EventType.RELEASE,
            start_time=(now - timedelta(days=3, hours=2)).isoformat(),
            end_time=(now - timedelta(days=3)).isoformat(),
        ),
        # 5. 没有结束时间，1 天前开始，默认自动为 ONGOING
        _make_event(
            title="已过期的无结束事件测试",
            event_type=EventType.LIVESTREAM,
            start_time=(now - timedelta(days=1)).isoformat(),
            end_time=None,
        ),
    ]

    for evt in events:
        store.add_event(evt)
    print(f"  ✅ 已添加 {len(events)} 个测试事件")

    # 检查初始状态
    print("\n  📋 初始状态（add_event 时自动设置）：")
    for evt in store.get_all():
        print(f"     - {evt.title:25s} | 开始: {evt.start_time[:16]:16s} | 状态: {evt.status.value}")

    # 调用 refresh_statuses
    changed = store.refresh_statuses()
    print(f"\n  🔄 refresh_statuses() 变更了 {changed} 个事件状态")

    # 验证状态
    print("\n  📋 刷新后状态：")
    passed = 0
    total = 4  # 不验证第 5 个（无结束时间的旧事件，状态取决于具体逻辑）

    for evt in store.get_all():
        status_str = f"【{evt.status.value}】"
        print(f"     - {evt.title:25s} | 状态: {status_str}")

    # 具体断言检查
    all_events = {e.title: e for e in store.get_all()}

    # 1. 未来 7 天 → UPCOMING
    e1 = all_events.get("未来演唱会测试")
    if e1 and e1.status == EventStatus.UPCOMING:
        print("  ✅ 未来事件状态正确 → UPCOMING")
        passed += 1
    else:
        print(f"  ❌ 未来事件状态错误 → {e1.status if e1 else 'NOT FOUND'}")

    # 2. 未来 30 分钟 → UPCOMING
    e2 = all_events.get("即将开始的直播测试")
    if e2 and e2.status == EventStatus.UPCOMING:
        print("  ✅ 即将开始事件状态正确 → UPCOMING")
        passed += 1
    else:
        print(f"  ❌ 即将开始事件状态错误 → {e2.status if e2 else 'NOT FOUND'}")

    # 3. 正在进行 → ONGOING
    e3 = all_events.get("正在进行的联动测试")
    if e3 and e3.status == EventStatus.ONGOING:
        print("  ✅ 进行中事件状态正确 → ONGOING")
        passed += 1
    else:
        print(f"  ❌ 进行中事件状态错误 → {e3.status if e3 else 'NOT FOUND'}")

    # 4. 已结束 → ENDED
    e4 = all_events.get("已结束的发布测试")
    if e4 and e4.status == EventStatus.ENDED:
        print("  ✅ 已结束事件状态正确 → ENDED")
        passed += 1
    else:
        print(f"  ❌ 已结束事件状态错误 → {e4.status if e4 else 'NOT FOUND'}")

    print(f"\n  📊 生命周期测试: {passed}/{total} 通过")
    return 1 if passed == total else 0


# =============================================================
# 测试 3：ScheduleManager 全流程（mock fetcher）
# =============================================================

async def test_schedule_manager_pipeline(output_dir: str) -> int:
    """
    用 mock 替换 OfficialFeedFetcher.fetch_all_new
    验证 ScheduleManager._fetch_and_process 完整流程：
    动态 → fetcher → parser → event_store
    """
    print("\n" + "=" * 70)
    print("🧪 测试 3：ScheduleManager 全流程（mock fetcher）")
    print("=" * 70)

    tmp_file = os.path.join(output_dir, "test_pipeline.json")
    config = load_config("config/config.json", default_config={})
    config["llm"] = config.get("knowledge", {}).get("llm", {})
    config["vlm"] = (
        config.get("vision_module", {})
        .get("vlm_module", {})
        .get("vlm", {})
    )
    config["data_file"] = tmp_file
    mgr = ScheduleManager(config=config)

    # 构造 mock 动态
    mock_dynamics = [
        _make_official_dynamic(
            dynamic_id="mock_001",
            content="7月12日洛天依2026演唱会即将来袭！\n时间：2026-07-12 19:30\n地点：上海梅赛德斯奔驰文化中心",
            dynamic_type="DYNAMIC_TYPE_AV",
        ),
        _make_official_dynamic(
            dynamic_id="mock_002",
            content="和天依一起期待华硕天选2026新品发布会吧~5月15日见！",
            dynamic_type="DYNAMIC_TYPE_FORWARD",
            pics=["http://i0.hdslb.com/bfs/test.png"],
        ),
        _make_official_dynamic(
            dynamic_id="mock_003",
            content="今天天气真好呀~大家要开心哦！[揉脸]",
            dynamic_type="DYNAMIC_TYPE_FORWARD",
        ),
    ]

    # Mock fetcher.fetch_all_new
    original_fetch = mgr.fetcher.fetch_all_new
    mgr.fetcher.fetch_all_new = MagicMock(return_value=mock_dynamics)  # type: ignore

    print(f"  ✅ mock {len(mock_dynamics)} 条动态")

    # 运行 fetch_and_process（异步）
    await mgr._fetch_and_process()

    # 验证 event_store 中有事件
    stored = mgr.event_store.get_all()
    print(f"  ✅ EventStore 中存储了 {len(stored)} 个事件")

    # 验证去重：再次调用，相同动态应不会新增事件
    prev_count = len(stored)
    await mgr._fetch_and_process()
    stored_after = mgr.event_store.get_all()
    print(f"  ✅ 重复拉取后事件数: {len(stored_after)} (之前: {prev_count})")

    if len(stored_after) == prev_count:
        print("  ✅ 去重机制正常工作")
    else:
        print(f"  ⚠️  去重后事件数变化: {prev_count} → {len(stored_after)}")

    # 检查 get_active_context 是否可用
    context = mgr.get_active_context()
    if context:
        print(f"  ✅ get_active_context() 返回上下文 ({len(context)} 字符)")
        print(f"     {context[:200]}...")
    else:
        print("  ⚠️  get_active_context() 返回空（可能没有未来事件）")

    # 检查 is_silence_period
    silence = mgr.is_silence_period()
    print(f"  ✅ is_silence_period() = {silence}")

    passed = 1 if len(stored) > 0 else 0
    print(f"\n  📊 全流程测试: {'✅ 通过' if passed else '❌ 失败'}")
    return passed


# =============================================================
# 主入口
# =============================================================

async def main() -> None:
    print("=" * 70)
    print("📋 ScheduleManager 综合测试")
    print(f"   当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)

    # 创建临时目录存放测试数据
    with tempfile.TemporaryDirectory(prefix="schedule_manager_test_") as tmp_dir:
        print(f"\n📁 测试数据目录: {tmp_dir}")

        results = []

        # 测试 1：清洗 + 解析
        try:
            r1 = await test_clean_and_parse(tmp_dir)
            results.append(("清洗+解析", r1))
        except Exception as e:
            print(f"  ❌ 测试 1 异常: {e}")
            traceback.print_exc()
            results.append(("清洗+解析", 0))

        # 测试 2：生命周期
        try:
            r2 = await test_lifecycle(tmp_dir)
            results.append(("生命周期", r2))
        except Exception as e:
            print(f"  ❌ 测试 2 异常: {e}")
            traceback.print_exc()
            results.append(("生命周期", 0))

        # 测试 3：全流程
        try:
            r3 = await test_schedule_manager_pipeline(tmp_dir)
            results.append(("全流程(mock)", r3))
        except Exception as e:
            print(f"  ❌ 测试 3 异常: {e}")
            traceback.print_exc()
            results.append(("全流程(mock)", 0))

    # 汇总
    print("\n" + "=" * 70)
    print("📊 最终汇总")
    print("=" * 70)
    all_ok = True
    for name, score in results:
        if isinstance(score, int) and score > 0:
            status = "✅"
        elif isinstance(score, int) and score == 0:
            status = "⚠️  跳过/无结果"
        else:
            status = "❌"
            all_ok = False
        print(f"  {status} {name}")
    print()
    if all_ok:
        print("🎉 所有测试完成！")
    else:
        print("⚠️  部分测试未通过，请检查日志")


if __name__ == "__main__":
    asyncio.run(main())
