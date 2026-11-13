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

### Linux 源码环境

准备上述主机依赖后，以普通账号运行安装器。它创建仓库内的 `.venv/`，按锁安装依赖，安装 Chromium 系统库及浏览器，并检查 CUDA、音频处理和浏览器渲染；系统库安装需要管理员权限。

```bash
bash scripts/deploy/environment/install_linux.sh
source .venv/bin/activate
uv pip install --python .venv/bin/python -e ".[dev]"
bash scripts/deploy/startup/start_linux.sh --check-startup
bash scripts/deploy/startup/start_linux.sh
```

运行前准备开发配置、密钥和资源。路径默认是源码目录下的 `config/`、`res/`、`data/`、`.runtime/`，分别对应配置文件、资源文件、数据文件和运行时文件（日志等）。`--check-startup` 仅检查配置解析及监听设置，不启动 HTTP、数据库或模型，也不替代资源检查和实际推理。路径解析、资源校验命令及迁移方式见 [资源布局说明](scripts/deploy/RESOURCE_LAYOUT.md)。

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
