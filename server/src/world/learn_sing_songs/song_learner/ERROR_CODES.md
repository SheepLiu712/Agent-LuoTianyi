# Songlearner 错误码查询表

这些错误码会出现在 `metadata.json` 的 `failure_reason` 中，也会由 `run_song_workflow.py` 写入 stderr。

| 错误码 | 退出码 | 步骤 | 含义 |
| --- | ---: | --- | --- |
| SL001 | - | startup | AutoSongLearner 找不到 Songlearner 启动脚本。 |
| SL010 | 10 | startup | 参数、路径或工作流状态初始化失败。 |
| SL020 | 20 | download_song | 下载歌曲或歌词失败，包括 QQ 音乐搜索、歌手/标题匹配、凭证、网络、歌词为空等问题。 |
| SL030 | 30 | normalize_download | 下载结果目录或文件归一化失败，例如下载标题与请求歌名不同后移动文件失败。 |
| SL040 | 40 | clean_audio | 音频清洗、人声分离或降噪失败。 |
| SL050 | 50 | generate_boundary | MSAF 伴奏边界生成失败。 |
| SL060 | 60 | generate_clear_lrc | 基于 boundary 生成 `clear.lrc` 失败。 |
| SL070 | 70 | generate_llm_lrc | LLM 歌词分段生成 `llm.lrc` 失败。 |
| SL080 | 80 | generate_song_json | 生成最终歌曲 JSON 失败。 |
| SL090 | 90 | validate_output_files | 最终输出文件校验失败，通常是关键产物缺失。 |
| SL091 | - | timeout | AutoSongLearner 等待 Songlearner 子进程超时。 |
| SL092 | - | finalize | 子进程结束后未找到有效输出目录。 |
| SL093 | - | finalize | 子进程结束后输出目录存在，但音频或 JSON 等关键文件缺失。 |
| SL099 | 99 | unexpected | 未分类异常，通常表示错误没有被具体步骤捕获。 |

stderr 示例：

```text
[SONGLEARNER_ERROR] code=SL040 exit_code=40 step=clean_audio message=清洗后音频不存在: ...
```
