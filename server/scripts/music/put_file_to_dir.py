import os
import json
import re
import pathlib
import psutil

song_name_list = ['I LOVE U', '三月雨', '光与影的对白', '又见月光光', 'Hello  Bye  Days', '一半一半', '代替我', '千年食谱颂', '又一个夜晚', '忆红莲', '歌行四方', '珍珠', '聘书', '迷航在最熟悉的世界', '下等马', '白鸟过河滩', '蝴蝶']

work_dir = "res/music/songs"

for song_name in song_name_list:
    # 查找包含song_name的文件
    for item in os.listdir(work_dir):
        if os.path.isdir(os.path.join(work_dir, item)):
            continue
        if song_name in item:
            # 重命名文件，不改变文件扩展名
            old_path = os.path.join(work_dir, item)
            new_path = os.path.join(work_dir, f"{song_name}{pathlib.Path(item).suffix}")
            os.rename(old_path, new_path)
            print(f"Renamed {old_path} to {new_path}")

            # 移动文件到对应目录
            target_dir = os.path.join(work_dir, song_name)
            os.makedirs(target_dir, exist_ok=True)
            final_path = os.path.join(target_dir, f"{song_name}{pathlib.Path(item).suffix}")
            os.replace(new_path, final_path)
            print(f"Moved {new_path} to {final_path}")