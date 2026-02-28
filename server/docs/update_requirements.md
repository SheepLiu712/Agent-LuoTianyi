# 迭代需求
Agent-LuoTianyi旨在设计并实现一个具备角色扮演能力的虚拟歌手洛天依（Luo Tianyi）智能对话Agent。该Agent整合了Live2D模型功能和GPT-SoVITS提供的语音合成（TTS）功能，并实现了基于嵌入（Embedding）的向量记忆检索和图结构知识图谱。这些技术旨在为用户提供沉浸式的洛天依互动体验。

在过去，Agent-LuoTianyi是一个本地项目，用户通过下载可执行的便携版压缩包来使用该项目。然而，随着项目的发展和用户需求的变化，我们决定将项目的核心功能移植到云端，以提升用户体验和系统的可扩展性。这意味着服务器需要并发处理多个用户的请求，同时确保响应速度和系统稳定性。我们要求：
- 用户数据的独立性：每个用户的数据和对话历史必须独立存储，确保隐私和数据安全。
- 用户数据管理的规范化：通过数据库系统管理用户数据，支持高效的查询和存储操作。
- 高并发处理能力：服务器需要能够处理大量（认为日活约为30人，请求频率约为每人每分钟1次）的并发请求，确保每个用户都能获得及时的响应。

本地版本使用的技术并不能满足上述要求，具体表现在：
1. 数据存储并未考虑多用户，所有数据统一存储到data/memory文件夹中；
2. 推理并未考虑多用户场景，内存中保存的上下文数据不区分用户，无法支持多用户同时对话；
3. 数据管理非常粗糙，使用json文件存储用户数据，查询和存储效率低下。
4. 系统架构为单线程的本地应用，在用户输入后阻塞地处理请求，无法支持高并发。

因此，我们计划进行以下更新：
1. 引入数据库系统来管理用户和洛天依的对话记忆，确保数据的独立性和高效存取。
2. 重构系统架构，采用客户端-服务器模式，服务器端处理用户请求，支持多用户并发对话。
3. 优化llm请求和tts请求的处理流程，避免阻塞等待，提高响应速度。

## 当前项目技术简介
具体而言，对于数据方面，我们存储的数据包括：
- 用户和洛天依对话的长期记忆，当前以chroma向量数据库的形式存储，应该随用户不同
- 用户和洛天依对话的所有历史记录，当前以json文件的形式存储，应该随用户不同
- 给llm的上下文窗口缓存，当前以json文件的形式存储，应该随用户不同
- 用户的基本信息，如用户名、注册时间等，应该随用户不同
- 领域的相关专业知识，可以为所有用户共享，目前以自定义的知识图谱形式存储（形式为json）

llm方面，目前使用的是硅基流动提供的API接口，使用Openai库进行调用，可能存在等待回复造成的阻塞问题。

tts方面，目前使用的是本地部署的GPT-SoVITS模型进行推理，通过单开一个进程来运行TTS推理服务，并通过HTTP请求与之通信，可能存在等待回复造成的阻塞问题。

整体架构上，原本的程序响应基于以下流程：
- 用户在GUI界面输入文本
- 触发回调函数（luotianyi_agent.py的handle_user_input）
- 回调函数中组装上下文，先调用memory_manager检索记忆，组装记忆后再调用main_chat生成回复。调用两次llm API。
- 获取回复后，将回复文本逐句传给tts模块进行语音合成，子线程调用tts服务API。
- 回调函数线程等待TTS服务完成，每完成一句输出后播放音频，并将语句显示在界面上，同时更新live2d模型，直到所有句子合成完毕。
- 回调函数线程同时会启用另一子线程更新记忆和压缩上下文。
- 结束回调函数。

而现在我们需要更新只，使之能够适应云端多用户的场景。

## 更新要求
请你根据上述需求，设计一个详细的更新方案。更新在文档下方。你的更新实现两大部分功能：
- 注册和登录功能。
- 响应对话请求功能。

## 请将你的方案写在下面

根据您提供的项目结构和 update_requirements.md，我为您制定了一份详细的更新计划。

由于项目规模较小（日活 ~30 人）且并发要求低，但开发时间紧张，本计划的核心原则是 "最小化重构，最大化复用"。我们将使用轻量级的技术栈来实现云端化和多用户隔离。

### 一、 总体架构与技术栈
|模块	|旧方案 (本地版)	|新方案 (云端版)	|理由|
|-|-|-|-|
|API 框架	|无 (本地 Python 脚本)	|FastAPI	|现代、开发快、原生支持异步 (Async)，非常适合 LLM/TTS 处理。|
数据库	|JSON 文件分散存储	|SQLite + SQLAlchemy	|无需额外部署 DB 服务，单文件易于备份/迁移，性能足以支撑 30 人日活。|
向量数据库|	Chroma (默认设置)	|Chroma (按 Collection 隔离)	|继续使用 Chroma，但通过命名规则为每个用户创建独立的 Collection。|
鉴权	|无	|OAuth2 / JWT	|标准的 Stateless 鉴权，实现简单。|
异步处理|	threading + 阻塞等待|	Python asyncio|	解决高并发下的 IO 阻塞问题 (LLM/TTS 请求)。|
### 二、 详细更新步骤与顺序
请按照以下顺序执行更新，以确保系统平稳过渡。

