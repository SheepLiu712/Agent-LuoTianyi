# AgentLuo 升级 gsv-tts-lite MultiSpeakerTTS 可行性报告

> 分支：`feat/gsv-multispeaker`（基于 `dev` @ `daa70a1`）
> 日期：2026-07-31
> 状态：~~可行性分析~~ → **已实施**（commit `41211dc`）

## 1. 背景

AgentLuo 自 v0.1.3 起将 TTS 依赖从 GPT-SoVITS 原生发布版迁移至 `gsv-tts-lite`（当前锁定 `==0.3.9`），使用标准单角色 `TTS` 类 API（`infer` / `infer_stream`），通过独立子进程 worker 提供服务。

GSV-TTS-Lite 多说话人分支（`multi-speaker-inference`）新增 `MultiSpeakerTTS`：多角色共享 GPT+SoVITS 骨干，每个角色仅注入 ~5-15% 专属权重，多角色场景显著节省显存。本次目标：评估 AgentLuo 升级至 `MultiSpeakerTTS` 的可行性。

## 2. 兼容性验证（已实测）

### 2.1 模型架构对比

| 字段 | 洛天依模型 | MultiSpeakerTTS base（默认） | 匹配 |
|---|---|---|---|
| GPT n_layer | 24 | 24（s1v3） | ✅ |
| GPT vocab_size | 1025 | 1025 | ✅ |
| SoVITS version | v2ProPlus | v2ProPlus | ✅ |
| SoVITS gin_channels | 1024 | 1024 | ✅ |
| SoVITS upsample_initial_channel | 768 | 768 | ✅ |
| SoVITS n_speakers | 300 | 300 | ✅ |

**结论：洛天依模型与默认 base 完全兼容，可真正共享骨干（GPT 共享 22/24 层），不会触发架构不兼容降级（`_add_full_model_speaker`）。**

### 2.2 API 对照

| 能力 | 现用 `TTS` API（0.3.9） | `MultiSpeakerTTS` API |
|---|---|---|
| 初始化 | `TTS(device, dtype, models_dir, use_bert)` + `load_gpt_model` + `load_sovits_model` | `MultiSpeakerTTS(speakers=[SpeakerConfig(...)], device, dtype, use_bert)` |
| 单次合成 | `infer(spk_audio_path, prompt_audio_path, prompt_audio_text, text)` | `infer(speaker, text, prompt_audio_path=None, prompt_audio_text=None)` |
| 流式合成 | `infer_stream(...)`（token 级低延迟） | `infer_stream(speaker, text, ...)`（**当前为逐句降级实现**） |
| 语气切换 | tone → 参考音频映射（外部模块） | `infer` 支持 `prompt_audio_path/prompt_audio_text` 覆盖，天然兼容 tone 机制 |
| 多角色 | 不支持 | 原生支持（`SpeakerConfig` 列表） |

## 3. 改造范围（agentluo 侧）

### 3.1 `docs/requirements.txt`

```diff
- gsv-tts-lite==0.3.9
+ # 多说话人分支暂未发布 PyPI，使用本地安装：
+ # pip install -e D:\GSV-TTS-Lite
+ gsv-tts-lite  # 或指定版本号
```

### 3.2 `src/capabilities/speech/tts_server.py`（核心）

worker 初始化改造：

```python
# 现状
tts = TTS(device=..., dtype=..., models_dir=..., use_bert=True)
tts.load_gpt_model(gpt_model_path)
tts.load_sovits_model(sovits_model_path)

# 目标
from gsv_tts import MultiSpeakerTTS, SpeakerConfig
tts = MultiSpeakerTTS(
    speakers=[
        SpeakerConfig(
            name="luotianyi",
            gpt_model_path="res/tts/luotianyi/custom_models/lty-tts_gpt_model.ckpt",
            sovits_model_path="res/tts/luotianyi/custom_models/lty-tts_sovits_model.pth",
            spk_audio_path="res/tts/luotianyi/reference_audio/叙述的参考音频.wav",
            prompt_audio_path="res/tts/luotianyi/reference_audio/叙述的参考音频.wav",
            prompt_audio_text="（lrc.json 对应歌词）",
        )
    ],
    device=..., dtype=..., use_bert=True,
)
```

命令处理改造：

```diff
  # synthesize / stream_synthesize 命令
  message["text"] / message["spk_audio_path"] / ...
+ message["speaker"]  # 新增字段，默认 "luotianyi"

- clip = tts.infer(spk_audio_path=..., prompt_audio_path=..., prompt_audio_text=..., text=...)
+ clip = tts.infer(speaker=..., text=...)

- for clip in tts.infer_stream(spk_audio_path=..., prompt_audio_path=..., prompt_audio_text=..., text=...):
+ for clip in tts.infer_stream(speaker=..., text=...):
```

### 3.3 `src/capabilities/speech/tts_module.py`

- `synthesize_speech(text, ref_audio_key)` / `stream_synthesize_speech(text, ref_audio_key)`：透传 `speaker` 参数（默认 `"luotianyi"`）
- tone 机制：保持现有 `tone_ref_audio_projection` 映射，将语气参考音频作为 `prompt_audio_path/prompt_audio_text` 覆盖传入 `infer`，实现语气切换

## 4. 风险与权衡

| 风险 | 等级 | 说明与缓解 |
|---|---|---|
| **流式体验退化** | 中 | `MultiSpeakerTTS.infer_stream` 目前是逐句降级（`cut_text` 切分后逐句 `infer`），非 token 级流式，首包延迟增加。缓解：对话场景可接受；或单角色继续走 `TTS` 双后端 |
| 依赖未发布 PyPI | 中 | 多说话人分支未发布，部署需本地安装（editable / wheel），`setup.bat` 需同步调整 |
| 开发分支稳定性 | 低 | 多说话人分支已合并 main（0.4.7）+ 修复静音裁剪崩溃 bug，需冒烟测试验证 |
| 单角色无显存收益 | 低 | 共享骨干优势在 3+ 角色时显著（3 角色省 51%），单角色等价于完整加载，功能不受影响 |

