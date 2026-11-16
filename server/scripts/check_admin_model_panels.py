"""用临时 API 响应验证五面板草稿与组件叶子保存；不证明真实 runtime 重启。"""

from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from src.infrastructure.config.model_editor import apply_llm_config_draft, build_llm_config_view


def main():
    config = {
        "llm_service": {
            "available_llms": {"main": {"model": "original"}},
            "client_model_types": [{"id": "chat", "name": "原名", "model_kind": "llm"}],
        },
        "call_transport": {"realtime_speech": {"model": "old-audio"}},
        "skill": {"llm": {"name": "main", "params": {}}},
    }
    static = Path(__file__).resolve().parents[1] / "res/admin_ui/admin_static"
    requests = []
    runtime = {"state": "stopped", "running": False}
    restarted = False

    def respond(route):
        nonlocal config
        path = urlsplit(route.request.url).path.removeprefix("/admin/")
        if not path.startswith("api/"):
            route.fulfill(path=static / (path or "index.html"))
            return
        if path == "api/llm/config/apply":
            requests.append(route.request.post_data_json)
            config = apply_llm_config_draft(config, route.request.post_data_json)
            result = {"ok": True, "config": build_llm_config_view(config), "restarted": restarted, "runtime": runtime}
        elif path == "api/llm/config":
            result = build_llm_config_view(config)
        elif path == "api/admin-auth/status":
            result = {"configured": True}
        elif path == "api/runtime/status":
            result = runtime
        else:
            result = {}
        route.fulfill(json=result)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        browser_errors = []
        page.on("pageerror", lambda error: browser_errors.append(str(error)))
        page.route("http://console.test/admin/**", respond)
        page.goto("http://console.test/admin/")
        page.get_by_role("button", name="服务配置").click()
        panels = page.locator("section.panel").filter(has=page.get_by_role("button", name="放弃草稿"))
        expect(panels.locator("h2")).to_have_text(
            [
                "模型 Interface（供应商接口）",
                "客户端模型需求",
                "实时音频模型配置",
                "模型 module（调用模块）绑定",
                "组件启动",
            ]
        )
        interfaces, clients, audio, bindings, components = panels.all()
        model = interfaces.get_by_placeholder("model", exact=True)
        client = clients.get_by_placeholder("客户端显示名称")
        speech = audio.get_by_label("模型名称")
        params = bindings.locator("textarea")
        speaking = components.get_by_role("checkbox", name="启用语音合成（TTS）")
        vectors = components.get_by_role("checkbox", name="启用长期记忆向量库")
        expect(speaking).to_be_checked()
        expect(vectors).to_be_checked()

        # 四处同时编辑；客户端草稿尚未填全，也应能提交实时音频面板。
        model.fill("next-model")
        client.fill("")
        speech.fill("next-audio")
        params.fill('{"limit":1}')
        speaking.uncheck()
        components.get_by_role("button", name="修改", exact=True).click()
        expect(components.get_by_text("runtime 当前状态：stopped", exact=False)).to_be_visible()
        assert requests[-1] == {"component_startup": {"speaking_enabled": False}}
        assert config["agent_runtime"]["skills"]["speaking"]["enabled"] is False
        expect(vectors).to_be_checked()
        expect(model).to_have_value("next-model")
        expect(client).to_have_value("")
        assert '"limit"' in params.input_value()
        # 另一面板保存不能带入或清除本面板尚未提交的向量草稿。
        vectors.uncheck()
        audio.get_by_role("button", name="修改", exact=True).click()
        expect(audio.get_by_text("配置已写入", exact=False)).to_be_visible()
        assert config["call_transport"]["realtime_speech"]["model"] == "next-audio"
        assert config["llm_service"]["available_llms"]["main"]["model"] == "original"
        assert config["llm_service"]["client_model_types"][0]["name"] == "原名"
        assert config["skill"]["llm"]["params"] == {}
        assert "component_startup" not in requests[-1]
        expect(vectors).not_to_be_checked()
        components.get_by_role("button", name="放弃草稿").click()
        expect(vectors).to_be_checked()
        expect(speaking).not_to_be_checked()
        expect(model).to_have_value("next-model")
        expect(client).to_have_value("")
        assert '"limit"' in params.input_value()

        clients.get_by_role("button", name="修改", exact=True).click()
        expect(clients.get_by_text("配置未写入", exact=False)).to_be_visible()
        clients.get_by_role("button", name="放弃草稿").click()
        expect(client).to_have_value("原名")
        expect(model).to_have_value("next-model")

        # 服务端规范化后，放弃后续编辑应恢复上次实际保存的值。
        client.fill(" 新名称 ")
        clients.get_by_role("button", name="修改", exact=True).click()
        expect(client).to_have_value("新名称")
        interfaces.get_by_role("button", name="修改", exact=True).click()
        expect(interfaces.get_by_text("配置已写入", exact=False)).to_be_visible()
        bindings.get_by_role("button", name="修改", exact=True).click()
        expect(bindings.get_by_text("配置已写入", exact=False)).to_be_visible()
        assert config["skill"]["llm"]["params"] == {"limit": 1}

        for panel, field, saved in [
            (interfaces, model, "next-model"),
            (clients, client, "新名称"),
            (audio, speech, "next-audio"),
            (bindings, params, params.input_value()),
        ]:
            field.fill("临时编辑")
            panel.get_by_role("button", name="放弃草稿").click()
            expect(field).to_have_value(saved)
        # restarted 只表示发起请求；不能把 starting/failed 说成运行就绪。
        runtime = {"state": "starting", "running": False}
        restarted = True
        vectors.uncheck()
        components.get_by_role("button", name="修改", exact=True).click()
        expect(components.get_by_text("runtime 当前状态：starting", exact=False)).to_be_visible()
        assert requests[-1] == {"component_startup": {"vector_store_enabled": False}}
        runtime = {"state": "failed", "running": False, "last_error": "test startup failure"}
        speaking.check()
        components.get_by_role("button", name="修改", exact=True).click()
        expect(components.get_by_text("runtime 当前状态：failed", exact=False)).to_be_visible()
        expect(page.get_by_text("test startup failure", exact=True)).to_be_visible()
        runtime = {"state": "running", "running": True}
        vectors.check()
        components.get_by_role("button", name="修改", exact=True).click()
        expect(components.get_by_text("runtime 当前运行中", exact=False)).to_be_visible()
        page.reload()
        page.get_by_role("button", name="服务配置").click()
        expect(model).to_have_value("next-model")
        expect(client).to_have_value("新名称")
        expect(speech).to_have_value("next-audio")
        assert '"limit"' in params.input_value()
        expect(speaking).to_be_checked()
        expect(vectors).to_be_checked()
        assert browser_errors == []
        browser.close()
        print("UI stub passed: four drafts isolated, two component leaves, runtime-state messages; not A4 restart")


if __name__ == "__main__":
    main()
