# AgentLuo — 洛天依对话Agent

[![MIT License](https://img.shields.io/badge/License-MIT-green.svg)](https://choosealicense.com/licenses/mit/)
[![Python 3.10](https://img.shields.io/badge/python-3.10-blue.svg)](https://www.python.org/downloads/)

## 项目介绍

AgentLuo 旨在设计并实现一个具备角色扮演能力的虚拟歌手 **洛天依（Luo Tianyi）** 智能对话 Agent。

该系统整合了 Live2D 模型交互、GPT-SoVITS 语音合成、基于 Embedding 的向量记忆检索、以及洛天依歌曲知识库，为用户提供沉浸式的互动体验。

### 展示视频

[这是独属于你的洛天依](https://www.bilibili.com/video/BV15LZ7BJE3e)

---

## 项目结构

本项目包含三个子项目：

| 子项目 | 技术栈 | 说明 |
|--------|--------|------|
| **server/** | Python 3.10, FastAPI | 服务端：WebSocket + REST，对话管道、记忆系统、TTS、插件 |
| **client/** | PySide6 | PC 客户端：Live2D 渲染、聊天界面、音频播放 |
| **app/** | React Native / Expo | 移动端客户端（Android） |

---

## 功能特色

- **角色扮演** — 基于洛天依官方设定和作品，塑造符合其性格的对话风格
- **Live2D 交互** — 点击模型不同部位（头、辫子、耳机等）触发 Tap 动画 + LLM 回应
- **语音合成** — GPT-SoVITS 情感语音，支持喜悦、温柔、悲伤、愤怒等多种语气
- **歌曲演唱** — 支持曲库中已配置歌曲的演唱，自动切片和分段播放
- **自动学歌** — 记录用户想听但不会唱的歌，凌晨自动检测 staging 目录并处理
- **图片识别** — 集成视觉语言模型（VLM）识别用户上传的图片
- **无限上下文** — 长对话自动压缩和摘要，保持交互连贯性
- **记忆系统** — 向量数据库存储用户记忆和偏好，支持语义检索
- **日程系统** — 自动爬取 B 站官方动态，解析演唱会/联动等活动，注入对话上下文
- **城市漫步** — Agent 每日独立探索中国城市（高德地图 API + LLM 决策），生成游记并存入记忆
- **公网访问** — 通过内网穿透（SakuraFrp）支持公网 WebSocket 连接

---

## 服务端架构

```
server_main.py  — FastAPI 入口
```

### 分层架构

| 层 | 路径 | 职责 |
|----|------|------|
| **接口层** | `server/src/interface/` | WebSocket 消息帧（鉴权、心跳）、REST API、ServiceHub 依赖注入容器 |
| **对话管道** | `server/src/pipeline/` | 每用户异步管道：消息预处理 → 话题规划 → 回复生成 → TTS 说话 |
| **Agent 层** | `server/src/agent/` | 核心 Agent：LLM 调用、记忆读写、话题提取、主动发言（ActivityMaker） |
| **记忆系统** | `server/src/memory/` | 多源记忆检索（向量 + 图）+ 记忆写入和摘要 |
| **数据库** | `server/src/database/` | SQLite（SQLAlchemy）、ChromaDB（向量）、Redis 缓冲区 |
| **插件** | `server/src/plugins/` | 城市漫步、曲库管理、日程系统、自动学歌 |
| **TTS** | `server/src/tts/` | GPT-SoVITS 语音合成（流式 + 非流式） |
| **视觉** | `server/src/vision/` | VLM 图片描述 |

### 对话管道流程

```
用户消息 → WebSocket → ChatStream (per user)
  → ingress (图片保存/视觉/实体提取)
  → unread_store (消息缓冲)
  → topic_planner (LLM话题提取)
  → topic_replier (记忆/歌曲检索 + LLM回复 + TTS生成)
  → global_speaking_worker (串行TTS队列)
  → WebSocket → 客户端
```

### 关键设计模式

- **每用户异步管道**：每个用户独立 ChatStream，task 在首次消息创建、断开时取消
- **ServiceHub 依赖注入**：所有单例服务在启动时注册到 ServiceHub，贯穿管道传递
- **Speaking Worker 串行化**：全局单队列串行化 TTS 任务，避免 GPU OOM
- **Agent 作为管道后端**：管道只负责流程控制，LLM/记忆/TTS 全部委托给 LuoTianyiAgent

### 启动流程

```
startup_event:
  init_databases → TTS → Agent → ServiceHub
  → ScheduleManager (B站日程)
  → ActivityMaker (主动发言)
  → GlobalSpeakingWorker (TTS队列)
  → DailyScheduler (4AM定时任务)

WebSocket /chat_ws:
  accept → system_ready → auth → get_or_register_chat_stream → message_loop
```

---

## 客户端架构

```
main.py  — PySide6 入口
```

### 五层结构

| 层 | 路径 | 职责 |
|----|------|------|
| **UI 层** | `src/gui/` | MainWindow、聊天气泡、登录/注册、设置界面、Live2D 渲染 |
| **Binder 层** | `src/gui/binder.py` | UI 与逻辑层之间的信号/槽桥梁 |
| **消息处理层** | `src/message_process/` | 发送/接收队列、多媒体流处理（音频、表情） |
| **通信管理层** | `src/network/` | REST API 调用、WS 消息收发、历史消息 |
| **WebSocket 层** | `src/network/ws_transport.py` | 连接维护、心跳、断线重连、SSL 兼容 |

### 关键组件

- **Live2DWidget** — Cubism SDK 渲染，支持面部追踪、Tap 动画、表情切换
- **MultiMediaStream** — 服务端音频片段 FIFO 播放，支持本地 TTS 打断、音量控制
- **MessageProcessor** — 双线程（监听 + 发送），事件队列驱动
- **WebSocketTransport** — 自动重连、10s 心跳、消息 ACK 确认

---

## 快速开始

### 客户端（普通用户）

1. 从 [Releases](https://github.com/SheepLiu712/Agent-LuoTianyi/releases) 下载最新客户端
2. 解压后运行 `Chat with Luotianyi.exe`
3. 向作者获取邀请码，注册后登录

### 客户端（开发者）

```bash
git clone https://github.com/SheepLiu712/Agent-LuoTianyi
cd Agent-LuoTianyi/client
setup.bat          # 创建 conda 环境并安装依赖
python main.py     # 启动客户端
```

### 服务端架设

#### 环境要求

- 内存 ≥ 4GB（推荐 8GB+）
- 存储 ≥ 7GB 可用空间（含模型文件和数据）
- NVIDIA GPU 推荐（GPT-SoVITS 推理）
- 需要访问外部 API（SiliconFlow、DashScope、DeepSeek 等）

#### 安装流程

```bash
git clone https://github.com/SheepLiu712/Agent-LuoTianyi
cd Agent-LuoTianyi/server
setup.bat          # 创建 conda 环境并安装依赖
```

配置环境变量（在 `config/config.json` 中引用）：

```bash
setx SILICONFLOW_API_KEY "your_key"
setx QWEN_API_KEY "your_key"
setx DEEPSEEK_API_KEY "your_key"
setx AMAP_KEY "your_key"       # 高德地图，可选（城市漫步用）
```

联系作者获取资源文件和模型文件，解压到项目根目录。

#### 启动服务

```bash
python server_main.py          # http://127.0.0.1:60030
python scripts/generate_cert.py  # （可选）生成 SSL 证书
```

### 移动端 App

```bash
cd app
npx expo start                 # 启动 Expo 开发服务器
```

---

## 技术栈

### 服务端

| 技术 | 用途 |
|------|------|
| Python 3.10 | 运行时 |
| FastAPI | Web 框架 + WebSocket |
| SQLite / SQLAlchemy | 关系数据库 |
| ChromaDB | 向量数据库 |
| Redis / MemoryStorage | 缓存 / 上下文存储 |
| GPT-SoVITS | 语音合成 |
| Qwen-VL | 图片识别 |
| SiliconFlow / DashScope / DeepSeek | LLM API |

### 客户端

| 技术 | 用途 |
|------|------|
| PySide6 | 桌面 UI 框架 |
| Cubism SDK (Live2D) | 模型渲染 |
| VLC / pydub | 音频播放 |
| RSA-OAEP | 密码加密传输 |

---

## 环境变量

| 变量名 | 用途 | 必需 |
|--------|------|------|
| `SILICONFLOW_API_KEY` | Embedding、备用 LLM | 是 |
| `QWEN_API_KEY` | 主聊天 LLM、视觉 | 是 |
| `DEEPSEEK_API_KEY` | 记忆搜索、对话摘要 | 是 |
| `AMAP_KEY` | 高德地图（城市漫步） | 否 |

---

## 开发命令

```bash
# 服务端
cd server
python server_main.py                              # 启动服务
python -m pytest tests/                            # 运行全部测试
python -m pytest tests/test_xxx.py                 # 单文件测试
python -m pytest tests/ -k "test_name"             # 指定测试
python scripts/generate_cert.py                    # 生成 SSL 证书

# 客户端
cd client
python main.py                                     # 启动客户端

# 移动端
cd app
npx expo start                                     # 启动 Expo
```

---

## 许可证和版权

本项目基于 [MIT 许可证](LICENSE) 开源。

知识库内容来源于 VCPedia，遵循其版权声明。文本内容除另有声明外，均在 [CC BY-NC-SA 3.0 CN](https://creativecommons.org/licenses/by-nc-sa/3.0/cn/) 许可协议下提供。

## AI 生成内容声明

1. 本项目大量使用 LLM 的场景包括：文本结构化、对话回复生成、情感/表情标签生成、上下文压缩、记忆检索和写入指令
2. GPT-SoVITS 语音合成基于 AI 技术，生成的语音内容为 AI 合成
3. Live2D 模型由火爆鸡王发布，非商业用途免费使用
4. 其他美术资源（背景图、Logo）来自网络公开免费资源
5. 本项目编写过程中使用了 AI 辅助编程工具

## 致谢

- 洛天依官方提供的角色设定
- [VCPedia](https://vcpedia.cn) 项目组提供的丰富知识库
- [GPT-SoVITS 项目](https://github.com/RVC-Boss/GPT-SoVITS/) 提供的开源语音合成技术
- [火爆鸡王](https://space.bilibili.com/5033594) 发布的 Live2D 模型
- 硅基流动平台提供的 API 服务
- 所有贡献者的努力和支持
