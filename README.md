# AgentLuo 洛天依对话Agent
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)

## 🎵 项目介绍
AgentLuo期望构建具有真实感的虚拟歌手洛天依的数字生命，并以多种模态与用户交流，提供沉浸式的交流体验和温暖的情感支撑。

AgentLuo具有以下功能：
- **角色扮演**：基于洛天依的官方设定和现有作品，塑造符合其性格和背景的对话风格。并支持用户自定义人设和对话风格。
- **多模态交互**：支持图片和文字输入。集成Live2D模型，实现动态表情和口型同步；利用TTS技术，实现自然流畅的语音输出，并支持少量洛天依歌曲的演唱功能。
- **长上下文管理**：支持长时间对话的上下文记忆，并支持不同用户的人物画像和相处方式记忆。
- **知识库集成**：结合向量数据库和图数据库，实现基于知识的智能回答，使得天依能够记住用户信息和偏好，并且对中V歌曲有较好的理解。
- **可拓展性**：模块化设计，原则上通过替换资源文件可以将该项目用于其他虚拟角色的构建，并可以拓展出更多的与用户、外界交互的能力。

本项目包含三个部分：
- server：服务端，负责处理用户请求，管理对话状态，调用LLM生成回复，调用TTS生成语音，以及管理知识库和记忆。
- client：PC客户端，提供用户界面，展示Live2D模型，播放语音，并与服务端进行通信。
- app：实际上是安卓客户端，提供和PC客户端类似的功能，但界面和交互方式适配移动设备。

服务端承担了绝大多数的数据处理、管理和计算任务。client和app均需要通过服务端请求服务，才能实现与洛天依的互动。

## 📁 项目结构
```text
Agent-LuoTianyi/
├─ server/       # FastAPI服务端，负责对话、记忆、TTS、world任务和管理控制台
├─ client/       # PySide桌面客户端
├─ app/          # Expo / React Native移动端App
├─ docs/         # 开发指引、设计文档、TODO和评审记录
└─ README.md     # 项目首页说明
```

如果你希望参与开发，请优先阅读 [开发指引](docs/开发指引.md)。其中说明了服务端架构、功能应该放在哪个模块、PR要求和贡献规范。

### 🎞️展示视频

<a href="https://www.bilibili.com/video/BV15LZ7BJE3e" target="_blank">
  <img src="https://i0.hdslb.com/bfs/archive/d8f3fde015e9e2efd16cc9b662a4a8ab1d2f1724.jpg" alt="这是独属于你的洛天依" width="720">
</a>

## 🚀快速开始
### PC客户端
#### 普通用户

