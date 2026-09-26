# CLI 真实服务端试运行样例

这些文件是手动试运行的输入样例，不由 `pytest` 自动运行。它们会访问你指定的服务端；发布动态、更新偏好等动作会产生真实副作用。历史响应与进度记录不在仓库中维护，测试结论应记录在相应 PR。

在 `client/` 目录运行。先用独立测试账号、受测服务地址和临时图片路径替换 JSON 样例中的 `https://example.invalid`、`cli_e2e_user`、`<redacted-password>` 与 `<TEMP>`；不要将填入凭据的副本提交到仓库。`07-image-generate.py` 会在系统临时目录生成图片并打印路径。

```powershell
python cli.py --scenario tests/manual_e2e/01-text-send-wait.json
```

`*.driver.py` 通过环境变量读取 `CLI_E2E_BASE_URL`、`CLI_E2E_USER` 和 `CLI_E2E_PASSWORD`，在同一 CLI 会话中处理动态回复 UUID。运行前还可设置 `CLI_E2E_OUT`（输出 JSONL 路径）与 `CLI_E2E_CLIENT_DIR`（客户端目录）；缺少服务地址或密码会直接退出。示例：

```powershell
$env:CLI_E2E_BASE_URL = 'https://your-test-server.example'
$env:CLI_E2E_USER = 'your-test-user'
$env:CLI_E2E_PASSWORD = '<your-password>'
python tests/manual_e2e/08-reply-read-audio-replay.driver.py
```

`18-failure-classifications.json`、`19-unreachable-connect.json` 和 `21-invalid-scenario.json` 用于观察预期失败分类。`reply.wait` 等待下一条完整回复；服务端没有把原始客户端消息 ID 稳定附到回复时，下一条回复可能属于更早的输入，应结合内容断言判断。

本轮注册、自动登录、历史和时序验收使用以下动作。密码与确认密码建议通过同一个环境变量提供，不要放入 JSON 文件；邀请码也只在调用时提供。`session.connect` 的 `remember_login` 默认是 `false`，设为 `true` 才会在 `client/temp/cli_auto_login.json` 保存 CLI 专用的加密令牌。`history.initial` 显示连接时自动发起的那一次历史加载，`events.wait` 可使用 `kind`、`value`、`contains`、`after_seq` 和 `timeout` 限定目标事件。

```json
{"action":"account.register","params":{"base_url":"https://your-test-server.example","username":"cli_test_user","password_env":"CLI_TEST_PASSWORD","password_confirm_env":"CLI_TEST_PASSWORD","invite_code":"<invite-code>"}}
{"action":"session.connect","params":{"base_url":"https://your-test-server.example","username":"cli_test_user","password_env":"CLI_TEST_PASSWORD","remember_login":true}}
{"action":"history.initial"}
{"action":"chat.send_typing","params":{"text_length":3}}
{"action":"events.wait","params":{"kind":"agent_state","value":"thinking","timeout":90}}
```

要重复检查文本和图片触发 `thinking` 的时间，请先生成图片，并使用独立测试账号创建 CLI 自动登录文件，然后运行 `python tests/manual_e2e/acceptance_timing.driver.py`。驱动会在 `client/temp/cli_acceptance_timing/` 保存每种场景的 JSONL 证据，输出从相关动作结果到状态事件的实测秒数；可用 `CLI_E2E_CREDENTIAL_FILE`、`CLI_E2E_IMAGE` 和 `CLI_E2E_CASE` 指定凭据文件、图片和单个场景。该驱动会向真实服务端发送多条消息，适合隔离的测试账号。
