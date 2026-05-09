"""
测试脚本：验证 B站动态清洗 + VLM 事件提取全流程。

功能：
① 从 temp/really_raw_dynamics.json 清洗出 OfficialDynamic 对象
② 对于有图片的动态：下载图片 → 转 base64 → 调用 VLM，验证正确调用
   对于无图片的动态：直接调用 VLM（纯文本），验证正确调用
③ 输出清洗后的动态 + 提取事件到 temp/ 文件夹
"""
import asyncio
import json
import os
import sys
import traceback
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.helpers import load_config
from src.plugins.schedule.official_feed_fetcher import OfficialFeedFetcher
from src.plugins.schedule.event_parser import EventParser
from src.plugins.schedule.event_models import OfficialDynamic, ScheduleEvent


async def test_step1_clean_dynamics(fetcher: OfficialFeedFetcher) -> list:
    """
    步骤①：从 temp/really_raw_dynamics.json 清洗出 OfficialDynamic 列表。
    """
    print("=" * 60)
    print("步骤①：清洗动态")
    print("=" * 60)

    raw_file = "temp/really_raw_dynamics.json"
    if not os.path.exists(raw_file):
        print(f"[ERROR] {raw_file} 不存在！请先准备该文件。")
        return []

    with open(raw_file, "r", encoding="utf-8") as f:
        raw_data = json.load(f)

    items = raw_data.get("data", {}).get("items", [])
    print(f"从 {raw_file} 读取到 {len(items)} 条原始动态\n")

    cleaned: list[OfficialDynamic] = []
    for item in items:
        parsed = fetcher._parse_bili_item("36081646", item)
        if parsed:
            cleaned.append(parsed)

    print(f"清洗后得到 {len(cleaned)} 条有效动态\n")

    # 打印摘要
    for i, d in enumerate(cleaned, 1):
        has_pics = "🖼️" if d.pics else "  "
        content_preview = d.content[:80].replace("\n", " ")
        print(f"  [{i:2d}] {has_pics} {d.dynamic_type:20s} | {d.publish_time[:16]} | {content_preview}")

    print()
    return cleaned


async def test_step2_vlm_calls(
    parser: EventParser, cleaned: list[OfficialDynamic]
) -> list[ScheduleEvent]:
    """
    步骤②：对每条动态调用 VLM（有图多模态/无图纯文本），验证能否正常调用。
    """
    print("=" * 60)
    print("步骤②：VLM 调用测试")
    print("=" * 60)

    if parser.vlm_client is None:
        print("[WARN] VLM 客户端未初始化，无法测试 VLM 调用")
        return []

    vlm_info = parser.vlm_client.get_interface_info()
    print(f"VLM 模型: {vlm_info.get('model', '?')}")
    print(f"VLM 端点: {vlm_info.get('base_url', '?')}")
    print()

    all_events: list[ScheduleEvent] = []

    for i, dyn in enumerate(cleaned, 1):
        has_pics_text = "🖼️有图片" if dyn.pics else "📝纯文本"
        preview = dyn.content[:50].replace("\n", " ")
        print(f"[{i:2d}/{len(cleaned)}] {has_pics_text} | {preview}...")

        # 解析单条动态（内部自动调用 VLM）
        events = await parser.parse_one(dyn)
        all_events.extend(events)

        if events:
            for evt in events:
                print(f"        → 事件: [{evt.event_type.value}] {evt.title}")
        else:
            print(f"        → 未提取出事件")

        # 如果是有图动态，额外输出图片信息
        if dyn.pics:
            print(f"        → 图片: {dyn.pics[0][:80]}...")

    print(f"\n总计提取 {len(all_events)} 个事件\n")
    return all_events


async def run() -> None:
    try:
        config = load_config("config/config.json", default_config={})

        # 创建爬取器
        fetcher = OfficialFeedFetcher(config=config)

        # 创建解析器 —— 同时传入 LLM 和 VLM 配置
        llm_cfg = config.get("knowledge", {}).get("llm", {})
        vlm_cfg = (
            config.get("vision_module", {})
            .get("vlm_module", {})
            .get("vlm", {})
        )
        parser = EventParser(llm_config=llm_cfg, vlm_config=vlm_cfg)

        print(f"当前时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        if vlm_cfg:
            print(f"VLM 已配置: {vlm_cfg.get('model', '?')}")
        print()

        # ==== 步骤①：清洗动态 ====
        cleaned = await test_step1_clean_dynamics(fetcher)
        if not cleaned:
            print("没有清洗出任何动态，退出。")
            return

        # ==== 保存清洗后的动态到 temp/ ====
        os.makedirs("temp", exist_ok=True)
        cleaned_dicts = [
            {
                "uid": d.uid,
                "account_name": d.account_name,
                "platform": d.platform,
                "dynamic_id": d.dynamic_id,
                "dynamic_type": d.dynamic_type,
                "content": d.content,
                "raw_content": d.raw_content,
                "pics": d.pics,
                "publish_time": d.publish_time,
                "source_url": d.source_url,
            }
            for d in cleaned
        ]
        cleaned_path = "temp/cleaned_dynamics.json"
        with open(cleaned_path, "w", encoding="utf-8") as f:
            json.dump(cleaned_dicts, f, ensure_ascii=False, indent=2)
        print(f"✅ 清洗后动态已保存到 {cleaned_path}\n")

        # ==== 步骤②：VLM 调用 ====
        all_events = await test_step2_vlm_calls(parser, cleaned)

        # ==== 保存提取的事件到 temp/ ====
        event_dicts = [e.to_dict() for e in all_events]
        events_path = "temp/extracted_events.json"
        with open(events_path, "w", encoding="utf-8") as f:
            json.dump(event_dicts, f, ensure_ascii=False, indent=2)
        print(f"✅ 提取的事件已保存到 {events_path}")

        # 汇总
        print()
        print("=" * 60)
        print("📊 汇总")
        print("=" * 60)
        print(f"  清洗动态数: {len(cleaned)}")
        print(f"  提取事件数: {len(all_events)}")
        print(f"  输出文件:")
        print(f"    - temp/cleaned_dynamics.json")
        print(f"    - temp/extracted_events.json")
        print("=" * 60)

    except Exception as e:
        print(f"\n[FATAL] {e}")
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(run())
