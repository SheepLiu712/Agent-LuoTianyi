"""实际隔离管理控制台：连接真实 API/新 bundle，不拦截网络响应。"""

from __future__ import annotations

import argparse
import importlib.util
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


def assert_running_restart(before, after, result):
    """重启请求成功不是证据：必须真实换 owner，且旧关闭先于新初始化。"""
    assert result["ok"] and result["written"] and result["restarted"]
    assert result["runtime"]["state"] == "running" and result["runtime"]["running"]
    assert before["running"] and after["running"]
    old_id, new_id = before["runtime_id"], after["runtime_id"]
    assert old_id is not None and new_id is not None, "runtime observer failed to identify an owner"
    assert old_id != new_id, "restarted response retained the old runtime owner"
    assert after["lifecycle_events"][len(before["lifecycle_events"]) :] == [
        {"event": "shutdown.begin", "runtime_id": old_id},
        {"event": "shutdown.complete", "runtime_id": old_id},
        {"event": "initialize.begin", "runtime_id": new_id},
        {"event": "initialize.complete", "runtime_id": new_id},
    ], "runtime lifecycle did not close the old owner before creating the new one"
    assert after["speaking_enabled"] is False and after["vector_enabled"] is False
    assert not any(after["resource_attempts"].values())


def open_console(page, url, root):
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
    return {"Authorization": "Bearer " + login.value.json()["token"]}


def load_chat_helpers():
    path = SERVER / "tests/e2e/chat/test_component_startup.py"
    spec = importlib.util.spec_from_file_location("component_startup_chat_helpers", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def run_running_restart(url, root, screenshot=None):
    helpers = load_chat_helpers()
    connect_chat, register_login, send_text = helpers.connect_chat, helpers.register_login, helpers.send_text

    errors = []
    with sync_playwright() as driver, requests.Session() as http:
        http.trust_env = False
        browser = driver.chromium.launch()
        try:
            page = browser.new_page()
            page.set_default_timeout(10000)
            page.on("pageerror", lambda error: errors.append(str(error)))
            headers = open_console(page, url, root)
            username = "spec412_restart"
            token = register_login(http, url, headers, username)
            ws = connect_chat(url, username, token)
            try:
                first, _ = send_text(ws, "请只回复：核心链路412")
            finally:
                ws.close()
            before = http.get(url + "/test/evidence", timeout=5).json()
            assert before["speaking_enabled"] is False and before["vector_enabled"] is False
            model_panel = page.locator("section.panel").filter(
                has=page.get_by_role("heading", name="模型 Interface（供应商接口）", exact=True)
            )
            model_panel.get_by_placeholder("model", exact=True).first.fill("offline-restart-verified")
            with page.expect_response(lambda response: response.url.endswith("/admin/api/llm/config/apply")) as saved:
                model_panel.get_by_role("button", name="修改", exact=True).click()
            assert saved.value.status == 200
            result = saved.value.json()
            after = http.get(url + "/test/evidence", timeout=5).json()
            assert_running_restart(before, after, result)
            assert result["config"]["component_startup"] == {"speaking_enabled": False, "vector_store_enabled": False}
            assert result["config"]["available_llms"]["dsv4-flash"]["model"] == "offline-restart-verified"
            ws = connect_chat(url, username, token)
            try:
                second, _ = send_text(ws, "请只回复：第二条")
            finally:
                ws.close()
            assert first == "核心链路412" and second == "第二条回复"
            history = http.get(
                url + "/history",
                headers={"Authorization": "Bearer " + token},
                params={"username": username, "count": 100, "end_index": -1},
                timeout=5,
            )
            assert history.status_code == 200
            content = json.dumps(history.json(), ensure_ascii=False)
            assert first in content and second in content
            assert errors == []
            if screenshot:
                page.screenshot(path=str(screenshot), full_page=True)
            return {
                "actual_api": True,
                "intercepted_api": False,
                "running_restart": True,
                "old_runtime_id": before["runtime_id"],
                "new_runtime_id": after["runtime_id"],
                "restart_events": after["lifecycle_events"][len(before["lifecycle_events"]) :],
                "components_remain_disabled": True,
                "resource_attempts": after["resource_attempts"],
                "ws_before_after": [first, second],
                "same_account_history": True,
                "page_errors": errors,
            }
        finally:
            browser.close()


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
        open_console(page, url, root)
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
    parser.add_argument("--running-restart", action="store_true", help="只补验实际运行态重启，不重复停止态场景")
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
                check = run_running_restart if args.running_restart else run_console
                result = check(url, root, args.screenshot)
                if args.output:
                    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                mode = (
                    "running-restart/same-account-ws-history"
                    if args.running_restart
                    else "stopped-save/refresh/tts-reject"
                )
                print(f"ACTUAL_CONSOLE_API=PASS; {mode}; not full TTS/provider reenabling")
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
