"""Browser acceptance check against a local admin UI, using real SQLite aggregation.

Run from server with a local Vite server on port 5173 and Playwright Chromium installed:
python scripts/check_admin_metrics_ui.py --output-dir /data/projects/.tmp/dpon/admin-metrics-ui
"""

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playwright.sync_api import sync_playwright

from src.infrastructure.observability.service import ObservabilityService


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:5173/admin/")
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    temporary = TemporaryDirectory(prefix="metrics-browser-", dir=args.output_dir)
    store = ObservabilityService({"db_path": str(Path(temporary.name) / "metrics.sqlite3")})
    now = datetime.now(timezone.utc)
    for index in range(24):
        at = now - timedelta(minutes=5 * index)
        count = index % 8
        if index != 8:  # deliberate gap
            store.record_population(
                at.isoformat(),
                "fixture",
                dict(
                    scope_count=count,
                    chat_stage_count=count,
                    call_stage_count=0,
                    overlap_count=0,
                    terminating_stage_count=0,
                ),
            )
        store._execute(
            "INSERT INTO llm_call_metrics(ts,module_name,total_tokens) VALUES (?,?,?)",
            (at.isoformat(), "reply", 1000 + index * 80),
        )
        for name in ("chat.v2.total", "call.v2.ack", "stage.termination.total"):
            store.record_pipeline_span(
                trace_id=f"fixture:{index}",
                span_name=name,
                start_ts=at.isoformat(),
                end_ts=at.isoformat(),
                duration_ms=100 + index * 150,
                metadata={"stage_kind": "chat"},
            )
    requests, errors = [], []

    def route(request):
        parsed = urlparse(request.request.url)
        window = parse_qs(parsed.query).get("window", ["24h"])[0]
        requests.append(parsed.path + "?" + parsed.query)
        if parsed.path.endswith("/metrics/usage"):
            result = store.usage_trends(window)
        elif parsed.path.endswith("/metrics/latency"):
            result = store.latency_groups(window)
        elif parsed.path.endswith("/llm/summary"):
            result = store.get_llm_summary()
        elif parsed.path.endswith("/admin-auth/status"):
            result = {"configured": True, "setup_required": False}
        elif parsed.path.endswith("/runtime/status"):
            result = {"running": True, "state": "running"}
        else:
            result = {"llm": {}, "logs": {}, "recent_logs": []}
        request.fulfill(status=200, content_type="application/json", body=json.dumps(result))

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            # Different browser timezone verifies display does not follow the browser.
            context = browser.new_context(viewport={"width": 1440, "height": 1100}, timezone_id="America/New_York")
            page = context.new_page()
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.route("**/admin/api/**", route)
            page.goto(args.base_url)
            page.get_by_role("button", name="用量趋势", exact=True).click()
            page.wait_for_selector(".usage-chart svg")
            assert page.locator(".usage-chart svg").count() == 3
            assert page.get_by_role("button", name="链路追踪", exact=True).count() == 0
            assert page.get_by_text("慢 Span", exact=True).count() == 0
            page.locator(".usage-chart svg").first.focus()
            page.keyboard.press("ArrowRight")
            assert "Token" in page.locator(".usage-readout").inner_text()
            page.screenshot(path=str(args.output_dir / "usage-desktop.png"), full_page=True)
            page.get_by_role("button", name="最近7天", exact=True).click()
            page.wait_for_function("document.querySelector('.usage-readout')?.textContent.includes('移动')")
            page.get_by_role("button", name="链路耗时", exact=True).click()
            page.get_by_role("columnheader", name="P99", exact=True).first.wait_for()
            assert page.get_by_role("columnheader", name="最大", exact=True).count() == 0
            assert page.get_by_role("heading", name="通话回复", exact=True).count() == 1
            for window in ("最近7天", "所有数据", "最近24小时"):
                page.get_by_role("button", name=window, exact=True).click()
                page.get_by_role("columnheader", name="P99", exact=True).first.wait_for()
            page.screenshot(path=str(args.output_dir / "latency-desktop.png"), full_page=True)
            page.set_viewport_size({"width": 390, "height": 844})
            page.screenshot(path=str(args.output_dir / "latency-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            page.get_by_role("button", name="用量趋势", exact=True).click()
            page.wait_for_selector(".usage-chart svg")
            page.screenshot(path=str(args.output_dir / "usage-mobile.png"), full_page=True)
            assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
            assert any("metrics/latency?window=all" in path for path in requests)
            assert any("metrics/latency?window=7d" in path for path in requests)
            assert not any("/traces" in path or "/pipeline/spans" in path for path in requests)
            assert not errors, errors
            browser.close()
        print("Admin metrics browser checks passed; screenshots:", args.output_dir)
    finally:
        store.close()
        temporary.cleanup()


if __name__ == "__main__":
    main()
