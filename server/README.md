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
python3 scripts/deploy/deploy.py init --root "$INSTALL_DIR"
```
脚本将在安装目录下搭建所需要的目录结构，并生成默认的部署配置。其中默认服务名称为 `agentluo.service`，端口为 `15673`；需要其他端口时加 `--port 端口`。`--name` 指定的是 `agentluo` 后的名称后缀，而不是完整重命名：例如 `--name test` 创建 `agentluo-test.service`。省略 `--name` 时服务为 `agentluo.service`，部署配置中的实例名仍为 `production`；指定 `--name test` 时实例名为 `test`。

然后配置密钥：
```bash
nano "$INSTALL_DIR/config/secrets.local.env"
```
在打开的文件中填写 `QWEN_API_KEY`、`SILICONFLOW_API_KEY` 和 `AMAP_KEY`，分别用于 DashScope 模型、硅基流动向量模型和高德地图。自动生成的 `JWT_SECRET` 保持原样。

**2. 导入模型资源。** 向维护者获取与当前版本配套的模型资源，解压到一个目录，使该目录下直接包含 `tts/` 和 `song_learner/`。把下面的路径改成你的解压位置：

```bash
MODEL_SOURCE="$HOME/agentluo-models"
python3 scripts/deploy/deploy.py assets --root "$INSTALL_DIR" --source "$MODEL_SOURCE"
```

脚本会检查所需文件是否齐全、内容是否匹配，复制到安装目录并设置权限；源文件保持不变。缺文件或版本不匹配时会列出具体路径，请补齐资源后重新执行。NLTK 等内部资源的位置与权限由脚本处理。

**3. 部署服务。** 脚本会从当前 Git 提交构建服务、安装锁定的 Python 环境和 Chromium、生成运行配置，并连接好各类资源路径。首次执行需要下载依赖，耗时取决于网络速度。

```bash
python3 scripts/deploy/deploy.py install --root "$INSTALL_DIR"
```

显示“首次部署文件已就绪”后进入下一步。此时尚未启动服务；无需手写 `instance.env`、创建符号链接或初始化数据库。模型导入与部署默认使用 `HEAD`；部署指定标签时，两条命令都加上同一个 `--ref 标签`。未提交的源码修改不会进入部署结果。

**4. 在终端启动服务。** 加载部署脚本自动生成的实例环境文件，再运行安装目录中的启动器；不需要注册系统服务。以下命令在 Bash 中执行：

```bash
INSTALL_DIR="$HOME/agentluo-production"
(
  set -a
  source "$INSTALL_DIR/deployments/instance.env" || exit 1
  set +a
  exec bash "$INSTALL_DIR/current/scripts/deploy/startup/start_linux.sh"
)
```

如果使用了其他安装位置，请修改 `INSTALL_DIR`。启动日志直接显示在当前终端，按 Ctrl+C 停止服务；再次启动时重复这段命令即可。环境设置放在子 Shell 中，不影响当前终端后续执行的其他命令。

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

`init` 和 `install` 只用于全新实例，不会覆盖已有数据或替代版本更新。后续更新沿用脚本生成的 `deployments/deploy.toml`，按[版本更新步骤](scripts/deploy/README.md#版本更新)操作。

### 更新已部署的服务

已由 systemd 管理的服务更新版本时，沿用原安装目录和部署配置，按[部署工具的版本更新步骤](scripts/deploy/README.md#版本更新)操作。该流程会检查目标版本，准备依赖，停服备份并切换版本；无需重新执行首次安装命令。该自动更新流程依赖 systemd；仅在终端运行的实例若要使用它，先完成上述可选的系统服务设置。

### 使用测试服务器的资源、配置和数据

支持将代码放在自己的 home 目录，通过外部路径或目录链接使用已有模型、配置和数据。前台启动可直接设置环境变量；使用 systemd 长期运行时，可将路径保存到自定义 `instance.env`。操作示例、共享数据的使用条件及与自动部署的区别见[外部路径与链接部署](scripts/deploy/README.md#外部路径与链接部署)。

## 开发环境与源码运行

开发环境在仓库中安装，生产实例的 `environments/` 由版本部署管理。以下命令均从仓库的 `server/` 执行，配置、数据和运行目录应与生产隔离。

### Linux 源码环境

准备上述主机依赖后，以普通账号运行安装器。它创建仓库内的 `.venv/`，按锁安装依赖，安装 Chromium 系统库及浏览器，并检查 CUDA、音频处理和浏览器渲染；系统库安装需要管理员权限。

```bash
bash scripts/deploy/environment/install_linux.sh
source .venv/bin/activate
uv pip install --python .venv/bin/python -e ".[dev]"
bash scripts/deploy/startup/start_linux.sh --check-startup
bash scripts/deploy/startup/start_linux.sh
```

运行前准备开发配置、密钥和资源。路径默认是源码目录下的 `config/`、`res/`、`data/`、`.runtime/`；通过 `AGENTLUO_CONFIG_DIR`、`AGENTLUO_RESOURCE_DIR`、`AGENTLUO_ASSET_DIR`、`AGENTLUO_DATA_DIR`、`AGENTLUO_RUNTIME_DIR` 可指定独立位置。`--check-startup` 仅检查配置解析及监听设置，不启动 HTTP、数据库或模型，也不替代资源检查和实际推理。路径解析、资源校验命令及迁移方式见 [资源布局说明](scripts/deploy/RESOURCE_LAYOUT.md)。

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

## 测试管理与运行

`server/tests` 按验证边界组织，而不是逐级复制 `src` 的内部目录。测试文件只放在 `unit/`、`integration/`、`e2e/`；可跨目录复用的 fake、样例构造器与测试装配集中放在 `support/`，不放业务断言。根目录的 `conftest.py` 负责公共 fixture、标记和外部依赖开关；`support/` 模块使用 `from support.<模块> import ...` 导入。

| 目录 | 用途 | 默认运行条件 |
| --- | --- | --- |
| `unit/<module>/` | 单一顶层模块的快速离线测试；外部系统使用 fake | 默认运行 |
| `integration/<boundary>/` | 在同一进程连接多个真实组件，可使用临时数据库、文件系统或 TestClient | 默认运行 |
| `e2e/chat/` | 从生产装配或真实入口验证完整离线业务链 | 默认运行 |
| `e2e/external/` | 需要公网、凭据、模型或其他真实外部依赖的探测 | 默认跳过，显式启用 |
| `support/` | 各层共用的 fixture、fake 与数据构造器 | 被测试导入，本身不收集为测试 |

在 `server` 目录运行：

```powershell
python -m pytest tests/unit -q --tb=short
python -m pytest tests/integration -q --tb=short
python -m pytest tests/e2e -q --tb=short
python -m pytest tests -q --tb=short
```

默认全套会跳过标记为 `external` 或 `real_llm` 的探测。需要真实外部依赖时运行 `python -m pytest tests/e2e/external -q --run-external --tb=short`；真实 LLM 测试另加 `--run-real-llm`。覆盖率门禁、标记和环境开关的完整说明见 [server/tests/README.md](tests/README.md)；架构边界验证位于 `tests/integration/architecture/`。

### 按改动选择验证入口

| 要修改的内容 | 首先查看 | 对应验证入口 |
| --- | --- | --- |
| 刺激、行动及报告结构 | `domain/agent`、双方 producer / consumer | [tests/unit/domain](tests/unit/domain) |
| 回复、图片理解、记忆与技能 | `agent/handlers`、`agent/skills`、`agent/context` | [tests/unit/agent](tests/unit/agent)、[tests/integration/agent](tests/integration/agent) |
| 等待、批次、打断、重连 | `stage`、`adapter/websocket` | [tests/integration/stage](tests/integration/stage)、[tests/integration/websocket](tests/integration/websocket) |
| 路由、账号、管理和启停 | `web`、`application`、`server_runtime.py` | [tests/integration/system](tests/integration/system)、[tests/integration/lifecycle](tests/integration/lifecycle) |
| 世界任务与事实投递 | `world`、`WorldStage`、相关刺激 handler | [tests/unit/world](tests/unit/world)、[tests/integration/world](tests/integration/world) |
| 持久化和模型接入 | `infrastructure`、相关技能适配器 | [tests/unit/infrastructure](tests/unit/infrastructure)、[tests/integration/persistence](tests/integration/persistence) |
| CLI 动作、回复聚合和机器输出 | `cli-client/cli_client` 中的动作、会话与网络层 | [cli-client/tests](../cli-client/tests) 中的离线测试；真实服务端试运行样例见 [manual_e2e](../cli-client/tests/manual_e2e) |

测试命令与外部依赖开关见 [server/tests/README.md](tests/README.md)，静态职责约束见 [check_architecture_boundaries.py](scripts/check_architecture_boundaries.py)。部分测试目录仍保留 `system` 等历史名字，定位生产代码时以[代码地图](../docs/代码地图.md)和当前 imports 为准。

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
- 感谢ChatGPT，这是我大爹，我的代码基本都是它写的。
- 感谢所有贡献者的努力和支持！
