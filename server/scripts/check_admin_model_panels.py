"""在 Chromium 中使用临时配置验证管理控制台四个模型面板。"""

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

    def respond(route):
        nonlocal config
        path = urlsplit(route.request.url).path.removeprefix("/admin/")
        if not path.startswith("api/"):
            route.fulfill(path=static / (path or "index.html"))
            return
        if path == "api/llm/config/apply":
            config = apply_llm_config_draft(config, route.request.post_data_json)
            result = {"ok": True, "config": build_llm_config_view(config), "restarted": False}
        elif path == "api/llm/config":
            result = build_llm_config_view(config)
        elif path == "api/admin-auth/status":
            result = {"configured": True}
        else:
            result = {}
        route.fulfill(json=result)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        page = browser.new_page()
        page.route("http://console.test/admin/**", respond)
        page.goto("http://console.test/admin/")
        page.get_by_role("button", name="服务配置").click()
        panels = page.locator("section.panel").filter(has=page.get_by_role("button", name="放弃草稿"))
        expect(panels.locator("h2")).to_have_text([
            "模型 Interface（供应商接口）", "客户端模型需求", "实时音频模型配置", "模型 module（调用模块）绑定",
        ])
        interfaces, clients, audio, bindings = panels.all()
        model = interfaces.get_by_placeholder("model", exact=True)
        client = clients.get_by_placeholder("客户端显示名称")
        speech = audio.get_by_label("模型名称")
        params = bindings.locator("textarea")

        # 四处同时编辑；客户端草稿尚未填全，也应能提交实时音频面板。
        model.fill("next-model")
        client.fill("")
        speech.fill("next-audio")
        params.fill('{"limit":1}')
        audio.get_by_role("button", name="修改", exact=True).click()
        expect(audio.get_by_text("配置已写入", exact=False)).to_be_visible()
        assert config["call_transport"]["realtime_speech"]["model"] == "next-audio"
        assert config["llm_service"]["available_llms"]["main"]["model"] == "original"
        assert config["llm_service"]["client_model_types"][0]["name"] == "原名"
        assert config["skill"]["llm"]["params"] == {}
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
            (interfaces, model, "next-model"), (clients, client, "新名称"),
            (audio, speech, "next-audio"), (bindings, params, params.input_value()),
        ]:
            field.fill("临时编辑")
            panel.get_by_role("button", name="放弃草稿").click()
            expect(field).to_have_value(saved)
        page.reload()
        page.get_by_role("button", name="服务配置").click()
        expect(model).to_have_value("next-model")
        expect(client).to_have_value("新名称")
        expect(speech).to_have_value("next-audio")
        assert '"limit"' in params.input_value()
        browser.close()


if __name__ == "__main__":
    main()