1. 从 [Releases](https://github.com/SheepLiu712/Agent-LuoTianyi/releases) 下载最新客户端
2. 解压后运行 `Chat with Luotianyi.exe`
3. 向作者或管理员获取邀请码（管理员可在控制台“邀请码管理”中发放），注册后登录

#### 开发者
```bash
git clone https://github.com/SheepLiu712/Agent-LuoTianyi
cd Agent-LuoTianyi/client
setup.bat          # 创建 conda 环境并安装依赖
python main.py     # 启动客户端
```

### 移动端 App
#### 普通用户
在Releases页面下载最新版本的apk文件，安装之。由于现在这个版本没有上架应用商店，所以需要允许安装未知来源的应用。

第一次运行需要向服务器注册，注册时填写账号、密码、邀请码即可。邀请码需要向服务器管理者获取，管理员可在控制台“邀请码管理”中发放。

#### 开发者
```bash
git clone https://github.com/SheepLiu712/Agent-LuoTianyi
cd Agent-LuoTianyi/app
npm install
npx expo start                 # 启动 Expo 开发服务器
```

---

## 🔧服务端部署
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

2. 确保 conda 已安装，随后运行安装脚本：
    ```bash
    setup.bat
    ```
    推荐将服务端环境命名为 `lty`。脚本会询问 conda 环境名称，以及是否安装 GPU 版本的 PyTorch；如果没有 NVIDIA 显卡，请选择否。

3. 下载资源：
   - 联系开发者获取资源文件。至少需要TTS模型、角色资源、知识库等基础资源，缺失时对应功能无法启动或会在控制台配置检查中报错。
   - 将 `res` 文件夹解压到 `server` 根目录。
   - 如需迁移已有用户、记忆或运行数据，将 `data` 文件夹解压到 `server` 根目录。
   - B站 cookie、QQ音乐 credential 等属于可选world功能配置；缺失时会禁用对应功能，但不应影响基础聊天。

4. 如果需要重新构建控制台前端：
   ```bash
   cd admin_ui
   npm install
   npm run build
   cd ..
   ```
   一般情况下仓库会包含已构建的控制台静态文件；只有修改控制台前端或构建产物缺失时才需要执行这一步。

### 三、启动并配置服务
1. 在命令行中进入服务端目录并启动 conda 环境：
   ```bash
   cd Agent-LuoTianyi/server
   conda activate lty
   python server_main.py
   ```
   启动后终端会显示控制台地址，例如：
   ```text
   AgentLuo 控制台: http://127.0.0.1:60030/admin
   ```

2. 打开控制台地址。首次进入需要初始化管理员密码，按页面提示输入 `config/admin_setup_token.txt` 中的 setup token。初始化后可在“邀请码管理”中查看、发放、禁用注册邀请码。

3. 进入“服务配置”页面，先配置环境变量 / Secrets：
   - `JWT_SECRET`：必需，用于服务端鉴权和加密相关逻辑。
   - `AMAP_KEY`：citywalk功能需要的高德地图 API Key。缺失时citywalk不可用。
   - LLM API Key：按实际需要新增，例如 `QWEN_API_KEY`、`SILICONFLOW_API_KEY`、`DEEPSEEK_API_KEY` 或自定义名称。LLM API Key 不再是固定必需项，名称只需要和后续 LLM Interface 中的 `$KEY_NAME` 占位符一致。

4. 配置 `LLM Interfaces` 和 `VLM Interfaces`：
   - 为每个模型接口填写 `api_type`、`model`、`base_url` 和 `api_key`。
   - `api_key` 建议填写为 `$KEY_NAME`，例如 `$QWEN_API_KEY`，实际密钥写在 Secrets 中。

5. 配置 `LLMModule / VLMModule 绑定`：
   - 将 `main_chat`、`topic_extractor`、`memory_writer`、`user_profile`、`image_understanding` 等模块绑定到对应的 Interface。
   - 根据模型能力配置 `thinking`、`json` 和额外 `params`。
   - 点击“修改”后，控制台会进行合规检查；如果 runtime 正在运行，会按需重启业务运行时。

6. 查看“配置检查”。核心配置全部通过后，点击“运行时控制”中的“启动”。B站 cookie、QQ 音乐 credential 等属于可选 world 功能；缺失时对应功能会禁用，但正常聊天仍可运行。

7. 如果需要公网访问，再打开 sakurafrp 等内网穿透工具，将 `60030` 端口暴露出去。

### 四、安全提示
如果将服务端暴露到公网，请务必注意：
- 首次启动后尽快初始化管理员密码，并使用足够强的密码。
- 不要提交或公开 `config` 中的密钥、cookie、credential、setup token、数据库和日志文件。
- 公网部署时建议使用HTTPS反向代理、访问白名单或额外网关认证。
- 定期检查管理控制台的配置检查和异常日志。

运行中如果遇到依赖缺失或资源文件缺失，可以私信作者，或者提交 issue。

## 🤝 参与贡献
欢迎提交功能、修复、测试、文档和资源相关PR。开发前请阅读 [开发指引](docs/开发指引.md)，路线图和详细TODO见 [TODO](docs/TODO.md)。

## 📜 许可证和版权

本项目基于 [MIT 许可证](LICENSE) 开源。

本项目的知识库内容来源于 VCPedia，遵循其版权声明和使用条款。该站全部内容禁止商业使用。文本内容除另有声明外，均在[知识共享 署名-非商业性使用-相同方式共享 3.0中国大陆 (CC BY-NC-SA 3.0 CN) 许可协议](https://creativecommons.org/licenses/by-nc-sa/3.0/cn/)下提供。其余开发者确保在使用和分发时遵守相关规定。
> 根据规定，本项目需要标明是否（对原始作品）作了修改。本项目在使用VCPedia内容时，大部分为直接引用，对歌曲的爬取使用了自动化脚本，并使用LLM进行了结构化，因此绝大部分均为原文引用。

## 🧠 关于AI生成内容的声明
我们认识到VC社区对AI生成内容的关注和担忧。为了透明起见，我们在此声明：
1. 本项目大量使用了LLM，场景包括：
   - 对爬取的文本内容进行结构化处理
   - 生成对话回复
   - 生成语音合成的情感标签
   - 生成Live2D模型的表情标签
   - 压缩对话上下文
   - 生成记忆检索和写入的指令
2. 本项目使用的语音合成技术为GPT-SoVITS，该项目基于AI技术，我们利用公开数据，对公开的语音合成模型进行了微调；此外，生成的语音内容为AI生成。
3. 在美术资源上，本项目使用了火爆鸡王发布的洛天依Live2D模型，该模型为非商业用途免费使用。在其他的美术资源（目前仅包括背景图和Logo）上，我们使用了网络上公开的免费资源，并且保证这些资源不是由AI生成的。
4. 本项目在编写过程中使用了AI辅助编程工具（如GitHub Copilot, Claude Code, Codex），以提高开发效率。但核心逻辑和设计均由开发者完成。

我们力求确保AI生成内容的准确性和合规性，但由于技术限制，可能会存在错误或偏差。如果发现AI生成内容存在明显错误或不当之处，欢迎反馈。

## 🙏 致谢

- 感谢洛天依官方提供的角色设定
- 感谢VCPedia项目组提供的丰富知识库
- 感谢[GPT-SoVITS项目](https://github.com/RVC-Boss/GPT-SoVITS/)提供的开源语音合成技术
- 感谢[火爆鸡王](https://space.bilibili.com/5033594)发布的Live2D模型
- 感谢所有贡献者的努力和支持！

## 更新日志
### v0.3.1
本版本完成了以下更新：
1. 新增每日日记功能，为高活跃用户自动生成每日日记；
2. 管理员控制台新增邀请码管理（增删查/禁用）；
3. 修复了一系列 Bug（Bug#1-#15）：登录密码加密失败重试、自动登录并发保护、历史记录快速滑动闪退、多句回复只展示一句、音频播放互斥、唱歌后缺失最后一句话、唱歌音频不保存、输入框自动增高、概率性连接错误、同一句话重复显示两次并播放两次、打字事件误判、极端情绪标签映射等。

### v0.3.0
本版本完成了以下更新：
1. 增加动态功能，支持用户和天依在聊天之外发布动态、评论动态，并展示动态入口红点；
2. 天依可以在完成城市漫步、学会新歌等 world 事件后发布动态，也可以稍后回复用户动态和评论；
3. 管理员控制台增加动态管理能力，可查看动态、评论、处理状态和失败原因，便于排查运行问题；
4. 修复了一系列bug。

### v0.2.1
本版本完成了以下更新：
1. 支持微调天依的人设；
2. 触摸天依会发出可爱的声音；
3. 可配置服务器地址；
4. 忘记账号密码时可以使用邀请码重置；
5. 同步天依官方动态，可根据动态主动发言；
6. 增加了自动学习新歌曲的功能。
7. 一系列安全和性能更新，修复了一系列bug；
8. 手机版现在支持黑夜模式；

### v0.1.3
实现了以下功能：
1. 改用WS通讯，支持全双工，并极大地提高了连接稳定性；
2. 实现了TTS语音的回放功能；
3. 降低了延时，减少了一次大模型调用，并实现了TTS的流式输出与返回；
4. 移除了redis依赖，将gsv的依赖从原生发布版改为了gsv-tts-lite
5. 修改了记忆机制，使得记忆的写入和读取更严格了；
6. 增加了日常的从vcpedia更新数据的功能；
7. 增加了城市漫步的功能；
8. 增加了在特殊日子主动发言的功能。
9. 修复了已知的bug

## 路线图
- [x] v0.3.x: 动态功能更新（动态 v0.3.0、每日日记 v0.3.1）
- [ ] v0.4.x: 电话功能更新
- [ ] v0.5.x: 重构回复链路，明确工具调用；
- [ ] v0.6.x: 记忆和知识库更新
- [ ] v1.0.x: 多角色支持

详细TODO见 [docs/TODO.md](docs/TODO.md)。
