"""UA-2 手工端到端：桌面网络层 → 真实服务端 HTTP → 真实数据库。

用法（需要一台已部署新接口的服务端）：

```bash
# 1) 在服务端准备一个未使用的邀请码（管理控制台或 CLI）
# 2) 运行：
cd client
python tests/manual_e2e/register_with_agreement_e2e.py \
    --base-url https://your-server:port \
    --invite-code INVITE-XXXX \
    --current-version terms-2026-10-v1 \
    --old-version terms-2026-10-v0
```

脚本只做只读的业务断言，不改服务端数据；它会真实创建账号（这是验证原子注册的必要副作用），
因此**必须使用测试服务端与测试邀请码**。

说明：脚本走真实 AuthApi→HTTP 链路，但不模拟响应丢失、进程重启或真实并发；这些场景由自动化契约测试/桌面验收覆盖。

覆盖场景（与 spec 接口规范 4 对应）：

1. 旧客户端（不带同意字段）→ 403 AGREEMENT_REQUIRED，且不创建账号、不消耗邀请码；
2. 新客户端首次提交 → 成功；
3. 响应丢失后用同一请求 ID 重试 → 返回原成功结果，不重复建号、不再次消耗邀请码；
4. 同一请求 ID 换用户名 → 409 REGISTRATION_REQUEST_CONFLICT；
5. 用未成功的旧版本请求 → 409 AGREEMENT_CHANGED，并带服务端当前版本；
6. 另一请求 ID 抢同一邀请码 → 失败（不再消耗邀请码）。

输出为逐项 PASS/FAIL；任何一项失败都会以非 0 退出码结束。
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from src.network.auth import AuthApi  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="UA-2 桌面注册链路手工端到端")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--invite-code", required=True)
    parser.add_argument("--current-version", required=True, help="服务端当前协议版本")
    parser.add_argument("--old-version", default="", help="历史上存在但已不是当前的版本（用于换版场景）")
    parser.add_argument("--password", default="e2e-password")
    parser.add_argument("--verify-ssl", default="true", choices=["true", "false"])
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    api = AuthApi(args.base_url, verify_ssl=args.verify_ssl == "true")
    suffix = uuid.uuid4().hex[:8]
    username = f"ua2-e2e-{suffix}"
    other_username = f"ua2-e2e-other-{suffix}"
    request_id = str(uuid.uuid4())
    failures: list[str] = []

    def check(label: str, condition: bool, detail: object) -> None:
        status = "PASS" if condition else "FAIL"
        print(f"[{status}] {label}: {json.dumps(detail, ensure_ascii=False)}")
        if not condition:
            failures.append(label)

    legacy = api.register_with_agreement(username, args.password, args.invite_code)
    check(
        "旧客户端被拒绝且给出升级提示",
        legacy.ok is False and legacy.code == "AGREEMENT_REQUIRED",
        {"ok": legacy.ok, "code": legacy.code, "message": legacy.message},
    )

    first = api.register_with_agreement(
        username,
        args.password,
        args.invite_code,
        registration_request_id=request_id,
        agreement_version=args.current_version,
        accepted=True,
    )
    check("新客户端首次提交成功", first.ok is True, {"ok": first.ok, "message": first.message})

    replay = api.register_with_agreement(
        username,
        args.password,
        args.invite_code,
        registration_request_id=request_id,
        agreement_version=args.current_version,
        accepted=True,
    )
    check("同请求 ID 重复提交仍恢复原结果", replay.ok is True, {"ok": replay.ok, "message": replay.message})

    conflict = api.register_with_agreement(
        other_username,
        args.password,
        args.invite_code,
        registration_request_id=request_id,
        agreement_version=args.current_version,
        accepted=True,
    )
    check(
        "同请求 ID 换用户名被判定冲突",
        conflict.ok is False and conflict.code == "REGISTRATION_REQUEST_CONFLICT",
        {"ok": conflict.ok, "code": conflict.code},
    )

    if args.old_version and args.old_version != args.current_version:
        changed = api.register_with_agreement(
            f"{username}-v",
            args.password,
            args.invite_code,
            registration_request_id=str(uuid.uuid4()),
            agreement_version=args.old_version,
            accepted=True,
        )
        check(
            "未成功的旧版本请求被要求重读",
            changed.ok is False
            and changed.code == "AGREEMENT_CHANGED"
            and changed.agreement_version == args.current_version,
            {"ok": changed.ok, "code": changed.code, "server_version": changed.agreement_version},
        )
    else:
        print("[SKIP] 未提供 --old-version，跳过换版场景")

    competing = api.register_with_agreement(
        f"{username}-c",
        args.password,
        args.invite_code,
        registration_request_id=str(uuid.uuid4()),
        agreement_version=args.current_version,
        accepted=True,
    )
    check("另一请求 ID 顺序重用已用邀请码失败", competing.ok is False, {"ok": competing.ok, "message": competing.message})

    print()
    if failures:
        print(f"FAILED: {len(failures)} 项未通过 -> {failures}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
