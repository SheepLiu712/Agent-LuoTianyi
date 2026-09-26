# CLI 真实服务端试运行样例

这些 `.cli` 文件是手动试运行的斜杠命令脚本，不由 `pytest` 自动运行。它们会访问指定服务端；发布动态、更新偏好等命令会产生真实副作用。测试结论应记录在相应 PR。

在 `cli-client/` 目录设置独立测试账号和受测服务：

```powershell
$env:CLI_E2E_BASE_URL = 'https://your-test-server.example'
$env:CLI_E2E_USER = 'your-test-user'
$env:CLI_E2E_PASSWORD = '<your-password>'
python cli.py --script tests/manual_e2e/01-text-send-wait.cli
```

图片样例可用 `python tests/manual_e2e/07-image-generate.py` 生成，再把输出路径设置为 `CLI_E2E_IMAGE`。脚本中的 `${CLI_E2E_IMAGE}` 会在执行时展开。`18-failure-classifications.cli`、`19-unreachable-connect.cli` 和 `21-invalid-command.cli` 用于观察预期失败；运行 18 时加 `--continue-on-failure`，并可设置 `CLI_E2E_MISSING_IMAGE`、`CLI_E2E_INVALID_IMAGE` 为不存在的图片路径与不受支持的文件路径。`/reply` 等待下一条完整回复；服务端没有把原始客户端消息 ID 稳定附到回复时，下一条回复可能属于更早的输入，应结合内容判断。

带 `.driver.py` 后缀的脚本通过同一斜杠命令入口驱动 CLI，用 `--jsonl` 读取机器结果，处理动态回复 UUID。可设置 `CLI_E2E_OUT`（证据输出路径）与 `CLI_E2E_ROOT`（客户端目录）。例如：

```powershell
python tests/manual_e2e/08-reply-read-audio-replay.driver.py
```

注册、自动登录、历史和时序检查可以直接在交互会话中进行。`/login --remember` 会将 CLI 专用加密令牌保存到 `temp/cli_auto_login.json`；`/initial-history` 显示连接时自动加载的历史。

```text
/register
/login --remember
/initial-history
/typing 3
/wait agent_state thinking --timeout 90
/logout
/auto-login
```

要重复测量文本和图片触发 `thinking` 的时间，先准备图片并创建 CLI 自动登录文件，再运行 `python tests/manual_e2e/acceptance_timing.driver.py`。驱动在 `temp/cli_acceptance_timing/` 保存各场景 JSONL 证据；可用 `CLI_E2E_CREDENTIAL_FILE`、`CLI_E2E_IMAGE` 和 `CLI_E2E_CASE` 指定凭据、图片和单个场景。该驱动会向真实服务端发送多条消息，适合隔离的测试账号。
