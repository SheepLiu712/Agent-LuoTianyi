# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

AgentLuo (洛天依对话Agent) — an AI chatbot that roleplays as the virtual singer Luo Tianyi. Features Live2D model display, GPT-SoVITS voice synthesis, image recognition, vector/graph memory, and song playback. Three sub-projects:

- **server/** — Python 3.10 FastAPI backend (WebSocket + REST)
- **client/** — PySide6 desktop app (Windows)
- **app/** — React Native / Expo mobile app (Android)

## Server Architecture

```
server_main.py  (FastAPI entry — /chat_ws WebSocket, /auth/*, /history, /get_image)
```

### Key Layers

**1. Interface Layer** (`server/src/interface/`)
- `websocket_service.py` — WebSocket message framing (auth, heartbeat, agent state), connection management
- `service_hub.py` — `ServiceHub` dataclass: shared runtime dependency container holding all singleton services
- `account.py` — Registration, login, token auth, RSA encryption
- `types.py` — Pydantic request/response models, `WSEventType` enum

**2. Chat Pipeline** (`server/src/pipeline/`)
Per-user async pipeline processing messages sequentially:
- `chat_stream.py` — `ChatStream` per user: ingress_queue → topic_planner → topic_replier → response_sender
- `modules/ingress.py` — Preprocessing: save images, call vision API, extract song entities, detect important dates
- `modules/unread_store.py` — Buffers user messages until they form a complete topic
- `modules/listen_timer.py` — Timed deadline: waits for user to finish typing before flushing topic
- `topic_planner.py` — Groups buffered messages into `ExtractedTopic` (by LLM or fallback heuristic)
- `topic_replier.py` — Consumes topics: memory/fact/sing lookup parallel → agent generates reply → speaking worker → async memory write
- `global_chat_stream_manager.py` — Manages all active `ChatStream` instances (per user UUID)
- `global_speaking_worker.py` — Global TTS queue: serializes audio generation to avoid GPU OOM

**3. Agent** (`server/src/agent/`)
- `luotianyi_agent.py` — `LuoTianyiAgent` class: the core agent orchestrating all sub-modules
- `main_chat.py` — LLM call logic: constructs prompts with persona, history, memories; parses structured response lines (text, song, expressions)
- `conversation_manager.py` — Conversation persistence, context window management, compression/forgetting
- `topic_extractor.py` — LLM-based topic extraction from user messages
- `activity_maker.py` — Proactive agent behaviors: first-greet, return-user greeting, silence-triggered chit-chat
- `jargon_retriver.py` — Song entity extraction from user input

**4. Memory System** (`server/src/memory/`)
- `memory_manager.py` — Unified entry: `search_memories_for_topic` (read) + `post_process_interaction` (write)
- `memory_search.py` — Multi-source search: vector store + graph + song knowledge
- `memory_write.py` — LLM decides what to remember, writes to vector store
- `user_profile_updater.py` — Maintains user persona description over time
- `graph_retriever.py` — Knowledge graph queries (VCPedia song data)

**5. Database** (`server/src/database/`)
- `sql_database.py` — SQLAlchemy ORM: User, ConversationItem tables
- `vector_store.py` — ChromaDB wrapper for memory embeddings
- `memory_storage.py` — Redis buffer for fast context access
- `knowledge_graph.py` — In-memory JSON knowledge graph loader
- `sql_writer.py` — Async bulk conversation writer

**6. Plugins** (`server/src/plugins/`)
- `citywalk/` — Autonomous city exploration: Amap POI search, LLM decision engine, energy/mood simulation, diary generation
- `music/` — Song database (VCPedia), singing manager (segment matching), daily new-song fetcher
- `schedule/` — Bilibili event feed fetcher, activity/concert calendar, context injection into chat, reminder dispatching
- `daily_scheduler.py` — Cron-like daily task scheduler (citywalk, new song sync)

**7. TTS** (`server/src/tts/`)
- GPT-SoVITS integration: tone-based voice synthesis, streaming audio, reference audio management

**8. Vision** (`server/src/vision/`)
- VLM-based image description (Qwen-VL) for user-uploaded images

**9. LLM Utils** (`server/src/utils/llm/`)
- `llm_module.py` — OpenAI-compatible API client (SiliconFlow, DashScope, DeepSeek...)
- `embedding.py` — Embedding generation for vector search
- `prompt_manager.py` — Jinja2 template-based prompt management (templates in `res/agent/prompts/`)

### Startup Flow (`server_main.py`)

1. `startup_event` lifespan: init databases → TTS → Agent → ServiceHub → ScheduleManager → ActivityMaker → GlobalSpeakingWorker → DailyScheduler
2. WebSocket `/chat_ws`: accept → `send_system_ready` → auth → `get_or_register_chat_stream` → message loop

## Client Architecture

```
main.py  (PySide6 entry)
```

- `src/gui/` — `MainWindow`, chat bubbles, login dialog, preferences
- `src/network/` — `WebSocketTransport` (ws/wss + reconnection), `NetworkClient` (API calls), `event_types`
- `src/message_process/` — `MessageProcessor` (message routing, TTS playback with VLC), `MultiMediaStream`
- `src/live2d/` — Live2D model rendering (Cubism SDK bindings)
- `src/safety/` — Credential management, password encryption
- `src/utils/` — Audio processing, HTTP client, image processing, helpers

## App (Mobile)

React Native / Expo project (`app/`) using expo-router navigation. Shared logic ported from the desktop client: WebSocket transport, chat stream, message processing, Live2D via cubism4 JS runtime.

## Key Design Patterns

- **Async pipeline per user**: Each user gets a `ChatStream` with async task loops running ingress → planner → replier → speaker. Tasks are created once on first message and cancelled on disconnect.
- **ServiceHub dependency injection**: All services registered once at startup in a `ServiceHub` dataclass, passed through the pipeline.
- **Speaking worker serialization**: A global `SpeakingWorker` serializes all TTS jobs across users to prevent GPU OOM from concurrent GPT-SoVITS calls.
- **Agent as pipeline backend**: The pipeline (topic_planner → topic_replier) delegates all LLM/memory/TTS work to `LuoTianyiAgent`, keeping the pipeline focused on flow control.

## Development Commands

```bash
# Server
cd server
python server_main.py          # Start FastAPI server (http://127.0.0.1:60030)
python scripts/generate_cert.py  # Generate SSL cert for HTTPS

# Client
cd client
python main.py                 # Launch desktop client

# App (mobile)
cd app
npx expo start                 # Start Expo dev server

# Tests (server)
cd server
python -m pytest tests/                        # Run all tests
python -m pytest tests/test_xxx.py            # Run single test file
python -m pytest tests/ -k "test_name"        # Run specific test

# Dependencies (server/client — conda)
setup.bat                      # Create conda env, install deps
```

## Environment Variables

API keys set as system env vars (referenced by `$KEY_NAME` in config.json):
- `SILICONFLOW_API_KEY` — SiliconFlow (embeddings, fallback LLM)
- `QWEN_API_KEY` — DashScope/Qwen (main chat LLM, vision)
- `DEEPSEEK_API_KEY` — DeepSeek (memory search, conversation summarization)
- `AMAP_KEY` — Amap/高德地图 (citywalk plugin)
