"""
Cookie 自动管理模块：检测 B站 Cookie 过期状态，使用无头浏览器刷新 Cookie。
"""
from __future__ import annotations

import asyncio
import json
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from playwright.async_api import async_playwright

from src.utils.logger import get_logger

logger = get_logger(__name__)

# 过期阈值（秒）：距离过期小于此值时触发刷新
SESSDATA_EXPIRE_THRESHOLD = 7 * 24 * 3600      # SESSDATA 还剩 7 天过期时刷新
BILL_TICKET_EXPIRE_THRESHOLD = 6 * 3600   # bili_ticket 还剩 6 小时过期时刷新


def _parse_cookie_expiry(cookie_str: str) -> dict:
    """
    从 cookie 字符串中提取 SESSDATA 和 bili_ticket 的过期时间信息。

    SESSDATA 格式形如: c2ea5c10%2C1793600231%2C82e16%2A...
    第二个字段（以 %2C 分隔) 是 Unix 时间戳。
    bili_ticket_expires 是直接的 Unix 时间戳数值。
    bili_ticket 是 JWT，里面 payload 有 exp 字段。

    返回值: {
        "sessdata_ts": int | None,
        "sessdata_expire_str": str | None,
        "bili_ticket_ts": int | None,
        "bili_ticket_expire_str": str | None,
        "all_good": bool,   # True = 都未过期或不存在
    }
    """
    result: dict = {
        "sessdata_ts": None,
        "sessdata_expire_str": None,
        "bili_ticket_ts": None,
        "bili_ticket_expire_str": None,
        "all_good": True,
    }

    now_ts = int(time.time())

    # ── 解析 SESSDATA ──────────────────────────────────────────
    m_sess = re.search(r"SESSDATA=([^;]+)", cookie_str)
    if m_sess:
        raw = m_sess.group(1)
        # 解码 %2C -> ,
        decoded = raw.replace("%2C", ",")
        parts = decoded.split(",")
        if len(parts) >= 2:
            try:
                sess_ts = int(parts[1])
                result["sessdata_ts"] = sess_ts
                result["sessdata_expire_str"] = datetime.fromtimestamp(
                    sess_ts, tz=timezone.utc
                ).strftime("%Y-%m-%d %H:%M:%S")
                if sess_ts - now_ts < SESSDATA_EXPIRE_THRESHOLD:
                    result["all_good"] = False
                    logger.info(
                        f"SESSDATA 将在 {sess_ts - now_ts} 秒后过期 "
                        f"({result['sessdata_expire_str']} UTC)，需要刷新"
                    )
                else:
                    logger.info(
                        f"SESSDATA 有效期至 {result['sessdata_expire_str']} UTC，"
                        f"剩余 {sess_ts - now_ts} 秒"
                    )
            except (ValueError, IndexError):
                logger.warning("无法解析 SESSDATA 过期时间")

    # ── 解析 bili_ticket_expires ──────────────────────────────
    m_ticket_exp = re.search(r"bili_ticket_expires=(\d+)", cookie_str)
    if m_ticket_exp:
        try:
            ticket_ts = int(m_ticket_exp.group(1))
            result["bili_ticket_ts"] = ticket_ts
            result["bili_ticket_expire_str"] = datetime.fromtimestamp(
                ticket_ts, tz=timezone.utc
            ).strftime("%Y-%m-%d %H:%M:%S")
            if ticket_ts - now_ts < BILL_TICKET_EXPIRE_THRESHOLD:
                result["all_good"] = False
                logger.info(
                    f"bili_ticket 将在 {ticket_ts - now_ts} 秒后过期 "
                    f"({result['bili_ticket_expire_str']} UTC)，需要刷新"
                )
            else:
                logger.info(
                    f"bili_ticket 有效期至 {result['bili_ticket_expire_str']} UTC，"
                    f"剩余 {ticket_ts - now_ts} 秒"
                )
        except (ValueError, IndexError):
            logger.warning("无法解析 bili_ticket_expires")

    return result


def _parse_set_cookie_to_jar(new_cookies: list[dict]) -> dict[str, str]:
    """
    将 Playwright 获取的浏览器 cookie 列表转换为 key=value 字典。
    """
    jar: dict[str, str] = {}
    for c in new_cookies:
        name = c.get("name", "")
        value = c.get("value", "")
        if name and value:
            jar[name] = value
    return jar


def _jar_to_cookie_string(jar: dict[str, str]) -> str:
    """将 cookie 字典转为 "; " 连接的字符串。"""
    return "; ".join(f"{k}={v}" for k, v in jar.items())


def _merge_cookies(old_cookie: str, new_jar: dict[str, str]) -> str:
    """
    将旧的 cookie 字符串与新的 cookie 字典合并。
    新 cookie 覆盖旧 cookie 的同名字段，其余保留旧值。
    这样只更新 SESSDATA / bili_ticket 等关键字段，保留 buvid 等不变。
    """
    # 解析旧 cookie 为字典
    old_parts = old_cookie.split(";")
    old_jar: dict[str, str] = {}
    for part in old_parts:
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            old_jar[k.strip()] = v.strip()

    # 用新值覆盖
    old_jar.update(new_jar)
    return _jar_to_cookie_string(old_jar)


