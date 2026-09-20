"""架构边界静态检查（#89 验收用）。

只读扫描 `server/src`，验证《行为不变量与副作用清单（#89 验收前置）》中的全局不变量
G1–G10 里可静态判定的部分；每条检查输出证据行，末行给出 PASS/FAIL 汇总。

用法（在 `server/` 目录下）：
    python scripts/check_architecture_boundaries.py            # 全量检查
    python scripts/check_architecture_boundaries.py --verbose  # 打印全部命中行

退出码：0 = 全部通过；1 = 存在违规。
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
from typing import Iterable, NamedTuple

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")


class Check(NamedTuple):
    """一条静态检查。

    roots 默认是「扫描范围」（命中即违规，allowlist 与 TYPE_CHECKING 例外）；
    exclusive=True 时语义反转：扫描整个 src，命中只允许出现在 roots 内（用于
    「入口调用点必须限定在某层」这类正向约束）。
    """

    name: str
    invariant: str
    roots: tuple[str, ...]
    pattern: str
    allow: tuple[str, ...] = ()
    exclusive: bool = False


CHECKS: tuple[Check, ...] = (
    Check(
        "B1-业务入口唯一",
        "G1 外部认知只经 handle_stimulus / realize_action_plan，调用点仅限 Stage",
        ("stage",),
        r"\.(handle_stimulus|realize_action_plan)\(",
        exclusive=True,
    ),
    Check(
        "B2-world-不得运行时依赖认知层",
        "G2 world 不 import Agent / Stage（类型检查除外）",
        ("world",),
        r"^\s*from\s+src\.(agent|stage)\b|^\s*import\s+src\.(agent|stage)\b",
    ),
    Check(
        "B3-handler-无基础设施直连",
        "G4 handler 不直连 world / EventStore / 记忆实现 / 数据库",
        ("agent/handlers",),
        r"src\.world|EventStore|event_store|subconscious|database_manager|dynamic_store",
    ),
    Check(
        "B4-action-不得自造副作用",
        "G3 效果只经 ActionPlan / EffectRef，action 层不得直接上网或写库",
        ("agent/handlers/action",),
        r"database_manager|requests\.|session\.(add|commit)|aiohttp|httpx",
    ),
    Check(
        "B5-world-无实时输出",
        "G7 world 链路无 SAY/SING 等实时输出通道",
        ("world",),
        r"\bOutputSink\b|\bSay\b|\bSing\b|output_channel(?!_)",
    ),
    Check(
        "B6-旧管线代理零残留",
        "G1 已删旧包、旧领域输入和角色对象图不得残留",
        ("",),
        (
            r"src\.(chat_session|subconscious|legacy)\b|src\.domain\.(chat|stimulus)\b|"
            r"src\.capabilities\b|\bCapabilityManager\b|\bcapability_manager\b|"
            r"\b(LuoTianyiAgent|CharacterRuntime|AgentRegistry|ChatPreprocessor|SubconsciousMemory)\b|"
            r"_for_pipeline|try_handle_reflex|get_character_runtime\([^)]*\)\.conscious"
        ),
    ),
    Check(
        "B7-已知偏差-不得扩散",
        "G2 已知偏差（world 只读 server_runtime.agent_runtime 属性）不得扩大",
        ("world",),
        r'getattr\([^)]*"agent_runtime"[^)]*\)',
        allow=(
            "world/world_runtime.py",
            "world/citywalk/task.py",
            "world/dynamic_interaction/task.py",
            "world/get_new_songs/task.py",
            "world/learn_sing_songs/task.py",
        ),
    ),
    Check(
        "B8-infrastructure-保持中立",
        "基础设施不反向 import agent / world / stage / adapter / application / web / server_runtime 业务层",
        ("infrastructure",),
        r"^\s*from\s+src\.(agent|world|stage|adapter|application|web|server_runtime)\b|"
        r"^\s*import\s+src\.(agent|world|stage|adapter|application|web|server_runtime)\b",
    ),
    Check(
        "B9-adapter-只做适配",
        "Adapter 不承载 FastAPI 路由、物理网络服务或管理应用用例",
        ("adapter",),
        r"^\s*(from|import)\s+fastapi\b|\b(APIRouter|WebSocketService|AdminShell|RuntimeSupervisor)\b",
    ),
    Check(
        "B10-application-传输无关",
        "Application 不依赖 FastAPI 或 Web 传输实现",
        ("application",),
        r"^\s*(from|import)\s+fastapi\b|^\s*(from|import)\s+src\.web\b",
    ),
)


def python_files(root: str) -> list[str]:
    out: list[str] = []
    for base, _dirs, names in os.walk(root):
        if "__pycache__" in base:
            continue
        for name in names:
            if name.endswith(".py"):
                out.append(os.path.join(base, name))
    return sorted(out)


def is_type_checking_only(path: str, lineno: int, line: str) -> bool:
    """判断命中行是否位于 `if TYPE_CHECKING:` 块内（缩进式近似判定）。"""
    if not line.startswith((" ", "\t")):
        return False
    if re.match(r"^\s*(if\s+TYPE_CHECKING|if\s+not\s+TYPE_CHECKING)", line):
        return False
    try:
        lines = io.open(path, encoding="utf-8").read().split("\n")
    except OSError:
        return False
    for index in range(lineno - 2, -1, -1):
        previous = lines[index]
        if not previous.strip():
            continue
        indent = len(previous) - len(previous.lstrip())
        if indent == 0:
            return bool(re.match(r"if\s+(not\s+)?TYPE_CHECKING\b", previous.strip()))
    return False


def scan(check: Check) -> list[str]:
    """返回 check 的命中行；exclusive 检查额外剔除 roots 内的合法命中。"""
    hits: list[str] = []
    rx = re.compile(check.pattern)
    if check.exclusive:
        roots = [os.path.join(SRC, *root.split("/")) for root in check.roots]
        paths = python_files(SRC)
        allowed_root = roots
        unexpected = []
        matched = 0
        for path in paths:
            rel = os.path.relpath(path, SRC).replace("\\", "/")
            try:
                lines = io.open(path, encoding="utf-8").read().split("\n")
            except OSError:
                continue
            inside = any(path.startswith(root) for root in allowed_root)
            for lineno, line in enumerate(lines, 1):
                if not rx.search(line):
                    continue
                matched += 1
                if inside:
                    hits.append(f"{rel}:{lineno}: [Stage 内合法] {line.strip()[:120]}")
                else:
                    unexpected.append(f"{rel}:{lineno}: {line.strip()[:120]}")
        return hits + unexpected if matched else ["<未发现任何调用点：入口可能已失联>"]

    for root in check.roots:
        root_path = os.path.join(SRC, *root.split("/"))
        for path in python_files(root_path):
            rel = os.path.relpath(path, SRC).replace("\\", "/")
            if any(rel == item or rel.startswith(item + "/") for item in ()):
                continue
            try:
                lines = io.open(path, encoding="utf-8").read().split("\n")
            except OSError:
                continue
            for lineno, line in enumerate(lines, 1):
                if not rx.search(line):
                    continue
                if check.name.startswith("B2") and is_type_checking_only(path, lineno, line):
                    continue
                hits.append(f"{rel}:{lineno}: {line.strip()[:140]}")
    return hits


def summarise(label: str, hits: Iterable[str]) -> bool:
    items = list(hits)
    print(f"{label}: {'PASS' if not items else f'FAIL({len(items)})'}")
    return not items


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--verbose", action="store_true", help="打印全部命中行")
    args = parser.parse_args()

    print(f"扫描根目录: {SRC}\n")
    failures: list[str] = []
    for check in CHECKS:
        hits = scan(check)
        unexpected: list[str] = []
        for hit in hits:
            if "[Stage 内合法]" in hit:
                continue
            if hit.startswith("<未发现"):
                unexpected.append(hit)
                continue
            rel = hit.split(":", 1)[0]
            if any(rel == item for item in check.allow):
                continue
            unexpected.append(hit)
        ok = summarise(f"[{check.name}] {check.invariant}", unexpected)
        if not ok:
            failures.append(check.name)
        if unexpected and (args.verbose or not ok):
            for hit in unexpected:
                print(f"    ! {hit}")
        if hits and check.allow and (args.verbose or not ok):
            print(f"    (allowlist 内命中 {len(hits) - len(unexpected)} 条，属已知偏差)")

    print()
    if failures:
        print(f"结果: FAIL —— 违规检查 {', '.join(failures)}")
        return 1
    print("结果: PASS —— 全部静态边界检查通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
