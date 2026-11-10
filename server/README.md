# AgentLuo-Server 洛天依对话Agent的服务端
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)

## 项目介绍

AgentLuo 是以虚拟歌手洛天依为角色的对话系统。服务端负责对话、记忆检索、图片理解、语音合成和歌曲处理；桌面端和移动端负责播放声音并展示 Live2D 角色表情和口型。

## 服务端部署

服务端使用 Python 3.10 和 FastAPI 提供 HTTP 与 WebSocket 接口。SQLite 保存业务数据，ChromaDB 保存向量索引，短期消息缓冲由服务进程管理。GPT-SoVITS 在本机执行语音合成，文本、视觉等模型按配置调用外部接口。

### 准备代码、资源和配置

在部署目录克隆仓库，进入包含 `server_main.py` 的目录。下文的相对路径和命令均从该目录执行。

```bash
git clone https://github.com/SheepLiu712/Agent-LuoTianyi.git
cd Agent-LuoTianyi/server
```

1. 向项目维护者获取运行资源，放入 `res/` 。 `data/`是用户数据，独立部署不需要获取。管理后台的静态入口是 `res/admin_ui/admin_static/index.html`，同目录的 `assets/` 保存网页脚本和样式。
2. 迁移已有实例时，先停止源服务或取得数据库的一致性备份，再复制配置、资源和数据。SQLite 数据库和关联的预写日志（WAL）应来自同一份快照。迁移到 Linux 后，核对配置和模型文件中的路径、文件名大小写以及运行账号的读写权限。
3. 编辑 `config/config.json`，将 `is_debug` 设为 `false`，确认 `server.production_port`（仓库默认 `15673`）。默认监听地址为 `127.0.0.1`。
4. 编辑 `config/secrets.local.env`，每行写入一个 `变量名=实际值`，保留已有条目。服务启动时会加载该文件。下表列出仓库默认配置所需的密钥；自定义模型使用对应配置引用的环境变量。

| 变量 | 用途 |
| --- | --- |
| `JWT_SECRET` | 登录令牌签名。迁移时沿用原值可保持已有令牌有效。 |
| `QWEN_API_KEY` | DashScope 平台的文本、视觉及语音模型。 |
| `SILICONFLOW_API_KEY` | 硅基流动平台的向量嵌入模型。 |
| `AMAP_KEY` | 城市漫步任务使用的高德地图 Web 服务。 |

### Linux 安装与启动

以下步骤适用于 Ubuntu 24.04、x86_64 架构和支持 CUDA 12.8 的 NVIDIA 显卡。使用同一个普通账号安装项目环境和运行服务。系统软件包安装需要管理员权限。

**1. 安装系统工具。** FFmpeg 用于音频编解码，编译工具用于构建学歌依赖，uv 用于安装 Python 和同步项目环境。使用 `nvidia-smi` 确认当前账号可访问显卡。

```bash
nvidia-smi
sudo apt update
sudo apt install -y curl ca-certificates ffmpeg libsndfile1 libportaudio2 build-essential
uv_installer=$(mktemp)
curl -fLsS https://astral.sh/uv/install.sh -o "$uv_installer" &&
  sudo env UV_INSTALL_DIR=/usr/local/bin UV_NO_MODIFY_PATH=1 sh "$uv_installer"
rm -f "$uv_installer"
uv --version
ffmpeg -version
```

**2. 设置权限并运行安装脚本。** 由运行账号持有生产目录，限制配置文件的访问权限。已有服务先停机，再同步依赖。

```bash
chmod 700 . config
touch config/secrets.local.env
chmod 600 config/secrets.local.env
if [ -f config/admin_auth.json ]; then chmod 600 config/admin_auth.json; fi
bash scripts/deploy/install_linux.sh
```

安装脚本使用 Python 3.10.22 创建 `.venv/`，按 [Linux 依赖锁文件](scripts/deploy/uv.lock) 安装 PyTorch 2.9.1、torchaudio 2.9.1 和 torchvision 0.24.1 的 CUDA 12.8 构建，以及语音合成和学歌依赖。随后安装 Chromium 的系统库和浏览器，浏览器文件保存在 `.runtime/browsers/`。安装结束前会检查 Python 依赖、显卡矩阵运算、音频重采样、MP3 编码和浏览器页面渲染。

**3. 前台启动并验收。**

```bash
bash scripts/deploy/start_linux.sh
```

