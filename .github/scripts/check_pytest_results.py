"""确认本轮选定的测试均已执行，避免将运行时跳过误报为全部通过。"""

import sys
import xml.etree.ElementTree as ET


def main() -> None:
    suites = list(ET.parse(sys.argv[1]).getroot().iter("testsuite"))
    counts = {
        key: sum(int(suite.get(key, 0)) for suite in suites)
        for key in ("tests", "skipped", "failures", "errors")
    }
    print(f"测试结果：{counts}")
    if counts["tests"] == 0 or any(
        counts[key] for key in ("skipped", "failures", "errors")
    ):
        raise SystemExit("选定测试未全部执行并通过，请检查测试报告。")


if __name__ == "__main__":
    main()
