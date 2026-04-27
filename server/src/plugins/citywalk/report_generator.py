from datetime import datetime
from pathlib import Path

from ...utils.helpers import ensure_directory
from .types import CitywalkSessionResult


class CitywalkReportGenerator:
    def __init__(self, title_prefix: str = "逛街小洛"):
        self.title_prefix = title_prefix

    def render(self, result: CitywalkSessionResult) -> str:
        date_str = result.created_at.strftime("%Y-%m-%d")
        lines = [
            f"# {self.title_prefix} | {date_str}",
            "",
            "## 总览",
            f"- 城市: {result.city}",
            f"- 今日目的地: {result.selected_destination or '未记录'}",
            f"- 目的地理由: {result.destination_reason or '未记录'}",
            f"- 起点: {result.start_location}",
            f"- 终点: {result.end_location}",
            f"- 总时长: {result.total_duration_minutes} 分钟",
            f"- 总路程: {result.total_distance_m} 米",
            f"- 剩余体力: {result.energy_left}",
            "",
            "## 去过的地点",
        ]
        if result.events:
            visited_text = ""
            for idx, event in enumerate(result.events, start=1):
                visited_text += f"{event.poi.name}、"
        lines.append(visited_text if result.events else "无")
        lines.extend(["", "## 事件记录"])

        if result.events:
            for idx, event in enumerate(result.events, start=1):
                lines.append(f"- 第{idx}站: {event.poi.name}。{event.__str__()}")
        else:
            lines.append("- 无")

        lines.extend(["", "## 地点分段记录（地点卡片）"])

        for idx, event in enumerate(result.events, start=1):
            time_str = event.timestamp.strftime("%H:%M")
            lines.extend(
                [
                    f"### 第{idx}站 | {event.poi.name}",
                    f"- 时间: {time_str}",
                    f"- 地址: {event.poi.address or '未知'}",
                    f"- 路程: {event.route.distance_m} 米, 预计 {int(round(event.route.duration_s / 60))} 分钟",
                    f"- 体力变化: {event.energy_before} -> {event.energy_after}",
                    f"- 饱腹度变化: {event.fullness_before} -> {event.fullness_after}",
                    f"- 心情变化: {event.mood_before} -> {event.mood_after}",
                ]
            )


        lines.extend(["", "## 去过地点的高德API信息"])
        if result.poi_details:
            for idx, detail in enumerate(result.poi_details, start=1):
                lines.extend(
                    [
                        f"### 第{idx}站详情 | {detail.get('name', '未知地点')}",
                        f"- 类型: {detail.get('type_name', '未知')}",
                        f"- 地址: {detail.get('address', '未知')}",
                        f"- 评分: {detail.get('rating', '未知')}",
                        f"- 招牌菜/标签: {', '.join(detail.get('signature_or_tags', [])) or '无'}",
                        f"- 图片描述: {detail.get('image_description', '无') or '无'}",
                    ]
                )
        else:
            lines.extend(["- 无", ""])

        lines.extend(["## 洛天依今日流水账", ""])
        if result.diary_text:
            lines.extend([result.diary_text, ""])
        else:
            lines.extend(["（未生成）", ""])

        return "\n".join(lines)

    def save(self, result: CitywalkSessionResult, output_dir: str) -> str:
        ensure_directory(output_dir)
        session_tag = result.created_at.strftime("%Y%m%d_%H%M%S")
        filename = f"citywalk_{session_tag}.md"
        output_path = Path(output_dir) / filename
        output_path.write_text(self.render(result), encoding="utf-8")
        return str(output_path)
