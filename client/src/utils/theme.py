"""
Voice Theme — PC 客户端统一设计令牌系统

集中定义色彩、字体、圆角等设计令牌，并通过 `load_full_qss()` 将
QSS 模板中的 {{PLACEHOLDER}} 替换为实际色值后返回完整样式表。
"""
import os
from typing import Dict


class VoiceTheme:
    """设计令牌 — 所有 UI 颜色和样式常量的唯一来源。"""

    # ── 主色 ──
    TIANYI_BLUE = "#66CCFF"          # 天依蓝（品牌色）
    TIANYI_BLUE_DEEP = "#3A9BD5"     # 深天依蓝（hover/active）
    TIANYI_BLUE_LIGHT = "#B3E5FC"    # 浅天依蓝（轻量高亮）
    TIANYI_BLUE_GLOW = "#E0F2FE"     # 辉光雾（Agent 气泡背景）

    # ── 背景 ──
    SURFACE = "#FAFAFA"              # 主背景（舞台白）
    CARD = "#FFFFFF"                 # 卡片/面板背景
    CHAT_BG = "#DDDDDD"             # 聊天区背景（保留原色）

    # ── 文字 ──
    TEXT_PRIMARY = "#1E293B"         # 主要文字（板岩黑）
    TEXT_SECONDARY = "#64748B"       # 辅助文字（板岩灰）
    TEXT_DISABLED = "#94A3B8"        # 禁用文字
    TEXT_ON_PRIMARY = "#FFFFFF"      # 主色上的文字

    # ── 边框 & 分割线 ──
    BORDER = "#E2E8F0"              # 默认边框
    DIVIDER = "#B9B9B9"             # 分割线（保留原色）

    # ── 功能色 ──
    ACCENT = "#F97316"              # 暖橙点缀
    SUCCESS = "#34D399"             # 成功绿
    ERROR = "#EF4444"               # 错误红
    WARNING = "#F59E0B"             # 警告黄
    INFO = "#66CCFF"                # 信息蓝

    # ── 气泡 ──
    AGENT_BUBBLE_BG = "#E0F2FE"     # Agent 气泡背景
    USER_BUBBLE_BG = "#FFFFFF"      # 用户气泡背景
    BUBBLE_RADIUS = "10px"          # 气泡圆角

    # ── 字型 ──
    FONT_FAMILY = (
        '"PingFang SC", "Microsoft YaHei UI", '
        '"Noto Sans CJK SC", sans-serif'
    )

    # ── 路径 ──
    QSS_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
        "resources", "qss",
    )

    @classmethod
    def as_dict(cls) -> Dict[str, str]:
        """将所有大写常量展平为 {NAME: value} 字典，供 QSS 替换。"""
        return {
            key: value
            for key, value in vars(cls).items()
            if isinstance(value, str) and not key.startswith("_")
        }

    @classmethod
    def load_qss(cls, filename: str) -> str:
        """读取单个 QSS 文件并替换占位符。"""
        filepath = os.path.join(cls.QSS_DIR, filename)
        if not os.path.exists(filepath):
            return ""
        with open(filepath, "r", encoding="utf-8") as f:
            qss = f.read()
        tokens = cls.as_dict()
        for name, value in tokens.items():
            qss = qss.replace(f"{{{{{name}}}}}", value)
        return qss

    @classmethod
    def load_full_qss(cls) -> str:
        """加载所有 QSS 文件并拼接成完整样式表。"""
        parts = []
        for name in ("voice_base.qss", "voice_chat.qss", "voice_dialogs.qss"):
            qss = cls.load_qss(name)
            if qss.strip():
                parts.append(qss)
        return "\n\n".join(parts)