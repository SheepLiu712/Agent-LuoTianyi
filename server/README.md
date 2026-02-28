# AgentLuo-Client 洛天依对话Agent的客户端
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
   git clone https://github.com/SheepLiu712/Agent-LuoTianyi-server.git
   cd Agent-LuoTianyi-server
   ```

2. 确保conda已安装，随后运行安装脚本（在命令行中运行，或者双击运行快速启动脚本）
    ```bash
    setup.bat
    ```
    注意，该脚本运行过程需要进行两次输入。第一次输入是确定conda环境的名称，第二次输入是确认是否安装GPU版本的pytorch（如果你的电脑没有NVIDIA显卡，请选择否）

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
  python server_main.py
  ```
- 打开sakurafrp的隧道接入公网（如果需要公网访问的话）

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
- 感谢Gemini3，这是我大爹，我的代码基本都是它写的。
- 感谢所有贡献者的努力和支持！