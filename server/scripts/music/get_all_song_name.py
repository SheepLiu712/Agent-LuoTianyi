import os
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT))

from src.utils.server_paths import resolve_server_path


work_dir = resolve_server_path("data/singing/luotianyi/songs")
all_song_names = []
for file in os.listdir(work_dir):
    if (work_dir / file / f"{file}.json").is_file():
        all_song_names.append(file)
        continue
    # 查找包含song_name的文件
    if not file.endswith(".mp3") and not file.endswith(".wav"):
        continue
    song_name = file.rsplit(".", 1)[0]
    try:
        song_name = song_name.split("-")[1] # 前面是歌手名字
    except:
        pass
    song_name = song_name.split("_")[0] # 后面是后处理标记
    song_name = song_name.lstrip().rstrip()
    all_song_names.append(song_name)

print(all_song_names)
print(len(all_song_names))
