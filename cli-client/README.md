# AgentLuo CLI 客户端

`cli-client/` 是项目根目录下的独立客户端，通过公开 HTTP 和 WebSocket 接口连接受测服务。运行时不导入桌面端 `client/` 的代码，也不读取它的配置或登录凭据。

## 安装与配置

需要 Python 3.10 或更新版本。在本目录执行：

```powershell
cd cli-client
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:CLI_E2E_BASE_URL = 'https://your-test-server.example'
$env:CLI_E2E_USER = 'your-test-user'
$env:CLI_E2E_PASSWORD = '<your-password>'
$env:CLI_E2E_INVITE = '<your-invite-code>' # 仅注册时需要
python cli.py
```

自动登录令牌使用 Windows DPAPI 加密，只能由保存它的 Windows 用户在本机解密。音频重放使用 Windows 的 `winsound`；其他平台仍可接收和保存音频。令牌与临时媒体保存在 `temp/` 中，已被 Git 忽略。

## 交互命令

输入 `/help` 查看完整命令列表，输入 `/help text` 查看单个命令的用法。输入命令前缀时会显示候选和说明；按 TAB 补全命令名。底部提示显示当前命令的用法。

```text
cli> /register
cli> /login --remember
cli> /initial-history
cli> /text "你好"
cli> /reply --timeout 120
cli> /image "C:\photos\sample.png"
cli> /touch
cli> /preferences
cli> /set-preference "relationship=朋友"
cli> /dynamics
cli> /post "今天天气真好"
cli> /logout
cli> /auto-login
cli> /exit
```

`/text`、`/image` 和 `/touch` 返回服务端 ACK；使用 `/reply` 等待完整回复。图片参数支持本地路径、`file://` URI 和带有受支持图片扩展名的 HTTP(S) URI，下载大小上限与服务端图片限制一致。`/touch` 不带参数时默认触摸“头”。包含空格的参数用引号括起来。登录信息也可以用 `/login <用户名> --url <地址> --password-env <环境变量名>` 指定；密码只从环境变量读取。`/login --remember` 显式保存 CLI 专用的自动登录令牌。

单条命令和脚本也使用同一套语法：

```powershell
python cli.py --command '/status'
python cli.py --script tests/manual_e2e/01-text-send-wait.cli
python cli.py --script tests/manual_e2e/01-text-send-wait.cli --jsonl --report temp/result.json
```

脚本一行一个斜杠命令，允许空行和以 `#` 开头的注释。默认在动作失败后跳过后续有副作用的动作；调试时可显式添加 `--continue-on-failure`。多个需要保持同一连接的动作须在同一个交互会话或脚本内运行。默认输出面向人阅读；`--jsonl` 输出机器可解析的结果。日志写入标准错误，报告默认只保留脱敏元数据。

## 测试

`tests/manual_e2e/` 提供真实服务端场景和图片生成工具，见 [运行说明](tests/manual_e2e/README.md)。离线测试在本目录运行：

```powershell
python -m pip install -r requirements-dev.txt
python -m pytest tests -q
```

动作与验收边界见 [CLI 规格](../docs/开发进程文档/CLI端到端测试客户端-spec.md)。本地回复音频保存在 `temp/tts_output/`。
