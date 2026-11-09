# 2026-10-28 桌面卡顿诊断

## 结论与边界

现场证据指向 Windows 桌面合成与 NVIDIA 显示驱动之间的呈现/同步状态异常。尚未证明具体缺陷位于 MPO、独立翻转、驱动电源管理或某个应用的交互代码中，不能将其表述为已确认的 MPO 故障。

本次 NVIDIA Overlay 进程没有运行。Minecraft 的 javaw.exe（PID 32024）从 08:30:05 一直运行到恢复之后。用户确认采样中途恢复，未退出游戏。因此，2026-09-28 重启 NVIDIA Overlay 后恢复，只能证明那次操作有效，不能证明 Overlay 是所有复发的唯一根因。

## 现场数据（北京时间）

- 08:59–09:00 卡顿持续时：CPU 十秒采样平均 3.57%，最大 7.10%；可用内存约 20,224 MiB；系统盘平均 I/O 响应约 0.11ms，最大约 0.31ms。未见持续资源饱和。
- 同期 DwmFlush 同步等待中位数 31.11–31.36ms，95 分位约 45.54ms。它是同步调用耗时，不直接等同于实际屏幕 FPS。
- 屏幕报告 2560×1600、165Hz。RTX 4070 Laptop GPU 使用 NVIDIA 610.74；首次读数 P8、210/405MHz、51°C，之后也采到 P4。未见正在触发的温度/功耗限频，不能仅凭低频断言显卡锁频。
- 恢复后 09:16:36：同样的 DwmFlush 采样中位数 6.04–6.06ms，95 分位约 6.3ms；GPU P0、1770/8001MHz、55°C。用户确认恢复流畅。
- 当前 Windows 版本 10.0.26300。近期系统/应用日志未发现对应的驱动重置、硬件错误或资源耗尽事件。

## 游戏证据

- 实例：`D:\minecraft\ttsever\versions\creatnewword`，Minecraft 1.21.1 / NeoForge 21.1.256。
- `logs\latest.log:793–799` 确认 NVIDIA OpenGL 3.3.0、驱动 610.74；Sodium 启用了 NVIDIA 线程提交兼容措施。兼容提示是启动信息，不能单独证明本次故障。
- 未发现 OutOfMemory 或 GC 暂停记录；这不代表没有 GC，只代表现有游戏日志无法提供该证据。

## ETW 轨迹的关键发现

原始文件：`display-stutter.etl`，约 1.05GB。计划主体采样为 20 秒，ETL 还包含启动和停止收尾，整体时间范围约 44 秒。共 17,567,331 个事件，报告丢失事件为 0。

用 Windows 原生 OpenTrace/ProcessTrace、TDH 提取事件，脚本为 `AnalyzeTrace.cs`。`native-analysis.txt` 记录解析返回值为 0、异常计数为 0。

`selected-processes.tsv` 确认 PID 43456 为 wpr.exe。`graphics-transitions.tsv` 记录该进程触发的 Microsoft-Windows-DxgKrnl 事件：

| 相对轨迹开始 | 事件 ID | 名称 |
| --- | --- | --- |
| 848ms | 428 | FlushPresentReferencesAndDisableOverlays |
| 850ms | 429 | ResumeSchedulerForVidPnSource |
| 2884ms | 428 | FlushPresentReferencesAndDisableOverlays |
| 2964ms | 429 | ResumeSchedulerForVidPnSource |
| 5934ms | 267 | IndependentFlipTransition（调用进程为 dwm.exe） |

从相对第 3 秒起，提取的 VSyncDPC 事件在完整秒中约为 165 次/秒；游戏 Present 事件约 117–119 次/秒。这些分别是垂直同步事件和提交次数，不等同于所有应用的实际显示帧率。

重要限制：开始 GPU 诊断本身会干预显示调度与硬件叠加状态。它是这次恢复的合理解释，但不能把时间相关性当成唯一因果证明，也不能用主要处于恢复状态的轨迹排除恢复前的所有故障。

## 后续方向

优先针对 NVIDIA 显示驱动与桌面呈现路径排查；建议首先评估更新至适配该电脑和 Windows 版本的稳定驱动。若仍复发，再单独做 MPO 禁用/恢复的受控对照，或收集不主动刷新该路径的专用跟踪。不要同时修改驱动、MPO、HAGS 等多项设置。

本次未修改驱动、注册表、显示配置、游戏配置或启动项，未关闭/重启 Minecraft、Wallpaper Engine 或 TranslucentTB。WPR 已停止。
