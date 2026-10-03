# AgentLuo-Server 洛天依对话Agent的服务端
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)

## 🎵 项目介绍
AgentLuo旨在设计并实现一个具备角色扮演能力的虚拟歌手洛天依（Luo Tianyi）智能对话Agent。该Agent整合了Live2D模型功能和GPT-SoVITS提供的语音合成（TTS）功能，并实现了基于嵌入（Embedding）的向量记忆检索和洛天依歌曲的知识库。

本项目旨在为用户提供沉浸式的洛天依互动体验。该仓库保存了项目的服务端。

### ☀️功能特色
- **角色扮演**：基于洛天依的官方设定和现有作品，塑造符合其性格和背景的对话风格。
- **多模态交互**：集成Live2D模型，实现动态表情和口型同步。
- **语音合成**：利用GPT-SoVITS技术，实现自然流畅的语音输出。
- **歌曲演唱**：支持少量洛天依歌曲的演唱功能。
- **图片识别**：通过集成图像识别技术，能够识别用户上传的图片内容，并进行相关对话。
- **无限上下文管理**：支持长时间对话的上下文记忆，提升交互连贯性。
- **知识库集成**：结合向量数据库和图数据库，实现基于知识的智能回答，使得天依能够记住用户信息和偏好，并且对圈子内的知识有较好的理解。
- **可拓展性**：模块化设计，原则上通过替换资源文件可以将该项目用于其他虚拟角色的构建。

### 🚀 技术栈
注意，服务端的配置难度要远高于客户端。下面简要介绍服务端的技术栈：
- **编程语言**：Python 3.10
- **Web框架**：FastAPI
- **数据库**：sqlite（使用 SQLAlchemy 进行 ORM 操作）
- **缓存**：Redis
- **向量数据库**：ChromaDB
- **TTS合成**：GPT-SoVITS
- **异步任务**：使用 asyncio 和 FastAPI 的 BackgroundTasks 实现异步
- **公网访问**：使用 sakurafrpp 实现内网穿透，支持公网访问

## 🔧服务端架设
### 一、环境要求
- 内存：至少 4GB RAM
- 存储：至少 7GB 可用空间
- 网络连接：需要访问外部API服务
- 运算能力：最消耗算力的部分是GPT-SoVITS的语音合成模块，其余均使用外部API，请访问GPT-SoVITS的[官方仓库](https://github.com/RVC-Boss/GPT-SoVITS/)了解配置要求。

### 二、安装流程
1. 克隆项目仓库：
   ```bash
   git clone https://github.com/SheepLiu712/Agent-LuoTianyi.git
   cd Agent-LuoTianyi/server
   ```

2. 确保 Conda 已安装，随后运行安装脚本（可以在命令行运行或双击）：
    ```bash
    setup.bat
    ```
    脚本会询问 Conda 环境名以及 PyTorch 的 CPU/CUDA 构建。它只负责 `pyproject.toml` 无法表达的环境步骤：创建 Python 3.10 环境、选择 PyTorch wheel 源、安装 FFmpeg 和 Playwright Chromium；其余 Python 依赖统一来自 `pyproject.toml`。

    需要手动安装时，可在已准备好 Python 3.10、PyTorch 和 FFmpeg 的环境中执行：
    ```bash
    python -m pip install -e ".[speech,song-learning]"
    python -m playwright install chromium
    ```

    开发、测试和风格检查工具使用独立依赖组：
    ```bash
    python -m pip install -e ".[dev]"
    ```

    当前安装形态是**从仓库 checkout 进行 editable install**。`config/`、`res/` 和 `data/` 是部署资源或运行数据，不打进 Python wheel；因此安装完成后仍应从 `server` 目录启动。VCPedia 默认模板规则另有一份包内资源随 wheel 分发，用于源码配置不存在时的加载；这不代表 wheel 已包含整个服务所需的部署资源。

    VCPedia 升级注意：
    - 安装项目依赖（包括 `mwparserfromhell`、`zhconv`），不要只复制采集模块；模块级依赖缺失会影响 `src.world` 导入。
    - `crawler.merge_rendered_fragments` 与 `crawler.use_llm` 缺省均开启；原配置显式 `false` 不会被改成开启。关闭前者禁止可选片段 POST，关闭后者禁止总结与补提模型注册/调用；正常页面 GET 不受这两个可选功能开关禁止。
    - 总结使用 `llm_module`；补提使用独立 `extraction_llm_module`，模板选择 `dsv4-flash`（DeepSeek）并在 `available_llms` 定义对应接口。需按配置准备环境变量和提示词资源；不要将 API Key 写进仓库。启用且明确引用无效接口的配置会在初始化报错，未配置模块不借用另一个模型替代。
    - 默认规则同时位于 `config/vcpedia_templates.json` 与 `src/world/get_new_songs/vcpedia_templates.json`，发布默认规则时两份同步。源码文件存在但损坏会明确失败，不隐式回退。
    - 测试与工具入口见 [World 测试说明](tests/unit/world/README.md)；未完成项和历史报告见 [VCPedia 审查记录](tests/support/vcpedia_review/README.md)。

3. 设置环境变量：
    - 根据config中所需要的api_key，配置对应的api密钥为环境变量。
    - 在Windows上，可以通过“系统属性”->“高级”->“环境变量”进行设置，或者在命令行中运行：
      ```bash
      setx SILICONFLOW_API_KEY "your_api_key_here"
      ```

4. 下载资源：
  - 联系开发者获取资源文件和数据文件。
  - 将res文件解压到根目录
  - 将data文件解压到根目录

### 三、启动服务
- 运行redis服务（如果你已经安装了redis，并且将其添加到了环境变量中，可以直接在命令行中运行 `redis-server` 来启动服务）
- 在命令行中启动对应conda环境，运行以下命令启动服务：
  ```bash
  cd Agent-LuoTianyi/server
  python server_main.py
  ```
- 打开sakurafrp的隧道接入公网（如果需要公网访问的话）

### 四、迁移到 `E:\server`

从当前 `server` 目录迁移运行文件和数据时，先预览复制范围：

```powershell
./scripts/deploy_to_e_server.ps1 -PlanOnly
```

停止所有正在运行的 `server_main.py` 进程后执行：

```powershell
./scripts/deploy_to_e_server.ps1
```

脚本复制 `src/`、`config/`、运行资源 `res/`、持久数据 `data/`、管理后台构建产物和安装入口。它不会复制 `__pycache__`、虚拟环境、Node 依赖、测试输出或日志，也不会删除目标目录里的文件。默认要求 `E:\server` 不存在或为空；复制中断后可用 `-Resume` 续传。迁移包含数据库与 WAL 文件，因此复制期间必须保持服务停止。Conda/Python 依赖、FFmpeg、Playwright Chromium 及系统环境变量需在目标运行环境中单独配置。

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
- 感谢硅基流动平台提供的API服务
- 感谢Gemini3，这是我大爹，我的代码基本都是它写的。
- 感谢所有贡献者的努力和支持！
