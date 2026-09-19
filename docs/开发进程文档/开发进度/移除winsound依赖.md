# 移除 winsound 依赖

- 大目标：清理闲置平台依赖，将歌曲试听切换为已有的 PyAudio 后端。
- PRD：[移除 winsound 依赖](../需求说明（PRD）/移除winsound依赖.md)。
- 总体设计：模块归属和架构不变。
- interface spec：[歌曲维护 CLI](../../项目说明/项目架构与接口（spec）/接口文档/system/music-tools.md)。
- 总体状态：进行中；本地候选已验证，未推送或合并。

## 已完成

### 2026-09-19 清理依赖并替换歌曲试听后端

- 交付：删除客户端闲置 `play_audio()`、`winsound` 导入和标志；原音频样例保留文件读取、Base64 往返、PyAudio 播放和异常处理，并将样例放入 `client/tests/example_audio.wav`；歌曲试听通过 PyAudio 输出截取片段的整数 PCM，退出时释放设备资源，不生成临时 WAV；脚本从自身位置解析当前歌曲库，不再依赖启动目录。
- 分支：`bugfix/remove-winsound-dependency`；SPEC commit `1f11721`。客户端纯删除及辅助脚本后端替换没有保留长期自动化 Red：前者使用静态验证，后者使用一次性隔离 CLI 检查，未新增测试文件。
- 自动验证：现有客户端相关测试 19 项通过；3 个变更 Python 文件编译通过；AST 比较确认音频样例的原编解码逻辑、PyAudio 分支和 main 入口未改变；运行代码及样例中无 `winsound` 引用；`git diff --check` 通过。
- 隔离 CLI 检查：真实 pydub 音频对象和外部设备替身验证了 16 位双声道 PCM 的截取、格式、分块输出，以及写入失败时 `stop_stream`、`close`、`terminate` 均执行。该检查不作为仓库测试文件维护。
- 路径验证：从仓库根目录和 `server` 目录运行脚本均解析到 `server/res/sing_song/luotianyi/songs/ILOVEU`；无操作运行和 `--listen` 前后 `ILOVEU.json`、`ILOVEU.mp3` 哈希均保持不变。
- Windows 真机验收：默认 Realtek 输出设备上，测试目录中的 0.86 秒样例通过现有测试和直接执行脚本各播放一次；实际 `ILOVEU.mp3` 经 FFmpeg/pydub 解码后完整播放 219.18–256.76 秒片段。用户于 2026-09-19 确认听到两次测试音频和一次歌曲片段，真机听感验收通过，且没有遗留临时 WAV。
- 未验证：未运行 `client/tests` 与 `server/tests` 的全量 pytest 回归；App 不在本次 Python 音频改动影响范围内。Linux/macOS 真机和完整 GUI 未验证。没有改动 README、开发指引或开发守则。
