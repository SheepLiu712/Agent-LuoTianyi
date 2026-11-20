# AgentLuo-Server 洛天依对话Agent的服务端
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)

## 项目介绍

AgentLuo 是以虚拟歌手洛天依为角色的对话系统。服务端负责对话、记忆检索、图片理解、语音合成和歌曲处理；桌面端和移动端负责播放声音并展示 Live2D 角色表情和口型。

## 服务端部署
已有实例迁移和版本更新见[部署工具说明](scripts/deploy/README.md)，下面介绍首次部署的步骤。

### 仓库与安装位置

源码仓库和服务安装目录往往不是同一个目录：仓库用于开发、测试和发布；服务安装目录负责保存和运行稳定的服务。

为了`部署`服务，您需要获取仓库中服务端的部分，并将其`部署`到一个独立的目录。服务使用的代码、模型、配置及用户数据由部署脚本放到独立安装目录。

部署目录可放在 home 下，也可放在其他磁盘分区；不建议直接在仓库目录运行生产服务。

先获取代码，进入 `server/`，后续命令都在这里执行：

```bash
git clone https://github.com/SheepLiu712/Agent-LuoTianyi.git
cd Agent-LuoTianyi/server
```

### Linux 首次部署

以下命令适用于 Ubuntu 24.04 x86_64，在普通用户终端执行；安装系统软件包时会请求 sudo 权限。先确认 `nvidia-smi` 能正常显示显卡。

```bash
nvidia-smi
```
应该保证其驱动版本和CUDA版本支持 Cuda 12.8。然后执行系统软件包的安装：

```bash
sudo apt update
sudo apt install -y git curl ca-certificates python3 ffmpeg libsndfile1 libportaudio2 build-essential pkg-config

# 安装 uv，并让当前终端能够找到它
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

# 按项目锁定的 Playwright 版本安装 Chromium 所需系统库和字体
uvx --from playwright==1.64.1 playwright install-deps chromium

# 检查uv和ffmpeg是否安装成功
uv --version
ffmpeg -version
```

完成主机依赖安装后，按下面四步安装，便可以在终端启动服务。需要后台运行和开机自启时，可选择执行最后的步骤。所有命令使用同一个普通账号执行。

**1. 创建安装目录。** 选择一个尚未使用的目录，脚本会创建所需子目录、生成登录签名密钥和部署配置。无需手动区分配置、数据库或临时文件的存放位置。

```bash
INSTALL_DIR="$HOME/agentluo-production"
bash scripts/deploy/init_instance.sh --root "$INSTALL_DIR"
```
脚本将在安装目录下搭建所需要的目录结构，并生成默认的部署配置。其中默认服务名称为 `agentluo.service`，端口为 `15673`；需要其他端口时加 `--port 端口`。使用`--name` 指定 `agentluo` 后的名称后缀：例如 `--name test` 创建 `agentluo-test.service`。省略 `--name` 时服务为 `agentluo.service`。

部署配置中的实例名默认为 `production`；指定 `--name test` 时实例名为 `test`。

然后配置密钥：
```bash
nano "$INSTALL_DIR/config/secrets.local.env"
```
在打开的文件中填写 `QWEN_API_KEY`、`SILICONFLOW_API_KEY` 和 `AMAP_KEY`，分别用于 DashScope 模型、硅基流动向量模型和高德地图。自动生成的 `JWT_SECRET` 保持原样。

**2. 导入模型资源。** 向维护者获取与当前版本配套的模型资源，解压到一个目录，使该目录下直接包含 `tts/` 和 `song_learner/`。把下面的路径改成你的解压位置：

```bash
MODEL_SOURCE= "/path/to/your/model_assets"
python3 scripts/deploy/deploy.py assets --root "$INSTALL_DIR" --source "$MODEL_SOURCE"
```

脚本会检查所需文件是否齐全、内容是否匹配，复制到安装目录并设置权限；源文件保持不变。缺文件或版本不匹配时会列出具体路径，请补齐资源后重新执行。

**3. 部署服务。** 脚本会从当前 Git 提交构建服务、安装锁定的 Python 环境和 Chromium、生成运行配置，并连接好各类资源路径。首次执行需要下载依赖，耗时取决于网络速度。

```bash
bash scripts/deploy/install_instance.sh --root "$INSTALL_DIR"
```

