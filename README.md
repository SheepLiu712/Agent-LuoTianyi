# Agent-LuoTianyi：虚拟歌手洛天依对话Agent

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)


## 🎵 项目介绍

本项目旨在设计并实现一个具备角色扮演能力的虚拟歌手洛天依（Luo Tianyi）智能对话Agent。该Agent整合了Live2D模型功能和GPT-SoVITS提供的语音合成（TTS）功能，并实现了基于嵌入（Embedding）的向量记忆检索和图结构知识图谱。这些技术旨在为用户提供沉浸式的洛天依互动体验。

### ☀️功能特色
- **角色扮演**：基于洛天依的官方设定，塑造符合其性格和背景的对话风格。
- **多模态交互**：集成Live2D模型，实现动态表情和口型同步。
- **语音合成**：利用GPT-SoVITS技术，实现自然流畅的语音输出。
- **无限上下文管理**：支持长时间对话的上下文记忆，提升交互连贯性。
- **知识库集成**：结合向量数据库和图数据库，实现基于知识的智能回答，使得天依能够记住用户信息和偏好，并且对圈子内的知识有较好的理解。
- **可拓展性**：模块化设计，原则上通过替换资源文件可以将该项目用于其他虚拟角色的构建。

### 🎞️展示视频

Comming soon...

## 🚀🚀更快速的开始

