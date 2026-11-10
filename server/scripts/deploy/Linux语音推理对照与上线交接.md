# Linux 语音推理对照与上线交接

请部署机上的 agent 在同一张显卡、同一份服务端代码和模型上完成对照，并实际启动验收通过的方案。A 为当前 PyTorch 2.8.0+cu128，B 为候选 2.9.1+cu128。两组均使用 Python 3.10.22 和 gsv-tts-lite 0.4.7。新的服务端代码在 A 选中 cuDNN 时为单步解码开放其他内核，在 B 中沿用上游选择。cuDNN 是 NVIDIA 的深度学习计算库。

## 准备环境

1. 在服务器上确认实际服务单元、运行账号、工作目录和启动命令。以下命令均在含有 `server_main.py` 的生产目录以运行账号执行；`systemctl` 操作使用管理员权限。记录当前服务状态、软件版本、显卡和驱动、代码版本、启动脚本，以及现有环境的绝对路径。核对 `.venv/bin/python` 是服务实际使用的解释器。
2. 在独立目录保存原代码版本或部署文件备份、原依赖清单和锁文件、原启动配置，记录恢复步骤。保留当前可启动的 A 环境。若现场并非上述基线，先用原基线锁文件在独立目录复建 A，保留现场环境作为恢复目标。升级文件包括新的语音工作进程代码、Linux 依赖清单、锁文件和测量脚本。两组均从这份服务端源码运行。
3. 预留足够空间容纳两套环境。先在单独的固定路径同步 B。下面的 `B` 目录同时作为候选上线环境，请保留其绝对路径。核对同步选中的软件包版本。

```bash
set -euo pipefail
umask 077
A="$PWD/.venv"
B="$PWD/.runtime/venv-torch291"
RUN="$PWD/.runtime/tts-compare-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RUN"
UV_PROJECT_ENVIRONMENT="$B" UV_LINK_MODE=copy uv sync --project scripts/deploy --python 3.10.22 --locked --no-dev
for envdir in "$A" "$B"; do
  uv pip check --python "$envdir/bin/python"
  "$envdir/bin/python" -c 'import sys, torch, torchaudio, torchvision; from importlib.metadata import version; print(sys.version, torch.__version__, torchaudio.__version__, torchvision.__version__, version("gsv-tts-lite"), torch.cuda.get_device_name(), torch.backends.cudnn.version())'
done
```

如果 A 是复建的基线，将 `A` 设为它的实际绝对路径。A 的 torchaudio / torchvision 应为 2.8.0 / 0.23.0，B 应为 2.9.1 / 0.24.1，均为 cu128 构建。确认两组使用同一份 GPT、SoVITS 权重、模型精度、参考音频和对应文字，记录各文件路径和校验和。按生产配置设置以下变量：

- `MODEL` 为服务端加载的 TTS 模型 YAML 路径。
- `REF` 为当前角色使用的一段参考音频路径。
- `LYRICS` 为 UTF-8 文本文件路径，将该参考音频在角色配置中的对应文字原样写入此文件。

## 在维护窗口测量

停止实际服务单元，用 `nvidia-smi` 确认显卡空闲。每次只运行一组。发生异常时保留对应轮次的日志，恢复服务后再作故障分析。按 A、B、B、A 顺序测量，降低运行先后和显卡温度对结果的影响。

```bash
bench() {
  PYTHONPATH="$PWD${PYTHONPATH:+:$PYTHONPATH}" "$1/bin/python" scripts/deploy/benchmark_tts.py "$MODEL" "$REF" "$LYRICS" "$RUN/$2" >"$RUN/$2.log" 2>&1
}
bench "$A" A1
bench "$B" B1
bench "$B" B2
bench "$A" A2
```

[测量脚本](benchmark_tts.py) 使用 [TTSServer](../../src/agent/skills/expression/speaking/tts_server.py) 启动生产语音工作进程，通过该类的 `stream_synthesize_call_pcm` 方法获取通话使用的 24 kHz、单声道、16 位音频流。每轮先对三句不同长度的中文各预热一次，再各测五次。计时从提交合成到收到首个非空音频块，表示**首包延迟**；完整合成耗时除以输出音频时长，得到**实时率（RTF）**。数值越小越好。试听各轮保存的 WAV 样本，确认内容正确、音频完整、无明显失真。记录预热失败、空音频、显存不足等异常。

按组汇总 30 个有效样本，中位数反映常见请求，P95 为按升序排列后第 95 百分位的值。保留原始记录，以便核对各句差异。

```bash
"$A/bin/python" - "$RUN" <<'PY'
import json, math, statistics, sys
from pathlib import Path
root = Path(sys.argv[1])
for group in ("A", "B"):
    rows = []
    for i in (1, 2):
        lines = (root / f"{group}{i}" / "samples.jsonl").read_text().splitlines()
        if len(lines) != 15:
            raise ValueError(f"{group}{i} 样本不完整")
        rows.extend(map(json.loads, lines))
    for metric in ("first_ms", "rtf"):
        values = sorted(row[metric] for row in rows)
        print(group, metric, "中位数", statistics.median(values), "P95", values[math.ceil(.95*len(values))-1])
PY
```

## 判定与上线

1. 先按可靠性和音质筛选。只有模型能预热、所有测量完成且音频验收通过的方案可入选。两组都未通过时恢复先前可用的生产部署，并报告阻塞原因。
2. 两组均通过时，默认以通话首包延迟为优先指标。采用以下现场决策阈值：首包中位数或 RTF 中位数至少一项降低 5%，另一项中位数及两项 P95 相对对照组的增幅均不超过 5%，即可选为优胜方案。指标冲突或结果接近时，交换顺序再测一轮完整对照，合并原始样本复算；仍无明确收益时采用已验收的基线 A。5% 是本次操作采用的决策容差。
3. 将选定环境接入实际服务。若原 A 胜出，继续使用原环境。若 B 胜出，或胜出的 A 为复建环境，先确认服务已停止、选定环境使用永久绝对路径。对于通过 `.venv/bin/python` 启动的实例，将原 `.venv` 目录或链接原样改名保存于同一文件系统，再将 `.venv` 建为指向选定环境的符号链接。恢复时移除新链接并将原目录或链接改回原名。自定义启动单元按其实际解释器路径切换，并保存原单元配置。
4. 将实际部署保留的依赖清单和锁文件与胜出环境配对。A 胜出时保留 A 的基线清单与锁文件作为该机后续同步入口；B 胜出时使用本次更新的文件。记录生效路径。
5. 用原服务单元启动，核对业务日志出现“配置校验通过，ServerRuntime 已自动启动”，通过管理后台确认运行状态，再发起一次实际客户端语音回复并试听。比较服务进程的解释器与选定环境，确认单元、浏览器目录和代理例外设置均已生效。任何上线验收失败时，停止服务，恢复原环境入口、部署文件和原锁文件，重新完成启动及语音验收。
6. 向维护者交付实际生效的方案、选择理由、版本和硬件、两组中位数与 P95、试听与业务验收结果、原始记录目录和恢复入口。以服务已运行并通过业务验收作为交接完成条件。