显示“首次部署文件已就绪”后进入下一步。此时尚未启动服务；无需手写 `instance.env`、创建符号链接或初始化数据库。模型导入与部署默认使用 `HEAD`；部署指定标签时，两条命令都加上同一个 `--ref 标签`。未提交的源码修改不会进入部署结果。

**4. 在终端启动服务。** 使用以下命令在终端中启动服务。启动器会自动加载该实例的 `deployments/instance.env`以读取对应的实例配置：

```bash
bash "$INSTALL_DIR/current/scripts/deploy/startup/start_linux.sh"
```

`INSTALL_DIR` 使用第一步设置的安装位置。新开终端时先重新设置该变量。日志直接显示在终端，按 Ctrl+C 停止，再次启动时重复上述命令即可。启动器中的环境设置不会影响当前终端。

启动后打开管理页面（默认 `http://127.0.0.1:15673/admin`），按照页面提示完成管理员设置，确认业务运行时已启动，再通过客户端发送消息并试听语音。数据库由服务首次启动时自动创建。模型密钥或资源的运行问题可在管理页面和终端日志中检查。

**5. 可选：设置为系统服务。** 如果希望关闭终端后继续运行，或需要开机自启，先按 Ctrl+C 停止前台服务，再从仓库的 `server/` 目录执行：

```bash
python3 scripts/deploy/deploy.py systemd --root "$INSTALL_DIR"
```

脚本会生成 systemd 单元，绑定当前账号和安装目录，安装并启动后台服务，同时设置开机自启。执行时按提示输入 sudo 密码。systemd 启动成功仅表示进程已启动，仍需通过管理页面确认业务运行时状态。

完成可选的 systemd 设置后，使用默认实例名称时，可执行以下命令查看状态和日志；仅在终端运行时直接查看终端输出和管理页面：

```bash
python3 scripts/deploy/deploy.py --config "$INSTALL_DIR/deployments/deploy.toml" status \
  --instance production --json
journalctl -u agentluo.service -n 100 --no-pager
```