async def check_and_refresh_cookie_async(cookie_file: Path, force: bool = False) -> bool:
    """
    检查 cookie 是否需要刷新，如果需要则用无头浏览器访问 B站 更新。

    Args:
        cookie_file: cookie 文件路径
        force: 如果 True，无论过期状态都强制刷新.

    Returns:
        True 表示 cookie 已更新（或无需更新），
        False 表示更新失败。
    """
    if not cookie_file.exists():
        logger.warning(f"Cookie 文件不存在: {cookie_file}")
        return False

    old_cookie = cookie_file.read_text(encoding="utf-8-sig").strip()

    # ── 检查过期状态 ────────────────────────────────────
    info = _parse_cookie_expiry(old_cookie)
    if info["all_good"] and not force:
        logger.info("Cookie 均未过期，无需刷新")
        return True

    # ── 用无头浏览器访问 B站 首页 ──────────────────────
    logger.info("正在使用无头浏览器访问 B站 首页以刷新 Cookie...")
    try:
        new_cookies = await _visit_bilibili_with_browser(old_cookie)
    except Exception as e:
        logger.error(f"浏览器访问 B站 失败: {e}")
        return False

    if not new_cookies:
        logger.warning("未获取到任何新 Cookie")
        return False

    # ── 合并并保存 ──────────────────────────────────────
    new_jar = _parse_set_cookie_to_jar(new_cookies)
    merged = _merge_cookies(old_cookie, new_jar)

    cookie_file.write_text(merged, encoding="utf-8")
    logger.info(f"Cookie 已更新并保存至 {cookie_file}")

    # 再次解析验证
    updated_info = _parse_cookie_expiry(merged)
    if updated_info["all_good"]:
        logger.info("✅ Cookie 刷新后所有关键字段均有效")
    else:
        logger.warning("Cookie 已保存，但仍有字段接近过期（可能服务器未完全更新）")

    return True


def check_and_refresh_cookie(cookie_file: Path, force: bool = False) -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(check_and_refresh_cookie_async(cookie_file=cookie_file, force=force))
    raise RuntimeError("check_and_refresh_cookie must be awaited; use check_and_refresh_cookie_async")


async def _visit_bilibili_with_browser(cookie_str: str) -> list[dict]:
    """
    使用 Playwright 无头浏览器访问 B站 首页，等待一段时间后获取更新后的 Cookie。

    原理：
    - 以当前 cookie 访问 https://www.bilibili.com
    - 等待页面加载及可能的 JS 执行（10 秒），B站 的 cookie 更新脚本会在此时运行
    - 获取浏览器中 set-cookie 后的所有 cookie
    - 返回 cookie 列表

    Returns:
        Playwright cookie 对象列表。
    """
    async with async_playwright() as p:
        browser = await p.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
            ],
        )
        context = await browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/147.0.0.0 Safari/537.36 Edg/147.0.0.0"
            ),
            locale="zh-CN",
        )

        cookies = []
        for kv in cookie_str.split(";"):
            kv = kv.strip()
            if "=" in kv:
                name, value = kv.split("=", 1)
                cookies.append({
                    "name": name.strip(),
                    "value": value.strip(),
                    "domain": ".bilibili.com",
                    "path": "/",
                })
        if cookies:
            await context.add_cookies(cookies)

        page = await context.new_page()
        try:
            await page.goto("https://www.bilibili.com", wait_until="load", timeout=30000)
            logger.info("B站 首页加载完成，等待 Cookie 更新...")
        except Exception as e:
            logger.warning(f"页面加载存在问题（可能已部分完成）: {e}")

        await page.wait_for_timeout(10000)
        cookies_after = await context.cookies()
        await browser.close()
        return cookies_after


def get_cookie_status(cookie_file: Path) -> dict:
    """
    获取当前 cookie 的过期状态摘要（用于日志/调试）。
    """
    if not cookie_file.exists():
        return {"exists": False, "message": "Cookie 文件不存在"}

    raw = cookie_file.read_text(encoding="utf-8-sig").strip()
    info = _parse_cookie_expiry(raw)

    lines = ["--- B站 Cookie 状态 ---"]
    if info["sessdata_expire_str"]:
        lines.append(f"  SESSDATA 过期时间: {info['sessdata_expire_str']} UTC")
    if info["bili_ticket_expire_str"]:
        lines.append(f"  bili_ticket 过期时间: {info['bili_ticket_expire_str']} UTC")
    lines.append(f"  是否需要刷新: {'否' if info['all_good'] else '是'}")
    info["report"] = "\n".join(lines)
    info["exists"] = True
    return info
