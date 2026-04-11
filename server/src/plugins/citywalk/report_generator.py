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
            f"- 起点: {result.start_location}",
            f"- 终点: {result.end_location}",
            f"- 总时长: {result.total_duration_minutes} 分钟",
            f"- 总路程: {result.total_distance_m} 米",
            f"- 剩余体力: {result.energy_left}",
            "",
            "## 地点卡片",
        ]

        for idx, event in enumerate(result.events, start=1):
            time_str = event.timestamp.strftime("%H:%M")
            lines.extend(
                [
                    f"### 第{idx}站 | {event.poi.name}",
                    f"- 时间: {time_str}",
                    f"- 地址: {event.poi.address or '未知'}",
                    f"- 路程: {event.route.distance_m} 米, 预计 {int(round(event.route.duration_s / 60))} 分钟",
                    f"- 活动: {event.activity}",
                    f"- 当时想法: {event.thought}",
                    f"- 体力变化: {event.energy_before} -> {event.energy_after}",
                    "",
                ]
            )

        return "\n".join(lines)

    def save(self, result: CitywalkSessionResult, output_dir: str) -> str:
        ensure_directory(output_dir)
        session_tag = result.created_at.strftime("%Y%m%d_%H%M%S")
        filename = f"citywalk_{session_tag}.md"
        output_path = Path(output_dir) / filename
        output_path.write_text(self.render(result), encoding="utf-8")
        return str(output_path)
