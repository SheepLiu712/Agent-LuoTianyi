# AgentLuo 洛天依对话Agent
[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)

## 🎵 项目介绍
AgentLuo期望构建具有真实感的虚拟歌手洛天依的数字生命，并以多种模态与用户交流，提供沉浸式的交流体验和温暖的情感支撑。

AgentLuo具有以下功能：
- **角色扮演**：基于洛天依的官方设定和现有作品，塑造符合其性格和背景的对话风格。
- **多模态交互**：支持图片和文字输入。集成Live2D模型，实现动态表情和口型同步；利用TTS技术，实现自然流畅的语音输出，并支持少量洛天依歌曲的演唱功能。
- **无限上下文管理**：支持长时间对话的上下文记忆，并支持不同用户的人物侧写和相处方式记忆。
- **知识库集成**：结合向量数据库和图数据库，实现基于知识的智能回答，使得天依能够记住用户信息和偏好，并且对中V歌曲有较好的理解。
- **可拓展性**：模块化设计，原则上通过替换资源文件可以将该项目用于其他虚拟角色的构建。

本项目包含三个部分：
- server：服务端，负责处理用户请求，管理对话状态，调用LLM生成回复，调用TTS生成语音，以及管理知识库和记忆。
- client：PC客户端，提供用户界面，展示Live2D模型，播放语音，并与服务端进行通信。
- app：实际上是安卓客户端，提供和PC客户端类似的功能，但界面和交互方式适配移动设备。

Server承担了绝大多数的数据处理、管理和计算任务。client和app均需要通过向server请求服务，才能实现与洛天依的互动。

### 🎞️展示视频

