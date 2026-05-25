"""
测试脚本：验证 B站 Cookie 自动更新功能。

测试流程：
① 检查当前 cookie 的过期状态
② 打印 SESSDATA 和 bili_ticket 的过期时间
③ 如果未过期则询问是否强制刷新
④ 执行实际的浏览器刷新操作
⑤ 验证刷新后的 cookie 是否更新了 key 字段
"""
import sys
import os
import time

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.plugins.schedule.cookie_manager import (
    check_and_refresh_cookie,
    get_cookie_status,
    COOKIE_FILE,
    _parse_cookie_expiry,
)


def test_step1_check_status():
    """步骤①：检查当前 cookie 过期状态。"""
    print("=" * 60)
    print("步骤①：检查 Cookie 过期状态")
    print("=" * 60)

    if not COOKIE_FILE.exists():
        print(f"[ERROR] Cookie 文件不存在: {COOKIE_FILE}")
        return None

    raw = COOKIE_FILE.read_text(encoding="utf-8-sig").strip()
    info = _parse_cookie_expiry(raw)

    print(f"  SESSDATA 过期时间: {info.get('sessdata_expire_str', 'N/A')} (UTC)")
    print(f"  bili_ticket 过期时间: {info.get('bili_ticket_expire_str', 'N/A')} (UTC)")
    print(f"  当前 UTC 时间: {time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())}")
    print(f"  是否需要刷新: {'否 ✅' if info['all_good'] else '是 ⚠️'}")
    print()
    return info


def test_step2_force_refresh():
    """步骤②：强制刷新 Cookie，验证浏览器交互是否正常。"""
    print("=" * 60)
    print("步骤②：强制刷新 Cookie（使用无头浏览器）")
    print("=" * 60)
    print("即将启动无头浏览器访问 bilibili.com...")

    # 记录刷新前的 cookie（部分关键字段）
    old_raw = COOKIE_FILE.read_text(encoding="utf-8-sig").strip()

    success = check_and_refresh_cookie(force=True)

    if not success:
        print("[FAILED] Cookie 刷新失败 ❌")
        return False

    print("[SUCCESS] Cookie 刷新完成 ✅")

    # 比较刷新前后的变化
    new_raw = COOKIE_FILE.read_text(encoding="utf-8-sig").strip()

    def get_field(cookie_str: str, field: str) -> str:
        for part in cookie_str.split(";"):
            part = part.strip()
            if part.startswith(field + "="):
                return part[len(field) + 1:]
        return ""

    old_sess = get_field(old_raw, "SESSDATA")
    new_sess = get_field(new_raw, "SESSDATA")
    old_ticket = get_field(old_raw, "bili_ticket")
    new_ticket = get_field(new_raw, "bili_ticket")
    old_ticket_exp = get_field(old_raw, "bili_ticket_expires")
    new_ticket_exp = get_field(new_raw, "bili_ticket_expires")

    print()
    print("--- 关键字段对比 ---")
    print(f"  SESSDATA 前10位: {old_sess[:10] if old_sess else 'N/A'} → {new_sess[:10] if new_sess else 'N/A'}")
    print(f"  bili_ticket 前10位: {old_ticket[:10] if old_ticket else 'N/A'} → {new_ticket[:10] if new_ticket else 'N/A'}")
    print(f"  bili_ticket_expires: {old_ticket_exp or 'N/A'} → {new_ticket_exp or 'N/A'}")

    # 检查是否确实有变化
    changed = (old_sess != new_sess) or (old_ticket != new_ticket)
    if changed:
        print("\n✅ Cookie 关键字段已更新！")
    else:
        print("\n⚠️ Cookie 关键字段未变化（可能浏览器未下发新值，或原值未过期）")

    print()
    return True


def test_step3_verify_after_refresh():
    """步骤③：刷新后再次检查过期状态。"""
    print("=" * 60)
    print("步骤③：刷新后过期状态验证")
    print("=" * 60)

    info = get_cookie_status()
    print(info.get("report", ""))
    print()

    if info.get("all_good"):
        print("✅ 所有关键 Cookie 字段均有效期内")
    else:
        print("⚠️ 部分 Cookie 字段仍接近过期（服务器可能未完全刷新）")

    print("=" * 60)


def main():
    print(f"Cookie 文件路径: {COOKIE_FILE.resolve()}")
    print(f"文件是否存在: {COOKIE_FILE.exists()}")
    print()

    # 步骤①：检查状态
    info = test_step1_check_status()

    # 步骤②：强制刷新
    test_step2_force_refresh()

    # 步骤③：刷新后验证
    test_step3_verify_after_refresh()

    print("\n测试完成。")


if __name__ == "__main__":
    main()