### 一、环境要求
- 内存：至少 4GB RAM
- 存储：至少 7GB 可用空间
- 网络连接：需要访问外部API服务
- 运算能力：最消耗算力的部分是GPT-SoVITS的语音合成模块，其余均使用外部API，请访问GPT-SoVITS的[官方仓库](https://github.com/RVC-Boss/GPT-SoVITS/)了解配置要求。

### 二、安装流程
- 下载可执行的便携版压缩包：[ChatWithLuotianyi_Portable](https://cloud.tsinghua.edu.cn/d/493593830d864f07ab4a/)
- 解压到任意目录，双击运行 `点我启动.bat` 即可启动洛天依对话Agent。


## 🚀 快速开始

### 一、环境要求
- Python 3.10（目前版本仅在该版本上测试过，因此建议使用Python 3.10）
- 硅基流动平台API密钥
- 操作系统：Windows 10/11
- conda（目前的安装过程依赖于conda而不是pip，所有这个暂时是必要的）
- 内存：至少 4GB RAM
- 存储：至少 3GB 可用空间
- 网络连接：需要访问外部API服务
- 运算能力：最消耗算力的部分是GPT-SoVITS的语音合成模块，其余均使用外部API，请访问GPT-SoVITS的[官方仓库](https://github.com/RVC-Boss/GPT-SoVITS/)了解配置要求。
   > 但GPT-SoVITS并不是当前响应效率的瓶颈，通常情况下普通的CPU也能胜任。

### 二、安装流程

1. 克隆项目仓库：
   ```bash
   git clone https://github.com/SheepLiu712/Agent-LuoTianyi.git
   cd Agent-LuoTianyi
   ```
2. 确保conda已安装，随后运行安装脚本（在命令行中运行，或者双击运行快速启动脚本）
    ```bash
    setup.bat
    ```
    注意，该脚本运行过程需要进行两次输入。第一次输入是确定conda环境的名称，第二次输入是确认是否安装GPU版本的pytorch（如果你的电脑没有NVIDIA显卡，请选择否）
3. 设置环境变量：
    - 将你的硅基流动平台API密钥设置为环境变量 `SILICONFLOW_API_KEY`。
    - 在Windows上，可以通过“系统属性”->“高级”->“环境变量”进行设置，或者在命令行中运行：
      ```bash
      setx SILICONFLOW_API_KEY "your_api_key_here"
      ```
4. 下载资源：
  从以下链接下载项目所需的资源文件，并将其解压到项目的 `res/` 目录下。
   - [清华云盘](https://cloud.tsinghua.edu.cn/f/2a543a238e87479ab1f4/?dl=1) 
  
  最终目录结构应如下所示：
   ```
   Agent-LuoTianyi/
   ├── res/
   │   ├── agent/
   │   ├── gui/
   │   └── knowledge/
   └── ...
   ```

### 三、基础使用

参考项目根目录下的`start.py`脚本，在新创建的conda环境中，运行该脚本即可启动洛天依对话Agent。

```bash
conda activate lty
python start.py
```


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

## 🔧 配置说明

### 主配置文件 (`config/config.json`)

我们按照其第一级键将配置文件划分为多个模块：
- `prompt_manager`：对话提示词管理器的配，它指向了提示词文件所在目录。
- `main_chat`：主对话模块的配置，主要配置了它所使用的大语言模型API接口
- `conversation_manager`：对话管理器的配置，主要配置了上下文窗口大小等参数，还包括了上下文的保存路径。
- `tts`：语音合成模块的配置，主要配置了TTS引擎的配置，包括模型目录、输出目录、参考音频等。`tone_ref_audio_projection`是不同语气（由main_chat的llm生成）对应的参考音频文件。
- `live2d`: Live2D模型的配置，主要配置了模型文件路径等。`expression_projection`是不同情绪（由main_chat的llm生成）对应的Live2D表情文件。
- `gui`： 图形界面模块的配置，主要配置了窗口背景、图标路径等，你可以根据需要进行调整。
- `memory_manager`: 记忆管理器的配置，配置了图数据库和向量数据库的路径等，也配置了记忆写入和搜索的llm的相关参数。
- `crawler`：用来爬取VCPedia知识的配置，目前版本并未实装。

## 🛠️ 开发指南

### 项目结构概览

```text
Agent-LuoTianyi/
├── config/             # 配置文件目录 (config.json, tts_infer.yaml)
├── data/               # 数据存储
│   ├── crawled_data/   # 爬虫数据
│   ├── memory/         # 记忆存储 (向量库, 对话历史)
│   └── tts_output/     # TTS生成的临时音频
├── docs/               # 项目文档
├── logs/               # 运行日志
├── res/                # 静态资源 (Live2D模型, 提示词, 知识图谱)
├── scripts/            # 实用脚本 (数据处理, 知识库构建)
├── src/                # 源代码核心
│   ├── agent/          # Agent核心逻辑 (对话管理, 角色扮演)
│   ├── gui/            # 图形用户界面 (PySide6)
│   ├── live2d/         # Live2D模型控制接口
│   ├── llm/            # 大语言模型API接口封装
│   ├── memory/         # 记忆系统 (RAG, 知识图谱)
│   ├── tts/            # 语音合成模块 (GPT-SoVITS)
│   └── utils/          # 通用工具函数
└── tests/              # 单元测试
```

### 核心模块说明

1.  **Agent (`src/agent`)**:
    *   `luotianyi_agent.py`: Agent的主入口，协调各个子模块。
    *   `conversation_manager.py`: 管理对话历史和上下文窗口。
    *   `main_chat.py`: 处理核心对话逻辑，调用LLM生成回复。

2.  **GUI (`src/gui`)**:
    *   基于 PySide6 构建。
    *   `main_ui.py`: 主窗口布局和事件循环。
    *   `binder.py`: 连接后端逻辑与前端界面，处理线程通信。

3.  **Memory (`src/memory`)**:
    *   实现了混合记忆系统：基于向量数据库 (ChromaDB) 的语义检索和基于图数据库 (NetworkX) 的知识检索。
    *   实现了在线抓取知识的功能：利用beautifulsoup4从VCPedia抓取洛天依相关知识并缓存到本地。
    *   `memory_manager.py`: 记忆系统的统一接口。

4.  **TTS (`src/tts`)**:
    *   集成 GPT-SoVITS 进行语音合成。
    *   支持根据情感标签选择不同的参考音频。

### 开发流程建议

1.  **环境配置**: 确保安装了 `setup/requirements.txt` 和 `setup/gsv_requirements.txt` 中的依赖。
2.  **功能开发**:
    *   在 `src/` 下对应模块进行修改。
    *   如果涉及配置变更，请同步更新 `config/config.json.template`。
3.  **测试**:
    *   使用 `tests/` 目录下的单元测试验证功能。
    *   运行 `python start.py` 进行集成测试。
4.  **日志调试**:
    *   程序运行日志会输出到 `logs/` 目录，可用于排查问题。   


## 🤝 贡献指南

我们欢迎社区贡献！请遵循以下步骤：

1. Fork 项目
2. 创建特性分支 (`git checkout -b feature/amazing-feature`)
3. 提交更改 (`git commit -m 'Add amazing feature'`)
4. 推送到分支 (`git push origin feature/amazing-feature`)
5. 创建Pull Request

### 代码规范
- 使用 Black 进行代码格式化
- 遵循 PEP 8 编码规范
- 写注释和文档以提高代码可读性

## 📞 联系方式

- 项目地址：[GitHub Repository](https://github.com/SheepLiu712/Agent-LuoTianyi)
- 问题反馈：[Issues](https://github.com/SheepLiu712/Agent-LuoTianyi/issues)
- 讨论交流：[Discussions](https://github.com/SheepLiu712/Agent-LuoTianyi/discussions)
- 开发者QQ：229817494

---

🎵 *"大家好，我是洛天依！让我们一起开始愉快的对话吧～"* 🎵
