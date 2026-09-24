# 移除 winsound 依赖

- 大目标：清理闲置平台依赖，将歌曲试听切换为已有的 PyAudio 后端。
- PRD：[移除 winsound 依赖](../需求说明（PRD）/移除winsound依赖.md)。
- 总体设计：模块归属和架构不变。
- interface spec：[歌曲维护 CLI](../../../../项目说明/项目架构与接口（spec）/接口文档/system/music-tools.md)。
- 总体状态：已完成；候选已完成本地验证及 Windows、Linux 真机音频实测。

## 已完成

### 2026-09-19 清理依赖并替换歌曲试听后端

- 交付：删除客户端闲置 `play_audio()`、`winsound` 导入和标志；原音频样例保留文件读取、Base64 往返、PyAudio 播放和异常处理，并将样例放入 `client/tests/example_audio.wav`；歌曲试听通过 PyAudio 输出截取片段的整数 PCM，退出时释放设备资源，不生成临时 WAV；脚本从自身位置解析当前歌曲库，不再依赖启动目录。
- 分支：`bugfix/remove-winsound-dependency`；SPEC commit `1f11721`。客户端纯删除及辅助脚本后端替换没有保留长期自动化 Red：前者使用静态验证，后者使用一次性隔离 CLI 检查，未新增测试文件。
- 自动验证：现有客户端相关测试 19 项通过；3 个变更 Python 文件编译通过；AST 比较确认音频样例的原编解码逻辑、PyAudio 分支和 main 入口未改变；运行代码及样例中无 `winsound` 引用；`git diff --check` 通过。
- 隔离 CLI 检查：真实 pydub 音频对象和外部设备替身验证了 16 位双声道 PCM 的截取、格式、分块输出，以及写入失败时 `stop_stream`、`close`、`terminate` 均执行。该检查不作为仓库测试文件维护。
- 路径验证：从仓库根目录和 `server` 目录运行脚本均解析到 `server/res/sing_song/luotianyi/songs/ILOVEU`；无操作运行和 `--listen` 前后 `ILOVEU.json`、`ILOVEU.mp3` 哈希均保持不变。
- Windows 真机验收：默认 Realtek 输出设备上，测试目录中的 0.86 秒样例通过现有测试和直接执行脚本各播放一次；实际 `ILOVEU.mp3` 经 FFmpeg/pydub 解码后完整播放 219.18–256.76 秒片段。用户于 2026-09-19 确认听到两次测试音频和一次歌曲片段，真机听感验收通过，且没有遗留临时 WAV。
- 本次记录时未验证：未运行 `client/tests` 与 `server/tests` 的全量 pytest 回归；App 不在本次 Python 音频改动影响范围内。Linux/macOS 真机和完整 GUI 未验证；后续 Linux 实测见下节。没有改动 README、开发指引或开发守则。

### 2026-09-19 Linux 真机音频链路实测

- 验证对象：`bugfix/remove-winsound-dependency`，实现 commit `290dcd7`，SPEC commit `1f11721`；沿用上述 PRD 与歌曲维护 CLI 契约。本次仅补充实测记录，未修改产品代码、测试或 interface，Red 不适用。
- 环境：Ubuntu 22.04.5 LTS，Linux `5.19.0-50-generic`，x86_64；Conda `lty` 的 Python 3.10.12、PyAudio 0.2.14、PortAudio 19.6.0-devel、FFmpeg 8.1.2；PulseAudio 15.99.1，本机输出设备 `alsa_output.pci-0000_00_1f.3.analog-stereo`。
- 环境准备：原 `lty` 环境缺少 pydub、pytest，使用 pip 将 pydub 0.25.1 和 pytest 9.1.1 安装到 `/tmp/luotianyi-linux-audio-deps`；FFmpeg 初次执行因找不到 `libtiff.so.6`、`libLerc.so.4` 失败，在 `/tmp/luotianyi-linux-audio-libs` 中分别链接已有的 `/home/lubin/miniconda3/envs/lty/lib/libtiff.so.6.3.0` 和 `/home/lubin/miniconda3/pkgs/lerc-4.1.0-h7354ed3_2/lib/libLerc.so.4` 后恢复。通过进程环境变量选用系统 ALSA 插件，未修改 Conda 环境或系统配置；本次结果以这些临时环境补充为前提。
- 音频样例：直接执行 `client/tests/test_audio_base64.py` 一次，再通过该文件的 pytest 入口执行一次；两次均输出数据完整性验证成功和 `Playback finished.`，pytest 结果为 `1 passed`。该旧样例会捕获播放异常，因此同时检查了实际输出，未仅凭退出码或 pytest 结果判断成功。
- 歌曲试听：从仓库根目录执行 `server/scripts/music/add_segment.py --listen`，真实 `ILOVEU.mp3` 经 FFmpeg/pydub 解码，完整输出 219.18–256.76 秒（37.58 秒）片段，最终打印“播放完毕”，退出码 0。播放期间 `pactl list short sink-inputs` 显示 `s16le 2ch 44100Hz` 音频流，目标设备状态为 `RUNNING`；未使用音频设备替身。
- 路径与资源：从仓库根目录和 `server` 目录无参数运行 CLI 均成功解析 9 行歌词及相同起止时间；试听前后 `ILOVEU.json` 的 SHA-256 均为 `af46b1d4c7ba9367259867602f9826ea9bc1c3c99cf021c7247f5a1f18a0c5c5`，`ILOVEU.mp3` 均为 `097afabc0bab8ec24be69ba159459104b654d0e3076ab2b6868ec7602dee1f36`；歌曲目录未发现 WAV 文件。
- 诊断信息：PortAudio 枚举设备时仍有未配置的 ALSA 通道、OSS/USB 和未运行 JACK 的诊断输出，本轮样例及歌曲播放均正常结束。
- 人工确认：用户于 2026-09-19 反馈“我刚才听到声音了”，确认本轮 Linux 真机实测有实际可听输出；未分别确认两次样例和歌曲片段的完整听感或音质。
- 验收边界：已验证 Linux 本机的解码、真实音频输出链路和正常退出，并取得用户实际听到声音的确认。未重跑此前记录的 19 项客户端相关回归或客户端、服务端全量测试；macOS、完整 GUI、生产环境未验证。

以下命令从仓库根目录执行，使用上述已准备好的临时依赖和动态库链接；真实声卡访问在沙箱外执行：

```bash
/home/lubin/miniconda3/envs/lty/bin/python client/tests/test_audio_base64.py
export PATH=/home/lubin/miniconda3/envs/lty/bin:$PATH
export PYTHONPATH=/tmp/luotianyi-linux-audio-deps
export LD_LIBRARY_PATH=/tmp/luotianyi-linux-audio-libs
export ALSA_PLUGIN_DIR=/usr/lib/x86_64-linux-gnu/alsa-lib
python -m pytest client/tests/test_audio_base64.py -q -s -p no:cacheprovider
python -u server/scripts/music/add_segment.py --listen
```
