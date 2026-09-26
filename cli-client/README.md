# AgentLuo CLI 客户端

`cli-client/` 是项目根目录下的独立无界面客户端。它通过公开 HTTP 和 WebSocket 接口完成注册、登录、聊天、图片、触摸、历史、动态与偏好验收；运行时不导入桌面端 `client/` 的代码，也不使用桌面端的配置或登录凭据。

## 安装

需要 Python 3.10 或更新版本。在本目录执行：

```powershell
cd cli-client
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

普通登录可在支持这些 Python 依赖的平台运行；自动登录令牌使用 Windows DPAPI 加密，只能由保存它的 Windows 用户在本机解密。音频重放使用 Windows 的 `winsound`；其他平台仍可接收和保存音频。

## 配置受测服务与账号

CLI 不读取桌面端 `client/config/config.json`。在当前 PowerShell 会话中指定受测服务和独立测试账号：

```powershell
$env:CLI_E2E_BASE_URL = 'https://your-test-server.example'
$env:CLI_E2E_USER = 'your-test-user'
$env:CLI_E2E_PASSWORD = '<your-password>'
```

如需注册，另外设置受测环境提供的邀请码，然后调用公开注册动作：

```powershell
$env:CLI_E2E_INVITE = '<your-invite-code>'
$register = @{ action = 'account.register'; params = @{
    base_url = $env:CLI_E2E_BASE_URL
    username = $env:CLI_E2E_USER
    password_env = 'CLI_E2E_PASSWORD'
    password_confirm_env = 'CLI_E2E_PASSWORD'
    invite_code = $env:CLI_E2E_INVITE
} } | ConvertTo-Json -Compress -Depth 5
$register | python cli.py
```

手动登录并读取连接时自动加载的聊天历史：

```powershell
$connect = @{ action = 'session.connect'; params = @{
    base_url = $env:CLI_E2E_BASE_URL
    username = $env:CLI_E2E_USER
    password_env = 'CLI_E2E_PASSWORD'
    remember_login = $true
} } | ConvertTo-Json -Compress -Depth 5
@($connect, '{"action":"history.initial"}') | python cli.py
```

`remember_login` 默认关闭。显式开启后，CLI 将服务端登录令牌加密保存到本目录的 `temp/cli_auto_login.json`；该目录被 Git 忽略，不与桌面端共享。后续可用 `'{"action":"session.auto_connect"}' | python cli.py` 自动登录。密码和邀请码不要写进受版本控制的场景文件；JSONL 输出会遮蔽动作中提供的敏感值。

## 运行场景与测试

`python cli.py --interactive` 从标准输入持续接收 JSON 动作；`--action '<JSON>'` 执行单个动作；`--scenario <文件>` 执行场景并输出 JSONL。日志写入标准错误。所有需要保持同一连接的动作应在一个 CLI 进程内发送。

`tests/manual_e2e/` 提供真实服务端场景和图片生成工具，运行方法见 [manual_e2e/README.md](tests/manual_e2e/README.md)。离线测试在本目录运行：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

动作与验收边界见 [CLI 规格](../docs/开发进程文档/CLI端到端测试客户端-spec.md)。默认本地音频位于 `temp/tts_output/`；临时文件和测试证据位于 `temp/`，均不提交到 Git。