`init_instance.sh` 和 `install_instance.sh` 只用于全新实例，不会覆盖已有数据或替代版本更新。后续更新沿用脚本生成的 `deployments/deploy.toml`，按[版本更新步骤](scripts/deploy/README.md#版本更新)操作。

### 使用测试服务器的资源、配置和数据

支持将代码放在自己的 home 目录，通过外部路径或目录链接使用已有模型、配置和数据。前台启动可直接设置环境变量；使用 systemd 长期运行时，可将路径保存到自定义 `instance.env`。操作示例、共享数据的使用条件及与自动部署的区别见[外部路径与链接部署](scripts/deploy/README.md#外部路径与链接部署)。

## 开发环境与源码运行

开发环境在仓库中安装，生产实例的 `environments/` 由版本部署管理。以下命令均从仓库的 `server/` 执行，配置、数据和运行目录应与生产隔离。

### 按组件关闭重资源：隔离源码联调

以下开关在业务 runtime 装配时生效，默认全部为 JSON `true`；只接受 `true/false`，`"false"`、`0`、`null` 等不是合法值。省略开关等同 `true`，不等于可以省略角色、模型和其他核心配置。本功能没有新增 preset、环境模式或一键关闭 world 的控制台入口。

| 完整配置键 | 默认 | 关闭后的行为与限制 |
| --- | --- | --- |
| `agent_runtime.skills.speaking.enabled` | `true` | 不创建 TTS worker、不加载 TTS 权重；普通 SAY（含预制欢迎和瞬时反应）只交付文字／表情和成功终态，不读取预制音频。它不是全局静音：Sing 演唱仍可输出歌曲音频。通话能力不可用，满足更早条件时原因是 `call_tts_unavailable`；独立通话配置错误仍按原规则校验。 |
| `agent_runtime.vector_store.enabled` | `true` | 不创建 Chroma／embedding 资源，长期记忆召回为空；显式记忆和维护仍保存 SQL 正本、画像、摘要及进度，不产生假向量 ID／链接。公共歌曲资料仍可查询。重新启用并重启后恢复旧索引，但关闭期间的新 SQL-only 正本不会自动回填，也不承诺已有回填命令。 |
| `world.citywalk.enabled` | `true` | 不构造／注册城市漫步；顶层 `false` 压过角色覆盖，并解除 AMAP 核心必需条件。 |
| `world.auto_song_learner.enabled` | `true` | 不构造自动学歌任务及其专属资源；不关闭已有歌曲演唱，显式学歌不保证完成。 |
| `world.qq_music_credential_refresh.enabled` | `true` | 不启动 QQ 音乐凭据定时或启动即刷新；即便开启，没有自动学歌任务时也不创建刷新任务。 |
| `world.bili_dynamic_fetcher.enabled` | `true` | 不采集 B 站动态，不读取该任务 cookie，也不启动该任务 browser。 |
| `world.dynamic_interaction.enabled` | `true` | 不进行 world 动态互动轮询；HTTP 动态读写仍可用。 |
| `world.diary.enabled` | `true` | 不进行定时日记规划；不改日记技能内部算法。 |
| `world.song_knowledge.enabled` | `true` | 不构造／注册 VCPedia 歌曲知识抓取任务；已有 SQL 歌曲知识和目录仍可读。 |
| `world.proactive_topic_check.enabled` | `true` | 不运行 world 主动提醒扫描；不关闭 ChatStage 自有期限、登录欢迎或 WS 心跳。 |
| `world.expired_event_cleanup.enabled` | `true` | 不注册过期事件清理任务；过期数据会积累，重新启用仍按原清理规则执行。 |

九项 world 都关闭时，world 定时注册与执行集合为空，不构造这些任务。它不表示进程没有其他后台工作：节假日正本初始化、Stage 回收、心跳和观测仍按原契约运行。`crawler.activated=false`、把间隔设为 `0` 或很大都不能代替关闭任务。

**城市漫步混合组合（M1-S）。** 若 `world.citywalk.enabled=true`，但向量库关闭，保留用户“请求开启”的配置和原任务周期，validator 发出 `citywalk.vector_projection` warning；整个城市漫步执行跳过，不生成报告、SQL travel 或观察事实，也没有可报告的向量写入成功数。该组合不是“城市漫步正常、只少索引”。AMAP 仍按 citywalk 请求开启进行校验；只有顶层明确设 `world.citywalk.enabled=false` 才解除 AMAP 核心要求。启用向量库并重启后恢复原城市任务，不补跑跳过轮次。

**旧索引与重置。** 向量关闭不删除已有数据。全新无索引隔离实例可正常重置；若磁盘有旧向量资料或无法确认目录为空，严格用户重置返回 `USER_DATA_RESET_FAILED`、`vectors.success=false`、`vectors.error="VectorDeletionUnavailable"`，表示向量步骤未清除。请先重新启用向量库并重启，再重试重置；不要手删共享目录或把删除数 `0` 当作清除完成。其他步骤可能已部分成功，不提供事务回滚保证。

#### 1. 创建独立配置、数据和运行目录

使用已经安装项目依赖的 Python 环境，不需要为切换开关重装环境。以下 PowerShell 命令块从**仓库根目录**开始，第一行进入 `server/`；后续直到服务启动均保持该 cwd。`$instance` 必须是一个全新、未使用的目录；只复制公开模板，不覆盖现用配置。配置、数据与日志各自隔离，源码静态资源只读共享；禁用的 TTS／学歌资产目录可以是这个隔离实例下不存在的路径。

```powershell
cd server
$instance = Join-Path $env:TEMP ('agentluo-components-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path (Join-Path $instance 'config') | Out-Null
Copy-Item config/config.json.template (Join-Path $instance 'config/config.json')
$env:AGENTLUO_CONFIG_DIR = Join-Path $instance 'config'
$env:AGENTLUO_DATA_DIR = Join-Path $instance 'data'
$env:AGENTLUO_RUNTIME_DIR = Join-Path $instance 'runtime'
$env:AGENTLUO_ASSET_DIR = Join-Path $instance 'assets'
$env:AGENTLUO_RESOURCE_DIR = (Resolve-Path res).Path
$env:SERVER_HOST = '127.0.0.1'
```

这些都是原有路径隔离变量，不是能力开关。`AGENTLUO_RESOURCE_DIR` 保留当前版本 persona、prompt、表情、预制文字及静态曲库；`AGENTLUO_DATA_DIR` 保存本实例 SQL、媒体和知识数据。不要把这些变量指向生产用户数据。Linux 可用相同绝对路径设置 `export AGENTLUO_*`，然后用已有 Python 或源码启动器；Windows 也可沿 `scripts/deploy/startup/start_server.bat` 选择已有环境。

用编辑器打开 `$env:AGENTLUO_CONFIG_DIR/config.json`，只在模板副本中把上表两项重组件与九项 world 开关设为 `false`，保留原角色 ID、模型绑定和其他节点。例如将以下片段**逐叶合并**，不要用它覆盖整个文件：

```json
{
  "agent_runtime": {
    "skills": {"speaking": {"enabled": false}},
    "vector_store": {"enabled": false}
  },
  "world": {
    "citywalk": {"enabled": false},
    "auto_song_learner": {"enabled": false},
    "qq_music_credential_refresh": {"enabled": false},
    "bili_dynamic_fetcher": {"enabled": false},
    "dynamic_interaction": {"enabled": false},
    "diary": {"enabled": false},
    "song_knowledge": {"enabled": false},
    "proactive_topic_check": {"enabled": false},
    "expired_event_cleanup": {"enabled": false}
  }
}
```

在同一副本明确设置 `is_debug=true`，把 `server.debug_port` 改为未占用的测试端口（例如 `24524`）。公开模板默认调试端口是 `24523`，生产端口是 `15673`；实际选取由 `is_debug` 决定，不靠另设能力环境变量覆盖。不得启动替代实例后声称现用服务已更新。

密钥仅由操作者写入该隔离配置目录的原有 `secrets.local.env`／管理 Secrets。保留有效 `JWT_SECRET`，并为仍引用的核心模型提供合法密钥及接口；只有所选组件／任务的专属资源可省略。关闭 TTS、embedding、AMAP、B 站和 QQ 任务**不等于零依赖**：角色 persona、prompt、模型引用、SQL／媒体、静态歌曲知识／目录和预制文字／表情仍须有效。关闭自动学歌不自动关闭演唱资料校验；模板保留的其他已启用能力也仍要满足原条件。

#### 2. 启动并完成注册、文字与历史闭环

在同一终端、`server/` cwd 中，使用已安装项目依赖的 Python：

```powershell
python server_main.py --check-startup
python server_main.py
```

`--check-startup` 只检查配置解析和监听设置，不证明数据库、业务装配、文字回复或资源收益已经验收。打开 `http://127.0.0.1:24524/admin`，从隔离配置目录的 `admin_setup_token.txt` 取得首次 setup token，并在页面初始化管理员密码；以后使用该管理员登录。检查 validation 和 Runtime 卡片，只有 `state=running` 且 `running=true` 才是业务运行。配置不全时管理壳仍可运行，不要把 HTTP 可访问等同业务就绪。

在“邀请码管理”生成一个隔离测试邀请码。在另一终端先切到**同一仓库根目录**，以下块第一行再进入 `cli-client/`。使用已有 CLI 环境，按[CLI 操作说明](../cli-client/README.md)设置以下**示例变量**；密码和邀请码由隔离实例操作者提供，不粘贴真实凭据：

```powershell
cd cli-client
$env:CLI_E2E_BASE_URL = 'http://127.0.0.1:24524'
$env:CLI_E2E_USER = 'spec412_user'
$env:CLI_E2E_PASSWORD = '<隔离测试密码>'
$env:CLI_E2E_INVITE = '<本隔离实例生成的邀请码>'
python cli.py
```

在同一 CLI 会话执行；每轮回复后用 `/history` 刷新服务端历史（不要用只读取登录缓存的 `/initial-history`）：

```text
/register
/login
/text "请只回复：核心链路412"
/reply --timeout 120
/history
/text "再说一句你好"
/reply --timeout 120
/history
```

CLI 注册／登录会取当前 RSA 公钥、加密密码并使用原 HTTP 接口，登录后完成原 WebSocket 鉴权。确认两次实际回复正文非空、各有成功终态、普通 SAY 没有音频，历史能找到本用户输入和对应的实际回复，且第二次对话可继续。只有离线固定生成器验收要求逐字“核心链路412”；真实自由模型不保证逐字输出，不能据合理文案差异判失败。此操作流程供非作者联调，当前 README 不声称已完成真实供应商 A5 或性能／内存对比。

#### 3. 控制台修改与恢复

“服务配置”中的独立“组件启动”面板有语音合成和长期向量两个复选框，默认均勾选。切换一项后点击“修改”，只提交变化的叶子；“放弃草稿”恢复本面板最后保存值，不清理其他模型面板的未保存草稿。正在运行时，保存沿 validator → 原子落盘 → 旧 runtime 安全停止／新 runtime 装配；停止状态保存不自动启动。提示以返回的 `runtime.state/running` 为准，`restarted=true` 只表示发起过重启，不等于已就绪。

保存失败保留草稿；已落盘但启动失败时看 Runtime 卡片、配置检查和 `last_error`，补齐所需 TTS 权重／embedding／其他资源后再启动。刷新页面核对保存值，并重新做文字／记忆行为复核。JSON 手改后须显式重启，两个开关不是热切换。重新启用向量不自动回填关闭期间 SQL-only 记录；重新启用语音恢复原校验与音频链路，不吞真实供应商错误。

#### 与全量部署、验证的区别

全量生产 `install/apply` 和资源导入仍按部署锁检查完整 `tts/`、`song_learner/` 资产，本功能不保证全量安装可以省略它们，也不弱化资源清单。无需 TTS 权重的验证应采用上述隔离源码实例；依赖安装耗时／磁盘体积不是启动开关指标。控制台浏览器脚本使用临时 API 响应只验证面板与草稿行为，不替代真实管理 API 重启、两轮 WS／历史、资源构造或真实供应商闭环；这些结果须各自记录。

### Linux 源码环境

准备上述主机依赖后，以普通账号运行安装器。它创建仓库内的 `.venv/`，按锁安装依赖，安装 Chromium 系统库及浏览器，并检查 CUDA、音频处理和浏览器渲染；系统库安装需要管理员权限。

```bash
bash scripts/deploy/environment/install_linux.sh
source .venv/bin/activate
uv pip install --python .venv/bin/python -e ".[dev]"
bash scripts/deploy/startup/start_linux.sh --check-startup
bash scripts/deploy/startup/start_linux.sh
```

运行前准备开发配置、密钥和资源。路径默认是源码目录下的 `config/`、`res/`、`data/`、`.runtime/`，分别对应配置文件、资源文件、数据文件和运行时文件（日志等）。`--check-startup` 仅检查配置解析及监听设置，不启动 HTTP、数据库或模型，也不替代资源检查和实际推理。路径解析、资源校验命令及迁移方式见 [部署工具说明](scripts/deploy/README.md#独立实例路径)。

如果需要指定配置、资产、数据的外部路径，需要提供一个`instance.env`文件，其中设置
```
AGENTLUO_CONFIG_DIR="/path/to/your/config"
AGENTLUO_DATA_DIR="/path/to/your/data"
AGENTLUO_RUNTIME_DIR="/path/to/your/runtime"
AGENTLUO_ASSET_DIR="/path/to/your/assets"
AGENTLUO_RESOURCE_DIR="/path/to/your/resources"
AGENTLUO_PYTHON="path/to/your/python"
```
对于源码运行，`assets`和`resources`目录默认是同一个目录，即源码目录下的`res`。这两类资源的区别是：前者时可跨代码版本复用的，后者是当前版本特有的。

然后使用
```bash
AGENTLUO_INSTANCE_ENV="path/to/your/instance.env"
bash scripts/deploy/startup/start_linux.sh --check-startup
bash scripts/deploy/startup/start_linux.sh
```

来执行。
> `instance.env` 还会可以额外提供以下字段：`PLAYWRIGHT_BROWSERS_PATH`指定无头浏览器的安装路径，`PYTHONDONTWRITEBYTECODE="1"`表示禁止在导入模块的时候写入`.pyc`文件，`SERVER_HOST`指定服务监听的主机地址。示例：
> ```
> PLAYWRIGHT_BROWSERS_PATH="/path/to/your/browsers"
> PYTHONDONTWRITEBYTECODE="1"
> SERVER_HOST="127.0.0.1"
> ```

### Windows 源码环境

推荐使用 uv 管理项目内的 Python 虚拟环境。两种方案都安装 Python 3.10、PyTorch、语音合成与学歌依赖，以及 Chromium。编译学歌依赖需要 Visual Studio Build Tools 的“使用 C++ 的桌面开发”工作负载。以下命令均从仓库的 `server/` 目录执行；这是源码环境安装方式，版本化 `apply` 流程依赖 Linux/systemd。

**方案一：uv（默认）。** 准备 uv 和 FFmpeg，使 `uv --version` 和 `ffmpeg -version` 能在终端运行。可分别通过 `winget install --id astral-sh.uv -e` 和 `winget install --id Gyan.FFmpeg -e` 安装，安装后重新打开终端。一行命令安装项目环境到 `.venv`：

```bat
.\scripts\deploy\environment\install_windows.bat uv
```

随后运行以下命令，或双击 `scripts\deploy\startup\start_server.bat`：

```bat
.\scripts\deploy\startup\start_server.bat
```

**方案二：Conda。** 安装 Miniconda 或 Anaconda，在 Anaconda Prompt 中执行以下命令。脚本创建或更新名为 `lty` 的环境，并在该环境中安装 FFmpeg：

```bat
.\scripts\deploy\environment\install_windows.bat conda
```

在 Anaconda Prompt 中使用同一启动脚本：

```bat
.\scripts\deploy\startup\start_server.bat conda
```

**选择显卡和环境名。** 安装命令的第二个参数选择 PyTorch 构建，默认值为 `cpu`。使用 NVIDIA 显卡时，按驱动支持的 CUDA 版本选择 `cu126`、`cu128` 或 `cu130`。例如，`.\scripts\deploy\environment\install_windows.bat uv cu128` 安装 CUDA 12.8 构建。Conda 可通过第三个参数指定环境名，例如用 `.\scripts\deploy\environment\install_windows.bat conda cu128 agentluo` 安装，再用 `.\scripts\deploy\startup\start_server.bat conda agentluo` 启动。

Windows 和 Linux 启动脚本都会保留已有的代理例外，并将本机、模型接口、高德地图和 VCPedia 的主机名加入 `NO_PROXY`，使这些连接直接访问目标主机。启动后按终端显示的地址进入管理后台，确认业务运行时已启动。

迁移到 Windows 生产目录时，在 PowerShell 中运行 `./scripts/deploy_to_e_server.ps1 -PlanOnly` 预览复制范围。停止源服务后运行 `./scripts/deploy_to_e_server.ps1`，默认目标为 `E:\server`；复制中断后可加 `-Resume` 续传。在目标环境中完成上述依赖安装和配置，再启动服务。

### 开发与采集配置

开发和测试工具可在已激活且包含 pip 的开发环境中使用 `python -m pip install -e ".[dev]"` 安装；uv 环境使用 `uv pip install -e ".[dev]"`。VCPedia 采集规则随 Python 包分发；可选片段合并和模型辅助提取由 `crawler.merge_rendered_fragments` 和 `crawler.use_llm` 控制。启用模型辅助处理时，分别为摘要配置 `llm_module`、为补提配置 `extraction_llm_module`，并提供对应模型的密钥。采集测试入口见 [World 测试说明](tests/unit/world/README.md)。

## 📜 许可证和版权

本项目代码基于 [MIT 许可证](../LICENSE) 开源。

本项目使用的 VCPedia 内容不因进入本仓库而自动获得 MIT 授权。适用条款见站点[浏览前必读](https://vcpedia.cn/VCPedia:浏览前必读)：2026-09-16 后站点编辑团队的授权文本使用 CC BY-NC-SA 4.0；更早的部分历史版本仍适用 CC BY-NC-SA 3.0 中国大陆。歌词、引文、媒体及另有声明的内容不包含在站点整体 CC 授权中，权利仍归各自权利人。

测试材料按页保留来源、捕获/版本证据、版权提示和修改说明，参见 [VCPedia 语料说明](tests/support/vcpedia_corpus/README.md)。自动解析和可选模型补提会转换、清理或重组文本，不能将所有产出称为未经修改的原文；分发和再使用须分别核对站点编辑文本及第三方作品的授权，不以测试用途或仓库许可证替代该核对。

## 🧠 关于AI生成内容的声明
关于AI生成内容。我们认识到VC社区对AI生成内容的关注和担忧。为了透明起见，我们在此声明：
1. 本项目大量使用了LLM，场景包括：
   - 对爬取的文本内容进行结构化处理
   - 生成对话回复
   - 生成语音合成的情感标签
   - 生成Live2D模型的表情标签
   - 压缩对话上下文
   - 生成记忆检索和写入的指令
2. 本项目使用的语音合成技术为GPT-SoVITS，该项目基于AI技术，我们对公开的语音合成模型进行了微调；此外，生成的语音内容为AI生成。
3. 在美术资源上，本项目使用了火爆鸡王发布的洛天依Live2D模型，该模型为非商业用途免费使用，感谢火爆鸡王的分享。在其他的美术资源（目前仅包括背景图和Logo）上，我们使用了网络上公开的免费资源，并且保证这些资源不是由AI生成的。
4. 本项目在编写过程中使用了AI辅助编程工具（如GitHub Copilot），以提高开发效率。但核心逻辑和设计均由开发者完成。
5. 我们力求确保AI生成内容的准确性和合规性，但由于技术限制，可能会存在错误或偏差。如果发现AI生成内容存在明显错误或不当之处，欢迎反馈。

## 🙏 致谢

- 感谢洛天依官方提供的角色设定
- 感谢VCPedia项目组提供的丰富知识库
- 感谢[GPT-SoVITS项目](https://github.com/RVC-Boss/GPT-SoVITS/)提供的开源语音合成技术
- 感谢[火爆鸡王](https://space.bilibili.com/5033594)发布的Live2D模型
- 感谢阿里云、硅基流动平台提供的API服务
- 感谢所有贡献者的努力和支持！


### Stage 回收耗时

回收计时写入现有可观测性 SQLite 数据库（默认 `data/admin_metrics.sqlite3`）的
`pipeline_spans`，正常路径不输出耗时数值日志，不需要数据库迁移。
`trace_id = stage:<interaction_id>` 关联同一次交互，`metadata_json.stage_kind` 区分 `chat` / `call`。

| span_name | 范围 |
| --- | --- |
| `stage.termination.total` | 完整终止任务，包含停止任务、结束维护和上下文/资源清理 |
| `stage.termination.stop_tasks` | 聊天：停止初始化和工作任务；通话：按 `phase` 分别记录 `playback`、`initialization`、`inflight`、`cleanup`，可按交互求和 |
| `stage.termination.maintenance` | 聊天：结束刺激、维护计划执行及超时后的退出等待；通话：结束认知维护技能，不含随后生成的通话概要 |
| `stage.termination.close_context` | 聊天关闭上下文 |
| `stage.termination.cleanup` | 通话资源清理，每次调用分别记录，包含其 `cleanup` 停止任务，不能与它重复相加 |
| `agent.cognitive_maintenance` | 聊天认知维护技能以及通话阈值维护，用 `reason` 区分触发原因 |

`duration_ms` 使用单调时钟；`status` 区分 `success`、`error`、`cancelled`。
业务返回的维护失败也记为 `error`，总计时包含 `finalization_error`、`cleanup_error` 和
`resources_released`。未执行的阶段不产生记录；进程被强制终止时，未退出的计时段无法落库。
埋点写入失败不会改变回收结果。计时只保存身份、状态、错误类型与数值，不保存对话内容。
聊天维护的 90 秒预算保持原有范围，不是整个回收过程的硬上限。

例如查询最近 24 小时的回收耗时：

```sql
SELECT trace_id, span_name, duration_ms, status, metadata_json
FROM pipeline_spans
WHERE span_name LIKE 'stage.termination.%'
  AND julianday(start_ts) >= julianday('now', '-1 day')
ORDER BY start_ts DESC;
```


### 管理看板的用量与链路耗时

“用量趋势”将在线规模、LLM 调用量和 Token 用量放在同一时间轴，固定按北京时间
（UTC+8）显示。在线规模是 Stage 估计值：每 5 分钟按 `(user_id, character_id)`
对保留的 ChatStage、CallStage 去重，包含断线保留及回收中的 Stage。缺失采样显示断线，
不补零。24 小时按 5 分钟展示；7 日按小时展示有效在线样本的平均值、调用及 Token 的总量。
新采样不会补造升级前的在线历史。

“链路耗时”默认最近 24 小时，可选 7 日及数据库中保留的全部数据，分为聊天、通话、
TTS、聊天 Stage 回收、通话 Stage 回收。每行展示样本量、平均值、P50、P90、P99。
各阶段独立统计实际完成的样本，不将缺失或失败阶段补零；回收的多个停止任务及清理
片段先按同一交互求和再计算分位数。失败、取消及不完整请求数量单独显示。

- 聊天包括输入准备、等待回复、主题与意图、记忆检索、LLM 首段、首段交付及总耗时。
  首段交付结束于 Stage 接纳输出，不表示客户端已收到；总耗时从输入准备完成开始。
- 通话仅展示供应商判停至首个音频 ACK、判断说话结束（估计）、记忆检索、LLM 首段、
  首段回复至 TTS 首包。ACK 是客户端确认的代理指标，不是实际扬声器播放时间。
  当前实时模型自动触发回复，LLM 起点是收到 `response.created` 事件，
  不包含此前的供应商内部处理及网络时间。不同轮次汇总展示，不再逐轮展开。
- TTS 从 `SpeakingSkill.speak` 请求进入计时；排队包括线程调度、合成锁等待和 worker
  接收前的等待。首包产出在 worker 生成首个有效音频时记录，同时保留父进程收到首包的
  时间。取消后仍在 worker 内运行的任务继续占用队列统计，直到 worker 完成。

新增的受保护接口是 `GET /admin/api/metrics/usage?window=24h|7d` 和
`GET /admin/api/metrics/latency?window=24h|7d|all`。数据库自动新增
`stage_population_samples`、`tts_requests`、`tts_queue_windows`；TTS 队列在状态变化
及每 10 秒观察一次，每 5 分钟保存等待数量峰值、运行数量峰值和观察到的最长等待。
这些峰值保留供排障查询，界面只显示请求耗时分布。新口径的聊天/通话阶段使用
`chat.v2.*`、`call.v2.*`，不混入旧口径记录。数据沿用现有保留期（默认 30 天）。

TTS 数值由父进程后台批量写 SQLite，音频路径不等待数据库提交；查询及正常关闭会
等待已有写入完成。强制结束进程可能丢失尚未写入的事件，重新打开时将遗留 pending
请求标为 incomplete。埋点不记录对话或音频内容。界面已移除链路追踪及慢 Span，
原始记录和原有查询接口保留供排障使用。

浏览器验收脚本：先在 `res/admin_ui` 执行 `npm run dev -- --host 127.0.0.1`，
再从 `server` 执行 `python scripts/check_admin_metrics_ui.py --output-dir <截图目录>`
（需安装 Playwright 及 Chromium）。脚本使用临时 SQLite 和模拟管理 API，验证桌面、
窄屏、UTC+8 时间展示、时间范围切换及移除的入口；它不调用生产服务。

### 通话建立总时限

管理员在管理控制台“实时音频模型配置”面板设置“通话建立总时限（秒）”，对应 `stage_manager.call_setup_timeout`。缺省为 10 秒，必须是正的有限数字；允许小数。控制台显示实际生效的缺省或已保存值，修改后沿用配置校验和运行时重启流程。此字段只修改 `stage_manager` 下的这一项，不覆盖聊天结束维护等其他设置。

同次拨号的连接、模型就绪、源聊天切换及响铃共用登记时确定的唯一截止时间，重连不续期。明确的连接拒绝、鉴权或初始化错误会立即结束；总时限不是必须等待的最小时长，也不保证网络连接成功。关闭资源可晚于用户看见终态，未确认安全释放前仍保护交互占用。

生产 Qwen 通话不再使用 `call_transport.realtime_speech.connect_timeout_seconds` 和 `session_timeout_seconds`。旧文件可以保留这两项（包括旧非法值），不会用它们截断拨号或阻止生产配置校验；服务启动不自动删除或重写用户配置。请只修改总时限，不再调整旧键。关闭、清理超时和队列容量仍保留各自用途。底层 Aliyun/Fun-ASR 适配器仍保留显式连接与初始化限时，但不属于当前生产 Qwen 通话路径。

### Embedding 请求与维护降级

向量库的 `embedding_model` 配置可设置 `connect_timeout_seconds`（默认 5）、`read_timeout_seconds`（默认 10）、`request_timeout_seconds`（单次完整请求默认 10）、`total_timeout_seconds`（整批含重试默认 30）和 `max_attempts`（默认 3，允许 1–5）。每次重试仍受整批预算约束；查询与维护共用此策略。环境代理与 NO_PROXY 继续由 HTTP 客户端读取，不写死代理。

维护候选先整批生成向量，再持久化。Embedding 耗尽重试时本次记忆跳过，画像、摘要与进度仍更新；日志 `Maintenance memory skipped` 保存批次 ID、候选数、原因、尝试数及 HTTP 状态，不记录记忆正文或密钥。不会自动补写已跳过的批次。数据库错误仍使维护失败。回复前检索最终失败的处理方式未改变。

### 触摸位置契约

服务端内部只接受 `头`、`身体`、`腿`、`手`。`user_touch` 的 `touchArea` 数组或 `touch_area` 字符串/数组可携带 `左腿`、`右腿`、`左手`、`右手`，入口归一并去重；其他名称（包括英文名和模型细分命中区）返回 BAD_MESSAGE，不进入 Stage。App 已将模型命中区转换为四种标准位置。

客户端负责触摸节流；服务端保留 `click_frequency` 格式校验，但不根据计数再次拒绝有效触摸，旧 `touch_reaction.characters.<角色>.policy` 配置不再参与处理。预制语音资源选择、音频交付、表情恢复及瞬时消息不写聊天记录的行为保持不变。