#### 阶段 1：数据层改造 (Model Layer)
目标：将原本散落在 JSON 文件中的数据迁移至数据库，并建立用户隔离。

A.设计 SQLite 数据库模型 (database.py)

- 扩展现有的 init_db。
- User 表：id, username, password_hash, created_at。
- UserProfile 表：user_id (FK), nickname, description (原 user_profile.json 内容)，avatar_url 等。
- Conversation 表：id, user_id (FK), role (user/agent), content, timestamp。替代原本的 history_0.jsonl。

- 建议工具：使用 SQLAlchemy 或 SQLModel 定义 ORM 模型，方便操作。

B. 重构用户配置管理 (user_profile.py)

- 废弃读写 json 文件的逻辑。
- 修改 UserProfile 类，使其在初始化时接收 user_id，并从 SQLite 读取/保存数据。

C.重构记忆管理 (memory_manager.py)
- 核心变更：MemoryManager 不应再是应用启动时创建的单例。
- 改为 工厂模式 或 请求作用域 模式。
- __init__ 方法需要接收 user_id。
- 在初始化 VectorStore 时，传入 user_id，使 Chroma 客户端指向 f"collection_{user_id}"，从而实现物理隔离。

#### 阶段 2：核心业务逻辑解耦 (Service Layer)
目标：剥离 GUI 代码，将业务逻辑转化为无状态或短状态的服务。

1. 剥离 GUI 依赖
   - 检查 luotianyi_agent.py，移除 MainWindow, AgentBinder 等 GUI 相关代码。
   -   这些模块在服务器端是不需要的。

2. 创建 ChatService (src/service/chat_service.py)
- 提取原 LuoTianyiAgent.handle_user_input 的逻辑。
- 新流程：
  - 接收 user_id 和 text。
  - 从 DB 加载该用户的 ConversationManager (历史记录)。
  - 初始化该用户的 MemoryManager。
  - (异步) 调用 Memory 检索。
  - (异步) 调用 LLM 生成 (建议使用 AsyncClient 替代同步 HTTP 调用)。
  - (异步) 调用 TTS 接口。
3. 改造 TTS 调用 (tts_module.py)
- 原逻辑：add_task -> while True: sleep (轮询等待文件生成)。
- 新逻辑：改为 async 方法。如果 TTS 服务在本地，使用 asyncio.to_thread 包装耗时操作；如果是 HTTP 调用，使用 aiohttp 或 httpx 发起异步请求，避免阻塞主线程。

#### 阶段 3：API 接口实现 (Controller Layer)
目标：提供外部访问能力的 RESTful API。

A.完善 server_main.py

认证接口：
- POST /auth/register: 注册账号。
- POST /auth/token: 登录，返回 JWT Access Token。

业务接口：
- GET /user/profile: 获取用户设定。
- POST /user/profile: 更新用户设定。
- POST /chat: 对话接口。

B.流式响应设计 (Streaming Response)
- 为了更快的首字延迟（TTFT），建议 /chat 接口返回 StreamingResponse (FastAPI 功能)。
- 服务器端逻辑：一旦 LLM 生成一句话 -> 立即送入 TTS -> TTS 音频流/文件 URL 立即返回给前端。前端可以边收边播。


#### 阶段 4：后台任务与清理
A. 记忆后台处理

原逻辑中，记忆写入和压缩是在子线程做的。
在 FastAPI 中，使用 BackgroundTasks 对象。在 /chat 接口返回响应后，后台自动执行 memory_manager.post_process_interaction，将当轮对话存入向量库。

B. 清理旧代码

移除 data/memory/*.json 的读写权限和逻辑。
移除 tkinter 或 pyqt 相关的 GUI 库依赖。
### 三、 更新后的请求处理流程图
graph TD
    User[Web/Client] -->|POST /chat (JWT Token)| Server[FastAPI Server]
    Server -->|Parse Token| Identity[Get User ID]
    
    Identity -->|Restore Context| SQL[SQLite DB]
    Identity -->|Init Memory| Chroma[ChromaDB (Collection_UserID)]
    
    Server -->|Async Call| LLM[LLM Service]
    LLM -->|Stream Text| Logic[Chat Service]
    
    Logic -->|Async Call| TTS[GPT-SoVITS API]
    TTS -->|Audio Data/URL| Response[Streaming Response]
    
    Response -->|Return| User
    
    Response -.->|Background Task| SaveMem[Save to Memory & DB]
### 四、 关键建议
不要过度设计：对于 30 人日活，不要引入 Redis 或复杂的 Message Queue。FastAPI 的内存队列和 SQLite 足够了。

依赖注入：在 FastAPI 中使用 Depends 来获取 current_user 和 db_session，会让代码非常整洁。

TTS 并发瓶颈：TTS 推理是最耗时的部分。如果多用户同时请求，本地单显卡可能会排队。这是硬件瓶颈，软件上只需确保 HTTP 请求不超时，且告知用户正在处理即可。