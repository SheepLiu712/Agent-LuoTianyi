"""用真实节拍分析覆盖旧 librosa 与新 SciPy 的分段兼容问题。"""

import sys
from types import SimpleNamespace

import librosa
import numpy as np
import soundfile as sf
from scipy import signal

from src.world.learn_sing_songs.song_learner.src.pipeline.msaf_segment_boundaries import generate_boundary_inst


def test_song_boundaries_can_be_generated_with_legacy_beat_tracker(tmp_path, monkeypatch):
    directory = tmp_path / "节拍测试"
    directory.mkdir()
    sample_rate = 22050
    audio = librosa.clicks(times=np.arange(0.5, 8, 0.5), sr=sample_rate, length=8 * sample_rate)
    sf.write(directory / "节拍测试.inst.mp3", audio, sample_rate, format="WAV")

    # 注册恢复操作，再模拟新版 SciPy 缺少旧入口；不污染其他测试。
    monkeypatch.setattr(signal, "hann", None, raising=False)
    monkeypatch.delattr(signal, "hann")

    def process(path):
        # CI 不安装完整的重型 MSAF 依赖，但实际运行其故障所在的 librosa 节拍分析。
        samples, sr = librosa.load(path)
        _, frames = librosa.beat.beat_track(y=samples, sr=sr)
        times = librosa.frames_to_time(frames, sr=sr)
        assert len(times) >= 4, "有规律的节拍应能被检测，不能以空结果掩盖故障"
        return times, None

    monkeypatch.setitem(sys.modules, "msaf", SimpleNamespace(process=process))
    output = generate_boundary_inst(directory)
    boundaries = [
        float(line.split(":")[0]) * 60 + float(line.split(":")[1]) for line in output.read_text().splitlines()
    ]
    assert len(boundaries) >= 4
    assert all(0 <= boundary <= 8 for boundary in boundaries)
    assert all(left < right for left, right in zip(boundaries, boundaries[1:]))
