"""
农历日期工具函数：公历/农历转换，节日判断。
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Optional, Tuple


def solar_to_lunar(year: int, month: int, day: int) -> Optional[Tuple[int, int, int]]:
    """公历转农历，返回 (lunar_year, lunar_month, lunar_day) 或 None。"""
    try:
        from lunardate import LunarDate
        lunar = LunarDate.fromSolarDate(year, month, day)
        return (lunar.year, lunar.month, lunar.day)
    except ImportError:
        return None
    except Exception:
        return None


def lunar_to_solar(lunar_year: int, lunar_month: int, lunar_day: int) -> Optional[Tuple[int, int, int]]:
    """农历转公历，返回 (year, month, day) 或 None。"""
    try:
        from lunardate import LunarDate
        solar = LunarDate(lunar_year, lunar_month, lunar_day).toSolarDate()
        return (solar.year, solar.month, solar.day)
    except ImportError:
        return None
    except Exception:
        return None


def get_lunar_mmdd(solar_year: int, solar_month: int, solar_day: int) -> Optional[str]:
    """获取公历日期对应的农历 MM-DD 字符串。"""
    result = solar_to_lunar(solar_year, solar_month, solar_day)
    if result is None:
        return None
    _, lunar_month, lunar_day = result
    return f"{lunar_month:02d}-{lunar_day:02d}"


def is_lunar_new_year_eve(solar_year: int, solar_month: int, solar_day: int) -> bool:
    """判断是否是农历除夕（腊月廿九或三十）。"""
    from lunardate import LunarDate
    try:
        lunar = LunarDate.fromSolarDate(solar_year, solar_month, solar_day)
        # 除夕是农历最后一天
        next_day_lunar = LunarDate.fromSolarDate(solar_year, solar_month, solar_day + 1)
        return next_day_lunar.month == 1 and next_day_lunar.day == 1
    except Exception:
        return False


# ── 常见中国节日（公历固定） ──────────────────────────────

FIXED_SOLAR_HOLIDAYS = {
    "01-01": ("元旦", "元旦节"),
    "02-14": ("情人节", "情人节"),
    "03-08": ("妇女节", "国际妇女节"),
    "04-01": ("愚人节", "愚人节"),
    "05-01": ("劳动节", "国际劳动节"),
    "05-04": ("青年节", "五四青年节"),
    "05-12": ("护士节", "国际护士节"),
    "06-01": ("儿童节", "国际儿童节"),
    "07-01": ("建党节", "中国共产党建党纪念日"),
    "08-01": ("建军节", "中国人民解放军建军节"),
    "09-10": ("教师节", "教师节"),
    "10-01": ("国庆节", "国庆节"),
    "10-31": ("万圣节", "万圣节"),
    "12-25": ("圣诞节", "圣诞节"),
    "05-20": ("网络情人节", "谐音'我爱你'的网络情人节"),
    "05-21": ("天依节", "谐音'我爱依'的喜欢洛天依的节日"),
    "04-12": ("乐正绫生日", "乐正绫的生日"),
    "07-12": ("洛天依生日", "洛天依的生日"),
    "07-11": ("言和生日", "言和的生日"),
    "11-11": ("光棍节", "双十一光棍节/购物节"),
}

# ── 常见中国节日（农历） ──────────────────────────────

LUNAR_HOLIDAYS_MMDD = {
    "01-01": ("春节", "农历新年"),
    "01-15": ("元宵节", "元宵节/上元节"),
    "05-05": ("端午节", "端午节"),
    "07-07": ("七夕节", "七夕节/乞巧节"),
    "07-15": ("中元节", "中元节/盂兰盆节"),
    "08-15": ("中秋节", "中秋节"),
    "09-09": ("重阳节", "重阳节/登高节"),
    "12-30": ("除夕", "除夕夜（腊月三十）"),  # fallback
}


def get_holiday_name(solar_year: int, solar_month: int, solar_day: int) -> Optional[str]:
    """获取公历日期对应的节日名称（如有）。"""
    mmdd = f"{solar_month:02d}-{solar_day:02d}"

    # 1) 检查固定公历节日
    if mmdd in FIXED_SOLAR_HOLIDAYS:
        return FIXED_SOLAR_HOLIDAYS[mmdd][0]

    # 2) 检查农历节日
    lunar_mmdd = get_lunar_mmdd(solar_year, solar_month, solar_day)
    if lunar_mmdd and lunar_mmdd in LUNAR_HOLIDAYS_MMDD:
        return LUNAR_HOLIDAYS_MMDD[lunar_mmdd][0]

    # 3) 特判除夕
    if is_lunar_new_year_eve(solar_year, solar_month, solar_day):
        return "除夕夜"

    return None


def get_holiday_description(solar_year: int, solar_month: int, solar_day: int) -> Optional[str]:
    """获取公历日期对应的节日描述（如有）。"""
    mmdd = f"{solar_month:02d}-{solar_day:02d}"

    if mmdd in FIXED_SOLAR_HOLIDAYS:
        return FIXED_SOLAR_HOLIDAYS[mmdd][1]

    lunar_mmdd = get_lunar_mmdd(solar_year, solar_month, solar_day)
    if lunar_mmdd and lunar_mmdd in LUNAR_HOLIDAYS_MMDD:
        return LUNAR_HOLIDAYS_MMDD[lunar_mmdd][1]

    if is_lunar_new_year_eve(solar_year, solar_month, solar_day):
        return "除夕夜"

    return None
