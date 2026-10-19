"""协议签署窗口排版/滚动复验（Windows 真机或 Linux offscreen 均可跑）。

用途：复验 `AgreementSignDialog` 的四个现象是否消失——
缩放不重排、窄窗裁切、滚到底仍差一截/回弹、滚动条对比度不足。

用法（在 client 目录下，需 PySide6）：

    python tests/manual_e2e/sign_dialog_ui_recheck.py
    python tests/manual_e2e/sign_dialog_ui_recheck.py --json out.json

判定标准：
- 任一宽度下文档排版宽 ≤ viewport + 2px；
- 窄窗（560）下的排版高度 > 宽窗（1400）下的高度（证明真的重排）；
- 滚到底后 value == maximum，且再次同步排版不改变 maximum；
- 滚动条滑块色与白底对比度 ≥ 3:1。

脚本只读，不改产品代码与数据库。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from PySide6.QtWidgets import QApplication  # noqa: E402

from src.gui.agreement_dialog import COLOR_SCROLL_HANDLE  # noqa: E402
from src.gui.agreement_sign_dialog import AgreementSignDialog  # noqa: E402

WIDTHS = (1400, 900, 640, 560)


def long_document() -> dict:
    """长段落正文：宽度变化会改变换行数，用来验证响应式排版。"""
    return {
        "version": "terms-2026-10-v1",
        "title": "用户协议",
        "format": "agreement.richtext.v1",
        "blocks": [
            {"font_size": 16, "align": "justify", "runs": [{"text": "甲" * 400, "bold": False}]}
            for _ in range(20)
        ],
    }


def contrast_with_white(hex_color: str) -> float:
    """按 WCAG 2.1 计算与白色背景的对比度。"""
    value = hex_color.lstrip("#")
    channels = [int(value[index : index + 2], 16) / 255 for index in (0, 2, 4)]

    def linear(channel: float) -> float:
        return channel / 12.92 if channel <= 0.03928 else ((channel + 0.055) / 1.055) ** 2.4

    luminance = 0.2126 * linear(channels[0]) + 0.7152 * linear(channels[1]) + 0.0722 * linear(channels[2])
    return (1.05) / (luminance + 0.05)


def measure(app: QApplication, widget: AgreementSignDialog, width: int) -> dict:
    widget.resize(width, 600)
    app.processEvents()
    widget._sync_scroll_state()
    size = widget.view.document().documentLayout().documentSize()
    bar = widget.view.verticalScrollBar()
    return {
        "requested_width": width,
        "dialog_width": widget.width(),
        "viewport_width": widget.view.viewport().width(),
        "document_width": round(size.width(), 1),
        "document_height": round(size.height(), 1),
        "scroll_maximum": bar.maximum(),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="协议签署窗口排版/滚动复验")
    parser.add_argument("--json", default="", help="把测量结果写入该 JSON 文件")
    args = parser.parse_args()

    app = QApplication.instance() or QApplication(sys.argv)
    widget = AgreementSignDialog(document=long_document())
    widget.show()
    results: dict = {"widths": [], "checks": {}}
    failures: list[str] = []
    try:
        for width in WIDTHS:
            row = measure(app, widget, width)
            row["pass_no_clip"] = row["document_width"] <= row["viewport_width"] + 2
            if not row["pass_no_clip"]:
                failures.append(f"宽度 {width}: 文档宽 {row['document_width']} > viewport {row['viewport_width']}")
            results["widths"].append(row)

        narrow = next(row for row in results["widths"] if row["requested_width"] == 560)
        wide = next(row for row in results["widths"] if row["requested_width"] == 1400)
        reflows = narrow["document_height"] > wide["document_height"]
        results["checks"]["reflows_when_narrow"] = reflows
        if not reflows:
            failures.append("窄窗下文档高度未增加：正文没有随窗口重排")

        bar = widget.view.verticalScrollBar()
        bar.setValue(bar.maximum())
        app.processEvents()
        widget._sync_scroll_state()
        app.processEvents()
        stable_maximum = bar.maximum()
        at_bottom = bar.value() == stable_maximum
        widget._sync_scroll_state()
        app.processEvents()
        range_stable = bar.maximum() == stable_maximum
        results["checks"].update({
            "bottom_value_equals_max": at_bottom,
            "maximum_stable_after_sync": range_stable,
            "stable_maximum": stable_maximum,
        })
        if not at_bottom:
            failures.append(f"滚到底后 value={bar.value()} != maximum={stable_maximum}")
        if not range_stable:
            failures.append(f"再次同步排版后 maximum 变化：{stable_maximum} -> {bar.maximum()}")

        ratio = contrast_with_white(COLOR_SCROLL_HANDLE)
        results["scroll_handle"] = {"color": COLOR_SCROLL_HANDLE, "contrast": round(ratio, 2)}
        results["checks"]["scroll_contrast_at_least_3"] = ratio >= 3.0
        if ratio < 3.0:
            failures.append(f"滚动条对比度 {ratio:.2f}:1 低于 3:1")
    finally:
        widget.close()
        widget.deleteLater()
        app.processEvents()

    print(json.dumps(results, ensure_ascii=False, indent=2))
    if args.json:
        Path(args.json).write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")

    print()
    if failures:
        print(f"FAIL: {len(failures)} 项未通过")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("ALL PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