启动日志应出现“配置校验通过，ServerRuntime 已自动启动”。在服务器上打开 `http://127.0.0.1:15673/admin`（端口以配置为准），确认业务运行时已启动，再通过客户端发送一条消息并试听语音回复。前台运行时可用 Ctrl+C 停止服务。

**4. 需要后台运行时，交给 systemd 管理。** 先停止前台实例，复制 [systemd 模板](scripts/deploy/agentluo.service.example) 并编辑：

```bash
cp scripts/deploy/agentluo.service.example /tmp/agentluo.service
nano /tmp/agentluo.service
```

将模板中的全部占位符替换为实际值：`@SERVICE_USER@` 是安装环境时使用的普通账号（`id -un`），`@SERVER_DIR@` 是包含 `server_main.py` 的绝对路径（`pwd -P`），`@SERVICE_HOME@` 是该账号的主目录。模板设置失败重启、5 分钟内最多启动 3 次、120 秒停止超时，并将日志交给 journal。检查并安装服务单元：

```bash
systemd-analyze verify /tmp/agentluo.service
sudo install -m 644 /tmp/agentluo.service /etc/systemd/system/agentluo.service
sudo systemctl daemon-reload
sudo systemctl start agentluo
systemctl status agentluo --no-pager
sudo journalctl -u agentluo -n 100 --no-pager
```

按前述启动日志和客户端交互步骤验收。需要开机自启时执行 `sudo systemctl enable agentluo`。日常启停使用 `sudo systemctl stop agentluo` 和 `sudo systemctl restart agentluo`。

### Windows 安装与启动

推荐使用 uv 管理项目内的 Python 虚拟环境。两种方案都安装 Python 3.10、PyTorch、语音合成与学歌依赖，以及 Chromium。编译学歌依赖需要 Visual Studio Build Tools 的“使用 C++ 的桌面开发”工作负载。以下命令均从服务端目录执行。

**方案一：uv（默认）。** 准备 uv 和 FFmpeg，使 `uv --version` 和 `ffmpeg -version` 能在终端运行。可分别通过 `winget install --id astral-sh.uv -e` 和 `winget install --id Gyan.FFmpeg -e` 安装，安装后重新打开终端。一行命令安装项目环境到 `.venv`：

```bat
.\scripts\deploy\install_windows.bat uv
```

随后运行以下命令，或双击 `scripts\deploy\start_server.bat`：

```bat
.\scripts\deploy\start_server.bat
```

**方案二：Conda。** 安装 Miniconda 或 Anaconda，在 Anaconda Prompt 中执行以下命令。脚本创建或更新名为 `lty` 的环境，并在该环境中安装 FFmpeg：

```bat
.\scripts\deploy\install_windows.bat conda
```

在 Anaconda Prompt 中使用同一启动脚本：

```bat
.\scripts\deploy\start_server.bat conda
```

**选择显卡和环境名。** 安装命令的第二个参数选择 PyTorch 构建，默认值为 `cpu`。使用 NVIDIA 显卡时，按驱动支持的 CUDA 版本选择 `cu126`、`cu128` 或 `cu130`。例如，`.\scripts\deploy\install_windows.bat uv cu128` 安装 CUDA 12.8 构建。Conda 可通过第三个参数指定环境名，例如用 `.\scripts\deploy\install_windows.bat conda cu128 agentluo` 安装，再用 `.\scripts\deploy\start_server.bat conda agentluo` 启动。

Windows 和 Linux 启动脚本都会保留已有的代理例外，并将本机、模型接口、高德地图和 VCPedia 的主机名加入 `NO_PROXY`，使这些连接直接访问目标主机。启动后按终端显示的地址进入管理后台，确认业务运行时已启动。

迁移到 Windows 生产目录时，在 PowerShell 中运行 `./scripts/deploy_to_e_server.ps1 -PlanOnly` 预览复制范围。停止源服务后运行 `./scripts/deploy_to_e_server.ps1`，默认目标为 `E:\server`；复制中断后可加 `-Resume` 续传。在目标环境中完成上述依赖安装和配置，再启动服务。

### 开发与采集配置

开发和测试工具可在开发环境中使用 `python -m pip install -e ".[dev]"` 安装。VCPedia 采集规则随 Python 包分发；可选片段合并和模型辅助提取由 `crawler.merge_rendered_fragments` 和 `crawler.use_llm` 控制。启用模型辅助处理时，分别为摘要配置 `llm_module`、为补提配置 `extraction_llm_module`，并提供对应模型的密钥。采集测试入口见 [World 测试说明](tests/unit/world/README.md)。

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
