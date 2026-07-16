"""
Voice Theme — PC 客户端统一设计令牌系统

集中定义色彩、字体、圆角等设计令牌，并通过 `load_full_qss()` 将
QSS 模板中的 {{PLACEHOLDER}} 替换为实际色值后返回完整样式表。
"""
import os
import sys
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

    # ── 文字 ──
    TEXT_PRIMARY = "#1E293B"         # 主要文字（板岩黑）
    TEXT_SECONDARY = "#64748B"       # 辅助文字（板岩灰）
    TEXT_DISABLED = "#94A3B8"        # 禁用文字
    TEXT_ON_PRIMARY = "#FFFFFF"      # 主色上的文字

    # ── 边框 & 分割线 ──
    BORDER = "#E2E8F0"              # 默认边框

    # ── 功能色 ──
    ERROR = "#EF4444"               # 错误红

    # ── 动态对话框 ──
    DYNAMICS_SURFACE = "#F6F7F9"    # 动态页背景（区别于主背景的冷白）
    DYNAMICS_ACTION = "#1296DB"     # 动态编辑器操作按钮色
    DYNAMICS_ERROR = "#A35C00"      # 动态错误/警告文字

    # ── 气泡 ──
    AGENT_BUBBLE_BG = "#E0F2FE"     # Agent 气泡背景
    USER_BUBBLE_BG = "#FFFFFF"      # 用户气泡背景

    # ── 字型 ──
    FONT_FAMILY = (
        '"PingFang SC", "Microsoft YaHei UI", '
        '"Noto Sans CJK SC", sans-serif'
    )

    # ── 路径 ──
    # 在 frozen (PyInstaller) 环境下，QSS 文件相对于可执行文件路径查找
    if getattr(sys, "frozen", False):
        _base = os.path.dirname(os.path.abspath(sys.executable))
    else:
        _base = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
    QSS_DIR = os.path.join(_base, "resources", "qss")

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