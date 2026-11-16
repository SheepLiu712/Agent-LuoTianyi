"""实际隔离管理控制台：连接真实 API/新 bundle，不拦截网络响应。"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import requests
from playwright.sync_api import expect, sync_playwright

SERVER = Path(__file__).resolve().parents[1]


def wait_server(process, root, http):
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError((root / "server.log").read_text(encoding="utf-8"))
        address = root / "address.json"
        if address.exists():
            url = json.loads(address.read_text(encoding="utf-8"))["url"]
            try:
                if http.get(url + "/test/evidence", timeout=0.5).json().get("running"):
                    return url
            except (requests.RequestException, ValueError):
                pass
        time.sleep(0.05)
    raise TimeoutError("production console instance did not become ready in45s")


def run_console(url, root, screenshot=None):
    requests_seen = []
    errors = []
    with sync_playwright() as driver:
        browser = driver.chromium.launch()
        page = browser.new_page()
        page.set_default_timeout(10000)
        page.on("pageerror", lambda error: errors.append(str(error)))
        page.on(
            "request",
            lambda request: (
                requests_seen.append((request.method, request.url, request.post_data_json))
                if request.method == "POST" and request.url.endswith("/admin/api/llm/config/apply")
                else None
            ),
        )
        page.goto(url + "/admin/")
        page.get_by_placeholder("Setup token").fill((root / "config/admin_setup_token.txt").read_text(encoding="utf-8"))
        page.get_by_placeholder("Admin password").fill("isolated-console-password")
        with page.expect_response(lambda response: response.url.endswith("/admin/api/admin-auth/setup")) as setup:
            page.get_by_role("button", name="完成初始化", exact=True).click()
        assert setup.value.status == 200
        expect(page.get_by_role("heading", name="控制台登录", exact=True)).to_be_visible()
        page.get_by_placeholder("Admin password").fill("isolated-console-password")
        with page.expect_response(lambda response: response.url.endswith("/admin/api/admin-auth/login")) as login:
            page.get_by_role("button", name="登录", exact=True).click()
        assert login.value.status == 200
        page.get_by_role("button", name="服务配置", exact=True).click()
        panel = page.locator("section.panel").filter(has=page.get_by_role("heading", name="组件启动", exact=True))
        tts = panel.get_by_label("启用语音合成（TTS）", exact=True)
        vector = panel.get_by_label("启用长期记忆向量库", exact=True)
        expect(tts).not_to_be_checked()
        expect(vector).not_to_be_checked()
        page.get_by_role("button", name="停止", exact=True).click()
        expect(page.get_by_text("业务未启动", exact=True)).to_be_visible(timeout=15000)
        for checkbox, leaf in ((vector, "vector_store_enabled"),):
            checkbox.check()
            with page.expect_response(
                lambda response: response.url.endswith("/admin/api/llm/config/apply")
            ) as response:
                panel.get_by_role("button", name="修改", exact=True).click()
            result = response.value.json()
            assert result["written"] is True and result["restarted"] is False
            assert result["runtime"]["running"] is False
            assert result["config"]["component_startup"][leaf] is True
            page.reload()
            page.get_by_role("button", name="服务配置", exact=True).click()
            expect(vector).to_be_checked()
            vector.uncheck()
            with page.expect_response(
                lambda response: response.url.endswith("/admin/api/llm/config/apply")
            ) as response:
                panel.get_by_role("button", name="修改", exact=True).click()
            assert response.value.json()["config"]["component_startup"][leaf] is False
        before = (root / "config/config.json").read_bytes()
        tts.check()
        with page.expect_response(lambda response: response.url.endswith("/admin/api/llm/config/apply")) as response:
            panel.get_by_role("button", name="修改", exact=True).click()
        result = response.value.json()
        assert result["ok"] is False and result["written"] is False and result["restarted"] is False
        assert (root / "config/config.json").read_bytes() == before
        expect(tts).to_be_checked()
        expect(panel.get_by_text("配置未写入", exact=False)).to_be_visible()
        panel.get_by_role("button", name="放弃草稿", exact=True).click()
        expect(tts).not_to_be_checked()
        page.reload()
        page.get_by_role("button", name="服务配置", exact=True).click()
        expect(tts).not_to_be_checked()
        expect(vector).not_to_be_checked()
        assert errors == []
        assert requests_seen[0][2] == {"component_startup": {"vector_store_enabled": True}}
        assert requests_seen[1][2] == {"component_startup": {"vector_store_enabled": False}}
        assert requests_seen[2][2] == {"component_startup": {"speaking_enabled": True}}
        if screenshot:
            page.screenshot(path=str(screenshot), full_page=True)
        browser.close()
    return {
        "actual_api": True,
        "intercepted_api": False,
        "page_errors": errors,
        "stopped_save_refresh": True,
        "tts_missing_resources_rejected": True,
        "vector_enabled_save_only_not_started": True,
        "apply_requests": [item[2] for item in requests_seen],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path)
    parser.add_argument("--screenshot", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="component-console-") as directory:
        root = Path(directory)
        env = dict(os.environ)
        env["PYTHONPATH"] = os.pathsep.join((str(SERVER), str(SERVER / "tests")))
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        for key in tuple(env):
            if key.upper().endswith("_PROXY") or key in {
                "AMAP_KEY",
                "QWEN_API_KEY",
                "SILICONFLOW_API_KEY",
                "OPENAI_API_KEY",
            }:
                env.pop(key, None)
        http = requests.Session()
        http.trust_env = False
        with (root / "server.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [sys.executable, "-B", "-m", "support.component_startup_offline_server", str(root)],
                cwd=root,
                env=env,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            url = None
            try:
                url = wait_server(process, root, http)
                result = run_console(url, root, args.screenshot)
                if args.output:
                    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                print(
                    "ACTUAL_CONSOLE_API=PASS; stopped-save/refresh/tts-validation-reject; "
                    "not full TTS/provider reenabling"
                )
            except BaseException:
                log.flush()
                print((root / "server.log").read_text(encoding="utf-8"), file=sys.stderr)
                raise
            finally:
                if process.poll() is None and url:
                    try:
                        http.post(url + "/test/stop", timeout=2)
                    except requests.RequestException:
                        pass
                if process.poll() is None:
                    try:
                        process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                http.close()
                assert process.returncode == 0
                assert json.loads((root / "closed.json").read_text(encoding="utf-8"))["closed"] is True
                assert time.monotonic() - started < 90


if __name__ == "__main__":
    main()