[这是独属于你的洛天依](https://www.bilibili.com/video/BV15LZ7BJE3e)

## 🚀快速开始
### PC客户端
#### 普通用户

1. 从 [Releases](https://github.com/SheepLiu712/Agent-LuoTianyi/releases) 下载最新客户端
2. 解压后运行 `Chat with Luotianyi.exe`
3. 向作者获取邀请码，注册后登录

#### 开发者
注册成功之后即可登录。勾选自动登录后，下一次运行将直接进入主界面。

登录界面提供「服务器设置」按钮，可配置自定义服务器地址（支持 HTTP/HTTPS），方便连接到自建服务端或内网穿透地址。

### 开发者方式
1. 克隆仓库：
```bash
git clone https://github.com/SheepLiu712/Agent-LuoTianyi
cd Agent-LuoTianyi/client
setup.bat          # 创建 conda 环境并安装依赖
python main.py     # 启动客户端
```

### 移动端 App
#### 普通用户
在Releases页面下载最新版本的apk文件，安装之。由于现在这个版本没有上架应用商店，所以需要允许安装未知来源的应用。

第一次运行需要向服务器注册，注册时填写账号、密码、邀请码即可。邀请码需要私信服务器管理者（现在即作者）获取。

#### 开发者
```bash
git clone https://github.com/SheepLiu712/Agent-LuoTianyi
cd Agent-LuoTianyi/app
npx expo start                 # 启动 Expo 开发服务器
```
2. 进入项目的client目录并运行setup.bat，按照提示创建并激活conda环境，安装依赖。
3. 运行`main.py`启动客户端。

---

## 🔧服务端架设

> **💡 推荐使用一键脚本**：自动完成仓库拉取 → 环境安装 → 配置向导 → 放行端口 → 启动服务，全程交互式引导。

### 一、环境要求
- 内存：至少 4GB RAM
- 存储：至少 7GB 可用空间
- 网络连接：需要访问外部API服务
- 运算能力：最消耗算力的部分是GPT-SoVITS的语音合成模块，其余均使用外部API，请访问GPT-SoVITS的[官方仓库](https://github.com/RVC-Boss/GPT-SoVITS/)了解配置要求。

### 二、一键安装（推荐）

#### Windows (PowerShell)
以普通用户身份打开 PowerShell，运行：
```powershell
# 在线运行（无需克隆仓库）：
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass -Force
irm https://lty.mywifeluotianyi.com/setup_server.ps1 | iex

3. 设置环境变量：
    - 根据config中所需要的api_key，配置对应的api密钥为环境变量。
    - 在Windows上，可以通过“系统属性”->“高级”->“环境变量”进行设置，或者在命令行中运行：
      ```bash
      setx SILICONFLOW_API_KEY "your_api_key_here"
      setx QWEN_API_KEY "your_api_key_here"
      setx DEEPSEEK_API_KEY "your_key"
      setx AMAP_KEY "your_key"       # 高德地图，可选（城市漫步用）
      ```
    - 所配置的环境变量需要和config.json中的占位符一致，并不局限于硅基流动的api_key，如果你使用了其他需要密钥的服务，建议也按照同样的方式配置环境变量。
# 或者下载后本地运行：
Invoke-WebRequest -Uri “https://lty.mywifeluotianyi.com/setup_server.ps1” -OutFile setup_server.ps1
.\setup_server.ps1
```

脚本将引导你完成：仓库拉取 → 虚拟环境安装 → API密钥配置 → 防火墙放行 → 启动服务。

支持参数：
```powershell
.\setup_server.ps1 -Quick          # 仅安装环境 + 模板配置，跳过向导
.\setup_server.ps1 -ConfigOnly     # 仅运行配置向导
.\setup_server.ps1 -NoEnv          # 跳过环境安装
```

#### Linux (bash)
```bash
# 在线运行（无需克隆仓库）：
bash <(curl -fsSL https://lty.mywifeluotianyi.com/setup_server.sh)

# 或者下载后本地运行：
wget https://lty.mywifeluotianyi.com/setup_server.sh
bash setup_server.sh
```

支持参数：
```bash
bash setup_server.sh --quick        # 仅安装环境 + 模板配置
bash setup_server.sh --config-only  # 仅运行配置向导
bash setup_server.sh --no-env       # 跳过环境安装
```

#### Python (跨平台通用)
```bash
# 下载后运行：
wget https://lty.mywifeluotianyi.com/setup_server.py
python setup_server.py

# 或者在已克隆的仓库中运行：
python server/scripts/setup_server.py --quick
```

#### 一键脚本功能说明
| 功能 | 说明 |
|------|------|
| 仓库拉取 | 自动 `git clone` 或 `git pull` 更新 |
| 环境安装 | 自动创建 conda/venv + pip 安装依赖，可选 GPU 版 PyTorch |
| 智能配置向导 | 交互式填写 API 密钥（SiliconFlow / Qwen / DeepSeek / AMAP），端口、HTTPS、TTS 等；自动检测公网 IP，智能决策域名绑定和内网穿透方案 |
| 防火墙放行 | 自动检测并开放端口（Linux: ufw/firewalld/iptables；Windows: netsh advfirewall） |
| 最低权限 | 仅防火墙和 systemd 服务安装需要提权，服务本身以普通用户运行 |
| SSL 证书 | 可选自动生成自签名 HTTPS 证书 |
| SakuraFrp 隧道 | 自动创建内网穿透隧道并配置 frpc 客户端 |
| 域名绑定 | 有域名时自动配置 Caddy 反向代理 + Let's Encrypt HTTPS |
| Systemd 服务 | Linux 下可选创建开机自启服务 |

### 三、手动安装

#### 1. 克隆项目仓库
```bash
git clone https://github.com/SheepLiu712/Agent-LuoTianyi.git
cd Agent-LuoTianyi/server
```

#### 2. 安装虚拟环境与依赖
确保conda已安装，随后运行安装脚本：
```bash
setup.bat
```
> 注意：该脚本运行过程需要进行两次输入。第一次输入是确定conda环境的名称，第二次输入是确认是否安装GPU版本的pytorch（如果你的电脑没有NVIDIA显卡，请选择否）

#### 3. 设置环境变量
根据 `config/config.json` 中所需要的 API Key，配置对应的 API 密钥为环境变量：
```bash
setx SILICONFLOW_API_KEY “your_api_key_here”
setx QWEN_API_KEY “your_api_key_here”
setx DEEPSEEK_API_KEY “your_api_key_here”
```
或者在 Linux 上：
```bash
export SILICONFLOW_API_KEY=”your_api_key_here”
export QWEN_API_KEY=”your_api_key_here”
export DEEPSEEK_API_KEY=”your_api_key_here”
```
所配置的环境变量需要和 config.json 中的占位符一致。

#### 4. 下载资源
- 联系开发者获取资源文件和数据文件（只有需要迁移数据库时需要）。
- 将 `res` 文件解压到根目录
- 将 `data` 文件解压到根目录（如需要迁移数据库）

### 四、启动服务
- 进入 server 目录，激活对应环境，运行：
  ```bash
  python server_main.py
  ```
- 打开 SakuraFrp 的隧道接入公网（如果需要公网访问的话）
- 在运行中如果遇到任何依赖缺失的问题，可以私信作者，或者提 issue

## 📜 许可证和版权

本项目基于 [MIT 许可证](LICENSE) 开源。

本项目的知识库内容来源于 VCPedia，遵循其版权声明和使用条款。该站全部内容禁止商业使用。文本内容除另有声明外，均在[知识共享 署名-非商业性使用-相同方式共享 3.0中国大陆 (CC BY-NC-SA 3.0 CN) 许可协议](https://creativecommons.org/licenses/by-nc-sa/3.0/cn/)下提供。其余开发者确保在使用和分发时遵守相关规定。
> 根据规定，本项目需要标明是否（对原始作品）作了修改。本项目在使用VCPedia内容时，大部分为直接引用，对歌曲的爬取使用了自动化脚本，并使用LLM进行了结构化，因此绝大部分均为原文引用。在此基础上

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
- 感谢Copilot，这是我大爹，我的代码基本都是它写的。
- 感谢所有贡献者的努力和支持！

## 开发
### 🚀 技术栈
注意，服务端的配置难度要远高于客户端。下面简要介绍服务端的技术栈：
- **编程语言**：Python 3.10 与Typescripts
- **Web框架**：FastAPI
- **client UI框架**：PySide6
- **app 框架**：Expo + React
- **数据库**：sqlite（使用 SQLAlchemy 进行 ORM 操作）
- **向量数据库**：ChromaDB
- **TTS合成**：GPT-SoVITS(轻量化：gsv-tts-lite)
- **公网访问**：使用 sakurafrp 实现内网穿透，支持公网访问

### TODO List
等待有缘人帮我做完（其实做完了，正在测）
- [ ] 自动学歌功能；
- [ ] 同步官方日程功能；
- [ ] 更口语化的对话；
- [ ] Live2d互动和反应功能；
- [ ] 纪念日记忆和反应功能；
- [ ] 用户与洛天依关系保存和演变功能；
- [ ] 更好的记忆检索和保存，提升命中率；
- [ ] 上下文注意力机制，规划关系、心情、日程、记忆、前文对回复的影响。

### 项目架构
#### 客户端架构
客户端采用以下五层架构：
1. WebSocket层：建立并维护web socket连接，处理web socket发送和接收任务。
2. NetworkClient层：处理具体的网络服务，包括登录、注册、拉取历史等。对话消息通过调用WebSocket暴露的接口实现。
3. MessageProcessor：实际处理用户操作和服务器发包的部分。其中包括MultiMediaProcessor，用于处理音频播放和口型同步。
4. Binder：连接前端UI和MessageProcessor的中间层。
5. GUI：实际绘制前端，将用户输入发回中层，并显示服务器发来的数据。

#### 服务端架构
服务器为每一个登录的用户创建一个ChatStream，每个ChatStream会绑定一个WebSocket连接。ChatStream会在用户登陆时创建，在WebSocket长时间未绑定WebSocket时被回收。

按照消息流动的过程，ChatStream会经过以下生产者-消费者结构：
- Ingress：预处理。WebSocket收到消息后，先送个预处理，完成消息的落库、术语（歌词和歌名）提取、以及图片信息的识别。然后将处理之后的消息送往下一层。
- TopicExtractor：提取话题。根据积压的消息，当用户不再输入时，用LLM总结用户这一轮输入所对应的话题，同时，生成以下3类信息，得到完整的Topic输入下一层：
  - 事实约束(fact constraint)：包括歌曲的信息，天依能唱的歌。
  - 记忆检索(memory attempt)：用于向量记忆检索的关键词（key）。
  - 唱歌计划(sing plan)：如果用户要求天依唱歌，则进行唱歌尝试。
- TopicReplier：回复话题。根据所需要的信息，组装上下文，由LLM生成风格化的回复。随后异步地进行回复的落库、记忆的更新以及上下文压缩。生成的回复会在生成完成后即可进入下一层：
- GlobalSpeakingManager：生成带音频的回复。这一部分不在ChatStream内，而是所有用户共用的。所有回复任务依次排队进行TTS合成或者唱歌音频获取。模块将流式地生成音频，并将最后的回复包发回对应ChatStream的发送队列。
- send_reply：发送回复包。将队列中的回复包利用WebSocket发回客户端。

此外，DailyScheduler模块会在每天凌晨进行尝试
- 每3天从VCPedia拉去洛天依的当年的歌曲，如果有新的就加入知识库；
- 每天有20%的概率进行一次城市漫步，并生成相应的记忆。

### 如何为项目出一份力？
目前项目非常缺人！欢迎所有朋友为项目出一份力，只要你：
- 熟悉Python/Typescript编程，或者有其它一技之长；
- 认可本项目理念；
- 希望为项目做出贡献/锻炼自己的能力。

你就可以尝试为项目贡献代码！

你可以用常用的方式贡献代码：
1. 将项目fork到你自己的目录；
2. 创建feat分支或bugfix分支；
3. 实现功能；
4. 提交Pull request，等待作者和协作者审核
5. 完成贡献！

由于作者本身的代码规范也是一坨，所以我们对代码的要求比较简单：
- 在贡献代码时，详细说明你的代码是要实现什么功能；
- 在贡献代码时，详细说明你使用了什么方案实现这一功能；
- 实现代码时，遵循项目架构；
- 实现代码时，按照PEP8标准进行编写（大差不差就行，对于函数，注意命名规范，以及参数和返回值的类型提示）；你可以使用black进行格式化；
- 实现代码时，在必要的地方写注释。
- 为你的功能写单元测试，即在整个项目之外，独立验证你的功能模块是可以用的。

联系作者：QQ 229817494