## 5. 收益

- 解锁 0.4.7 性能优化（3-4x 提速）与稳定性修复
- 验证多角色架构，为路线图 **v1.0.x 多角色支持** 铺路
- 新增角色仅需追加 `SpeakerConfig`（共享骨干，3 角色省 51% 显存、5 角色省 65%）

## 6. 结论

**可行性高**，核心风险已通过实测排除（模型架构完全兼容，无需降级）。工作量中等偏小：核心改动集中在 `tts_server.py`（worker 初始化 + 命令处理）与 `tts_module.py`（参数透传），外加依赖配置。

**待确认事项**：
1. 流式降级（逐句输出）是否可接受？还是要求保留 token 级流式（需给 `MultiSpeakerTTS.infer_stream` 补实现，或单角色双后端）
2. 部署环境是否接受本地安装多说话人版本（而非 PyPI 版本）

---

## 7. 实施记录（2026-07-31）

### 7.1 已提交改动（commit `41211dc`）

| 文件 | 改动 |
|---|---|
| `server/src/capabilities/speech/tts_server.py` | 新增 `_extract_multispeaker_config` / `_build_speaker_configs`；worker 按 `multispeaker.enabled` 分支初始化 `MultiSpeakerTTS`（回退保留原 `TTS` 路径）；`synthesize`/`stream_synthesize` 命令接受可选 `speaker` 字段 |
| `server/src/capabilities/speech/tts_module.py` | `synthesize_speech` / `stream_synthesize_speech` / `*_with_tone` 接受 `speaker` 参数并透传 |
| `server/docs/requirements.txt` | `gsv-tts-lite==0.3.9` → 取消锁定 + 本地安装指引（多说话人版未发布 PyPI） |

### 7.2 部署配置（资源包内 `res/tts/luotianyi/tts_infer.yaml`，不入 git，需手动更新）

```yaml
custom:
  pretrained_models_path: res/tts/gsv
  bert_base_path: res/tts/gsv/chinese-roberta-wwm-ext-large
  cnhuhbert_base_path: res/tts/gsv/chinese-hubert-base
  device: cuda
  is_half: true
  t2s_weights_path: res/tts/luotianyi/custom_models/lty-tts_gpt_model.ckpt
  version: v2ProPlus
  vits_weights_path: res/tts/luotianyi/custom_models/lty-tts_sovits_model.pth

multispeaker:
  enabled: true
  base_gpt_path: res/tts/gsv/s1v3
  base_sovits_path: res/tts/gsv/s2Gv2ProPlus
  reference_audio_dir: res/tts/luotianyi/reference_audio
  reference_audio_lyrics: res/tts/luotianyi/reference_audio/lrc.json
  speakers:
    - name: luotianyi
      gpt_model_path: res/tts/luotianyi/custom_models/lty-tts_gpt_model.ckpt
      sovits_model_path: res/tts/luotianyi/custom_models/lty-tts_sovits_model.pth
      spk_audio_path: res/tts/luotianyi/reference_audio/叙述的参考音频.wav
      prompt_audio_name: 叙述的参考音频
```

> `enabled: false` 即回退原单角色 TTS 模式。

### 7.3 依赖安装（多说话人版本）

```bash
# 在 lty 环境中安装 GSV-TTS-Lite 多说话人分支（含 main 合并 + 流式修复）
pip install -e D:\GSV-TTS-Lite
```

### 7.4 实测验证（CPU，gsvlite 环境 + agentluo 模型）

- ✅ `MultiSpeakerTTS` 加载 agentluo 模型成功（safetensors 目录 base + 洛天依 ckpt/pth）
- ✅ **真共享骨干**（`full_model=False`，25 GPT keys / 37 SoVITS keys）
- ✅ `infer` / `infer_stream`（真流式）正常
- ✅ 顺带修复 gsv-tts-lite 两个 safetensors 目录加载 bug（见 gsv-tts-lite `agentluotts` 分支 commit `545affb`）

### 7.5 行为差异说明（相对原 TTS 模式）

- 音色（ge）固定为 speaker 配置的 `spk_audio_path`（叙述的参考音频）；tone 语气切换通过 prompt 覆盖实现（风格变化，音色不变）——9 个参考音频均为洛天依本人声音，效果一致
- 流式：`MultiSpeakerTTS.infer_stream` 已升级为 **token 级真流式**（gsv-tts-lite `agentluotts` 分支 commit `bb5a6ef`），首包延迟与 `TTS.infer_stream` 一致

## 8. 运行时所有权加固（2026-08-01）

- `capabilities.tts.<character>.speaker` 定义显式的 character 到 speaker 映射；业务入口 `say` 和 `say_stream` 都会将该值传到底层 worker。
- TTSServer 由 `(backend, 规范化 server_config_path, suppress_worker_output, trim_startup_memory)` 唯一标识。多个角色只有键完全相同时才共享一个 worker；角色 TTSModule 仅保留 tone 和参考音频等轻量配置。
- 初始化任一角色失败会回收此前已经启动的所有独立 worker；共享 worker 在 stop/retry 中只处理一次，停止操作保持幂等。
- fake 自动化覆盖路由、共享所有权、不同 worker flags、部分失败回滚与重复停止。真实双 speaker 音色、20 次 restart、PID/VRAM 和首包延迟仍是部署环境的发布门槛，未由本地测试替代。
