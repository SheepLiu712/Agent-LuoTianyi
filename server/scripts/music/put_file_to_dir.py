import os
import sys
from pathlib import Path

SERVER_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(SERVER_ROOT))

from src.utils.server_paths import resolve_server_path

song_name_list = ['I LOVE U', '三月雨', '光与影的对白', '又见月光光', 'Hello  Bye  Days', '一半一半', '代替我', '千年食谱颂', '又一个夜晚', '忆红莲', '歌行四方', '珍珠', '聘书', '迷航在最熟悉的世界', '下等马', '白鸟过河滩', '蝴蝶']

work_dir = resolve_server_path("data/singing/luotianyi/songs")

for song_name in song_name_list:
    # 查找包含song_name的文件
    for item in os.listdir(work_dir):
        if os.path.isdir(os.path.join(work_dir, item)):
            continue
        if song_name in item:
            source = work_dir / item
            target = work_dir / song_name / f"{song_name}{source.suffix}"
            if target.exists():
                raise FileExistsError(f"歌曲库中已存在文件: {target}")
            target.parent.mkdir(exist_ok=True)
            source.rename(target)
            print(f"Moved {source} to {target}")
