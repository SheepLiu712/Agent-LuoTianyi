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
